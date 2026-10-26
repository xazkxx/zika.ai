# -*- coding: utf-8 -*-
"""第二阶段 P2-1：App.jsx 接「草稿编辑 + 反审核」。
   · 销售退货：编辑态 + 存草稿 + 反审核（后端已做账实同步）
   · 购销合同：编辑态 + 退回草稿
先备份，再改，最后核对换行符。
"""
import re
import shutil
from datetime import datetime
from pathlib import Path

FRONT = Path(__file__).resolve().parents[1] / "frontend" / "src"
APP = FRONT / "App.jsx"
BACKUP = APP.with_suffix(f".jsx.bak-{datetime.now():%m%d%H%M%S}")
shutil.copy2(APP, BACKUP)

raw = APP.read_bytes().decode("utf-8")
text = raw.replace("\r\n", "\n")


def sub_once(source: str, old: str, new: str, label: str) -> str:
    count = source.count(old)
    assert count == 1, f"[{label}] 锚点命中 {count} 次"
    return source.replace(old, new)


# ---------------------------------------------------------------- 1. 编辑态 state
text = sub_once(
    text,
    """  const [salesReturnKeyword, setSalesReturnKeyword] = useState('');
""",
    """  const [salesReturnKeyword, setSalesReturnKeyword] = useState('');
  // 销售退货编辑态：非空表示左侧表单正在改这张草稿（null = 新建）
  const [salesReturnEditingId, setSalesReturnEditingId] = useState(null);
""",
    "salesReturnEditingId",
)

text = sub_once(
    text,
    """  const [selectedContract, setSelectedContract] = useState(null);
""",
    """  const [selectedContract, setSelectedContract] = useState(null);
  // 合同编辑态：非空表示左侧表单正在改这张草稿合同（null = 新建）
  const [contractEditingId, setContractEditingId] = useState(null);
""",
    "contractEditingId",
)

