/**
 * SalesOrderUnitsBoard —— 独立的「销售出库（多单位）」面板（第三阶段 3c）
 *
 * ## 为什么要做成一个**独立组件**
 *
 * `App.jsx` 是 11k 行的单体，任何改动都要先给精确行号才能动。
 * 本组件不 import `App.jsx` 的任何东西、也不被 `App.jsx` import，
 * 只通过 4 个 props（`apiBase` / `authHeaders` / `onError` / `onNotice`）
 * 和外界说话。所以它可以：
 *
 *   · 先在测试台里单独挂载跑通（`verify_3c_frontend/`）；
 *   · 确认无误后，`App.jsx` 那边**一行 import + 一行分发**就接上了。
 *
 * 参考数据（客户/仓库/商品/出库单）全部由本组件自取，不依赖 `ctx` 里
 * 那几十个 App.jsx 的状态 —— 这样它才能在 App.jsx 之外活下来。
 *
 * ## 它只做四种操作，因为后端只有这四种
 *
 * `POST /sales-orders`（开单，真实出库）· `GET`（列表）·
 * `DELETE`（删单，自动冲销库存与应收）· `PATCH {id}/status`（改状态）
 *
 *   ⚠️ **没有"改明细"**。后端没有这个路由。硬做只能"删了重建"，
 *      那会换掉单据 id 和开单号，下游引用全错位。
 *
 * ## 多单位在哪儿体现
 *
 *   ① 明细行有「单位」下拉（`UnitSelectCell`）；
 *   ② 旁边一列实时显示「实际出库（最小单位）」（`BaseQuantityCell`）；
 *   ③ 商品下方实时显示「现存量 → 出库后」（来自 `/inventory/stock`）；
 *   ④ 列表里每张单都能看到「3 箱 ×12 = 36 盒」。
 *
 * 依赖：React + `../../lib/salesUnits` + 同桶组件。无第三方库、无全局污染。
 */

import { useCallback, useEffect, useMemo, useRef, useState } from 'react';

import {
  buildUnitOptions,
} from '../../lib/salesUnits';
import SalesOrderUnitsModal from './SalesOrderUnitsModal';
import './salesUnits.css';

const STATUS_LABELS = {
  draft: '草稿',
  submitted: '已出库',
  completed: '已完成',
  cancelled: '已作废',
};

/** 把 cache 里的原始单位行编成「商品 → 可选单位」。纯函数，方便测。 */
function buildOptionsMap(products, cache) {
  const map = new Map();
  if (!cache || typeof cache.forEach !== 'function') return map;
  const byId = new Map((Array.isArray(products) ? products : []).map((item) => [String(item.id), item]));
  cache.forEach((rows, key) => {
    map.set(key, buildUnitOptions(byId.get(key) || null, rows));
  });
  return map;
}

/** 把 FastAPI 的错误体变成一句能看的中文（与弹窗里那份同源）。 */
function readError(data, fallback) {
  const detail = data && data.detail;
  if (typeof detail === 'string' && detail.trim()) return detail;
  // 结构化 detail（删单被资金流水拦下时后端返回 {code,message,hint}）：
  // 只认字符串的话会退回泛泛的「请求失败（HTTP 409）」，用户等于看不到原因，
  // 就会以为"删成功了但提示怪怪的"。这里把 message + hint 拼成人能读的中文。
  if (detail && typeof detail === 'object' && !Array.isArray(detail)) {
    const text = [detail.message, detail.hint].filter(Boolean).join('；');
    if (text) return text;
  }
  if (Array.isArray(detail) && detail.length) {
    const text = detail
      .map((item) => (item && item.msg) || '')
      .filter(Boolean)
      .join('；');
    if (text) return text;
  }
  return fallback;
}

const money = (value) =>
  `¥${Number(value || 0).toLocaleString('zh-CN', {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  })}`;

