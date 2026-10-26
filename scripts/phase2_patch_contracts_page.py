# -*- coding: utf-8 -*-
"""第二阶段 P2-1：购销合同页 —— 详情里加「编辑草稿 / 反审核」，列表行同步。"""
import shutil
from datetime import datetime
from pathlib import Path

PAGE = Path(__file__).resolve().parents[1] / "frontend" / "src" / "pages" / "ContractsPage.jsx"
shutil.copy2(PAGE, PAGE.with_suffix(f".jsx.bak-{datetime.now():%m%d%H%M%S}"))

text = PAGE.read_bytes().decode("utf-8").replace("\r\n", "\n")


def sub_once(source, old, new, label):
    n = source.count(old)
    assert n == 1, f"[{label}] 命中 {n} 次"
    return source.replace(old, new)


# 1) ctx
text = sub_once(
    text,
    """    setSelectedContract,
""",
    """    setSelectedContract,
    // —— 第二阶段新增：合同草稿编辑 / 反审核 ——
    contractEditingId,
    startContractEdit,
    cancelContractEdit,
    unsubmitContract,
""",
    "ctx",
)

# 2) 表单标题与按钮文案随编辑态变化
text = sub_once(
    text,
    """                    <h2>新增购销合同</h2>
""",
    """                    <h2>{contractEditingId ? '编辑购销合同（草稿）' : '新增购销合同'}</h2>
""",
    "form-title",
)

# 编辑态禁止改合同类型：销售↔采购会把 party_id 当错边的档案
text = sub_once(
    text,
    """                        <select value={contractForm.contract_type} onChange={handleContractChange('contract_type')}>
""",
    """                        <select
                          value={contractForm.contract_type}
                          onChange={handleContractChange('contract_type')}
                          disabled={Boolean(contractEditingId)}
                          title={contractEditingId ? '编辑草稿时不能改合同类型，请新建一张' : undefined}
                        >
""",
    "type-select",
)

text = sub_once(
    text,
    """                    <button className="primary-btn" type="submit">保存合同</button>
""",
    """                    <div className="form-actions">
                      <button className="primary-btn" type="submit">
                        {contractEditingId ? '保存合同修改' : '保存合同'}
                      </button>
                      {contractEditingId && (
                        <button type="button" className="secondary-btn" onClick={cancelContractEdit}>
                          取消编辑
                        </button>
                      )}
                    </div>
""",
    "form-buttons",
)

# 3) 详情弹窗底部：编辑草稿 / 反审核
text = sub_once(
    text,
    """                      <div className="modal-actions">
                        <button
                          type="button"
                          className="secondary-btn"
                          onClick={() => printPdf(`/print/contract/${selectedContract.id}`, `购销合同_${selectedContract.contract_no}.pdf`)}
                        >
                          打印合同
                        </button>
                        <button type="button" className="secondary-btn" onClick={() => setSelectedContract(null)}>关闭</button>
                      </div>
""",
    """                      <div className="modal-actions">
                        <button
                          type="button"
                          className="secondary-btn"
                          onClick={() => printPdf(`/print/contract/${selectedContract.id}`, `购销合同_${selectedContract.contract_no}.pdf`)}
                        >
                          打印合同
                        </button>
                        {selectedContract.status === 'draft' && (
                          <button
                            type="button"
                            className="secondary-btn"
                            data-contract-edit={selectedContract.id}
                            onClick={() => startContractEdit(selectedContract)}
                          >
                            编辑草稿
                          </button>
                        )}
                        {(selectedContract.status === 'signed' || selectedContract.status === 'executing') && (
                          <button
                            type="button"
                            className="secondary-btn"
                            data-contract-unsubmit={selectedContract.id}
                            disabled={Boolean(selectedContract.order_id)}
                            title={selectedContract.order_id ? '已生成单据的合同不能退回草稿，否则单据溯源会断链' : undefined}
                            onClick={() => unsubmitContract(selectedContract)}
                          >
                            反审核（退回草稿）
                          </button>
                        )}
                        <button type="button" className="secondary-btn" onClick={() => setSelectedContract(null)}>关闭</button>
                      </div>
""",
    "detail-actions",
)

# 4) 列表行：加「详情」按钮（行本身可点，但按钮更好找）
text = sub_once(
    text,
    """                            <td>
                              <button
                                type="button"
                                className="secondary-btn small-btn"
                                onClick={(event) => {
                                  event.stopPropagation();
                                  printPdf(`/print/contract/${row.id}`, `购销合同_${row.contract_no}.pdf`);
                                }}
                              >
                                打印
                              </button>{' '}
""",
    """                            <td>
                              <button
                                type="button"
                                className="secondary-btn small-btn"
                                data-contract-detail={row.id}
                                onClick={(event) => {
                                  event.stopPropagation();
                                  setSelectedContract(row);
                                }}
                              >
                                详情
                              </button>{' '}
                              <button
                                type="button"
                                className="secondary-btn small-btn"
                                onClick={(event) => {
                                  event.stopPropagation();
                                  printPdf(`/print/contract/${row.id}`, `购销合同_${row.contract_no}.pdf`);
                                }}
                              >
                                打印
                              </button>{' '}
""",
    "row-detail-btn",
)

PAGE.write_bytes(text.replace("\n", "\r\n").encode("utf-8"))
print("OK ContractsPage.jsx 已更新")
