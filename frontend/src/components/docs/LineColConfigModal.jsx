/**
 * LineColConfigModal —— 明细表格「列配置」弹窗（2026-10-21 老系统 UX 下沉）。
 *
 * 解决什么问题：不同行业/不同人关心的列不一样 —— 有人从来不看「单位」，
 * 有人只想快录「数量 × 单价」。把不关心的列藏起来，表格更紧凑、录单更快。
 *
 * 设计要点：
 * ① **受控组件**：父组件 `colOpen && <LineColConfigModal … />` 控制显隐，
 *    与批量选商品弹窗同一套模式（挂在 ResizableLayout 外面）。
 * ② **隐藏清单存 localStorage**：刷新页面/明天再来，配置还在。
 *    存储格式 `{ hidden: string[] }`，键由父组件传入（销售/采购各存各的）。
 * ③ **商品列与操作列永远显示**：商品是行的主体，操作列藏着就没法复制/删行；
 *    可隐藏的只有 数量/单位/单价/金额 四列，且至少保留一列可编辑数据列
 *    （全藏了没法录单 —— 「恢复默认」永远能救回来）。
 * ④ 只管"哪些列显示"，不碰列宽/顺序 —— 那是表格组件自己的契约，改了会坏。
 */
const LINE_COL_LABELS = {
  quantity: '数量',
  unit: '单位',
  unit_price: '单价',
  amount: '金额',
};

export default function LineColConfigModal({ hiddenCols, onToggle, onReset, onClose }) {
  const toggleable = Object.keys(LINE_COL_LABELS);
  const visibleCount = toggleable.filter((key) => !hiddenCols.includes(key)).length;

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal-card" onClick={(event) => event.stopPropagation()}>
        <div className="modal-header">
          <h3>明细列配置</h3>
          <button type="button" className="secondary-btn small-btn" onClick={onClose}>
            关闭
          </button>
        </div>

        <div className="modal-body">
          <p className="doc-detail__hint">
            商品列与操作列始终显示。勾选 = 显示，取消勾选 = 隐藏；配置保存在本机浏览器。
          </p>
          <ul className="doc-colpick-list" data-doc-colpick-list>
            {toggleable.map((key) => {
              const visible = !hiddenCols.includes(key);
              // 只剩一列可编辑数据列时禁止再藏 —— 不然整表没法录单
              const locked = visible && visibleCount <= 1;
              return (
                <li key={key}>
                  <label className={locked ? 'doc-colpick--locked' : ''}>
                    <input
                      type="checkbox"
                      checked={visible}
                      disabled={locked}
                      onChange={() => onToggle(key)}
                    />
                    <span>{LINE_COL_LABELS[key]}</span>
                  </label>
                </li>
              );
            })}
          </ul>
        </div>

        <div className="modal-actions">
          <button type="button" className="secondary-btn" onClick={onReset}>
            恢复默认
          </button>
          <button type="button" className="primary-btn" onClick={onClose}>
            完成
          </button>
        </div>
      </div>
    </div>
  );
}
