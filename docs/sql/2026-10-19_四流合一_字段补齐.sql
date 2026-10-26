-- ============================================================================
-- 四流合一 · 第一阶段：字段补齐（销售 / 物流签收 / 发票 / 资金）
-- 目标库：PostgreSQL 18，库 erp，三套账套 schema：public / co_02 / co_03
-- 执行方式（务必用 psql，不要用 GUI 逐段贴，DO 块里有多语句）：
--     psql -h 127.0.0.1 -U erp -d erp -f "docs/sql/2026-10-19_四流合一_字段补齐.sql"
--
-- 三条安全约定：
--   1. **完全幂等**：全部 ADD COLUMN IF NOT EXISTS / CREATE INDEX IF NOT EXISTS，
--      重复执行不会报错、不会改数据。
--   2. **只加不删**：不重命名、不改既有列类型（金额类型迁移是单独一份脚本，
--      必须与第二阶段模型改造同时上线，见
--      2026-10-19_四流合一_金额精度(第二阶段用).sql）。
--   3. **新列一律可空或带默认值**：老单据不需要任何回填就能继续用，
--      签收/发票认证这些"还没发生"的事，NULL 就是最准确的表达。
--
-- 体检结论见 docs/四流合一_第一阶段体检报告.md，字段与业务含义一一对应。
-- ============================================================================

BEGIN;

-- ---------------------------------------------------------------------------
-- 0. 执行前快照：把四张表的行数记下来，执行后对比，确认"只加列没动数据"
-- ---------------------------------------------------------------------------
DO $$
DECLARE
    s text;
    n integer;
BEGIN
    FOREACH s IN ARRAY ARRAY['public', 'co_02', 'co_03'] LOOP
        IF EXISTS (SELECT 1 FROM information_schema.tables
                   WHERE table_schema = s AND table_name = 'sales_orders') THEN
            EXECUTE format('SELECT count(*) FROM %I.sales_orders', s) INTO n;
            RAISE NOTICE '[执行前] %: sales_orders = % 行', s, n;
        END IF;
    END LOOP;
END $$;


-- ---------------------------------------------------------------------------
-- 1. sales_orders —— 业务流（销售日期/送货日期已有）+ 物流流（全部新增）
--
--    已有：order_date（销售日期）、delivery_date（送货日期）、address（送货地址快照）
--    只缺：合同的直连锚点、发货时间点、签收时间/签收人、物流公司/物流单号
--
--    为什么合同锚点要加在销售单上：
--      现在合同 → 订单的关系只能靠 contracts.order_id 反查，而这一列**一条都没填**
--      （2 张合同的 order_id / order_no 全为 NULL）。也就是说"按合同号聚合"
--      今天只能退化成"按往来单位 + 签收日期区间"去猜。加 contract_id + contract_no
--      之后，一条销售单就能自报"我属于哪份合同"，聚合链路才可能 100%。
-- ---------------------------------------------------------------------------
DO $$
DECLARE
    s text;
BEGIN
    FOREACH s IN ARRAY ARRAY['public', 'co_02', 'co_03'] LOOP
        IF NOT EXISTS (SELECT 1 FROM information_schema.tables
                       WHERE table_schema = s AND table_name = 'sales_orders') THEN
            CONTINUE;
        END IF;

        -- 合同直连（可空：不是所有销售单都签了合同）
        EXECUTE format('ALTER TABLE %I.sales_orders ADD COLUMN IF NOT EXISTS contract_id integer', s);
        EXECUTE format('ALTER TABLE %I.sales_orders ADD COLUMN IF NOT EXISTS contract_no varchar(50)', s);

        -- 物流流：发货时间点（delivery_date 只有日期，算在途时长需要时刻）
        EXECUTE format('ALTER TABLE %I.sales_orders ADD COLUMN IF NOT EXISTS shipped_at timestamptz', s);
        -- 签收：signed_at IS NULL ⇔ 未签收。刻意不加 sign_status 枚举 ——
        -- 两个字段表达同一件事，迟早不一致。
        EXECUTE format('ALTER TABLE %I.sales_orders ADD COLUMN IF NOT EXISTS signed_at timestamptz', s);
        EXECUTE format('ALTER TABLE %I.sales_orders ADD COLUMN IF NOT EXISTS signed_by varchar(50)', s);
        -- 物流信息：单号 + 公司（用户清单里的「单号/公司」）
        EXECUTE format('ALTER TABLE %I.sales_orders ADD COLUMN IF NOT EXISTS logistics_no varchar(100)', s);
        EXECUTE format('ALTER TABLE %I.sales_orders ADD COLUMN IF NOT EXISTS logistics_company varchar(100)', s);

        EXECUTE format($f$COMMENT ON COLUMN %I.sales_orders.contract_id IS '所属合同 id（四流合一锚点，可空）'$f$, s);
        EXECUTE format($f$COMMENT ON COLUMN %I.sales_orders.shipped_at IS '实际发货时间（物流流起点）'$f$, s);
        EXECUTE format($f$COMMENT ON COLUMN %I.sales_orders.signed_at IS '客户签收时间；为 NULL 表示未签收'$f$, s);
        EXECUTE format($f$COMMENT ON COLUMN %I.sales_orders.signed_by IS '签收人姓名（收货方签字人）'$f$, s);
        EXECUTE format($f$COMMENT ON COLUMN %I.sales_orders.logistics_no IS '物流/快递单号'$f$, s);
        EXECUTE format($f$COMMENT ON COLUMN %I.sales_orders.logistics_company IS '物流/快递公司'$f$, s);
    END LOOP;