/**
 * 一条明细的换算文案：「3 箱 ×12 = 36 盒」。
 *
 * `baseUnit` 得从商品档案里带过来 —— 明细行本身**没有**存基本单位
 * （`sales_order_items` 只有 `unit` 和 `unit_factor`），
 * 不传就只能写出「3 箱 ×12 = 36」，读者不知道 36 是什么。
 *
 * factor ≤ 1 时返回 `null`，让调用方自己决定显示什么（列表里显示"按基本单位"）。
 */
function conversionText(row, baseUnit = '') {
  const quantity = Number(row && row.quantity);
  const factor = Number((row && row.unit_factor) || 1);
  const unit = (row && row.unit) || '';
  if (!Number.isFinite(quantity) || !Number.isFinite(factor) || factor <= 1) return null;
  const suffix = baseUnit ? ` ${baseUnit}` : '';
  return `${quantity} ${unit} ×${factor} = ${quantity * factor}${suffix}`;
}

export default function SalesOrderUnitsBoard({ apiBase, authHeaders, onError, onNotice }) {
  const [customers, setCustomers] = useState([]);
  const [warehouses, setWarehouses] = useState([]);
  const [products, setProducts] = useState([]);
  const [orders, setOrders] = useState([]);

  const [loading, setLoading] = useState(true);
  const [listError, setListError] = useState('');
  const [notice, setNotice] = useState('');

  const [modalOpen, setModalOpen] = useState(false);
  const [detailOrder, setDetailOrder] = useState(null);

  const [stockByProduct, setStockByProduct] = useState(() => new Map());
  const [stockReady, setStockReady] = useState(false);

  // 单位缓存：ref 因为它是"跨渲染的纯缓存"，不需要因为写入而触发额外的状态机；
  // 但**必须**有一个 epoch 去驱动重渲染，否则界面永远停在"还没加载单位"的样子。
  const unitCacheRef = useRef(new Map());
  const inflightRef = useRef(new Map());
  const [unitEpoch, setUnitEpoch] = useState(0);

  const auth = useCallback(
    () => (typeof authHeaders === 'function' ? authHeaders() : {}),
    [authHeaders]
  );

  const fetchJson = useCallback(
    async (path, options) => {
      const response = await fetch(`${apiBase}${path}`, {
        ...options,
        headers: {
          Accept: 'application/json',
          ...(options && options.body ? { 'Content-Type': 'application/json' } : {}),
          ...auth(),
          ...((options && options.headers) || {}),
        },
      });
      const data = await response.json().catch(() => null);
      if (!response.ok) {
        throw new Error(readError(data, `请求失败（HTTP ${response.status}）`));
      }
      return data;
    },
    [apiBase, auth]
  );

  const loadReference = useCallback(async () => {
    setLoading(true);
    setListError('');
    try {
      const [customerRows, warehouseRows, productRows, orderRows] = await Promise.all([
        fetchJson('/customers'),
        fetchJson('/warehouses'),
        fetchJson('/products'),
        // 只取真实出库（doc_type=outbound）；销售订单是另一套，不混进来
        fetchJson('/sales-orders?doc_type=outbound'),
      ]);
      setCustomers(Array.isArray(customerRows) ? customerRows : []);
      setWarehouses(Array.isArray(warehouseRows) ? warehouseRows : []);
      setProducts(Array.isArray(productRows) ? productRows : []);
      setOrders(Array.isArray(orderRows) ? orderRows : []);
    } catch (err) {
      setListError(err.message || '加载基础数据失败');
      if (onError) onError(err.message || '加载基础数据失败');
    } finally {
      setLoading(false);
    }
  }, [fetchJson, onError]);

  useEffect(() => {
    loadReference();
  }, [loadReference]);

  /** 拉某商品的辅助单位，带缓存 + 并发去重（同一商品被两行同时选中时只发一次）。 */
  const loadUnits = useCallback(
    async (productId) => {
      const key = String(productId ?? '');
      if (!key) return [];
      if (unitCacheRef.current.has(key)) return unitCacheRef.current.get(key);
      if (inflightRef.current.has(key)) return inflightRef.current.get(key);

      const task = (async () => {
        const rows = await fetchJson(`/products/${key}/units`);
        const list = Array.isArray(rows) ? rows : [];
        unitCacheRef.current.set(key, list);
        setUnitEpoch((value) => value + 1);
        return list;
      })();

      inflightRef.current.set(key, task);
      try {
        return await task;
      } catch (err) {
        // 失败的**不写缓存**：否则用户改完档案回来还是那份空表，
        // 界面会一直说"这个商品没有单位"而没有任何线索。
        throw err;
      } finally {
        inflightRef.current.delete(key);
      }
    },
    [fetchJson]
  );

  /**
   * 提交前把要用到的单位全部补齐，并**返回补齐后的完整映射**。
   *
   * ⚠️ 返回值不能省。校验发生在 `await` 之后，那时 `optionsByProduct`
   * （render 期算出来的）还是旧的快照 —— 拿它校验会把用户刚选好的
   * 合法单位判成"不存在"，然后弹一句莫名其妙的错误。
   */
  const ensureUnits = useCallback(
    async (productIds) => {
      const unique = Array.from(new Set((productIds || []).map((id) => String(id)).filter(Boolean)));
      await Promise.all(unique.map((id) => loadUnits(id)));
      return buildOptionsMap(products, unitCacheRef.current);
    },
    [loadUnits, products]
  );

  /** 取某仓库的现存量。`warehouseId` 为空时不猜 —— 宁可显示 —，也不显示一个错的数。 */
  const loadStock = useCallback(
    async (warehouseId) => {
      if (!warehouseId) {
        setStockByProduct(new Map());
        setStockReady(false);
        return;
      }
      setStockReady(false);
      try {
        const data = await fetchJson(`/inventory/stock?warehouse_id=${encodeURIComponent(warehouseId)}`);
        const rows = Array.isArray(data) ? data : (data && data.rows) || [];
        const map = new Map();
        for (const row of rows) {
          map.set(Number(row.product_id), Number(row.quantity || 0));
        }
        setStockByProduct(map);
        setStockReady(true);
      } catch (err) {
        setStockReady(false);
        if (onError) onError(err.message || '读取现存量失败');
      }
    },
    [fetchJson, onError]
  );

  // 缓存是 ref —— 靠 epoch 才能重算。第二项依赖没有"被用掉"的话，
  // 用户选完商品会看到单位下拉一直是空的。
  const optionsByProduct = useMemo(
    () => buildOptionsMap(products, unitCacheRef.current),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [products, unitEpoch]
  );

  const customerName = useCallback(
    (id) => {
      const hit = customers.find((item) => Number(item.id) === Number(id));
      return hit ? hit.name : `#${id}`;
    },
    [customers]
  );

  /** 商品档案按 id 索引 —— 列表的换算列要靠它拿到基本单位 */
  const productsById = useMemo(
    () => new Map(products.map((item) => [Number(item.id), item])),
    [products]
  );
  const baseUnitOf = useCallback(
    (productId) => {
      const product = productsById.get(Number(productId));
      return (product && product.unit) || '';
    },
    [productsById]
  );

  /**
   * ⚠️ `loadUnits` 是异步的，而它在 `handleProductChange` 里是**点火不管结果**地调用。
   * 直接把 `loadUnits` 交出去，接口一挂就会产生一个未处理的 Promise rejection
   * （浏览器红字 + 用户看不到任何提示）。这里显式 catch 并转成界面提示。
   *
   * 注意：失败**不**阻止用户继续填单 —— 真正拦住"换算率不明就提交"的是
   * 提交时的 `ensureUnits()`，那里才是必须成功的一步。
   */
  const handleProductPick = useCallback(
    (productId) => {
      loadUnits(productId).catch((err) => {
        const message = err.message || '加载商品辅助单位失败';
        setListError(message);
        if (onError) onError(message);
      });
    },
    [loadUnits, onError]
  );

  const openModal = () => {
    setNotice('');
    setStockByProduct(new Map());
    setStockReady(false);
    setModalOpen(true);
  };

  const handleSaved = useCallback(
    (order) => {
      setModalOpen(false);
      const text = `已出库：${order.order_no} · ${money(order.total_amount)}`;
      setNotice(text);
      if (onNotice) onNotice(text);
      // 单据与库存都要重新读 —— 只更新本地 list 会让"出库后余量"停在旧数
      loadReference();
      setStockByProduct(new Map());
      setStockReady(false);
    },
    [loadReference, onNotice]
  );

  const handleDelete = useCallback(
    async (order) => {
      const ok =
        typeof window === 'undefined' || typeof window.confirm !== 'function'
          ? true
          : window.confirm(
              `确认删除出库单 ${order.order_no}？\n\n` +
                '该单产生的库存流水与应收会一并冲销，删除后无法恢复。'
            );
      if (!ok) return;
      try {
        await fetchJson(`/sales-orders/${order.id}`, { method: 'DELETE' });
        setNotice(`已删除 ${order.order_no}，库存与应收已冲销`);
        loadReference();
      } catch (err) {
        setListError(err.message || '删除失败');
      }
    },
    [fetchJson, loadReference]
  );

  const handleStatus = useCallback(
    async (order, status) => {
      try {
        await fetchJson(`/sales-orders/${order.id}/status`, {
          method: 'PATCH',
          body: JSON.stringify({ status }),
        });
        setNotice(`${order.order_no} 状态已改为「${STATUS_LABELS[status] || status}」`);
        loadReference();
      } catch (err) {
        setListError(err.message || '修改状态失败');
      }
    },
    [fetchJson, loadReference]
  );

  return (
    <section className="panel" data-sunit-board>
      <div className="section-header">
        <div className="sunit-head-left">
          <h2>销售出库（多单位）</h2>
          <span className="status-badge">真实出库 · 写库存与应收 · 按辅助单位换算</span>
        </div>
        <div style={{ display: 'flex', gap: 8 }}>
          <button type="button" className="secondary-btn small-btn" onClick={loadReference} disabled={loading}>
            刷新
          </button>
          <button type="button" className="primary-btn small-btn" onClick={openModal} data-sunit-new>
            + 新增销售出库单
          </button>
        </div>
      </div>

      {listError ? (
        <div className="notice-box" data-sunit-list-error style={{ marginBottom: 12 }}>
          {listError}
        </div>
      ) : null}
      {notice ? (
        <div className="notice-box" data-sunit-notice style={{ marginBottom: 12 }}>
          {notice}
        </div>
      ) : null}

      {loading ? (
        <div className="empty-state">正在加载…</div>
      ) : orders.length === 0 ? (
        <div className="empty-state" data-sunit-empty>
          暂无销售出库单。点右上角「新增销售出库单」开第一张 ——
          选好商品后可以切「箱」「大箱」等辅助单位，右侧会实时显示实际出库的最小单位数量。
        </div>
      ) : (
        <div className="wide-table-wrap">
          <table className="data-table wide-table" data-sunit-table>
            <thead>
              <tr>
                <th>出库单号</th>
                <th>客户</th>
                <th>日期</th>
                <th>明细</th>
                <th>换算</th>
                <th>合计金额</th>
                <th>状态</th>
                <th>操作</th>
              </tr>
            </thead>
            <tbody>
              {orders.map((order) => {
                const converted = (order.items || [])
                  .map((row) => conversionText(row, baseUnitOf(row.product_id)))
                  .filter(Boolean);
                return (
                  <tr key={order.id} data-sunit-order={order.id}>
                    <td>{order.order_no}</td>
                    <td>{customerName(order.customer_id)}</td>
                    <td>{order.order_date || '—'}</td>
                    <td>{(order.items || []).length} 行</td>
                    <td>
                      {converted.length === 0 ? (
                        <span className="sunit-summary-muted">按基本单位</span>
                      ) : (
                        <div className="sunit-list-conv">
                          <strong>{converted[0]}</strong>
                          {converted.length > 1 ? (
                            <small>另有 {converted.length - 1} 行按辅助单位换算</small>
                          ) : null}
                        </div>
                      )}
                    </td>
                    <td>{money(order.total_amount)}</td>
                    <td>
                      <span className="status-badge">
                        {STATUS_LABELS[order.status] || order.status}
                      </span>
                    </td>
                    <td>
                      <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
                        <button
                          type="button"
                          className="secondary-btn small-btn"
                          onClick={() => setDetailOrder(order)}
                        >
                          明细
                        </button>
                        {order.status !== 'completed' ? (
                          <button
                            type="button"
                            className="secondary-btn small-btn"
                            onClick={() => handleStatus(order, 'completed')}
                          >
                            完成
                          </button>
                        ) : null}
                        <button
                          type="button"
                          className="danger-btn small-btn"
                          onClick={() => handleDelete(order)}
                        >
                          删除
                        </button>
                      </div>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}

      <SalesOrderUnitsModal
        open={modalOpen}
        onClose={() => setModalOpen(false)}
        customers={customers}
        warehouses={warehouses}
        products={products}
        optionsByProduct={optionsByProduct}
        ensureUnits={ensureUnits}
        onProductPick={handleProductPick}
        onWarehouseChange={loadStock}
        stockByProduct={stockByProduct}
        stockReady={stockReady}
        apiBase={apiBase}
        authHeaders={authHeaders}
        onSaved={handleSaved}
        onError={onError}
      />

      {detailOrder ? (
        <div className="modal-overlay" onClick={() => setDetailOrder(null)}>
          <div className="modal-card sunit-modal-card" onClick={(event) => event.stopPropagation()}>
            <div className="modal-header">
              <h2>
                出库单明细 · {detailOrder.order_no}
                <span className="status-badge" style={{ marginLeft: 10 }}>
                  {STATUS_LABELS[detailOrder.status] || detailOrder.status}
                </span>
              </h2>
              <button type="button" className="secondary-btn small-btn" onClick={() => setDetailOrder(null)}>
                关闭
              </button>
            </div>
            <div className="modal-body">
              <div className="wide-table-wrap">
                <table className="data-table wide-table">
                  <thead>
                    <tr>
                      <th>商品</th>
                      <th>规格</th>
                      <th>录入数量</th>
                      <th>单位</th>
                      <th>换算率</th>
                      <th>实际出库（最小单位）</th>
                      <th>录入单价</th>
                      <th>最小单位成本</th>
                      <th>金额</th>
                    </tr>
                  </thead>
                  <tbody>
                    {(detailOrder.items || []).map((row) => {
                      const factor = Number(row.unit_factor || 1);
                      const quantity = Number(row.quantity || 0);
                      const price = Number(row.unit_price || 0);
                      return (
                        <tr key={row.id}>
                          <td>{row.product_name}</td>
                          <td>{row.standards || '—'}</td>
                          <td>{quantity}</td>
                          <td>{row.unit || '—'}</td>
                          <td>{factor > 1 ? `×${factor}` : '—'}</td>
                          <td>
                            <strong>{quantity * factor}</strong>
                          </td>
                          <td>{money(price)}</td>
                          <td>{money(factor > 1 ? price / factor : price)}</td>
                          <td>{money(row.amount)}</td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
              <div className="sunit-detail-total">
                <span>应收：{money(detailOrder.receivable_amount)}</span>
                <span>实收：{money(detailOrder.received_amount)}</span>
                <span>本次欠款：{money(detailOrder.current_debt)}</span>
              </div>
            </div>
          </div>
        </div>
      ) : null}
    </section>
  );
}
