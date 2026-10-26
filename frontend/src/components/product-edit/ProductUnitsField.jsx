/**
 * ProductUnitsField —— 商品弹窗里的「辅助单位与换算」维护区（第三阶段 3a）
 *
 * ## 它做什么
 *
 * 一张可增删改的表：每行是「单位名 / 换算率 / 进价 / 售价 / 条码 / 默认 / 启用」。
 * 用户在这里维护 1箱=10盒 这类关系，随商品一起保存。
 *
 * ## 它**不**做什么（本阶段刻意划的界）
 *
 * **不参与任何数量计算。** `factor` 在这里只是被录入、校验、展示，
 * 没有任何地方拿它去乘/除一个数量。所以这一步做完，现存量不会因为
 * 配置了辅助单位而变动一个数 —— 出问题的影响面是零。
 * 真正开始按换算率乘数量是 3b（采购入库单）。
 *
 * ## 为什么组件自己发请求（本组件是第二个例外）
 *
 * `ProductEditModal` 的既定边界是"不持有状态、不直接调保存接口"，
 * 唯一例外是图片上传。这里是第二个例外，原因和图片一样：**读一个商品的辅助单位
 * 只需要 productId，不需要任何外部状态**。让组件自己拉，App.jsx 那边
 * 一行都不用改（`openProductEdit` 原本就传了 id / apiBase / authHeaders / onError）。
 * 拉回来的数据仍然通过 `onChange` 交出去 —— 值始终住在 App.jsx 的 `productEdit` 里，
 * 组件自己只留"加载中 / 加载失败"这种转瞬即逝的界面状态。
 *
 * ## ⚠️ 加载失败时**绝不能**提交空表
 *
 * `units` 为 `undefined` 表示"还没拿到"。此时 App.jsx 的 `serializeProductForm`
 * 会**整个略过 `units` 键**，后端 PATCH 用 `exclude_unset` 就一个字段都不碰。
 * 所以网络失败 = 原样不动，而不是"把已有的辅助单位清空"。
 * 这一点必须守住：清空是不可逆的，静默清空更是。
 *
 * 依赖：React + `../../lib/productUnits`，无第三方库、无全局污染。
 * 样式在 `src/styles.css` 的「商品弹窗 · 辅助单位」一节，类名前缀 `.punit-`。
 */

import { useEffect, useRef, useState } from 'react';

import {
  MAX_UNITS_PER_PRODUCT,
  UNIT_FACTOR_MAX,
  UNIT_FACTOR_MIN,
  defaultUnitName,
  describeFactor,
  makeEmptyUnitDraft,
  packQtyMirror,
  setDefaultUnit,
  unitsToDrafts,
} from '../../lib/productUnits';