END $$;


-- ---------------------------------------------------------------------------
-- 2. invoices —— 发票流（开票金额已有，缺时间精度、收票人、认证状态、挂单）
--
--    已有：issue_date（开票日期，varchar 只到日）、total_amount（开票金额）、
--          source_path/name/mime（电子原件）、customer_id、contract_id
--    只缺：
--      · issued_at    开票时间（精确到时分；数电票的"开票时间"是有时分秒的）
--      · receiver     收票人（纸质票/专票快递签收人，和 handler"开票经办人"不是一个人）
--      · verified     是否已认证（增值税勾选认证）。注意 deducted 是"专票已抵扣"，
--                     是申报动作，不等于认证 —— 两者不能互相顶替。
--      · verified_at  认证时间
--      · sales_order_id / purchase_order_id
--                     发票挂到具体单据。**这是当前四流合一最大的断点**：
--                     4 张销项发票的 customer_id、contract_id 全是 NULL，
--                     只能靠 counterparty_name（"陕西送变电工程有限公司"）去猜，
--                     而客户档案里那条叫"陕西送变电公司一分司-攀西特高压…"，
--                     名称不相等 → 一张都匹配不上。这也是历史对账单"已开票=0"的根因。
--                     加列之后由人工/脚本认领，聚合才能做到 100%。
-- ---------------------------------------------------------------------------
DO $$
DECLARE
    s text;
BEGIN
    FOREACH s IN ARRAY ARRAY['public', 'co_02', 'co_03'] LOOP
        IF NOT EXISTS (SELECT 1 FROM information_schema.tables
                       WHERE table_schema = s AND table_name = 'invoices') THEN
            CONTINUE;
        END IF;

        EXECUTE format('ALTER TABLE %I.invoices ADD COLUMN IF NOT EXISTS issued_at timestamptz', s);
        EXECUTE format('ALTER TABLE %I.invoices ADD COLUMN IF NOT EXISTS receiver varchar(50)', s);
        EXECUTE format('ALTER TABLE %I.invoices ADD COLUMN IF NOT EXISTS verified boolean NOT NULL DEFAULT false', s);
        EXECUTE format('ALTER TABLE %I.invoices ADD COLUMN IF NOT EXISTS verified_at timestamptz', s);
        EXECUTE format('ALTER TABLE %I.invoices ADD COLUMN IF NOT EXISTS sales_order_id integer', s);
        EXECUTE format('ALTER TABLE %I.invoices ADD COLUMN IF NOT EXISTS purchase_order_id integer', s);

        EXECUTE format($f$COMMENT ON COLUMN %I.invoices.issued_at IS '开票时间（精确到时分；issue_date 仅到日）'$f$, s);
        EXECUTE format($f$COMMENT ON COLUMN %I.invoices.receiver IS '收票人（纸质票签收人，区别于 handler 开票经办人）'$f$, s);
        EXECUTE format($f$COMMENT ON COLUMN %I.invoices.verified IS '是否已认证（增值税勾选认证），与 deducted 已抵扣不同'$f$, s);
        EXECUTE format($f$COMMENT ON COLUMN %I.invoices.sales_order_id IS '销项发票所属销售单 id（四流合一：发票流→业务流）'$f$, s);
        EXECUTE format($f$COMMENT ON COLUMN %I.invoices.purchase_order_id IS '进项发票所属采购单 id'$f$, s);
    END LOOP;
END $$;