# ------------------------------------------------- 2. 销售退货提交（新建/编辑/草稿）
OLD_SR = text[text.index("  const submitSalesReturn = async (event) => {"):text.index("  // —— 库存调拨（对齐浩技云「库存管理 → 调拨管理」）——")]
NEW_SR = '''  /** 销售退货：新建 / 编辑共用一条提交链路。status='draft' 时只存单不落账。 */
  const persistSalesReturn = async (status) => {
    setNotice('');

    const lines = salesReturnForm.items
      .filter((row) => row.product_id)
      .map((row) => ({
        product_id: Number(row.product_id),
        quantity: Number(row.quantity) || 0,
        unit_price: Number(row.unit_price) || 0,
      }));
    if (!salesReturnForm.customer_id) {
      setNotice('请先选择客户。');
      return;
    }
    if (lines.length === 0) {
      setNotice('至少要有一行退货明细（商品不能为空）。');
      return;
    }

    const num = (v) => (v === '' || v === null || v === undefined ? null : Number(v));
    const editingId = salesReturnEditingId;

    try {
      const response = await fetch(
        editingId ? `${API_BASE}/sales-returns/${editingId}` : `${API_BASE}/sales-returns`,
        {
          method: editingId ? 'PATCH' : 'POST',
          headers: {
            'Content-Type': 'application/json',
            ...(authToken ? { Authorization: `Bearer ${authToken}` } : {}),
          },
          body: JSON.stringify({
            customer_id: Number(salesReturnForm.customer_id),
            warehouse_id: num(salesReturnForm.warehouse_id),
            businesser: salesReturnForm.businesser || null,
            return_date: salesReturnForm.return_date || null,
            return_reason: salesReturnForm.return_reason || null,
            payment_method: salesReturnForm.payment_method || null,
            note: salesReturnForm.note || null,
            source_order_id: num(salesReturnForm.source_order_id),
            source_order_no: salesReturnForm.source_order_no || null,
            items: lines,
            status,
          }),
        },
      );

      if (!response.ok) {
        const errorData = await response.json().catch(() => ({ detail: '保存销售退货单失败' }));
        const detail = errorData.detail;
        throw new Error(
          typeof detail === 'string'
            ? detail
            : Array.isArray(detail)
              ? detail.map((item) => item?.msg || item).join('；')
              : '保存销售退货单失败',
        );
      }

      const saved = await response.json();
      setSalesReturns((prev) =>
        editingId ? prev.map((item) => (item.id === saved.id ? saved : item)) : [saved, ...prev],
      );
      setSalesReturnForm({ ...emptySalesReturnForm, items: [{ product_id: '', quantity: '1', unit_price: '0' }] });
      setSalesReturnEditingId(null);
      if (status === 'draft') {
        setNotice(`销售退货单 ${saved.return_no} 已存为草稿：库存与应收都还没动，审核后才落账。`);
      } else {
        setNotice(`销售退货单 ${saved.return_no} 已保存（${saved.amount_chinese}），库存与应收已同步。`);
      }
    } catch (err) {
      setNotice(err.message || '销售退货单保存失败');
    }
  };

  const submitSalesReturn = async (event) => {
    event.preventDefault();
    await persistSalesReturn('submitted');
  };

  const saveSalesReturnDraft = () => {
    // 按钮在 form 内，用 type="button" 不会触发 onsubmit，这里直接走草稿分支
    persistSalesReturn('draft');
  };

  /** 把一行草稿退货单载入左侧表单，进入编辑态。 */
  const startSalesReturnEdit = (row) => {
    if (!row) return;
    setNotice('');
    setSalesReturnEditingId(row.id);
    setSalesReturnForm({
      ...emptySalesReturnForm,
      customer_id: row.customer_id ?? '',
      warehouse_id: row.warehouse_id ?? '',
      businesser: row.businesser || '',
      return_date: row.return_date || '',
      return_reason: row.return_reason || '',
      payment_method: row.payment_method || '',
      note: row.note || '',
      source_order_id: row.source_order_id ?? '',
      source_order_no: row.source_order_no || '',
      contact: row.contact || '',
      contact_phone: row.contact_phone || '',
      address: row.address || '',
      // 明细转回表单态：数量/单价一律字符串，否则 input 会把 8.000 重排成 8
      items: (row.items || []).length
        ? row.items.map((line) => ({
            product_id: line.product_id ?? '',
            quantity: String(line.quantity ?? '1'),
            unit_price: String(line.unit_price ?? '0'),
            unit: line.unit || '',
          }))
        : [{ product_id: '', quantity: '1', unit_price: '0' }],
    });
    setNotice(`正在编辑销售退货单 ${row.return_no}，改完点「保存并退货」或「存为草稿」。`);
    if (typeof window !== 'undefined') window.scrollTo({ top: 0, behavior: 'smooth' });
  };

  const cancelSalesReturnEdit = () => {
    setSalesReturnEditingId(null);
    setSalesReturnForm({ ...emptySalesReturnForm, items: [{ product_id: '', quantity: '1', unit_price: '0' }] });
    setNotice('已取消编辑。');
  };

  /** 销售退货反审核：已退货 → 草稿。后端会把库存入库与应收冲减一起撤回。 */
  const unsubmitSalesReturn = async (row) => {
    if (!row) return false;
    setNotice('');
    try {
      const response = await fetch(`${API_BASE}/sales-returns/${row.id}/status`, {
        method: 'PATCH',
        headers: {
          'Content-Type': 'application/json',
          ...(authToken ? { Authorization: `Bearer ${authToken}` } : {}),
        },
        body: JSON.stringify({ status: 'draft' }),
      });
      const data = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(data.detail || '反审核失败');
      setSalesReturns((prev) => prev.map((item) => (item.id === row.id ? data : item)));
      setNotice(`销售退货单 ${row.return_no} 已退回草稿：库存入库与应收冲减都已撤回。`);
      return true;
    } catch (err) {
      setNotice(err.message || '反审核失败');
      return false;
    }
  };

'''
text = text.replace(OLD_SR, NEW_SR)

