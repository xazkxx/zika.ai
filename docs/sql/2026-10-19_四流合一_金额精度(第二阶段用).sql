-- ============================================================================
-- 四流合一 · 金额精度升级（⚠️ 第二阶段专用，**现在不要执行**）
--
-- 为什么单独一份文件：这份脚本会把 4 类表的金额列从 double precision 改成
-- numeric(14,2)。DB 改完，psycopg 返回的就是 Decimal 而不是 float，
-- 而 Python 里 `Decimal * float` 会直接抛 TypeError —— 只要有一处没改模型，
-- 生产就会在"保存单据"这一步炸。所以它必须与第二阶段
-- 「模型 Float → Numeric + 金额运算全量排查」同一次上线，不能单独跑。
--
-- 现状体检结论（2026-10-19 实测 public 账套）：
--   · sales_orders / sales_order_items / purchase_orders / purchase_order_items
--     / invoices / financial_transactions 的金额列**全是 double precision**
--   · statements(10 个金额列) 与 contracts.total_amount 已经是 numeric(12,2) ✅
--   · 当前库里没有 >2 位小数的脏值（0 行），所以这次迁移是"干净数据 + 换类型"
--
-- 口径（沿用项目既有铁律，别改）：
--   · **钱**（金额/合计/税额/已收已付/欠款）→ numeric(14,2)
--   · **费率**（单价/数量）→ numeric(14,4)，最多 4 位**且不截断**
--     （73.901 × 580 = 42862.58；抹成 73.90 就变成 42862.00）
--   · 税率 tax_rate 是百分比，保持 double precision，不在本次迁移范围
--
-- 回滚（万一上线后异常）：
--   ALTER TABLE xxx ALTER COLUMN yyy TYPE double precision USING yyy::double precision;
--
-- 执行顺序建议：
--   1. 先跑 §0 预检（只读），确认没有超出 precision 的脏值
--   2. 模型层改完 + 单测全绿 + 构建通过
--   3. 停服 → pg_dump 备份 → 执行 §1 → 重启 → 跑对账回归
-- ============================================================================


-- ---------------------------------------------------------------------------
-- 0. 预检（只读）：有没有超出 numeric(14,2) 的脏值、有没有 >2 位小数
--    期望：三列都为 0，否则先人工处理再迁移
-- ---------------------------------------------------------------------------
SELECT 'sales_orders.total_amount' AS col,
       count(*) FILTER (WHERE abs(total_amount) >= 1e12) AS 超精度,
       count(*) FILTER (WHERE total_amount <> round(total_amount::numeric, 2)) AS 超两位小数
  FROM public.sales_orders
UNION ALL
SELECT 'invoices.total_amount',
       count(*) FILTER (WHERE abs(total_amount) >= 1e12),
       count(*) FILTER (WHERE total_amount <> round(total_amount::numeric, 2))
  FROM public.invoices
UNION ALL
SELECT 'financial_transactions.amount',
       count(*) FILTER (WHERE abs(amount) >= 1e12),
       count(*) FILTER (WHERE amount <> round(amount::numeric, 2))
  FROM public.financial_transactions;


