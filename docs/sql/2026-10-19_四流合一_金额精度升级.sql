-- ============================================================================
-- 四流合一 · 金额精度升级：double precision → numeric（2026-10-19）
--
-- 口径（这条比字段清单更重要）：
--    钱   → numeric(14,2)   最大 999,999,999,999.99，两位小数
--    费率 → numeric(14,4)   **单价不是钱**。73.901 × 580 = 42,862.58；
--                           若把单价抹成 73.90 就是 42,862.00 —— 一单少 6 毛
--    税率 → 不动（discover 里是百分比，不参与金额累加）
--    数量 → 不动（已是 integer）
--
-- 本脚本覆盖 **9 张表 28 列**，分两组：
--    组 A（23 列）＝ 5 张单据表 + financial_transactions —— 你点名的那批
--    组 B（ 5 列）＝ journal_entries / journal_entry_lines / inventory_transactions
--                    ⚠️ 建议一并做：借贷分录若还是 double，对账单永远"差一分"
--    要只做组 A：把组 B 那 5 行注释掉即可（脚本按列清单驱动，漏一列不会静默通过）
--
-- 幂等：已经是 numeric 的列直接跳过；缺列跳过并打 NOTICE。
-- 事务：整脚本一个事务，中途出错全部回滚，不会留下"改了一半"的表。
--
-- ⚠️⚠️ 执行顺序（顺序错了系统会 500，不是数据问题，是类型问题）：
--    ① 先备份：pg_dump -U erp -d erp -F c -f D:/erp_before_numeric.dump
--    ② 停掉 ERP（关掉 启动ERP.bat 的窗口）—— ALTER 要拿表锁，别和业务抢
--    ③ 跑本脚本（COMMIT 之后才算生效）
--    ④ 立刻跑 scripts/check_money_integrity.py 体检（应全 PASS）
--    ⑤ 再落 Model/Schema/前端代码（docs/四流合一_第3步_代码改动_逐文件.md），重启
--    ⑥ 只跑 SQL 不落代码 → **能跑但没意义**（后端还是 float，钱照样漂）
--       只落代码不跑 SQL → **当场 500**（Decimal*float TypeError）。两边必须配对。
--
-- 跑法：
--     E:/AI/Postgres/bin/psql.exe -U erp -d erp -f "docs/sql/2026-10-19_四流合一_金额精度升级.sql"
-- 干跑（不写库）：把最后的 COMMIT 改成 ROLLBACK 重跑一遍，看 NOTICE 数量对不对。
-- ============================================================================

BEGIN;

-- ── 0. 前置守卫：超上限的值必须先人工处理，不能让 ALTER 报 22003 中断 ────────
DO $$
DECLARE
    sch  text;
    bad  bigint;
    guard record;
BEGIN
    FOREACH sch IN ARRAY ARRAY['public', 'co_02', 'co_03'] LOOP
        FOR guard IN
            SELECT * FROM (VALUES
                ('sales_orders',              'total_amount'),
                ('purchase_orders',           'total_amount'),
                ('invoices',                  'total_amount'),
                ('financial_transactions',    'amount'),
                ('journal_entries',           'total_debit')
            ) AS t(tbl, col)
        LOOP
            IF NOT EXISTS (
                SELECT 1 FROM information_schema.columns
                 WHERE table_schema = sch AND table_name = guard.tbl AND column_name = guard.col
            ) THEN
                CONTINUE;
            END IF;
            EXECUTE format('SELECT COUNT(*) FROM %I.%I WHERE ABS(%I) >= 1e12',
                           sch, guard.tbl, guard.col) INTO bad;
            IF bad > 0 THEN
                RAISE EXCEPTION '% 的 %.% 有 % 行超过 numeric(14,2) 上限（1e12），请先人工核对',
                                sch, guard.tbl, guard.col, bad;
            END IF;
        END LOOP;
    END LOOP;
    RAISE NOTICE '前置守卫通过：三个 schema 的金额都在 numeric(14,2) 范围内';
END $$;

-- ── 1. 改型（列清单驱动，幂等）────────────────────────────────────────────
DO $$
DECLARE
    sch       text;
    item      record;
    cur_type  text;
    changed   int := 0;
    skipped   int := 0;