-- ---------------------------------------------------------------------------
-- 3. financial_transactions —— 资金流（付款日期/金额已有，缺收付方式与凭证号）
--
--    已有：occurred_at（业务发生日期）、amount（每笔金额）、applied_amount（实际冲抵单据）、
--          related_type + related_order_id（挂单）、customer_id/supplier_id、
--          reversal_of_id（红冲）、bank_account_id
--    只缺：
--      · payment_method  收付方式（现金 / 转账 / 承兑 / 微信 / 支付宝…）。
--                        对账时要能跟银行流水对上，光有金额对不出来。
--      · voucher_no      银行流水号 / 回单号。
--    多笔收款能力**本来就具备**：实测销售单 XSD20261018001 已挂 3 笔收款
--    （1000 + 600 + 50），所以第二阶段「多笔付款数组」不需要新建表。
-- ---------------------------------------------------------------------------
DO $$
DECLARE
    s text;
BEGIN
    FOREACH s IN ARRAY ARRAY['public', 'co_02', 'co_03'] LOOP
        IF NOT EXISTS (SELECT 1 FROM information_schema.tables
                       WHERE table_schema = s AND table_name = 'financial_transactions') THEN
            CONTINUE;
        END IF;

        EXECUTE format('ALTER TABLE %I.financial_transactions ADD COLUMN IF NOT EXISTS payment_method varchar(30)', s);
        EXECUTE format('ALTER TABLE %I.financial_transactions ADD COLUMN IF NOT EXISTS voucher_no varchar(80)', s);

        EXECUTE format($f$COMMENT ON COLUMN %I.financial_transactions.payment_method IS '收付方式：现金/转账/承兑/微信/支付宝…'$f$, s);
        EXECUTE format($f$COMMENT ON COLUMN %I.financial_transactions.voucher_no IS '银行流水号/回单号（与银行对账用）'$f$, s);
    END LOOP;
END $$;


-- ---------------------------------------------------------------------------
-- 4. 索引 —— 四流合一聚合是"按单据反查多条明细"，没有索引会全表扫
--
--    体检发现 sales_orders 只有 id / order_no 两个索引，连 customer_id 都没索引；
--    financial_transactions 的 (related_type, related_order_id) 组合也没有。
--    第二阶段预览接口要按这些键反复查，先把索引补上。
-- ---------------------------------------------------------------------------
DO $$
DECLARE
    s text;
BEGIN
    FOREACH s IN ARRAY ARRAY['public', 'co_02', 'co_03'] LOOP
        IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_schema = s AND table_name = 'sales_orders') THEN
            EXECUTE format('CREATE INDEX IF NOT EXISTS ix_sales_orders_customer_id ON %I.sales_orders (customer_id)', s);
            EXECUTE format('CREATE INDEX IF NOT EXISTS ix_sales_orders_contract_id ON %I.sales_orders (contract_id)', s);
            EXECUTE format('CREATE INDEX IF NOT EXISTS ix_sales_orders_order_date ON %I.sales_orders (order_date)', s);
            EXECUTE format('CREATE INDEX IF NOT EXISTS ix_sales_orders_doc_type ON %I.sales_orders (doc_type)', s);
        END IF;

        IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_schema = s AND table_name = 'invoices') THEN
            EXECUTE format('CREATE INDEX IF NOT EXISTS ix_invoices_sales_order_id ON %I.invoices (sales_order_id)', s);
            EXECUTE format('CREATE INDEX IF NOT EXISTS ix_invoices_purchase_order_id ON %I.invoices (purchase_order_id)', s);
            EXECUTE format('CREATE INDEX IF NOT EXISTS ix_invoices_issue_date ON %I.invoices (issue_date)', s);
        END IF;

        IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_schema = s AND table_name = 'financial_transactions') THEN
            EXECUTE format('CREATE INDEX IF NOT EXISTS ix_financial_transactions_customer ON %I.financial_transactions (customer_id, occurred_at)', s);
            EXECUTE format('CREATE INDEX IF NOT EXISTS ix_financial_transactions_supplier ON %I.financial_transactions (supplier_id, occurred_at)', s);
            EXECUTE format('CREATE INDEX IF NOT EXISTS ix_financial_transactions_related ON %I.financial_transactions (related_type, related_order_id)', s);
            EXECUTE format('CREATE INDEX IF NOT EXISTS ix_financial_transactions_reversal ON %I.financial_transactions (reversal_of_id)', s);
        END IF;

        IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_schema = s AND table_name = 'inventory_transactions') THEN
            EXECUTE format('CREATE INDEX IF NOT EXISTS ix_inventory_transactions_related ON %I.inventory_transactions (related_type, related_order_id)', s);
        END IF;
    END LOOP;
END $$;


-- ---------------------------------------------------------------------------
-- 5. 回填（只做"能 100% 确定"的那两类，其余留给人工认领）
-- ---------------------------------------------------------------------------

