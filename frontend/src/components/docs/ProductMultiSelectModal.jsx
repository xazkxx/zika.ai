/**
 * ProductMultiSelectModal —— 明细表格「批量选商品」弹窗（2026-10-20 老系统 UX 升级）。
 *
 * 解决什么问题：以前录一张 20 种材料的出库单，要在搜索下拉里搜 20 次、选 20 次。
 * 现在点「批量选商品」弹这个框：搜索 → 勾选 → 一次带入。
 *
 * 设计要点：
 * ① **受控组件**：父组件 `row && <ProductMultiSelectModal … />` 控制显隐，
 *    弹窗自己不管理开关（与详情/开票弹窗同一套模式，挂在 ResizableLayout 外面）。
 * ② **带出什么由父组件决定**：本组件只回传选中的商品 id 数组；单价/单位/单位联动
 *    全部由 App.jsx `makeAddProducts` 处理 —— 与手选商品走完全同一条链路，
 *    这里绝不自己拼价格（拼错了比不填更糟）。
 * ③ **搜索不换页**：商品几百条时直接 input 过滤（name/sku/code/助记码），
 *    数据量到几千条再考虑虚拟滚动，现在不预设复杂度。
 */
import { useMemo, useState } from 'react';

export default function ProductMultiSelectModal({ products, onClose, onConfirm }) {
  const [keyword, setKeyword] = useState('');
  const [checked, setChecked] = useState(() => new Set());

  const list = useMemo(() => {
    const kw = keyword.trim().toLowerCase();
    const source = products || [];
    if (!kw) return source.slice(0, 200); // 不搜就给前 200 条，避免一次渲染几千个 checkbox
    return source
      .filter((item) =>
        [item.name, item.sku, item.code, item.mnemonic, item.category]
          .filter(Boolean)
          .some((field) => String(field).toLowerCase().includes(kw)),
      )
      .slice(0, 200);
  }, [keyword, products]);

  const toggle = (id) => {
    setChecked((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  const confirm = () => {
    if (!checked.size) return;
    onConfirm([...checked]);
  };

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal-card modal-wide" onClick={(event) => event.stopPropagation()}>
        <div className="modal-header">
          <h3>批量选商品</h3>
          <button type="button" className="secondary-btn small-btn" onClick={onClose}>
            关闭
          </button>
        </div>

        <div className="modal-body">
          <input
            className="search-input"
            value={keyword}
            onChange={(event) => setKeyword(event.target.value)}
            placeholder="搜索商品名称 / SKU / 编码 / 类别"
            autoFocus
          />
          <p className="doc-detail__hint">
            已勾选 <strong>{checked.size}</strong> 件。带入后单价按档案价、数量为 1，可再逐行修改。
          </p>
          <ul className="product-pick-list" data-product-pick-list>
            {list.map((item) => {
              const id = String(item.id);
              return (
                <li key={id}>
                  <label>
                    <input
                      type="checkbox"
                      checked={checked.has(id)}
                      onChange={() => toggle(id)}
                    />
                    <span className="product-pick-name">{item.name}</span>
                    <span className="product-pick-meta">
                      {[item.sku, item.code, item.unit].filter(Boolean).join(' · ')}
                    </span>
                  </label>
                </li>
              );
            })}
            {list.length === 0 && <li className="product-pick-empty">没有匹配的商品</li>}
          </ul>
        </div>

        <div className="modal-actions">
          <button
            type="button"
            className="primary-btn"
            onClick={confirm}
            disabled={checked.size === 0}
            title={checked.size === 0 ? '先勾选至少一件商品' : `带入 ${checked.size} 件商品`}
          >
            带入已选 {checked.size} 件
          </button>
        </div>
      </div>
    </div>
  );
}