-- ---------------------------------------------------------------------------
-- 1. 类型迁移（默认整段注释掉，确认后再放开）
-- ---------------------------------------------------------------------------
-- BEGIN;
--
-- DO $$
-- DECLARE
--     s text;
-- BEGIN
--     FOREACH s IN ARRAY ARRAY['public', 'co_02', 'co_03'] LOOP
--
--         -- ---- 销售单头：钱 → 2 位 ----
--         IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_schema = s AND table_name = 'sales_orders') THEN
--             EXECUTE format($q$
--                 ALTER TABLE %I.sales_orders
--                     ALTER COLUMN total_amount       TYPE numeric(14,2) USING round(total_amount::numeric, 2),
--                     ALTER COLUMN receivable_amount  TYPE numeric(14,2) USING round(receivable_amount::numeric, 2),
--                     ALTER COLUMN discount_amount    TYPE numeric(14,2) USING round(discount_amount::numeric, 2),
--                     ALTER COLUMN received_amount    TYPE numeric(14,2) USING round(received_amount::numeric, 2),
--                     ALTER COLUMN current_debt       TYPE numeric(14,2) USING round(current_debt::numeric, 2),
--                     ALTER COLUMN prev_debt          TYPE numeric(14,2) USING round(prev_debt::numeric, 2),
--                     ALTER COLUMN total_debt         TYPE numeric(14,2) USING round(total_debt::numeric, 2)
--             $q$, s);
--         END IF;
--
--         -- ---- 销售明细：金额 2 位、单价 4 位（单价是费率，不许截断）----
--         IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_schema = s AND table_name = 'sales_order_items') THEN
--             EXECUTE format($q$
--                 ALTER TABLE %I.sales_order_items
--                     ALTER COLUMN amount     TYPE numeric(14,2) USING round(amount::numeric, 2),
--                     ALTER COLUMN unit_price TYPE numeric(14,4) USING round(unit_price::numeric, 4)
--             $q$, s);
--         END IF;
--
--         -- ---- 采购侧对称（金额口径必须两边一致，否则对账会出现一边有分一边没有）----
--         IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_schema = s AND table_name = 'purchase_orders') THEN
--             EXECUTE format($q$
--                 ALTER TABLE %I.purchase_orders
--                     ALTER COLUMN total_amount      TYPE numeric(14,2) USING round(total_amount::numeric, 2),
--                     ALTER COLUMN payable_amount    TYPE numeric(14,2) USING round(payable_amount::numeric, 2),
--                     ALTER COLUMN discount_amount   TYPE numeric(14,2) USING round(discount_amount::numeric, 2),
--                     ALTER COLUMN paid_amount       TYPE numeric(14,2) USING round(paid_amount::numeric, 2),
--                     ALTER COLUMN current_debt      TYPE numeric(14,2) USING round(current_debt::numeric, 2),
--                     ALTER COLUMN prev_debt         TYPE numeric(14,2) USING round(prev_debt::numeric, 2),
--                     ALTER COLUMN total_debt        TYPE numeric(14,2) USING round(total_debt::numeric, 2)
--             $q$, s);
--         END IF;
--
--         IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_schema = s AND table_name = 'purchase_order_items') THEN
--             EXECUTE format($q$
--                 ALTER TABLE %I.purchase_order_items
--                     ALTER COLUMN amount     TYPE numeric(14,2) USING round(amount::numeric, 2),
--                     ALTER COLUMN unit_price TYPE numeric(14,4) USING round(unit_price::numeric, 4)
--             $q$, s);
--         END IF;
--
--         -- ---- 发票：价税合计 / 税额 / 不含税 → 2 位；税率保持 double ----
--         IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_schema = s AND table_name = 'invoices') THEN
--             EXECUTE format($q$
--                 ALTER TABLE %I.invoices
--                     ALTER COLUMN total_amount     TYPE numeric(14,2) USING round(total_amount::numeric, 2),
--                     ALTER COLUMN tax_amount       TYPE numeric(14,2) USING round(tax_amount::numeric, 2),
--                     ALTER COLUMN excl_tax_amount  TYPE numeric(14,2) USING round(excl_tax_amount::numeric, 2)
--             $q$, s);
--         END IF;
--
--         -- ---- 资金流水：每笔金额 / 实际冲抵额 → 2 位 ----
--         IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_schema = s AND table_name = 'financial_transactions') THEN
--             EXECUTE format($q$
--                 ALTER TABLE %I.financial_transactions
--                     ALTER COLUMN amount         TYPE numeric(14,2) USING round(amount::numeric, 2),
--                     ALTER COLUMN applied_amount TYPE numeric(14,2) USING round(applied_amount::numeric, 2)
--             $q$, s);
--         END IF;
--     END LOOP;
-- END $$;
--
-- COMMIT;


-- ---------------------------------------------------------------------------
-- 2. 迁移后验收
-- ---------------------------------------------------------------------------
-- SELECT table_name, column_name, data_type, numeric_precision, numeric_scale
--   FROM information_schema.columns
--  WHERE table_schema = 'public'
--    AND table_name IN ('sales_orders','sales_order_items','purchase_orders','purchase_order_items','invoices','financial_transactions')
--    AND data_type = 'numeric'
--  ORDER BY table_name, ordinal_position;
--
-- -- 对账闭环：对账单已开票合计 vs 发票合计，必须一分不差
-- SELECT s.statement_no, s.invoiced_amount,
--        coalesce(sum(i.total_amount), 0) AS 发票合计,
--        s.invoiced_amount - coalesce(sum(i.total_amount), 0) AS 差额
--   FROM public.statements s
--   LEFT JOIN public.invoices i ON i.direction = 'output' AND i.customer_id = s.party_id
--  WHERE s.party_type = 'customer'
--  GROUP BY s.id, s.statement_no, s.invoiced_amount;