# ------------------------------------------------------- 3. 合同提交（新建/编辑）
OLD_CT_HEAD = '''  const submitContract = async (event) => {
    event.preventDefault();
    setNotice('');
'''
NEW_CT_HEAD = '''  /** 合同新建 / 编辑共用一条提交链路（编辑走 PATCH，只对草稿开放）。 */
  const submitContract = async (event) => {
    event.preventDefault();
    setNotice('');
'''
text = sub_once(text, OLD_CT_HEAD, NEW_CT_HEAD, "contract-head")

OLD_CT_FETCH = '''    try {
      const response = await fetch(`${API_BASE}/contracts`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          ...(authToken ? { Authorization: `Bearer ${authToken}` } : {}),
        },
        body: JSON.stringify({
          contract_type: contractForm.contract_type,
          party_type: contractForm.contract_type === 'sales' ? 'customer' : 'supplier',
          party_id: num(contractForm.party_id),
'''
NEW_CT_FETCH = '''    const editingId = contractEditingId;
    try {
      const response = await fetch(
        editingId ? `${API_BASE}/contracts/${editingId}` : `${API_BASE}/contracts`,
        {
          method: editingId ? 'PATCH' : 'POST',
          headers: {
            'Content-Type': 'application/json',
            ...(authToken ? { Authorization: `Bearer ${authToken}` } : {}),
          },
          body: JSON.stringify({
          // 编辑时**不允许换合同类型**（销售↔采购会把 party_id 当错边的档案），
          // 所以 PATCH 只带 party_id；新建仍带全量。
          contract_type: contractForm.contract_type,
          party_type: contractForm.contract_type === 'sales' ? 'customer' : 'supplier',
          party_id: num(contractForm.party_id),
'''
text = sub_once(text, OLD_CT_FETCH, NEW_CT_FETCH, "contract-fetch")

