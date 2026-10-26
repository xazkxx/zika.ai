# -*- coding: utf-8 -*-
"""第二阶段 P2-3：财务流水录入去冗余。

用户原话：「去掉页面中间的『客户/供应商』输入，只留左侧类型（收/付），确认后直接保存。」
改法：
  · 删掉「客户 ID / 供应商 ID」两个裸数字输入框（要填也是 7039 这种 ID，业务人员根本不知道）
  · 类型选项改成「收 / 付」两种，值仍是 income / expense（后端枚举不动）
  · 货币、关联订单 ID 收进「更多（可选）」，默认折叠 —— 主流程只剩 类型 / 金额 / 备注
"""
import shutil
from datetime import datetime
from pathlib import Path

PAGE = Path(__file__).resolve().parents[1] / "frontend" / "src" / "pages" / "FinancePage.jsx"
shutil.copy2(PAGE, PAGE.with_suffix(f".jsx.bak-{datetime.now():%m%d%H%M%S}"))

text = PAGE.read_bytes().decode("utf-8").replace("\r\n", "\n")

OLD = """                    <div className="form-row two-col">
                      <label>
                        类型
                        <select value={financeForm.transaction_type} onChange={handleFinanceChange('transaction_type')}>
                          <option value="income">收入</option>
                          <option value="expense">支出</option>
                        </select>
                      </label>
                      <label>
                        金额
                        <input type="number" step="any" value={financeForm.amount} onChange={handleFinanceChange('amount')} required />
                      </label>
                    </div>

                    <div className="form-row two-col">
                      <label>
                        货币
                        <input value={financeForm.currency} onChange={handleFinanceChange('currency')} />
                      </label>
                      <label>
                        关联订单 ID
                        <input type="number" value={financeForm.related_order_id} onChange={handleFinanceChange('related_order_id')} />
                      </label>
                    </div>

                    <div className="form-row two-col">
                      <label>
                        客户 ID
                        <input type="number" value={financeForm.customer_id} onChange={handleFinanceChange('customer_id')} />
                      </label>
                      <label>
                        供应商 ID
                        <input type="number" value={financeForm.supplier_id} onChange={handleFinanceChange('supplier_id')} />
                      </label>
                    </div>

                    <label>
                      备注
                      <textarea value={financeForm.note} onChange={handleFinanceChange('note')} rows="3" />
                    </label>

                    <button className="primary-btn" type="submit">保存财务记录</button>
"""

NEW = """                    {/* 收 / 付 是这一屏唯一的必选项：先定方向，再填钱。
                        值仍然是 income / expense（后端与统计口径都按它算），
                        只是把「收入/支出」换成业务人员日常说的「收/付」。 */}
                    <div className="form-row two-col">
                      <label>
                        类型
                        <select
                          value={financeForm.transaction_type}
                          onChange={handleFinanceChange('transaction_type')}
                          data-finance-type
                        >
                          <option value="income">收（收款 / 收入）</option>
                          <option value="expense">付（付款 / 支出）</option>
                        </select>
                      </label>
                      <label>
                        金额
                        <input type="number" step="any" value={financeForm.amount} onChange={handleFinanceChange('amount')} required />
                      </label>
                    </div>

                    <label>
                      备注
                      <textarea
                        value={financeForm.note}
                        onChange={handleFinanceChange('note')}
                        rows="3"
                        placeholder="如：收华邦公司货款 / 付焊条采购款"
                      />
                    </label>

                    {/* 客户 / 供应商不再让人手填 ID：这两栏对业务人员等于"填一串看不懂的数字"。
                        真要挂档案，从单据上走（收付款登记会自动带出往来单位）。 */}
                    <details className="finance-more" data-finance-more>
                      <summary>更多（可选）</summary>
                      <div className="form-row two-col">
                        <label>
                          货币
                          <input value={financeForm.currency} onChange={handleFinanceChange('currency')} />
                        </label>
                        <label>
                          关联订单 ID
                          <input
                            type="number"
                            value={financeForm.related_order_id}
                            onChange={handleFinanceChange('related_order_id')}
                            placeholder="一般不填"
                          />
                        </label>
                      </div>
                    </details>

                    <button className="primary-btn" type="submit">确认保存</button>
                    <p className="table-hint">
                      只填「收/付 + 金额」就能存。往来单位挂账请在订单/单据页登记收付款，那里会自动带出客户或供应商。
                    </p>
"""

assert text.count(OLD) == 1, text.count(OLD)
text = text.replace(OLD, NEW)

PAGE.write_bytes(text.replace("\n", "\r\n").encode("utf-8"))
print("OK FinancePage.jsx 去冗余完成")