-- 5.1 开票时间：issue_date 是 'YYYY-MM-DD' 字符串，直接转成当天 0 点。
--     只填 IS NULL 的行，重复执行无副作用。
DO $$
DECLARE
    s text;
    n integer;
BEGIN
    FOREACH s IN ARRAY ARRAY['public', 'co_02', 'co_03'] LOOP
        IF NOT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_schema = s AND table_name = 'invoices') THEN
            CONTINUE;
        END IF;
        EXECUTE format($f$
            UPDATE %I.invoices
               SET issued_at = (issue_date::date)::timestamptz
             WHERE issued_at IS NULL
               AND issue_date ~ '^[0-9]{4}-[0-9]{2}-[0-9]{2}'
        $f$, s);
        GET DIAGNOSTICS n = ROW_COUNT;
        RAISE NOTICE '[回填] %: invoices.issued_at 填了 % 行', s, n;
    END LOOP;
END $$;

-- 5.2 合同锚点：只有 contracts.order_id 已经指向销售单时才回填（实测当前 0 行，
--     但这句必须留——以后合同从订单生成时就会自动带过来，脚本要幂等可复用）。
DO $$
DECLARE
    s text;
    n integer;
BEGIN
    FOREACH s IN ARRAY ARRAY['public', 'co_02', 'co_03'] LOOP
        IF NOT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_schema = s AND table_name = 'sales_orders') THEN
            CONTINUE;
        END IF;
        IF NOT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_schema = s AND table_name = 'contracts') THEN
            CONTINUE;
        END IF;
        EXECUTE format($f$
            UPDATE %I.sales_orders so
               SET contract_id = c.id,
                   contract_no = c.contract_no
              FROM %I.contracts c
             WHERE c.order_id = so.id
               AND so.contract_id IS NULL
        $f$, s, s);
        GET DIAGNOSTICS n = ROW_COUNT;
        RAISE NOTICE '[回填] %: sales_orders.contract_id 填了 % 行（按 contracts.order_id 反查）', s, n;
    END LOOP;
END $$;

-- 5.3 ⚠️ 刻意**不自动回填** invoices.sales_order_id。
--     唯一可用的判据是"客户名 + 金额 + 期间"，而客户名现在就对不上（见 §2 说明），
--     自动匹配的错票会直接算错「未开票金额」，比留空危险得多。
--     第二阶段提供"候选认领"界面，由人点一下确认。
--     下面这条查询可以先把候选捞出来看一眼（只读，不写库）：
--
--     SELECT i.invoice_no, i.counterparty_name, i.total_amount, i.issue_date,
--            so.order_no, so.total_amount AS order_amount
--       FROM public.invoices i
--       LEFT JOIN public.sales_orders so
--              ON so.customer_id = i.customer_id
--             AND abs(so.total_amount - i.total_amount) < 0.01
--      WHERE i.direction = 'output' AND i.sales_order_id IS NULL;


COMMIT;


-- ---------------------------------------------------------------------------
-- 6. 验收：执行完跑这三段，结果贴给架构评审
-- ---------------------------------------------------------------------------

-- 6.1 新增列是否三套 schema 都齐（期望每列 3 行）
SELECT table_name, column_name, data_type, is_nullable, column_default
  FROM information_schema.columns
 WHERE table_schema IN ('public', 'co_02', 'co_03')
   AND (   (table_name = 'sales_orders' AND column_name IN
            ('contract_id','contract_no','shipped_at','signed_at','signed_by','logistics_no','logistics_company'))
        OR (table_name = 'invoices' AND column_name IN
            ('issued_at','receiver','verified','verified_at','sales_order_id','purchase_order_id'))
        OR (table_name = 'financial_transactions' AND column_name IN
            ('payment_method','voucher_no'))
       )
 ORDER BY table_name, column_name, table_schema;

-- 6.2 行数没变（与执行前 NOTICE 打印的数字对照）
SELECT 'public' AS schema, (SELECT count(*) FROM public.sales_orders) AS sales_orders,
       (SELECT count(*) FROM public.invoices) AS invoices,
       (SELECT count(*) FROM public.financial_transactions) AS finance,
       (SELECT count(*) FROM public.inventory_transactions) AS inventory;

-- 6.3 回填效果
SELECT count(*) AS 发票总数,
       count(*) FILTER (WHERE issued_at IS NOT NULL) AS 已填开票时间,
       count(*) FILTER (WHERE sales_order_id IS NOT NULL) AS 已挂销售单,
       count(*) FILTER (WHERE verified) AS 已认证
  FROM public.invoices;
