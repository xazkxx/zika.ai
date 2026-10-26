-- ============================================================================
-- 清理孤儿库存流水（2026-10-19）
--
-- 背景：pytest 跑完后，它的 session 级清理按"测试签名"删掉了测试客户 7021，
-- 并级联删掉该客户名下的出库单 XS20261019001（id=4343）及其明细/财务流水。
-- 但清理脚本 `scripts/clean_test_data.py` 没有覆盖 inventory_transactions 这张表，
-- 于是留下 2 行"指向一张已经不存在的单据"的库存流水：
--
--     id=18343  商品 15317  仓 25  数量 3  单价 150000
--     id=18344  商品 15317  仓 25  数量 2  单价  80000
--
-- 为什么必须清：库存数量是**流水累加**出来的（products 表没有库存列），
-- 这 2 行留着 → 商品 15317 在 25 号仓永远少 5 件，而且点任何单据都查不到来源。
--
-- 跑法（先看影响，再删）：
--     E:/AI/Postgres/bin/psql.exe -U erp -d erp -f docs/sql/2026-10-19_清理孤儿库存流水.sql
-- 整个脚本在一个事务里：第 1 段只 SELECT（看清楚再往下），第 2 段 DELETE，最后 COMMIT。
-- 想先干跑：把最后的 COMMIT 改成 ROLLBACK，重跑一遍看 NOTICE 即可。
-- ============================================================================

BEGIN;

-- ── 1. 影响预览：这 2 行是谁、删掉之后库存会变成多少 ───────────────────────
-- 库存口径 = 同商品同仓库所有流水的数量之和（入库正、出库负，sign 由 transaction_type 决定，
-- 这里直接用 quantity 的原始符号求和，与系统内 _stock_of 保持一致）。
\echo '--- 孤儿流水明细（related_type=sales_out 且订单已不存在）---'
SELECT t.id,
       t.doc_no,
       t.related_order_id AS 订单id,
       p.name             AS 商品,
       t.product_id,
       t.warehouse_id,
       t.transaction_type AS 出入类型,
       t.quantity,
       t.unit_price,
       t.created_at
FROM public.inventory_transactions t
LEFT JOIN public.products p ON p.id = t.product_id
WHERE t.related_type = 'sales_out'
  AND t.related_order_id IS NOT NULL
  AND NOT EXISTS (SELECT 1 FROM public.sales_orders o WHERE o.id = t.related_order_id)
ORDER BY t.id;

\echo '--- 受影响商品的现存量：删前 / 删后 ---'
-- ⚠️ 现存量**不是** quantity 直接相加：符号由 transaction_type 决定
--    （inbound 系列 = +abs(qty)，outbound 系列 = -abs(qty)，见 erp_common._stock_delta）。
--    这 2 行 transaction_type='outbound'、quantity=3/2，所以对现存量的贡献是 -5，
--    删掉之后现存量从 -5 回到 0 —— 正好抵掉"一张不存在的单据造成的负库存"。
WITH delta AS (
    SELECT t.product_id,
           t.warehouse_id,
           CASE
               WHEN lower(t.transaction_type) IN ('inbound','in','purchase','采购入库','盘盈','报溢','调拨入')
                   THEN ABS(t.quantity)
               WHEN lower(t.transaction_type) IN ('outbound','out','sales','销售出库','盘亏','报损','调拨出')
                   THEN -ABS(t.quantity)
               ELSE t.quantity
           END AS signed_qty,
           (t.related_type = 'sales_out'
            AND t.related_order_id IS NOT NULL
            AND NOT EXISTS (SELECT 1 FROM public.sales_orders o WHERE o.id = t.related_order_id)) AS is_orphan
    FROM public.inventory_transactions t
)
SELECT d.product_id,
       p.name AS 商品,
       d.warehouse_id,
       SUM(d.signed_qty)                                  AS 删前现存量,
       SUM(CASE WHEN NOT d.is_orphan THEN d.signed_qty ELSE 0 END) AS 删后现存量
FROM delta d
LEFT JOIN public.products p ON p.id = d.product_id
GROUP BY d.product_id, p.name, d.warehouse_id
HAVING SUM(CASE WHEN d.is_orphan THEN 1 ELSE 0 END) > 0
ORDER BY d.product_id;

-- ⚠️ 看到上面「删后现存量」比「删前」**高** 5 件是对的：那张出库单已经不存在了，
--    它的出库效果本就不该继续生效（现在是 -5 的幽灵负库存，删完回到 0）。
--    如果这两个商品确实已经发货给客户、只是单据被误删，请**别跑第 2 段**，
--    改成补建单据 —— 那种情况属于业务数据丢失，要用建单回补而不是删流水。

-- ── 2. 删除（双条件锁定，宁可删 0 行也不误删）─────────────────────────────
DELETE FROM public.inventory_transactions t
WHERE t.related_type = 'sales_out'
  AND t.related_order_id IS NOT NULL
  AND NOT EXISTS (SELECT 1 FROM public.sales_orders o WHERE o.id = t.related_order_id);

-- ── 3. 后置校验：孤儿必须为 0 ─────────────────────────────────────────────
\echo '--- 剩余孤儿流水（销售出库方向，应为 0）---'
SELECT COUNT(*) AS 剩余孤儿
FROM public.inventory_transactions t
WHERE t.related_type = 'sales_out'
  AND t.related_order_id IS NOT NULL
  AND NOT EXISTS (SELECT 1 FROM public.sales_orders o WHERE o.id = t.related_order_id);

COMMIT;

-- ============================================================================
-- 附：全库孤儿体检（只查不改，想看清楚还有没有别的方向的孤儿就跑这一段）
-- 口径：related_type 决定该去哪张表找"来源单"，找不到的就是孤儿。
-- ============================================================================
-- SELECT 'sales_out' AS 方向, COUNT(*) FROM public.inventory_transactions t
--   WHERE t.related_type='sales_out' AND NOT EXISTS (SELECT 1 FROM public.sales_orders o WHERE o.id=t.related_order_id)
-- UNION ALL
-- SELECT 'purchase_in', COUNT(*) FROM public.inventory_transactions t
--   WHERE t.related_type='purchase_in' AND NOT EXISTS (SELECT 1 FROM public.purchase_orders o WHERE o.id=t.related_order_id)
-- UNION ALL
-- SELECT 'sales_return', COUNT(*) FROM public.inventory_transactions t
--   WHERE t.related_type='sales_return' AND NOT EXISTS (SELECT 1 FROM public.sales_returns o WHERE o.id=t.related_order_id)
-- UNION ALL
-- SELECT 'purchase_return', COUNT(*) FROM public.inventory_transactions t
--   WHERE t.related_type='purchase_return' AND NOT EXISTS (SELECT 1 FROM public.purchase_returns o WHERE o.id=t.related_order_id);