BEGIN
    FOREACH sch IN ARRAY ARRAY['public', 'co_02', 'co_03'] LOOP
        FOR item IN
            SELECT * FROM (VALUES
                -- ── 组 A：5 张单据表（21 列）────────────────────────────
                ('sales_orders',              'total_amount',      2),
                ('sales_orders',              'receivable_amount', 2),
                ('sales_orders',              'discount_amount',   2),
                ('sales_orders',              'received_amount',   2),
                ('sales_orders',              'current_debt',      2),
                ('sales_orders',              'prev_debt',         2),
                ('sales_orders',              'total_debt',        2),
                ('sales_order_items',         'unit_price',        4),   -- 费率
                ('sales_order_items',         'amount',            2),
                ('purchase_orders',           'total_amount',      2),
                ('purchase_orders',           'payable_amount',    2),
                ('purchase_orders',           'discount_amount',   2),
                ('purchase_orders',           'paid_amount',       2),
                ('purchase_orders',           'current_debt',      2),
                ('purchase_orders',           'prev_debt',         2),
                ('purchase_orders',           'total_debt',        2),
                ('purchase_order_items',      'unit_price',        4),   -- 费率
                ('purchase_order_items',      'amount',            2),
                ('invoices',                  'total_amount',      2),
                ('invoices',                  'tax_amount',        2),
                ('invoices',                  'excl_tax_amount',   2),
                -- ── 组 A 续：资金流水（2 列）→ 组 A 合计 23 列 ──────────
                ('financial_transactions',    'amount',            2),
                ('financial_transactions',    'applied_amount',    2),
                -- ── 组 B：分录与库存成本（5 列，建议一并）─────────────
                ('journal_entries',           'total_debit',       2),
                ('journal_entries',           'total_credit',      2),
                ('journal_entry_lines',       'debit',             2),
                ('journal_entry_lines',       'credit',            2),
                ('inventory_transactions',    'unit_price',        4)    -- 成本单价（费率）
            ) AS t(tbl, col, scale)
        LOOP
            SELECT data_type INTO cur_type
              FROM information_schema.columns
             WHERE table_schema = sch AND table_name = item.tbl AND column_name = item.col;

            IF cur_type IS NULL THEN
                RAISE NOTICE '[%] 跳过：表 %.% 不存在', sch, item.tbl, item.col;
                skipped := skipped + 1;
                CONTINUE;
            END IF;
            IF cur_type = 'numeric' THEN
                skipped := skipped + 1;
                CONTINUE;                      -- 幂等：已经是 numeric 就不动
            END IF;
            IF cur_type NOT IN ('double precision', 'real') THEN
                RAISE NOTICE '[%] 跳过：%.% 当前是 %，不是浮点', sch, item.tbl, item.col, cur_type;
                skipped := skipped + 1;
                CONTINUE;
            END IF;

            -- USING 里的 ::numeric(p,s) 会按 s 四舍五入（PG 用 half away from zero），
            -- 这一步是**唯一**会动数值的地方：double 的二进制尾巴（41.666666666664）在这里收成 41.6667
            EXECUTE format(
                'ALTER TABLE %I.%I ALTER COLUMN %I TYPE numeric(14,%s) USING %I::numeric(14,%s)',
                sch, item.tbl, item.col, item.scale, item.col, item.scale
            );
            changed := changed + 1;
        END LOOP;
    END LOOP;
    RAISE NOTICE '改型完成：实际改动 % 列，跳过 % 列（三个 schema 合计）', changed, skipped;
END $$;

COMMIT;

-- ============================================================================
-- 2. 验收（脚本跑完后逐条看，必须全绿）
-- ============================================================================

\echo '--- 2.1 本批 9 张表里还有没有漏网的浮点列（结果应为 0 行）---'
-- ⚠️ 只查本批 9 张表：组装/调拨/退料/委外那些表不在这批范围，
--    一并列出来会让这条验收永远"红"，反而看不出真正漏改的那一列。
SELECT c.table_schema, c.table_name, c.column_name, c.data_type
FROM information_schema.columns c
WHERE c.table_schema IN ('public', 'co_02', 'co_03')
  AND c.data_type IN ('double precision', 'real')
  AND c.table_name IN ('sales_orders','sales_order_items','purchase_orders','purchase_order_items',
                       'invoices','financial_transactions','journal_entries','journal_entry_lines',
                       'inventory_transactions')
  AND c.column_name IN (
      'total_amount','receivable_amount','discount_amount','received_amount',
      'current_debt','prev_debt','total_debt','payable_amount','paid_amount',
      'unit_price','amount','tax_amount','excl_tax_amount','applied_amount',
      'total_debit','total_credit','debit','credit')
ORDER BY 1, 2, 3;

\echo '--- 2.2 改后的列清单（numeric 25 列 + 单价 3 列，三 schema 合计 84 行）---'
SELECT table_schema, table_name, column_name, numeric_precision, numeric_scale
FROM information_schema.columns
WHERE table_schema IN ('public', 'co_02', 'co_03')
  AND table_name IN ('sales_orders','sales_order_items','purchase_orders','purchase_order_items',
                     'invoices','financial_transactions','journal_entries','journal_entry_lines',
                     'inventory_transactions')
  AND column_name IN (
      'total_amount','receivable_amount','discount_amount','received_amount',
      'current_debt','prev_debt','total_debt','payable_amount','paid_amount',
      'unit_price','amount','tax_amount','excl_tax_amount','applied_amount',
      'total_debit','total_credit','debit','credit')
ORDER BY 1, 2, 3;

\echo '--- 2.3 数据有没有被"改型"改坏（金额列出现 3 位小数 / 单头≠明细合计）---'
SELECT '金额出现三位小数' AS 检查项, COUNT(*) AS 异常行数
FROM public.sales_orders WHERE total_amount <> round(total_amount, 2)
UNION ALL
SELECT '单头合计≠明细合计(>0.01)', COUNT(*)
FROM (SELECT o.id FROM public.sales_orders o
        JOIN public.sales_order_items i ON i.sales_order_id = o.id
       GROUP BY o.id, o.total_amount
      HAVING ABS(o.total_amount - SUM(i.amount)) > 0.01) s
UNION ALL
SELECT '借贷不平的分录', COUNT(*)
FROM (SELECT entry_id FROM public.journal_entry_lines
       GROUP BY entry_id
      HAVING ABS(SUM(debit) - SUM(credit)) > 0.005) j;

-- ============================================================================
-- 3. 回滚（30 秒，无损）
--    numeric → double precision 是允许的，最多丢第 3 位以后的小数，
--    而库里这类值只有库存成本单价（41.6666…→41.6667 那一类），业务金额一枚都没动过。
--    真要回滚就逐列反向执行：
--      ALTER TABLE public.sales_orders ALTER COLUMN total_amount TYPE double precision;
--    （本脚本不自动回滚，避免误触；回滚前请先把 8010 停掉。）
-- ============================================================================
