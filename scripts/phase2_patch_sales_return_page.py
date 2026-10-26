# -*- coding: utf-8 -*-
"""第二阶段 P2-1：销售退货页 —— 详情弹窗 + 草稿编辑 + 反审核。"""
import shutil
from datetime import datetime
from pathlib import Path

PAGE = Path(__file__).resolve().parents[1] / "frontend" / "src" / "pages" / "SalesReturnPage.jsx"
shutil.copy2(PAGE, PAGE.with_suffix(f".jsx.bak-{datetime.now():%m%d%H%M%S}"))

text = PAGE.read_bytes().decode("utf-8").replace("\r\n", "\n")


def sub_once(source, old, new, label):
    n = source.count(old)
    assert n == 1, f"[{label}] 命中 {n} 次"
    return source.replace(old, new)


# 1) ctx 取新方法 + 页内 state
text = sub_once(
    text,
    """    warehouses
  } = ctx;
  return (
""",
    """    warehouses,
    // —— 第二阶段新增：草稿编辑 / 反审核 ——
    salesReturnEditingId,
    startSalesReturnEdit,
    cancelSalesReturnEdit,
    saveSalesReturnDraft,
    unsubmitSalesReturn
  } = ctx;
  // 详情弹窗只存"点开的那一行"，数据本体仍在列表里（列表刷新自动跟着变）
  const [detailRow, setDetailRow] = useState(null);
  return (
""",
    "ctx-and-state",
)

# 2) return 包一层 Fragment（弹窗必须挂在 ResizableLayout 外面，否则只剩 3 个子元素就拖不动了）
text = sub_once(
    text,
    """  return (

              <ResizableLayout>
""",
    """  return (
    <>
              <ResizableLayout>
""",
    "fragment-open",
)

text = sub_once(
    text,
    """              </ResizableLayout>
            
  );
}
""",
    """              </ResizableLayout>

      {detailRow && (
        <div className="modal-overlay" onClick={() => setDetailRow(null)}>
          <div
            className="modal-card doc-detail"
            role="dialog"
            aria-label="销售退货单详情"
            data-sales-return-detail-card={detailRow.id}
            onClick={(event) => event.stopPropagation()}
          >
            <div className="modal-header">
              <h3>销售退货单 {detailRow.return_no}</h3>
              <button type="button" className="secondary-btn small-btn" onClick={() => setDetailRow(null)}>
                关闭
              </button>
            </div>

            <div className="modal-body">
              <p>
                <strong>客户：</strong>{' '}
                {detailRow.customer_name ||
                  customers.find((item) => item.id === detailRow.customer_id)?.name ||
                  '—'}
                {'　'}
                <strong>状态：</strong>{' '}
                <span className="status-badge">{salesReturnStatusLabel(detailRow.status)}</span>
              </p>
              <p>
                <strong>退货日期：</strong> {detailRow.return_date || '—'}
                {'　'}
                <strong>仓库：</strong>{' '}
                {warehouses.find((item) => item.id === detailRow.warehouse_id)?.name || '默认仓库'}
                {'　'}
                <strong>业务员：</strong> {detailRow.businesser || '—'}
              </p>
              <p>
                <strong>合计：</strong> ¥{Number(detailRow.total_amount || 0).toFixed(2)}
                {'（'}
                {detailRow.amount_chinese || '—'}
                {'）'}
                {'　'}
                <strong>明细：</strong> {detailRow.items?.length ?? 0} 行
              </p>
              <p>
                <strong>退货原因：</strong> {detailRow.return_reason || '—'}
                {'　'}
                <strong>退款方式：</strong> {detailRow.payment_method || '—'}
              </p>
              {detailRow.source_order_no && (
                <p>
                  <strong>来源单号：</strong> {detailRow.source_order_no}
                </p>
              )}
              {detailRow.note && (
                <p>
                  <strong>备注：</strong> {detailRow.note}
                </p>
              )}

              <div className="doc-detail__table">
                <table className="data-table">
                  <thead>
                    <tr>
                      <th style={{ width: 44 }}>#</th>
                      <th>商品</th>
                      <th style={{ width: 90 }}>规格</th>
                      <th style={{ width: 70 }}>单位</th>
                      <th style={{ width: 80 }} className="num">数量</th>
                      <th style={{ width: 100 }} className="num">单价</th>
                      <th style={{ width: 110 }} className="num">金额</th>
                    </tr>
                  </thead>
                  <tbody>
                    {(detailRow.items || []).map((line, index) => (
                      <tr key={line.id ?? index}>
                        <td>{index + 1}</td>
                        <td>
                          {line.product_name ||
                            products.find((item) => item.id === line.product_id)?.name ||
                            '—'}
                        </td>
                        <td>{line.standards || '—'}</td>
                        <td>{line.unit || '—'}</td>
                        <td className="num">{line.quantity}</td>
                        <td className="num">
                          {Number(line.unit_price || 0).toFixed(4).replace(/0+$/, '').replace(/\\.$/, '')}
                        </td>
                        <td className="num">{Number(line.amount || 0).toFixed(2)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>

              <p className="doc-detail__hint">
                状态说明：<strong>草稿</strong>不动库存也不冲应收，可以随便改；
                <strong>已退货</strong>已经加了库存、冲了应收，要改请先「反审核」退回草稿。
              </p>
            </div>

            <div className="modal-actions">
              <button
                type="button"
                className="secondary-btn"
                onClick={() =>
                  printPdf(`/print/sales-return/${detailRow.id}`, `销售退货单_${detailRow.return_no}.pdf`)
                }
              >
                打印 / 下载 PDF
              </button>
              {detailRow.status === 'draft' && (
                <button
                  type="button"
                  className="secondary-btn"
                  data-sales-return-edit={detailRow.id}
                  onClick={() => {
                    startSalesReturnEdit(detailRow);
                    setDetailRow(null);
                  }}
                >
                  编辑草稿
                </button>
              )}
              {detailRow.status === 'submitted' && (
                <button
                  type="button"
                  className="secondary-btn"
                  onClick={async () => {
                    const ok = await unsubmitSalesReturn(detailRow);
                    if (ok) setDetailRow(null);
                  }}
                >
                  反审核（退回草稿）
                </button>
              )}
              <button type="button" className="secondary-btn" onClick={() => setDetailRow(null)}>
                关闭
              </button>
            </div>
          </div>
        </div>
      )}
    </>
  );
}
""",
    "fragment-close-and-modal",
)