export default function ProductUnitsField({
  /** 数组 = 已加载（哪怕是空数组）；undefined / null = 还没拿到 */
  units,
  /** `form.unit`，即**基本单位**。换算率的基准。 */
  baseUnit = '',
  /** 编辑态才有值；新增态不请求（商品还没有 id） */
  productId,
  apiBase,
  authHeaders,
  /** `(drafts: Array) => void` —— 整张表交回给 App.jsx 的 productEdit / productForm */
  onChange,
  onError,
}) {
  const loaded = Array.isArray(units);
  const drafts = loaded ? units : [];

  const [loading, setLoading] = useState(false);
  const [loadFailed, setLoadFailed] = useState(false);
  const [reloadKey, setReloadKey] = useState(0);

  // 回调放进 ref：这两个函数在 App.jsx 里每次渲染都是新身份，
  // 直接写进 useEffect 依赖会导致依赖永远"变了"；用 ref 既避开这个问题，
  // 又不会读到过期闭包。里面都是 setState(prev => …) 的函数式更新，本身就不怕过期。
  const onChangeRef = useRef(onChange);
  useEffect(() => {
    onChangeRef.current = onChange;
  }, [onChange]);
  const authHeadersRef = useRef(authHeaders);
  useEffect(() => {
    authHeadersRef.current = authHeaders;
  }, [authHeaders]);

  useEffect(() => {
    if (loaded || !productId) return undefined;

    let cancelled = false;
    setLoading(true);
    setLoadFailed(false);

    fetch(`${apiBase}/products/${productId}/units`, {
      headers: typeof authHeadersRef.current === 'function' ? authHeadersRef.current() : {},
    })
      .then((response) => {
        if (response.ok) return response.json();
        return response.json().catch(() => ({})).then((data) => {
          throw new Error(data.detail || '加载辅助单位失败');
        });
      })
      .then((data) => {
        if (cancelled) return;
        onChangeRef.current(unitsToDrafts(Array.isArray(data) ? data : []));
      })
      .catch((err) => {
        if (cancelled) return;
        setLoadFailed(true);
        if (onError) onError(err.message || '加载辅助单位失败');
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });

    return () => {
      cancelled = true;
    };
    // `loaded` 在拿到数据后会变 true，这个 effect 随即提前返回，不会重复请求。
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [loaded, productId, apiBase, reloadKey]);

  const commit = (next) => {
    if (onChangeRef.current) onChangeRef.current(next);
  };

  const update = (index, field, value) => {
    commit(drafts.map((draft, i) => (i === index ? { ...draft, [field]: value } : draft)));
  };

  const addRow = () => {
    if (drafts.length >= MAX_UNITS_PER_PRODUCT) return;
    commit([...drafts, makeEmptyUnitDraft()]);
  };

  const removeRow = (index) => {
    commit(drafts.filter((_, i) => i !== index));
  };

  const markDefault = (index) => {
    commit(setDefaultUnit(drafts, index));
  };

  const mirror = packQtyMirror(drafts);
  const mirrorName = defaultUnitName(drafts);

  const head = (
    <div className="punit-head">
      <span className="punit-title">辅助单位与换算</span>
      <span className="punit-base">
        基本单位：
        {baseUnit ? <b>{baseUnit}</b> : <em>未填 —— 请先填上面的「单位」</em>}
      </span>
    </div>
  );

  if (loading) {
    return (
      <div className="punit">
        {head}
        <p className="punit-hint">正在加载辅助单位…</p>
      </div>
    );
  }

  if (loadFailed) {
    return (
      <div className="punit">
        {head}
        <p className="punit-hint punit-hint-warn">
          辅助单位加载失败。<b>此时保存不会改动该商品已有的辅助单位</b>（不会清空），
          可以点下面重试。
        </p>
        <div className="punit-actions">
          <button type="button" className="secondary-btn" onClick={() => setReloadKey((n) => n + 1)}>
            重新加载
          </button>
        </div>
      </div>
    );
  }

  return (
    <div className="punit">
      {head}

      <p className="punit-hint">
        换算率的意思是「<b>1 个辅助单位 = 几个基本单位</b>」：基本单位是「盒」、辅助单位写「箱」、
        换算率填 10，就是 1 箱 = 10 盒。
        <br />
        库存一律按基本单位存整数，所以换算率只能是 <b>≥{UNIT_FACTOR_MIN} 的整数</b>，
        而且基本单位必须是<b>最小的那个</b> —— 基本单位填「箱」、辅助单位填「盒」是不允许的。
      </p>

      {drafts.length === 0 ? (
        <p className="punit-empty">还没有辅助单位 —— 只有一个计量单位的话，不用填这里。</p>
      ) : (
        <div className="punit-list">
          {drafts.map((draft, index) => (
            /* key 用下标：这里是"就地编辑的固定几行"，没有重排也没有外部数据源，
               用下标不会出现"内容串行"；行数上限 50，代价可以忽略。 */
            <div className="punit-row" key={index}>
              <div className="punit-cell punit-cell-name">
                <span className="punit-cell-label">单位名</span>
                <input
                  list="lookup-product-unit"
                  value={draft.unit_name}
                  placeholder="如 箱"
                  aria-label={`第 ${index + 1} 行的辅助单位名称`}
                  onChange={(event) => update(index, 'unit_name', event.target.value)}
                />
              </div>

              <div className="punit-cell punit-cell-factor">
                <span className="punit-cell-label">换算率</span>
                {/* 刻意用 text + inputMode 而不是 number：
                    number 的默认 step=1 会让浏览器**先于**我们拦下 2.5，
                    用户看到的是一句英文原生气泡，而不是下面那条带行号的中文提示。
                    用 text 之后 factorIsValid 是唯一的一道闸，提示口径完全统一。 */}
                <input
                  type="text"
                  inputMode="numeric"
                  value={draft.factor}
                  placeholder={`≥${UNIT_FACTOR_MIN}`}
                  aria-label={`第 ${index + 1} 行的换算率`}
                  onChange={(event) => update(index, 'factor', event.target.value)}
                />
              </div>

              <div className="punit-cell punit-cell-desc">
                <span className="punit-cell-label">换算说明</span>
                <span className="punit-desc-text">{describeFactor(draft.factor, draft.unit_name, baseUnit)}</span>
              </div>

              <div className="punit-cell punit-cell-price">
                <span className="punit-cell-label">进价</span>
                <input
                  type="number"
                  step="any"
                  value={draft.price}
                  placeholder="可空"
                  aria-label={`第 ${index + 1} 行的进价`}
                  onChange={(event) => update(index, 'price', event.target.value)}
                />
              </div>

              <div className="punit-cell punit-cell-price">
                <span className="punit-cell-label">售价</span>
                <input
                  type="number"
                  step="any"
                  value={draft.sale_price}
                  placeholder="可空"
                  aria-label={`第 ${index + 1} 行的售价`}
                  onChange={(event) => update(index, 'sale_price', event.target.value)}
                />
              </div>

              <div className="punit-cell punit-cell-barcode">
                <span className="punit-cell-label">条码</span>
                <input
                  value={draft.bar_code}
                  placeholder="如箱码，可空"
                  aria-label={`第 ${index + 1} 行的条码`}
                  onChange={(event) => update(index, 'bar_code', event.target.value)}
                />
              </div>

              {/* 用 div 包 span+input，而不是 <label>：
                  .erp-form label / .invoice-edit-form label 是全局规则（grid 布局、
                  各种宽度），套在这么窄的格子中会把行高和列宽整个带偏。
                  accessibility 由 input 自己的 aria-label 承担。 */}
              <div className="punit-cell punit-cell-flag">
                <span className="punit-cell-label">默认</span>
                <div className="punit-flag-body">
                  <input
                    type="radio"
                    name="punit-default"
                    checked={!!draft.is_default}
                    aria-label={`把第 ${index + 1} 行设为默认辅助单位`}
                    onChange={() => markDefault(index)}
                  />
                </div>
              </div>

              <div className="punit-cell punit-cell-flag">
                <span className="punit-cell-label">启用</span>
                <div className="punit-flag-body">
                  <input
                    type="checkbox"
                    checked={draft.is_enabled !== false}
                    aria-label={`第 ${index + 1} 行是否启用`}
                    onChange={(event) => update(index, 'is_enabled', event.target.checked)}
                  />
                </div>
              </div>

              <div className="punit-cell punit-cell-action">
                <button
                  type="button"
                  className="link-btn danger"
                  aria-label={`删除第 ${index + 1} 行`}
                  onClick={() => removeRow(index)}
                >
                  删除
                </button>
              </div>
            </div>
          ))}
        </div>
      )}

      <div className="punit-actions">
        <button
          type="button"
          className="secondary-btn"
          disabled={drafts.length >= MAX_UNITS_PER_PRODUCT}
          onClick={addRow}
        >
          ＋ 添加辅助单位
        </button>
        <span className="punit-mirror">
          {mirror === null
            ? '未指定默认辅助单位 → 上面的「包装数」会是空的'
            : `默认辅助单位已设为「${mirrorName || '未命名'}」→ 上面的「包装数」会同步为 ${mirror}`}
        </span>
      </div>

      <p className="punit-hint punit-hint-dim">
        换算率上限 {UNIT_FACTOR_MAX}。勾「默认」的那一行 = 商品档案里的「包装数」，
        只设一个就好 —— 两个字段存的是同一件事，勾一个等于把那个死字段接活了。
      </p>
    </div>
  );
}