OLD_CT_TAIL = '''          items: lines,
        }),
      });

      if (!response.ok) {
        const errorData = await response.json().catch(() => ({ detail: '创建合同失败' }));
        throw new Error(errorData.detail ?? '创建合同失败');
      }

      const created = await response.json();
      setContracts((prev) => [created, ...prev]);
      setContractForm({ ...emptyContractForm, items: [{ product_id: '', quantity: '1', unit_price: '0' }] });
      await loadContractMeta();
      setNotice(`合同 ${created.contract_no} 已生成（${created.amount_chinese}）。`);
    } catch (err) {
      setNotice(err.message || '合同新增失败');
    }
  };
'''
NEW_CT_TAIL = '''          items: lines,
          }),
        },
      );

      if (!response.ok) {
        const errorData = await response.json().catch(() => ({ detail: '保存合同失败' }));
        const detail = errorData.detail;
        throw new Error(
          typeof detail === 'string'
            ? detail
            : Array.isArray(detail)
              ? detail.map((item) => item?.msg || item).join('；')
              : '保存合同失败',
        );
      }

      const created = await response.json();
      setContracts((prev) =>
        editingId ? prev.map((item) => (item.id === created.id ? created : item)) : [created, ...prev],
      );
      setContractForm({ ...emptyContractForm, items: [{ product_id: '', quantity: '1', unit_price: '0' }] });
      setContractEditingId(null);
      setSelectedContract(null);
      await loadContractMeta();
      setNotice(
        editingId
          ? `合同 ${created.contract_no} 已保存。`
          : `合同 ${created.contract_no} 已生成（${created.amount_chinese}）。`,
      );
    } catch (err) {
      setNotice(err.message || '合同保存失败');
    }
  };

  /** 把一张草稿合同载入左侧表单，进入编辑态。 */
  const startContractEdit = (row) => {
    if (!row) return;
    setNotice('');
    setContractEditingId(row.id);
    setSelectedContract(null);
    setContractForm({
      ...emptyContractForm,
      contract_type: row.contract_type || 'sales',
      party_id: row.party_id ?? '',
      party_name: row.party_name || '',
      warehouse_id: row.warehouse_id ?? '',
      title: row.title || '',
      own_name: row.own_name || '',
      own_tax_no: row.own_tax_no || '',
      own_legal_person: row.own_legal_person || '',
      own_address: row.own_address || '',
      own_contact: row.own_contact || '',
      own_phone: row.own_phone || '',
      own_bank_name: row.own_bank_name || '',
      own_bank_account: row.own_bank_account || '',
      sign_date: row.sign_date || '',
      sign_place: row.sign_place || '',
      valid_from: row.valid_from || '',
      valid_to: row.valid_to || '',
      delivery_date: row.delivery_date || '',
      delivery_place: row.delivery_place || '',
      delivery_method: row.delivery_method || '',
      freight_bearer: row.freight_bearer || '',
      payment_terms: row.payment_terms || '',
      invoice_requirement: row.invoice_requirement || '',
      quality_standard: row.quality_standard || '',
      package_standard: row.package_standard || '',
      inspection_days: row.inspection_days ?? '',
      objection_days: row.objection_days ?? '',
      warranty_terms: row.warranty_terms || '',
      // 后端存的是日利率小数，界面按「万分之几」填 → ×10000 还原
      penalty_rate: row.penalty_rate === null || row.penalty_rate === undefined
        ? ''
        : String(Number(row.penalty_rate) * 10000),
      dispute_resolution: row.dispute_resolution || '',
      copies: row.copies ?? '',
      service_address: row.service_address || '',
      other_terms: row.other_terms || '',
      note: row.note || '',
      items: (row.items || []).length
        ? row.items.map((line) => ({
            product_id: line.product_id ?? '',
            quantity: String(line.quantity ?? '1'),
            unit_price: String(line.unit_price ?? '0'),
            unit: line.unit || '',
          }))
        : [{ product_id: '', quantity: '1', unit_price: '0' }],
    });
    setNotice(`正在编辑合同 ${row.contract_no}，改完点「保存合同修改」。`);
    if (typeof window !== 'undefined') window.scrollTo({ top: 0, behavior: 'smooth' });
  };

  const cancelContractEdit = () => {
    setContractEditingId(null);
    setContractForm({ ...emptyContractForm, items: [{ product_id: '', quantity: '1', unit_price: '0' }] });
    setNotice('已取消编辑。');
  };

  /** 合同反审核：已签订 / 执行中 → 草稿。已生成单据的合同不允许回退，避免单据断链。 */
  const unsubmitContract = async (row) => {
    if (!row) return false;
    setNotice('');
    try {
      const response = await fetch(`${API_BASE}/contracts/${row.id}/status`, {
        method: 'PATCH',
        headers: {
          'Content-Type': 'application/json',
          ...(authToken ? { Authorization: `Bearer ${authToken}` } : {}),
        },
        body: JSON.stringify({ status: 'draft' }),
      });
      const data = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(data.detail || '反审核失败');
      setContracts((prev) => prev.map((item) => (item.id === row.id ? data : item)));
      setSelectedContract(null);
      setNotice(`合同 ${row.contract_no} 已退回草稿，可以重新编辑。`);
      return true;
    } catch (err) {
      setNotice(err.message || '反审核失败');
      return false;
    }
  };
'''
text = sub_once(text, OLD_CT_TAIL, NEW_CT_TAIL, "contract-tail")

# --------------------------------------------------------------- 4. ctx 导出
text = sub_once(
    text,
    """  startQuotationEdit,
  cancelQuotationEdit,
  quotationEditingId,
  unsubmitQuotation,
""",
    """  startQuotationEdit,
  cancelQuotationEdit,
  quotationEditingId,
  unsubmitQuotation,
  startSalesReturnEdit,
  cancelSalesReturnEdit,
  salesReturnEditingId,
  saveSalesReturnDraft,
  unsubmitSalesReturn,
  startContractEdit,
  cancelContractEdit,
  contractEditingId,
  unsubmitContract,
""",
    "ctx-export",
)

APP.write_bytes(text.replace("\n", "\r\n").encode("utf-8"))
crlf = APP.read_bytes().count(b"\r\n")
lf_only = APP.read_bytes().count(b"\n") - crlf
print(f"OK App.jsx 已更新 · CRLF={crlf} 纯LF={lf_only} · 备份={BACKUP.name}")