# 3) 表单：编辑态提示 + 三个按钮
text = sub_once(
    text,
    """                  <div className="section-header">
                    <h2>新增销售退货单</h2>
                    <span className="status-badge">退货冲减库存 · 应收</span>
                  </div>
""",
    """                  <div className="section-header">
                    <h2>{salesReturnEditingId ? '编辑销售退货单（草稿）' : '新增销售退货单'}</h2>
                    <span className="status-badge">退货冲减库存 · 应收</span>
                  </div>
                  {salesReturnEditingId && (
                    <p className="doc-detail__hint" data-sales-return-editing>
                      正在编辑草稿：草稿不落账，点「保存并退货」才会把库存与应收记上。
                    </p>
                  )}
""",
    "form-header",
)

text = sub_once(
    text,
    """                    <button className="primary-btn" type="submit">保存销售退货单</button>
                    <p className="table-hint">
                      退货后自动增加库存并冲减应收，删除退货单会撤销这两笔动作。
                    </p>
""",
    """                    <div className="form-actions">
                      <button className="primary-btn" type="submit">
                        {salesReturnEditingId ? '保存并退货' : '保存销售退货单'}
                      </button>
                      <button
                        type="button"
                        className="secondary-btn"
                        data-sales-return-draft
                        onClick={saveSalesReturnDraft}
                      >
                        存为草稿
                      </button>
                      {salesReturnEditingId && (
                        <button type="button" className="secondary-btn" onClick={cancelSalesReturnEdit}>
                          取消编辑
                        </button>
                      )}
                    </div>
                    <p className="table-hint">
                      「保存并退货」= 立刻加库存 + 冲应收；「存为草稿」= 只存单，什么都不动，
                      等确认无误再回来点反审核/审核。删除退货单会撤销库存与应收两笔动作。
                    </p>
""",
    "form-buttons",
)

# 4) 列表行：详情 / 编辑 / 反审核
text = sub_once(
    text,
    """                            <td className="row-actions">
                              <button
                                type="button"
                                className="secondary-btn small-btn"
                                onClick={() => printPdf(`/print/sales-return/${row.id}`, `销售退货单_${row.return_no}.pdf`)}
                              >
                                打印
                              </button>{' '}
                              <button
""",
    """                            <td className="row-actions">
                              <button
                                type="button"
                                className="secondary-btn small-btn"
                                data-sales-return-detail={row.id}
                                onClick={() => setDetailRow(row)}
                              >
                                详情
                              </button>{' '}
                              <button
                                type="button"
                                className="secondary-btn small-btn"
                                onClick={() => printPdf(`/print/sales-return/${row.id}`, `销售退货单_${row.return_no}.pdf`)}
                              >
                                打印
                              </button>{' '}
                              {row.status === 'draft' && (
                                <>
                                  <button
                                    type="button"
                                    className="secondary-btn small-btn"
                                    data-sales-return-edit={row.id}
                                    onClick={() => startSalesReturnEdit(row)}
                                  >
                                    编辑
                                  </button>{' '}
                                </>
                              )}
                              {row.status === 'submitted' && (
                                <>
                                  <button
                                    type="button"
                                    className="secondary-btn small-btn"
                                    data-sales-return-unsubmit={row.id}
                                    onClick={() => unsubmitSalesReturn(row)}
                                  >
                                    反审核
                                  </button>{' '}
                                </>
                              )}
                              <button
""",
    "row-actions",
)

PAGE.write_bytes(text.replace("\n", "\r\n").encode("utf-8"))
print("OK SalesReturnPage.jsx 已更新")
