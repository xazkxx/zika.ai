/**
 * 测算明细表（v1.81.0）
 *
 * 列的设计围绕用户那句"进 306 卖 50"：
 *   销售数量 / 卖价  → 收入侧
 *   采购数量 / 进价  → 成本侧（采购数量留空 = 与销售数量相同，最常见的"进一批卖一批"）
 *   专票             → 只决定进项能不能抵，**不影响成本不含税**（Excel 口径）
 *
 * 输入框全部是 `text + inputMode="decimal"`：
 *   · 保留 `73.901` 这种三位小数不被浏览器吃掉；
 *   · 不出现 number 输入框的上下箭头（那一列本来就窄，箭头会挡住数字）；
 *   · 中间态（用户正敲"0."）可以原样存进状态，不用 onChange 里做半吊子转换。
 */
import { memo } from 'react';
import { lineAmount, lineCostAmount, money } from '../../lib/projectCalc';

const COLUMNS = [
  { key: 'product_name', label: '产品', placeholder: '4x35', width: '18%' },
  { key: 'unit', label: '单位', placeholder: '米', width: '7%' },
  { key: 'qty', label: '销售数量', placeholder: '0', numeric: true },
  { key: 'sale_price', label: '卖价（含税）', placeholder: '0.00', numeric: true },
  { key: 'cost_qty', label: '采购数量', placeholder: '同销售', numeric: true },
  { key: 'cost_price', label: '进价（含税）', placeholder: '0.00', numeric: true },
];

function CalcLineTable({ lines, onChange, onAdd, onRemove }) {
  const totals = lines.reduce(
    (acc, line) => ({
      sale: acc.sale + lineAmount(line),
      cost: acc.cost + lineCostAmount(line),
    }),
    { sale: 0, cost: 0 },
  );

  return (
    <div className="pc-lines">
      <div className="pc-lines__scroll">
        <table className="pc-lines__table">
          <thead>
            <tr>
              <th className="is-idx">#</th>
              {COLUMNS.map((column) => (
                <th key={column.key} className={column.numeric ? 'is-num' : ''} style={column.width ? { width: column.width } : undefined}>
                  {column.label}
                </th>
              ))}
              <th className="is-num">销售额</th>
              <th className="is-num">采购额</th>
              <th className="is-center">专票</th>
              <th className="is-center"> </th>
            </tr>
          </thead>
          <tbody>
            {lines.map((line, index) => (
              <tr key={index}>
                <td className="is-idx">{index + 1}</td>
                {COLUMNS.map((column) => (
                  <td key={column.key} className={column.numeric ? 'is-num' : ''}>
                    <input
                      className={`pc-input${column.numeric ? ' pc-input--num' : ''}`}
                      value={line[column.key] ?? ''}
                      placeholder={column.placeholder}
                      inputMode={column.numeric ? 'decimal' : 'text'}
                      aria-label={`第 ${index + 1} 行 ${column.label}`}
                      onChange={(event) => onChange(index, { [column.key]: event.target.value })}
                    />
                  </td>
                ))}
                <td className="is-num pc-lines__amount">{money(lineAmount(line))}</td>
                <td className="is-num pc-lines__amount">{money(lineCostAmount(line))}</td>
                <td className="is-center">
                  <input
                    type="checkbox"
                    checked={Boolean(line.has_invoice)}
                    aria-label={`第 ${index + 1} 行已取得专票`}
                    title="勾上 = 取得增值税专用发票，进项可抵扣；取消 = 只拿普票，进项按 0"
                    onChange={(event) => onChange(index, { has_invoice: event.target.checked })}
                  />
                </td>
                <td className="is-center">
                  <button
                    type="button"
                    className="pc-icon-btn"
                    title="删除这一行"
                    aria-label={`删除第 ${index + 1} 行`}
                    onClick={() => onRemove(index)}
                  >
                    ×
                  </button>
                </td>
              </tr>
            ))}
            {lines.length === 0 ? (
              <tr>
                <td colSpan={11} className="pc-lines__empty">
                  还没有明细。点下面的「增加一行」手填，或用右上角「从单据带出」拉一张销售单/采购单/合同。
                </td>
              </tr>
            ) : null}
          </tbody>
          <tfoot>
            <tr>
              <td colSpan={7} className="is-num">
                合计（{lines.length} 行）
              </td>
              <td className="is-num pc-lines__amount">{money(totals.sale)}</td>
              <td className="is-num pc-lines__amount">{money(totals.cost)}</td>
              <td colSpan={2} className="is-center pc-lines__hint">
                含税差 {money(totals.sale - totals.cost)}
              </td>
            </tr>
          </tfoot>
        </table>
      </div>

      <div className="pc-lines__actions">
        <button type="button" className="secondary-btn small-btn" onClick={onAdd}>
          + 增加一行
        </button>
        <span className="pc-lines__note">
          采购数量留空 = 与销售数量相同。数量分开填，才能看见"进 306 卖 50"压住的那部分资金。
        </span>
      </div>
    </div>
  );
}

export default memo(CalcLineTable);
