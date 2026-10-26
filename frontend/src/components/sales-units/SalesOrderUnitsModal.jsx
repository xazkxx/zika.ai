/**
 * SalesOrderUnitsModal —— 销售出库开单弹窗（第三阶段 3c）
 *
 * ## 它在 3a / 3b 之后补上的那一环
 *
 * 3a 让商品档案能维护「1 箱 = 12 盒」，3b 让采购入库按它换算。
 * 这一步让**销售出库**也按它换算 —— 至此进、销、存三个方向的
 * 「录入单位 → 最小单位」都走同一条路：`_apply_stock`。
 *
 * ## ⚠️ 一条硬纪律：请求体里没有 `factor`
 *
 * `serializeSalesItems()` 只发 `unit`。服务端 `_resolve_unit_factor` 从 `unit`
 * 现场解析换算率。前端算出来的数量**纯展示**。
 * 客户端要是能自己说"我这 3 箱是 3000 盒"，库存就凭空放大 1000 倍 ——
 * 所以后端 `SalesOrderItemCreate` 里连 `unit_factor` 这个字段都不存在。
 *
 * ## 本组件**不做**改单
 *
 * 后端销售开单只有 `POST` / `DELETE` / `PATCH {id}/status`，
 * **没有**改明细的路由。硬做「编辑」只能靠"删了重建"，
 * 那会悄悄换掉单据 id 和开单号，下游引用全部错位。
 * 所以这里只提供：新增 / 删除（自动冲销库存与应收）/ 查看 / 改状态。
 *
 * 依赖：React + `../../lib/salesUnits`。样式复用 `src/styles.css` 的
 * `.erp-form` `.form-row` `.modal-*` 等既有类，本桶只加 `.sunit-` 前缀的那几块。
 */

import { useEffect, useState } from 'react';

import {
  baseQuantity,
  makeEmptySalesLine,
  serializeSalesItems,
  suggestUnitPrice,
  summarizeLines,
  validateSalesLines,
} from '../../lib/salesUnits';
import UnitSelectCell, { BaseQuantityCell } from './UnitSelectCell';
import ErpSearchSelect from '../ui/ErpSearchSelect.jsx';

/** 本地日期（`toISOString` 会按 UTC 走，晚上 8 点后会显示成第二天）。 */
function todayText() {
  const now = new Date();
  const pad = (value) => String(value).padStart(2, '0');
  return `${now.getFullYear()}-${pad(now.getMonth() + 1)}-${pad(now.getDate())}`;
}

function emptyForm() {
  return {
    customer_id: '',
    warehouse_id: '',
    order_date: todayText(),
    payment_method: '',
    note: '',
    items: [makeEmptySalesLine()],
  };
}

/**
 * 把 FastAPI 的错误体变成一句能看的中文。
 *
 * 校验失败时 `detail` 是**数组**（`[{loc, msg, type}, …]`），
 * 业务错误时是**字符串**。直接 `String(detail)` 会得到 `[object Object]` ——
 * 用户看到的就是"保存失败"，然后没有任何线索。
 */
function readError(data, fallback) {
  const detail = data && data.detail;
  if (typeof detail === 'string' && detail.trim()) return detail;
  if (Array.isArray(detail) && detail.length) {
    const text = detail
      .map((item) => {
        const loc = Array.isArray(item && item.loc)
          ? item.loc.filter((part) => part !== 'body' && part !== 'query').join('.')
          : '';
        const msg = (item && item.msg) || '';
        if (!msg) return '';
        // Pydantic 的英文 msg 混在里面，至少把字段位置点出来
        return loc ? `${loc}：${msg}` : msg;
      })
      .filter(Boolean)
      .join('；');
    if (text) return text;
  }
  return fallback;
}

export default function SalesOrderUnitsModal({
  open,
  onClose,
  customers = [],
  warehouses = [],
  products = [],
  /** `Map<string, options[]>`（或普通对象）—— 已加载过单位的商品才有 */
  optionsByProduct,
  /**
   * `(productIds: string[]) => Promise<Map<string, options[]>>`
   *
   * ⚠️ **必须返回最新的完整映射**，不能只是"加载完就 resolve"。
   * 校验发生在 `await` 之后，那时 props 上的 `optionsByProduct` 还是**旧的**
   * （React 还没重渲染），拿它去校验会把合法的单位判成"不存在"。
   */
  ensureUnits,
  /** `(productId: string) => void` —— 选中商品时触发拉单位 */
  onProductPick,
  /** `(warehouseId: string) => void` —— 换仓库时重新读现存量 */
  onWarehouseChange,
  /** `Map<number, number>`：该仓库下 product_id → 现存量（最小单位） */
  stockByProduct,
  /** 现存量是否已就绪。未就绪时库存提示显示 —，不显示 0。 */
  stockReady = false,
  apiBase,
  authHeaders,
  /** `(order) => void` */
  onSaved,
  /** `(message) => void` */
  onError,
}) {
  const [form, setForm] = useState(emptyForm);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');

  // 每次打开都从干净的表单开始 —— 否则上一次的明细会留在里面，
  // 用户以为"新开一张"，实际提交的是上一张的残留。
  useEffect(() => {
    if (open) {
      setForm(emptyForm());
      setError('');
      setSaving(false);
    }
  }, [open]);

  if (!open) return null;

  const productMap = new Map(products.map((item) => [String(item.id), item]));
  const optionsFor = (productId) => {
    if (!optionsByProduct) return [];
    const key = String(productId);
    if (typeof optionsByProduct.get === 'function') {
      const hit = optionsByProduct.get(key);
      return Array.isArray(hit) ? hit : [];
    }
    const hit = optionsByProduct[key];
    return Array.isArray(hit) ? hit : [];
  };

  const patchItem = (index, updater) => {
    setForm((prev) => ({
      ...prev,
      items: prev.items.map((row, i) => (i === index ? updater(row) : row)),
    }));
  };

  const patchHeader = (field, value) => {
    setForm((prev) => ({ ...prev, [field]: value }));
  };

  const handleProductChange = (index, productId) => {
    patchItem(index, (row) => {
      // 重复选中同一个商品是无操作 —— 否则会把他刚挑好的「箱」重置回基本单位
      if (String(row.product_id) === String(productId)) return row;
      const product = productMap.get(String(productId)) || null;
      const base = product ? String(product.unit || '').trim() : '';
      const next = { ...row, product_id: productId, unit: base, note: '' };
      // ⚠️ 只有"单价是我们替用户猜的"或"单价还空着"才预填。
      //    用户手填过的价格（`price_auto === false`）绝不能被换商品这个动作覆盖。
      if (row.price_auto !== false || !String(row.unit_price || '').trim()) {
        const price = suggestUnitPrice(optionsFor(productId), base, product);
        next.unit_price = price === null ? '' : String(price);
        next.price_auto = true;
      }
      return next;
    });
    if (productId) onProductPick?.(productId);
  };

  const handleUnitChange = (index, unitName) => {
    patchItem(index, (row) => {
      const product = productMap.get(String(row.product_id)) || null;
      const next = { ...row, unit: unitName };
      // ⚠️ 换单位**必须**跟着换价：录入单位就是计价单位，
      //    「箱 180 元」和「盒 15 元」是同一个东西的两种说法，不换就是 12 倍错价。
      //    但用户手填过的值不动 —— 他可能就是在给这一单单独定价。
      if (row.price_auto !== false || !String(row.unit_price || '').trim()) {
        const price = suggestUnitPrice(optionsFor(row.product_id), unitName, product);
        next.unit_price = price === null ? '' : String(price);
        next.price_auto = true;
      }
      return next;
    });
  };

  const addItem = () => {
    setForm((prev) => ({ ...prev, items: [...prev.items, makeEmptySalesLine()] }));
  };

  const removeItem = (index) => {
    setForm((prev) => {
      if (prev.items.length <= 1) return prev;
      return { ...prev, items: prev.items.filter((_, i) => i !== index) };
    });
  };

  const summary = summarizeLines(form.items, optionsByProduct);
  const baseParts = [];
  summary.baseQtyByProduct.forEach((quantity, productId) => {
    const product = productMap.get(String(productId));
    const unit = product && product.unit ? product.unit : '';
    baseParts.push(`${product ? product.name : productId} ${quantity}${unit ? ` ${unit}` : ''}`);
  });

  const handleSubmit = async (event) => {
    event.preventDefault();
    if (saving) return;
    setError('');

    if (!form.customer_id) {
      setError('请先选择客户');
      return;
    }

    const picked = form.items.map((row) => row.product_id).filter(Boolean);

    // 先把单位的选项补齐，再校验 —— 否则"用户刚选完商品就立刻点保存"会被
    // 误判成"这个商品没有该单位"。
    let freshOptions = optionsByProduct;
    if (ensureUnits) {
      try {
        freshOptions = await ensureUnits(picked);
      } catch (err) {
        setError(err.message || '加载商品单位失败，无法确认换算率，已阻止提交');
        return;
      }
    }

    const result = validateSalesLines(form.items, freshOptions);
    if (!result.ok) {
      setError(result.error);
      return;
    }

    const body = {
      customer_id: Number(form.customer_id),
      doc_type: 'outbound',
      warehouse_id: form.warehouse_id ? Number(form.warehouse_id) : null,
      order_date: form.order_date || null,
      payment_method: form.payment_method || null,
      note: form.note || null,
      // ⚠️ 只有 unit，没有 factor
      items: serializeSalesItems(form.items),
    };

    setSaving(true);
    try {
      const response = await fetch(`${apiBase}/sales-orders`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          ...(typeof authHeaders === 'function' ? authHeaders() : {}),
        },
        body: JSON.stringify(body),
      });
      const data = await response.json().catch(() => ({}));
      if (!response.ok) {
        throw new Error(readError(data, `保存失败（HTTP ${response.status}）`));
      }
      onSaved?.(data);
    } catch (err) {
      const message = err.message || '保存失败';
      setError(message);
      if (onError) onError(message);
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal-card sunit-modal-card" onClick={(event) => event.stopPropagation()}>
        <div className="modal-header">
          <h2>新增销售出库单</h2>
          <button type="button" className="secondary-btn small-btn" onClick={onClose}>
            关闭
          </button>
        </div>

        <div className="modal-body">
          <form onSubmit={handleSubmit} className="erp-form" data-sunit-form data-doc-form="sales-units">
            <div className="form-row two-col">
              <label>
                客户
                {/* 客户档案可能几百条：平铺下拉改可搜索。`data-sunit-customer` 是测试钩子，
                    通过组件末尾的 ...rest 透传到根节点，别弄丢。 */}
                <ErpSearchSelect
                  options={customers}
                  value={String(form.customer_id ?? '')}
                  onChange={(value) => patchHeader('customer_id', value)}
                  placeholder="搜索客户名称 / 编码"
                  emptyText="没有匹配的客户"
                  getOptionValue={(item) => String(item.id)}
                  getOptionLabel={(item) => (item.code ? `${item.name}（${item.code}）` : item.name)}
                  getSearchText={(item) => [item.name, item.code, item.short_name, item.phone].filter(Boolean).join(' ')}
                  data-sunit-customer
                />
              </label>
              <label>
                出库仓库
                <select
                  value={form.warehouse_id}
                  onChange={(event) => {
                    patchHeader('warehouse_id', event.target.value);
                    // 换了仓库，「现存量 → 出库后」那行必须跟着重算，
                    // 否则用户会把 A 仓的库存当成 B 仓的
                    if (onWarehouseChange) onWarehouseChange(event.target.value);
                  }}
                  data-sunit-warehouse
                >
                  <option value="">请选择仓库</option>
                  {warehouses.map((item) => (
                    <option key={item.id} value={item.id}>
                      {item.name}
                    </option>
                  ))}
                </select>
              </label>
            </div>

            <div className="form-row two-col">
              <label>
                单据日期
                <input
                  type="date"
                  value={form.order_date}
                  onChange={(event) => patchHeader('order_date', event.target.value)}
                />
              </label>
              <label>
                收款方式
                <input
                  list="lookup-payment-method"
                  value={form.payment_method}
                  onChange={(event) => patchHeader('payment_method', event.target.value)}
                  placeholder="如：现金 / 微信 / 月结30天"
                />
              </label>
            </div>

            <label>
              备注
              <input
                value={form.note}
                onChange={(event) => patchHeader('note', event.target.value)}
                placeholder="如：送货地址、客户要求"
              />
            </label>

            <div className="section-header">
              <h3>商品明细</h3>
              <button
                type="button"
                className="secondary-btn small-btn"
                onClick={addItem}
                data-sunit-add
              >
                + 添加一行
              </button>
            </div>

            {form.items.map((row, index) => {
              const product = productMap.get(String(row.product_id)) || null;
              const options = optionsFor(row.product_id);
              const baseUnit = product ? String(product.unit || '') : '';
              // ⚠️ 这里**必须**调 `baseQuantity()`，不能自己再写一遍 `数量 × factor`。
              //    反证实验暴露过这一点：把 lib 的乘法改成除法时，
              //    「实际出库」那一格（走 lib）红了，而下面这条库存提示
              //    （自己乘了一遍）**照样绿** —— 同一份换算逻辑写两遍，
              //    改坏一处另一处就成了假绿的保护伞。数量口径只能有一个出处。
              const factorRow = options.find((option) => option.name === row.unit);
              const baseQty = factorRow ? baseQuantity(row.quantity, factorRow.factor) : null;
              const convertedQty = factorRow && factorRow.factor > 1 ? baseQty : null;
              const onHand =
                product && stockByProduct ? stockByProduct.get(Number(product.id)) : undefined;
              const after =
                convertedQty !== null && onHand !== undefined ? onHand - convertedQty : null;

              return (
                <div className="form-row sunit-line-row" key={index} data-sunit-row={index}>
                  <label>
                    商品
                                        <ErpSearchSelect
                      options={products}
                      value={String(row.product_id ?? '')}
                      onChange={(value) => handleProductChange(index, value)}
                      placeholder="搜索商品名称 / SKU"
                      emptyText="没有匹配的商品"
                      getOptionValue={(item) => String(item.id)}
                      getOptionLabel={(item) => item.name}
                      getSearchText={(item) => [item.name, item.sku, item.mnemonic, item.code, item.bar_code].filter(Boolean).join(' ')}
                      data-sunit-product={index}
                    />
                    <span className="sunit-unit-hint" data-sunit-stock={index}>
                      {!product
                        ? ''
                        : !form.warehouse_id
                          ? '选择出库仓库后显示现存量'
                          : !stockReady
                            ? '正在读取现存量…'
                            : onHand === undefined
                              ? `该仓暂无此商品库存记录（现存量 0 ${baseUnit}）`
                              : after === null
                                ? `现存量 ${onHand} ${baseUnit}`
                                : `现存量 ${onHand} ${baseUnit} → 出库后 ${after} ${baseUnit}` +
                                  (after < 0 ? '（将出现负库存，系统允许但会标红）' : '')}
                    </span>
                  </label>

                  <UnitSelectCell
                    options={options}
                    baseUnit={baseUnit}
                    value={row.unit}
                    onChange={(unitName) => handleUnitChange(index, unitName)}
                    disabled={!row.product_id}
                    rowIndex={index}
                  />

                  <label>
                    数量
                    <input
                      type="number"
                      min="1"
                      step="1"
                      value={row.quantity}
                      onChange={(event) =>
                        patchItem(index, (prev) => ({ ...prev, quantity: event.target.value }))
                      }
                      data-sunit-quantity={index}
                    />
                  </label>

                  <label>
                    单价
                    <input
                      type="number"
                      step="any"
                      value={row.unit_price}
                      onChange={(event) =>
                        patchItem(index, (prev) => ({
                          ...prev,
                          unit_price: event.target.value,
                          // 用户动过这个框 → 从此归他所有，换单位也不许覆盖
                          price_auto: false,
                        }))
                      }
                      data-sunit-price={index}
                    />
                  </label>

                  <BaseQuantityCell
                    options={options}
                    baseUnit={baseUnit}
                    unit={row.unit}
                    quantity={row.quantity}
                    disabled={!row.product_id}
                    rowIndex={index}
                  />

                  <button
                    type="button"
                    className="danger-btn small-btn row-remove-btn"
                    onClick={() => removeItem(index)}
                    disabled={form.items.length <= 1}
                    title={form.items.length <= 1 ? '至少保留一行' : '删除此行'}
                    data-sunit-remove={index}
                  >
                    删行
                  </button>
                </div>
              );
            })}

            <div className="order-items-summary sunit-summary">
              <span className="sunit-summary-main">
                <span>共 {summary.lineCount} 行</span>
                <span className="sunit-summary-muted">·</span>
                <span data-sunit-amount>
                  合计 ¥
                  {summary.amount.toLocaleString(undefined, {
                    minimumFractionDigits: 2,
                    maximumFractionDigits: 2,
                  })}
                </span>
              </span>
              <span className="sunit-summary-base" data-sunit-base-summary>
                {baseParts.length ? `实际出库：${baseParts.join(' · ')}` : '实际出库：—'}
              </span>
            </div>

            {error ? (
              <div className="notice-box" data-sunit-error style={{ marginTop: 12 }}>
                {error}
              </div>
            ) : null}

            <div style={{ display: 'flex', gap: 12, marginTop: 16 }}>
              <button className="primary-btn" type="submit" disabled={saving} data-sunit-submit>
                {saving ? '保存中…' : '保存并出库'}
              </button>
              <button type="button" className="secondary-btn" onClick={onClose} disabled={saving}>
                取消
              </button>
            </div>
          </form>
        </div>
      </div>
    </div>
  );
}
