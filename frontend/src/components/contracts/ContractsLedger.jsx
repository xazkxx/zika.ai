// 合同台账（第 13 批 · 第三阶段 · 第一步）
//
// 为什么是一个**自包含组件**，而不是改 `pages/ContractsPage.jsx`：
//   · `ContractsPage.jsx` 是 `scripts/extract_pages.py` 从 App.jsx 抽出来的 JSX，
//     开头就是 300 多行 `ctx` 解构 —— 它自己不持有任何状态，所有逻辑都在 App.jsx 里。
//     要给它加"方向 Tab + 导出 + 原件 + OCR"，等于改 App.jsx 的核心建单逻辑，
//     而那条链路还挂着转单、打印、强制删除，动一下就是全站回归。
//   · 所以按项目既定规矩「不动核心逻辑，先写独立组件」：本组件**自己取数、自己存状态**，
//     只依赖 `lib/` 与两个通用组件，挂在独立菜单 key `contracts-ledger` 上。
//   · 老页面「购销合同」保持原样（A2 逐条条款表单 + 转单），两者定位不同：
//       购销合同 = 逐条填条款、开单；
//       合同台账 = 看/筛/导出/挂原件/看识别结果。
//
// 数据获取：`localStorage.erp_token`（与 components/partner-tree/partnerTreeApi.js 同一套约定），
// 不通过 ctx 传 authHeaders —— 组件因此在任何页面里都能直接复用。

import { useCallback, useEffect, useMemo, useRef, useState } from 'react';

import ErpSearchSelect from '../ui/ErpSearchSelect.jsx';
import ErpTable from '../ui/ErpTable.jsx';
import PartyQuickCreate from './PartyQuickCreate.jsx';
import { API_BASE } from '../../lib/appLib.js';
import { exportWord } from '../../lib/wordExport.js';
import { confirmDanger } from '../../lib/printConfirm.js';
// 落盘统一口（见 lib/download.js 顶部）：能直写磁盘就不走下载管道，
// 否则文件带"来自 Internet"标记，Excel 会送进受保护视图、坏掉时报"文件已损坏"。
import { saveBlobSmart } from '../../lib/download.js';
import {
  CONTRACT_TABS,
  OCR_STATUS_LABELS,
  applyProductToRow,
  buildCreatePayload,
  cleanItems,
  contractTotal,
  emptyContractForm,
  emptyContractItem,
  exportQuery,
  fileNameFromDisposition,
  findPartyByName,
  formatFileSize,
  formatMoney,
  itemAmount,
  ocrLabel,
  statusLabel,
  tabOf,
  toMoney2,
  toRate4,
  validateContractForm,
} from '../../lib/contractsLedger.js';
import './contractsLedger.css';

// ---------------------------------------------------------------------------
// 请求工具
// ---------------------------------------------------------------------------

function authHeaders() {
  const token = localStorage.getItem('erp_token') || '';
  return token ? { Authorization: `Bearer ${token}` } : {};
}

/**
 * 统一的接口调用。错误一律转成中文 Error：
 * FastAPI 的 422 会给 `detail: [{loc, msg}]`，直接弹出去用户只看到一坨 JSON。
 */
async function api(path, options = {}) {
  const response = await fetch(`${API_BASE}${path}`, {
    ...options,
    headers: { ...authHeaders(), ...(options.headers || {}) },
  });
  if (!response.ok) {
    const data = await response.json().catch(() => ({}));
    const detail = data.detail;
    const message = typeof detail === 'string' ? detail : `请求失败（HTTP ${response.status}）`;
    throw new Error(message);
  }
  return response.json();
}

/**
 * 这个文件是不是 Word 原件（.doc/.docx/…）。
 *
 * 服务端只把 Word 当"可存档的原件"，从来不解析它 —— 让用户点完识别再吃一个
 * 红字报错，等于白等一次。所以前端在**选文件的瞬间**就认出来并给出黄色提示。
 * 后缀和 MIME 都看一眼：有些系统给 .docx 的 type 是空的。
 */
const WORD_SUFFIX_RE = /\.(doc|docx|docm|dot|dotx|rtf|wps)$/i;
const WORD_MIME_TYPES = new Set([
  'application/msword',
  'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
  'application/rtf',
]);

function isWordFile(file) {
  if (!file) return false;
  if (WORD_SUFFIX_RE.test(String(file.name || ''))) return true;
  return WORD_MIME_TYPES.has(String(file.type || '').toLowerCase());
}

/**
 * 本组件的落盘口。原来是"blob URL + a[download]"，现在统一委托给 `saveBlobSmart`：
 * 能「另存为」直写磁盘就直写（文件不带 Mark-of-the-Web），不支持才退回普通下载。
 * ⚠️ 副作用是变成**异步**了，调用处必须 `await` —— 否则空文件校验抛出的错误
 *    会变成未处理的 Promise 拒绝，用户那边就是"点了没反应"。
 */
async function saveBlob(blob, filename) {
  return saveBlobSmart(blob, filename);
}

// ---------------------------------------------------------------------------
// 主组件
// ---------------------------------------------------------------------------

export default function ContractsLedger() {
  const [direction, setDirection] = useState('out');
  const [keywordInput, setKeywordInput] = useState('');
  const [keyword, setKeyword] = useState('');

  const [rows, setRows] = useState([]);
  const [loading, setLoading] = useState(true);
  const [listError, setListError] = useState('');

  const [meta, setMeta] = useState(null);
  const [customers, setCustomers] = useState([]);
  const [suppliers, setSuppliers] = useState([]);
  const [products, setProducts] = useState([]);

  const [notice, setNotice] = useState('');
  const [exporting, setExporting] = useState(false);

  const [formOpen, setFormOpen] = useState(false);
  const [form, setForm] = useState(() => emptyContractForm('out'));
  const [formError, setFormError] = useState('');
  const [saving, setSaving] = useState(false);

  // ---- 新建弹窗的「智能优先」草稿：传原件 → 识别 → 按策略回填 → 保存时一并落库 ----
  // 老流程是"先建合同 → 进详情 → 上传 → 识别 → 再回填表单"，等于建两次单；
  // 新流程把原件先放进服务端 tmp/（拿到 temp_token），识别直接读它，保存时才搬进正式目录。
  const [draftFile, setDraftFile] = useState(null); // { temp_token, file_name, file_size }
  const [draftUploading, setDraftUploading] = useState(false);
  const [draftOcr, setDraftOcr] = useState(null); // 识别结果（fields / items / ocr_json）
  const [draftOcrRunning, setDraftOcrRunning] = useState(false);
  const [draftError, setDraftError] = useState('');
  // Word 原件的"温和提示"。刻意与 draftError（红字）分开：
  // 用户选错格式不是错误，只是这条路走不通 —— 用黄色提示，别吓人。
  const [draftWordHint, setDraftWordHint] = useState('');
  // 识别完成时表单里**已经有内容** → 存已填项名字；此时一个字都不自动改，等用户选策略
  const [draftConflict, setDraftConflict] = useState(null);
  const [draftApplied, setDraftApplied] = useState(''); // auto|empty-only|overwrite|skip|''
  // 往来单位匹配结果提示（任务 E 修 Bug 2）：OCR 只回了文字、没对上档案时，
  // 必须**贴在字段下面**说清楚，不能只在页面顶端闪一句 notice —— 用户看不到。
  const [partyHint, setPartyHint] = useState(null); // { tone: 'warn'|'info', text }

  // 就地补档案：{ kind: 'customer'|'supplier', name: string } | null
  // 只在「未匹配到系统客户」时出现 —— 用户往往就是开合同的时候才发现档案没录。
  const [quickCreate, setQuickCreate] = useState(null);

  const [detail, setDetail] = useState(null);
  // 《工矿产品购销合同》正文预览（2026-10-22）：
  // 存的是后端渲染好的 document + 生成它用的 payload —— 导出 PDF 时原样回传，
  // 保证"预览看到的"和"导出的"是同一份数据（各算一遍迟早会不一样）。
  const [docPreview, setDocPreview] = useState(null);
  const [docBusy, setDocBusy] = useState('');
  const [detailBusy, setDetailBusy] = useState(false);
  const draftInputRef = useRef(null);

  const tab = tabOf(direction);
  const isInbound = direction === 'in';

  /** 新建弹窗里识别结果的字段卡片（详情页那套是"识别 vs 已存合同"，这里只列识别到什么） */
  const draftChips = useMemo(() => {
    const fields = draftOcr?.fields || {};
    const chips = [];
    if (fields.contract_no) chips.push(['编号', fields.contract_no]);
    if (fields.title) chips.push(['标题', fields.title]);
    if (fields.party_name) chips.push([tab.partyLabel, fields.party_name]);
    if (fields.total_amount != null) chips.push(['金额', `¥${formatMoney(fields.total_amount)}`]);
    if (fields.sign_date) chips.push(['签订日期', fields.sign_date]);
    if (fields.payment_terms) chips.push(['付款条款', fields.payment_terms]);
    return chips;
  }, [draftOcr, tab]);

  // ---- 列表 ----
  /**
   * ⚠️ 必须带「只认最后一次请求」的守卫（`requestRef`）。
   * 没有它就会出现这种真实故障：进页面时先发了 `direction=out` 的请求，用户很快点了
   * 「采购合同（进）」→ 第二个请求先回来并渲染，第一个请求随后回来把 rows 覆盖成
   * **销售方向的结果**（若销售方向为空，就变成"进方向显示空态"）。
   * 表现是"切了 Tab 但列表说还没有数据"，而且偶发（取决于两个请求谁先到）。
   * E2E 里表现为 F16/F17 偶尔红，单独跑又全绿 —— 正是竞态的典型症状。
   */
  const requestRef = useRef(0);
  const loadRows = useCallback(
    async (nextDirection, nextKeyword) => {
      const ticket = requestRef.current + 1;
      requestRef.current = ticket;
      setLoading(true);
      setListError('');
      try {
        const params = new URLSearchParams({ direction: nextDirection });
        if (nextKeyword) params.set('keyword', nextKeyword);
        const data = await api(`/contracts?${params.toString()}`);
        if (ticket !== requestRef.current) return; // 过期响应，丢弃
        setRows(Array.isArray(data) ? data : []);
      } catch (err) {
        if (ticket !== requestRef.current) return;
        setRows([]);
        setListError(err.message || '合同列表加载失败');
      } finally {
        if (ticket === requestRef.current) setLoading(false);
      }
    },
    [],
  );

  // ---- 基础数据（只拉一次）----
  useEffect(() => {
    let alive = true;
    (async () => {
      try {
        const [metaData, customerData, supplierData, productData] = await Promise.all([
          api('/contracts/meta'),
          api('/customers'),
          api('/suppliers'),
          api('/products'),
        ]);
        if (!alive) return;
        setMeta(metaData);
        setCustomers(Array.isArray(customerData) ? customerData : []);
        setSuppliers(Array.isArray(supplierData) ? supplierData : []);
        setProducts(Array.isArray(productData) ? productData : []);
      } catch (err) {
        if (alive) setNotice(err.message || '基础档案加载失败（客户/供应商/商品）');
      }
    })();
    return () => {
      alive = false;
    };
  }, []);

  useEffect(() => {
    loadRows(direction, keyword);
  }, [direction, keyword, loadRows]);

  // ---- 方向切换 ----
  const switchDirection = (next) => {
    if (next === direction) return;
    setDirection(next);
    setKeyword('');
    setKeywordInput('');
  };

  // ---- 导出 Excel ----
  const exportExcel = async () => {
    setExporting(true);
    setNotice('');
    try {
      const qs = exportQuery(direction);
      const response = await fetch(`${API_BASE}/exports/contracts?${qs}`, { headers: authHeaders() });
      if (!response.ok) {
        const data = await response.json().catch(() => ({}));
        const detailText = typeof data.detail === 'string' ? data.detail : `HTTP ${response.status}`;
        throw new Error(`导出失败：${detailText}`);
      }
      const blob = await response.blob();
      const filename = fileNameFromDisposition(
        response.headers.get('Content-Disposition'),
        `合同台账_${tab.shortLabel}_${new Date().toISOString().slice(0, 10)}.xlsx`,
      );
      await saveBlob(blob, filename);
      setNotice(`已导出「${tab.label}」台账：${filename}（主表 + 明细两张工作表）`);
    } catch (err) {
      setNotice(err.message || '导出失败');
    } finally {
      setExporting(false);
    }
  };

  // ---- 新建 ----
  const resetDraft = () => {
    setDraftFile(null);
    setDraftOcr(null);
    setDraftError('');
    setDraftWordHint('');
    setDraftConflict(null);
    setDraftApplied('');
    setDraftUploading(false);
    setDraftOcrRunning(false);
    setPartyHint(null); // 换文件/关弹窗时，上一条"未匹配"提示不能留着误导下一单
    setQuickCreate(null); // 小弹窗正开着也要一起关，否则下一单会带着上一单的名字
    if (draftInputRef.current) draftInputRef.current.value = '';
  };

  /** 丢弃临时文件（换文件 / 关弹窗时）。删不掉不算错 —— 服务端 24h 也会清。 */
  const dropDraftFile = (token) => {
    if (!token) return;
    fetch(`${API_BASE}/contracts/ocr/upload?token=${encodeURIComponent(token)}`, {
      method: 'DELETE',
      headers: authHeaders(),
    }).catch(() => {});
  };

  const openCreate = () => {
    setForm(emptyContractForm(direction));
    setFormError('');
    resetDraft();
    setFormOpen(true);
  };

  const closeCreate = () => {
    if (saving) return;
    // 没保存就走人：把暂存的原件一起丢掉，别在 tmp/ 里留垃圾
    dropDraftFile(draftFile?.temp_token);
    setFormOpen(false);
    resetDraft();
  };

  const patchForm = (field, value) => setForm((prev) => ({ ...prev, [field]: value }));

  const patchItem = (index, field, value) =>
    setForm((prev) => {
      const items = prev.items.map((row, i) => {
        if (i !== index) return row;
        const next = { ...row, [field]: value };
        if (field === 'quantity' || field === 'unit_price') {
          next.amount = itemAmount(next.quantity, next.unit_price);
        }
        return next;
      });
      return { ...prev, items };
    });

  const pickProduct = (index, product) =>
    setForm((prev) => ({
      ...prev,
      items: prev.items.map((row, i) =>
        i === index ? applyProductToRow(row, product, prev.direction) : row,
      ),
    }));

  const addItem = () =>
    setForm((prev) => ({ ...prev, items: [...prev.items, emptyContractItem()] }));

  const removeItem = (index) =>
    setForm((prev) => ({
      ...prev,
      // 至少留一行：全删光后用户面对一张空表，得先找"加一行"在哪
      items: prev.items.length <= 1 ? prev.items : prev.items.filter((_, i) => i !== index),
    }));

  const submitForm = async (event) => {
    event.preventDefault();
    const invalid = validateContractForm(form);
    if (invalid) {
      setFormError(invalid);
      return;
    }
    setFormError('');
    setSaving(true);
    try {
      const payload = buildCreatePayload(form);
      // 原件与识别结果**随合同一次落库**：tmp/ 里的文件由后端搬进正式目录，
      // ocr_json 原样存下来（日后要能回看"当时到底认成了什么"）。
      if (draftFile?.temp_token) {
        payload.source_temp_token = draftFile.temp_token;
        payload.source_file_name = draftFile.file_name;
      }
      if (draftOcr?.ocr_json) {
        payload.ocr_json = draftOcr.ocr_json;
        // reviewed = 识别结果经人核对**并采用了**（表单里就是这些值）；
        // parsed  = 识别过但用户选了「暂不填充」→ 合同内容与识别无关，不能谎称核对过。
        payload.ocr_status = draftApplied && draftApplied !== 'skip' ? 'reviewed' : 'parsed';
      }

      const created = await api('/contracts', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      });

      const sourceNote = draftFile?.temp_token ? '，原件已随合同保存' : '';
      setFormOpen(false);
      resetDraft(); // 文件已"转正"，不能再走丢弃逻辑
      setNotice(`合同 ${created.contract_no} 已创建${sourceNote}`);
      await loadRows(direction, keyword);
      openDetail(created.id);
    } catch (err) {
      setFormError(err.message || '保存失败');
    } finally {
      setSaving(false);
    }
  };

  // ---- 新建弹窗：原件暂存 → 预识别 → 按策略回填 ----

  /** 选文件即上传到 tmp/（拿到 temp_token）；换文件时先丢弃上一份。 */
  const pickDraftFile = async (file) => {
    if (!file || draftUploading || draftOcrRunning) return;

    // Word 原件：上传前就拦住。不置 draftFile → 「开始识别」按钮保持禁用，
    // 用户不会点下去等半天再吃一个红字报错；提示走黄色，不走红色报错位。
    if (isWordFile(file)) {
      setDraftWordHint(
        `「${file.name}」是 Word 文档，暂不支持直接识别。请在 Word 里「另存为」PDF，再回来上传。`,
      );
      setDraftError('');
      // 清空 input 的值，否则用户改完格式再选同一个文件名不会触发 change
      if (draftInputRef.current) draftInputRef.current.value = '';
      return;
    }

    setDraftWordHint('');
    setDraftError('');
    setDraftOcr(null); // 换了原件，上一次的识别结果必须作废
    setDraftConflict(null);
    setDraftApplied('');
    setDraftUploading(true);
    try {
      if (draftFile?.temp_token) dropDraftFile(draftFile.temp_token);
      const body = new FormData();
      body.append('file', file);
      // ⚠️ 不要手写 Content-Type：浏览器要自己加 multipart 的 boundary
      const response = await fetch(`${API_BASE}/contracts/ocr/upload`, {
        method: 'POST',
        headers: authHeaders(),
        body,
      });
      const data = await response.json().catch(() => ({}));
      if (!response.ok) {
        const detailText = data?.detail;
        throw new Error(
          typeof detailText === 'string' ? detailText : `上传失败（HTTP ${response.status}）`,
        );
      }
      setDraftFile(data);
    } catch (err) {
      setDraftFile(null);
      setDraftError(err.message || '原件上传失败');
    } finally {
      setDraftUploading(false);
    }
  };

  /**
   * 表单里"用户已经填了"的项（用于冲突提示）。
   * ⚠️ 新建表单天生带默认值（标题=销售合同/采购合同、签订日期=今天、税率=13），
   * 这些**不算**用户填过 —— 否则永远会弹冲突条，保护就变成了噪声。
   */
  const filledLabels = (current) => {
    const labels = [];
    const defaultTitle = current.direction === 'in' ? '采购合同' : '销售合同';
    const title = String(current.title || '').trim();
    if (title && title !== defaultTitle) labels.push('合同标题');
    if (
      String(current.party_id || '').trim() ||
      String(current.party_name || '').trim()
    ) {
      labels.push(tabOf(current.direction).partyLabel);
    }
    const today = new Date().toISOString().slice(0, 10);
    if (current.sign_date && current.sign_date !== today) labels.push('签订日期');
    if (String(current.payment_terms || '').trim()) labels.push('付款条款');
    const rows = cleanItems(current.items).length;
    if (rows > 0) labels.push(`${rows} 行明细`);
    if (String(current.note || '').trim()) labels.push('备注');
    return labels;
  };

  /** 识别明细 → 表单行（商品按名称归一后精确匹配档案，匹配不到留空但名称可见） */
  const ocrItemsToRows = (items) => {
    const list = Array.isArray(items) ? items : [];
    if (!list.length) return null;
    const normalizeName = (value) => String(value || '').replace(/[\s（）()]/g, '');
    return list.map((item) => {
      const itemName = String(item.product_name || '').trim();
      const productHit = itemName
        ? products.find((p) => normalizeName(p.name) === normalizeName(itemName))
        : null;
      // ⚠️ 进表单前先统一精度（Bug 1 / Bug 3 的同一处根因）：
      //   · 数量、单价是"费率"——最多 4 位、去掉尾随 0；
      //     **绝不能 toFixed(2)**：73.901 抹成 73.90 后 ×580 就少 0.58 元；
      //   · 金额是"钱"——严格 2 位；
      //   · 金额用**清洗后**的数量/单价算，保证"表单上显示的单价 × 数量"能复算出这一行的金额。
      const quantity = toRate4(item.quantity) || '1';
      const unitPrice = toRate4(item.unit_price);
      return {
        ...emptyContractItem(),
        product_id: productHit ? String(productHit.id) : '',
        product_name: itemName,
        standards: productHit?.standards || '',
        // 档案里有单位就用档案的（跟库存口径一致）；档案里没有就用识别出的单位 ——
        // 扫描件表格本来就有"单位"列，白扔掉的话明细会是个没单位的数字
        unit: productHit?.unit || String(item.unit || ''),
        quantity,
        unit_price: unitPrice,
        amount: toMoney2(itemAmount(quantity, unitPrice)),
      };
    });
  };

  /**
   * 识别到的对方单位 → 档案。返回 `{ item, fuzzy }` 或 null。
   * 真匹配上了就一定要带回 `party_id`，否则就是用户说的"假选中"：
   * 下拉框里显示着名字、保存却报"请选择客户"。
   */
  const matchPartyByOcr = (name) =>
    findPartyByName(form.direction === 'in' ? suppliers : customers, name);

  /** 打开「就地新建」小弹窗：名称带过去，方向决定建客户还是供应商 */
  const openQuickCreate = (name) => {
    const partyType = tabOf(form.direction).partyType;
    setQuickCreate({ kind: partyType === 'supplier' ? 'supplier' : 'customer', name: String(name || '').trim() });
  };

  /**
   * 小弹窗建好之后：把新档案**同时**写进三条管道，缺一条就还是"假选中"——
   *   ① `form.party_id`（决定有没有选中）；
   *   ② `form.party_name`（决定框里显示什么）；
   *   ③ 本地的 customers/suppliers 列表（决定下拉里能不能立刻看到它）。
   * 另外要把"未匹配"黄条和"只是显示的文字"红条一起清掉，否则用户以为没生效。
   */
  const handleQuickCreated = (item, info = {}) => {
    if (!item || item.id === undefined || item.id === null) {
      setQuickCreate(null);
      return;
    }
    const id = String(item.id);
    const name = String(item.name || '');
    const isSupplier = quickCreate?.kind === 'supplier';

    setForm((prev) => ({ ...prev, party_id: id, party_name: name }));
    if (isSupplier) {
      setSuppliers((prev) => [item, ...prev.filter((row) => String(row.id) !== id)]);
    } else {
      setCustomers((prev) => [item, ...prev.filter((row) => String(row.id) !== id)]);
    }
    setPartyHint(null);
    setQuickCreate(null);
    setFormError((prev) => (prev && /只是显示的文字|请选择(客户|供应商)/.test(prev) ? '' : prev));
    setNotice(
      info.reused
        ? `系统里已有「${name}」，已直接选中（没有再建一条重复档案）`
        : `已新建${isSupplier ? '供应商' : '客户'}「${name}」并选中`,
    );
  };

  /**
   * 按策略把识别结果填进表单 —— **绝不无脑覆盖**：
   *   auto / empty-only：只填当前为空（或仍是默认值）的项，用户填过的一个字都不动；
   *   overwrite：整块替换，连明细一起换（用户是在"确认覆盖"后才点到的）。
   * 备注只写"回填说明"，且只在用户没写备注时写 —— 备注是人的话，机器不抢。
   */
  const applyDraftOcr = (pack, strategy) => {
    if (!pack) return;
    const fields = pack.fields || {};
    const rows = ocrItemsToRows(pack.items);
    const targetName = String(fields.party_name || '').trim();
    const hit = matchPartyByOcr(targetName); // { item, fuzzy } | null
    const today = new Date().toISOString().slice(0, 10);
    const overwrite = strategy === 'overwrite';
    // ⚠️ 这里必须在 setForm **之外**算好"要不要动对方单位"：
    //    setForm 的 updater 是下一次渲染才执行的，在它里面改外部变量、
    //    再在下一行读 —— 读到的一定是旧值（React 18 下这是真坑）。
    const partyFilledNow = Boolean(
      String(form.party_id || '').trim() || String(form.party_name || '').trim(),
    );
    const willTouchParty = (overwrite || !partyFilledNow) && Boolean(targetName || hit);

    setForm((prev) => {
      const next = { ...prev };

      const defaultTitle = prev.direction === 'in' ? '采购合同' : '销售合同';
      const titleFilled =
        String(prev.title || '').trim() && String(prev.title || '').trim() !== defaultTitle;
      if (fields.title && (overwrite || !titleFilled)) next.title = fields.title;

      const partyFilled = Boolean(
        String(prev.party_id || '').trim() || String(prev.party_name || '').trim(),
      );
      if ((overwrite || !partyFilled) && (targetName || hit)) {
        // ⚠️ Bug 2 的关键一行：匹配上了就必须写 party_id（下拉框的 value），
        //    只写 party_name 只是"显示"，保存时校验看的是 party_id → "假选中"。
        next.party_id = hit ? String(hit.item.id) : '';
        next.party_name = hit ? hit.item.name : targetName;
      }

      const dateFilled = Boolean(prev.sign_date && prev.sign_date !== today);
      if (fields.sign_date && (overwrite || !dateFilled)) next.sign_date = fields.sign_date;

      if (
        fields.payment_terms &&
        (overwrite || !String(prev.payment_terms || '').trim())
      ) {
        next.payment_terms = fields.payment_terms;
      }

      if (!String(prev.note || '').trim()) {
        next.note = fields.contract_no
          ? `OCR 识别回填（合同编号 ${fields.contract_no}），请逐项核对`
          : 'OCR 识别回填，请逐项核对';
      }

      const itemsFilled = cleanItems(prev.items).length > 0;
      if (rows && rows.length && (overwrite || !itemsFilled)) next.items = rows;

      return next;
    });

    // 黄色提示贴在字段下面（不是只在页面顶端闪一句）：
    //   · 没匹配上 → 明确告诉用户"保留的是识别文本，得自己选一次"
    //   · 唯一相似 → 告诉用户"按名字像的匹配了，请确认"（不静默，合同主体错了要重开）
    if (willTouchParty && !hit && targetName) {
      setPartyHint({
        tone: 'warn',
        text: `未匹配到系统${tab.partyLabel}「${targetName}」，已保留识别到的名称。请点开下拉手动选一次，否则保存会被拦。`,
      });
    } else if (willTouchParty && hit?.fuzzy) {
      setPartyHint({
        tone: 'info',
        text: `按名称相似匹配到「${hit.item.name}」，请确认是不是同一家；不是就重新选一次。`,
      });
    } else if (willTouchParty) {
      setPartyHint(null);
    }

    setDraftApplied(strategy);
    setDraftConflict(null);
    setNotice(
      hit
        ? `已按识别结果填入表单；${tab.partyLabel}「${hit.item.name}」已匹配到档案，请核对明细与金额`
        : '已按识别结果填入表单；对方单位没有匹配到档案，请手动选择',
    );
  };

  const startDraftOcr = async () => {
    if (!draftFile?.temp_token || draftOcrRunning) return;
    setDraftOcrRunning(true);
    setDraftError('');
    setDraftConflict(null);
    try {
      const result = await api('/contracts/ocr/recognize', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          temp_token: draftFile.temp_token,
          direction: form.direction,
          file_name: draftFile.file_name,
        }),
      });
      setDraftOcr(result);
      const filled = filledLabels(form);
      if (filled.length === 0) {
        // 表单本来就是空的：直接填，少点一次（不存在覆盖问题）
        applyDraftOcr(result, 'auto');
      } else {
        // 有内容：一个字都不动，等用户选「仅填空白 / 覆盖 / 暂不填」
        setDraftConflict(filled);
        setDraftApplied('');
        setNotice('识别完成。检测到表单里已有内容，请选择填充方式');
      }
    } catch (err) {
      setDraftError(err.message || '识别失败');
    } finally {
      setDraftOcrRunning(false);
    }
  };

  // ---- 详情 ----
  const openDetail = async (contractId) => {
    setDetailBusy(true);
    try {
      const data = await api(`/contracts/${contractId}`);
      setDetail(data);
    } catch (err) {
      setNotice(err.message || '合同详情加载失败');
    } finally {
      setDetailBusy(false);
    }
  };

  const closeDetail = () => setDetail(null);

  // ---- 原件 ----
  const uploadSource = async (contractId, file) => {
    const body = new FormData();
    body.append('file', file);
    // ⚠️ 不要手写 Content-Type：浏览器要自己加 multipart 的 boundary
    const response = await fetch(`${API_BASE}/contracts/${contractId}/source`, {
      method: 'POST',
      headers: authHeaders(),
      body,
    });
    if (!response.ok) {
      const data = await response.json().catch(() => ({}));
      throw new Error(typeof data.detail === 'string' ? data.detail : `上传失败（HTTP ${response.status}）`);
    }
    return response.json();
  };

  const reuploadSource = async (file) => {
    if (!detail || !file) return;
    try {
      await uploadSource(detail.id, file);
      setNotice(`原件「${file.name}」已上传`);
      await openDetail(detail.id);
      await loadRows(direction, keyword);
    } catch (err) {
      setNotice(err.message || '原件上传失败');
    }
  };

  const downloadSource = async (row) => {
    const target = row || detail;
    if (!target) return;
    try {
      const response = await fetch(`${API_BASE}/contracts/${target.id}/source`, {
        headers: { Accept: 'application/json', ...authHeaders() },
      });
      if (!response.ok) {
        const data = await response.json().catch(() => ({}));
        throw new Error(typeof data.detail === 'string' ? data.detail : '下载失败');
      }
      const payload = await response.json();
      const binary = atob(payload.content_base64 || '');
      const bytes = new Uint8Array(binary.length);
      for (let i = 0; i < binary.length; i += 1) bytes[i] = binary.charCodeAt(i);
      const blob = new Blob([bytes], { type: payload.content_type || 'application/octet-stream' });
      await saveBlob(blob, payload.filename || target.source_file_name || 'contract-source');
    } catch (err) {
      setNotice(err.message || '原件下载失败');
    }
  };

  // ---- 删除合同（2026-10-22）----
  // 必须二次确认：合同是法律文件，误删不可恢复（原件文件也会一起清掉）。
  // 已生成单据的合同后端会 409 拦下（那说明这条合同是某张单的溯源线索）。
  const removeContract = async (row) => {
    if (!row) return;
    const decision = await confirmDanger({
      title: '删除合同',
      name: `${row.contract_no || ''}${row.party_name ? ` · ${row.party_name}` : ''}`,
      hint:
        '删除后这份合同、它的明细与已上传的原件文件都会被一并清除，且无法恢复。' +
        '如果只是不想再用它，建议改为把状态置为「已作废」，这样还能查到。',
    });
    if (!decision.ok) return;
    try {
      const response = await fetch(`${API_BASE}/contracts/${row.id}`, {
        method: 'DELETE',
        headers: authHeaders(),
      });
      if (!response.ok) {
        const data = await response.json().catch(() => ({}));
        const detail = data.detail;
        const message =
          typeof detail === 'string'
            ? detail
            : (detail && detail.message) || `删除失败（HTTP ${response.status}）`;
        const hint = detail && detail.hint ? `\n${detail.hint}` : '';
        throw new Error(`${message}${hint}`);
      }
      setNotice(`合同 ${row.contract_no} 已删除`);
      if (detail && String(detail.id) === String(row.id)) closeDetail();
      await loadRows(direction, keyword);
    } catch (err) {
      setNotice(err.message || '删除失败');
    }
  };

  // ---- 按《工矿产品购销合同》范本生成正文（2026-10-22）----
  // 刻意**不写库**：用户常常只是"填完想看看正文长什么样"。
  // 表单没填的条款项由后端按行业常规兜底（见 contract_template.DEFAULTS），
  // 所以哪怕只填了客户和明细，也能得到一份能直接拿去谈的完整文本。
  const openContractDocument = async () => {
    const invalid = validateContractForm(form);
    if (invalid) {
      setFormError(invalid);
      return;
    }
    setDocBusy('preview');
    setFormError('');
    try {
      const payload = buildCreatePayload(form);
      const data = await api('/contracts/document/preview', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      });
      setDocPreview({ document: data.document, payload });
    } catch (err) {
      setFormError(err.message || '生成合同正文失败');
    } finally {
      setDocBusy('');
    }
  };

  // —— 业务流转（2026-10-25）：先 Word 确认，后 PDF 盖章 ——
  const exportContractDocumentWord = async () => {
    if (!docPreview) return;
    setDocBusy('word');
    try {
      const response = await fetch(`${API_BASE}/exports/word/contract-document`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...authHeaders() },
        body: JSON.stringify(docPreview.payload),
      });
      if (!response.ok) {
        const data = await response.json().catch(() => ({}));
        throw new Error(typeof data.detail === 'string' ? data.detail : '生成 Word 失败');
      }
      const blob = await response.blob();
      const no = String(docPreview.document.contract_no || '').replace(/[\\/:*?"<>|]/g, '');
      await saveBlob(blob, `合同正文-${no || '草稿'}.docx`);
      setNotice('Word 版已下载：请先与客户确认修改，确认无误后再生成 PDF 盖章版');
    } catch (err) {
      setNotice(err.message || '生成 Word 失败');
    } finally {
      setDocBusy('');
    }
  };

  const exportContractDocumentPdf = async () => {
    if (!docPreview) return;
    // 防呆提示：PDF 是拿去盖章的，别让用户跳过 Word 确认那一步
    const okToSeal = window.confirm(
      '建议先下载 Word 版与客户确认。若已确认无误，是否直接生成最终 PDF（盖章版）？',
    );
    if (!okToSeal) return;
    setDocBusy('pdf');
    try {
      const response = await fetch(`${API_BASE}/print/contract-document/pdf`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', Accept: 'application/json', ...authHeaders() },
        body: JSON.stringify(docPreview.payload),
      });
      if (!response.ok) {
        const data = await response.json().catch(() => ({}));
        throw new Error(typeof data.detail === 'string' ? data.detail : '生成 PDF 失败');
      }
      const payload = await response.json();
      const binary = atob(payload.content_base64 || '');
      const bytes = new Uint8Array(binary.length);
      for (let i = 0; i < binary.length; i += 1) bytes[i] = binary.charCodeAt(i);
      await saveBlob(new Blob([bytes], { type: payload.content_type || 'application/pdf' }), payload.filename);
      setNotice('合同正文 PDF 已生成');
    } catch (err) {
      setNotice(err.message || '生成 PDF 失败');
    } finally {
      setDocBusy('');
    }
  };

  // ---- 打印 ----
  const printContract = async (row) => {
    const target = row || detail;
    if (!target) return;
    try {
      const response = await fetch(`${API_BASE}/print/contract/${target.id}`, {
        headers: { Accept: 'application/json', ...authHeaders() },
      });
      if (!response.ok) {
        const data = await response.json().catch(() => ({}));
        throw new Error(typeof data.detail === 'string' ? data.detail : '生成打印文件失败');
      }
      const payload = await response.json();
      const binary = atob(payload.content_base64 || '');
      const bytes = new Uint8Array(binary.length);
      for (let i = 0; i < binary.length; i += 1) bytes[i] = binary.charCodeAt(i);
      await saveBlob(new Blob([bytes], { type: payload.content_type || 'application/pdf' }), payload.filename);
      setNotice(`合同 ${target.contract_no} 的 PDF 已生成`);
    } catch (err) {
      setNotice(err.message || '打印失败');
    }
  };

  // ---- 导出 Word（任务 E · 2026-10-19）----
  // 只读导出，不动任何业务字段；失败只提示不弹窗（导出失败不该打断正在做的事）。
  const [wordBusy, setWordBusy] = useState(false);
  const exportWordFile = async (row) => {
    const target = row || detail;
    if (!target?.id || wordBusy) return;
    setWordBusy(true);
    try {
      const name = await exportWord(
        'contract',
        target.id,
        `购销合同-${target.contract_no || target.id}.docx`,
      );
      setNotice(`已导出 ${name}`);
    } catch (err) {
      setNotice(err.message || '导出失败');
    } finally {
      setWordBusy(false);
    }
  };

  // ---- OCR 识别（任务 B · 2026-10-19）----
  //
  // 后端 `POST /contracts/:id/ocr` 负责"跑引擎 + 落库 + 提取候选字段"；
  // 前端只负责三件事：触发、展示（骨架屏 / 字段 / 原始 JSON）、把候选回填到表单。
  // 识别一定有错 —— 所以回填永远落到**表单**里让人核对，绝不直接改合同字段；
  // 把状态推进到「已人工核对」的唯一入口是「确认无误」（/ocr/review）。
  const [ocrRunning, setOcrRunning] = useState(false);
  const [ocrError, setOcrError] = useState('');
  const [ocrFields, setOcrFields] = useState(null);
  const [reviewing, setReviewing] = useState(false);

  // 「重新识别」的二次确认：已核对的数据被机器重写**不可逆**，必须拦一道。
  // 用自建小弹窗而不是 window.confirm：原生弹窗一弹就把整个页面线程占住，
  // 也没法写断言（E2E 里 dialog 会被 dismiss 掉，等于永远点不到「继续」）。
  const [ocrConfirm, setOcrConfirm] = useState(false);
  // 合同状态流转（草稿/待审 → 生效）
  const [statusBusy, setStatusBusy] = useState(false);

  /** 详情里那坨 ocr_json 是字符串 —— 解析出候选字段（解析失败就当没有） */
  const detailOcrPack = useMemo(() => {
    if (!detail?.ocr_json) return null;
    try {
      return JSON.parse(detail.ocr_json);
    } catch {
      return null;
    }
  }, [detail]);

  const ocrPack = ocrFields ?? detailOcrPack;

  const startOcr = async () => {
    if (!detail || ocrRunning) return;
    if (!detail.source_file_path) {
      setOcrError('请先上传合同原件（PDF 或图片），再开始识别');
      return;
    }
    setOcrRunning(true);
    setOcrError('');
    try {
      const result = await api(`/contracts/${detail.id}/ocr`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({}),
      });
      setOcrFields(result);
      await openDetail(detail.id);
      setNotice(result.message || '识别完成，请人工核对');
    } catch (err) {
      setOcrError(err.message || '识别失败');
    } finally {
      setOcrRunning(false);
    }
  };

  /**
   * 「开始识别」按钮的真正入口：已核对过就先问一句。
   *
   * 为什么必须拦：`POST /contracts/:id/ocr` 是**机器**写，它会把 `ocr_status`
   * 从 `reviewed` 退回 `parsed`（这是设计，见后端注释：到 reviewed 只能靠人）。
   * 也就是说误点一次，用户"已核对"的结论就被抹了，而且没有任何痕迹。
   */
  const requestOcr = () => {
    if (!detail || ocrRunning) return;
    if (detail.ocr_status === 'reviewed') {
      setOcrConfirm(true);
      return;
    }
    startOcr();
  };

  /**
   * 确认生效（草稿/待审 → 生效）。
   *
   * 后端 `PATCH /contracts/:id/status` 是个**直写**接口（只校验枚举，不做流转规则），
   * 所以前端必须自己把"给哪些状态显示这个按钮"收窄 —— 只在 draft/pending 上出现，
   * 已完成/已作废的合同不该被一键拉回生效。
   */
  const activateContract = async () => {
    if (!detail || statusBusy) return;
    setStatusBusy(true);
    try {
      await api(`/contracts/${detail.id}/status`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ status: 'active' }),
      });
      await openDetail(detail.id);
      await loadRows(direction, keyword);
      setNotice(`合同 ${detail.contract_no} 已生效`);
    } catch (err) {
      setNotice(err.message || '状态更新失败');
    } finally {
      setStatusBusy(false);
    }
  };

  /**
   * 一键回填：把识别候选写进**新增合同表单**（不碰已保存的合同字段）。
   * 对方单位按名称（去空格与括号）在档案里精确匹配 —— 匹配不到就留空让人选，
   * 因为档案名和合同抬头常常差一两个字（"陕西送变电" vs "陕西送变电第一分公司"），
   * 猜错档案比不填严重得多。
   */
  const applyOcrToForm = () => {
    const pack = ocrPack || ocrFields;
    if (!pack) return;
    const fields = pack.fields || {};
    const partyList = isInbound ? suppliers : customers;
    const targetName = String(fields.party_name || '').trim();
    const normalizeName = (value) => String(value || '').replace(/[\s（）()]/g, '');
    const hit = targetName
      ? partyList.find((item) => normalizeName(item.name) === normalizeName(targetName))
      : null;

    const ocrItems = Array.isArray(pack.items) ? pack.items : [];
    // 商品列与对方单位同一套"宁可漏、不可错"：按名称归一后**精确匹配**商品档案，
    // 匹配到就带上档案 id（触发器直接显示档案名）；匹配不到 product_id 留空，
    // 识别名靠 displayValue 兜底显示 —— 用户看得见 OCR 认成了什么，自己改。
    const rows = ocrItems.length
      ? ocrItems.map((item) => {
          const itemName = String(item.product_name || '').trim();
          const productHit = itemName
            ? products.find((p) => normalizeName(p.name) === normalizeName(itemName))
            : null;
          return {
            ...emptyContractItem(),
            product_id: productHit ? String(productHit.id) : '',
            product_name: itemName,
            standards: productHit?.standards || '',
            unit: productHit?.unit || String(item.unit || ''),
            quantity: String(item.quantity ?? '1'),
            unit_price: String(item.unit_price ?? ''),
            amount: itemAmount(item.quantity, item.unit_price),
          };
        })
      : [emptyContractItem()];

    setForm((prev) => ({
      ...prev,
      title: fields.title || prev.title,
      party_id: hit ? String(hit.id) : '',
      party_name: hit ? hit.name : targetName,
      sign_date: fields.sign_date || prev.sign_date,
      payment_terms: fields.payment_terms || prev.payment_terms,
      note: fields.contract_no
        ? `OCR 识别回填（合同编号 ${fields.contract_no}），请逐项核对`
        : 'OCR 识别回填，请逐项核对',
      items: rows,
    }));
    closeDetail();
    setFormOpen(true);
    setNotice(
      hit
        ? `已按识别结果回填表单：${tab.partyLabel}「${hit.name}」已自动匹配到档案，请核对明细与金额`
        : '已按识别结果回填表单；对方单位没有在档案里匹配到，请手动选择',
    );
  };

  /**
   * 确认无误：核对完成后把 OCR 状态推进到「已人工核对」。
   * 走 `confirm_empty: true` —— 合同字段以建单时人工填写为准，
   * 这里**不把识别值盖到合同上**：OCR 认错一个字，好合同就被改坏了。
   */
  const reviewOcr = async () => {
    if (!detail || reviewing) return;
    // 已经是「已人工核对」：按钮此时是 disabled，但键盘回车 / 旧缓存里的旧按钮 /
    // 脚本仍然可能触发到这里。再打一次既不会改变状态，又让用户觉得"点了没反应"，
    // 所以给一句明确回执，别让界面变成黑箱。
    if (detail.ocr_status === 'reviewed') {
      setNotice('识别结果已人工核对完成，无需重复确认；如需重做请点「重新识别」');
      return;
    }
    setReviewing(true);
    setOcrError('');
    try {
      const result = await api(`/contracts/${detail.id}/ocr/review`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ confirm_empty: true }),
      });
      setOcrFields(null);
      setNotice(result.message || '已确认无误');
      await openDetail(detail.id);
      await loadRows(direction, keyword);
    } catch (err) {
      setOcrError(err.message || '核对失败');
    } finally {
      setReviewing(false);
    }
  };

  /** 识别候选 vs 合同当前值的对照（这就是"核对"的实质：不一样的地方要人工裁决） */
  const ocrDiffs = useMemo(() => {
    const fields = ocrPack?.fields || {};
    const rows = [];
    if (fields.total_amount != null && detail?.total_amount != null) {
      const same = Math.abs(Number(fields.total_amount) - Number(detail.total_amount)) < 0.01;
      rows.push({ label: '金额', ocr: formatMoney(fields.total_amount), current: formatMoney(detail.total_amount), same });
    }
    if (fields.party_name && detail?.party_name) {
      const same = String(fields.party_name).trim() === String(detail.party_name).trim();
      rows.push({ label: tab.partyLabel, ocr: String(fields.party_name), current: String(detail.party_name), same });
    }
    if (fields.sign_date && detail?.sign_date) {
      const same = String(fields.sign_date).slice(0, 10) === String(detail.sign_date).slice(0, 10);
      rows.push({ label: '签订日期', ocr: String(fields.sign_date).slice(0, 10), current: String(detail.sign_date).slice(0, 10), same });
    }
    return rows;
  }, [ocrPack, detail, tab]);

  const ocrFieldChips = useMemo(() => {
    const fields = ocrPack?.fields || {};
    return [
      { label: '合同编号', value: fields.contract_no },
      { label: '标题', value: fields.title },
      { label: tab.partyLabel, value: fields.party_name },
      { label: '金额', value: fields.total_amount != null ? `¥${formatMoney(fields.total_amount)}` : '' },
      { label: '签订日期', value: fields.sign_date },
      { label: '付款条款', value: fields.payment_terms },
      { label: '明细行', value: (ocrPack?.items || []).length ? `${ocrPack.items.length} 行` : '' },
    ].filter((chip) => chip.value);
  }, [ocrPack, tab]);

  // ---- 表格列 ----
  const columns = useMemo(
    () => [
      { key: 'contract_no', title: '合同编号', mono: true, width: 138 },
      { key: 'title', title: '标题', ellipsis: true, minWidth: 140 },
      { key: 'party_name', title: tab.partyLabel, ellipsis: true, minWidth: 140 },
      { key: 'sign_date', title: '签订日期', width: 106 },
      {
        key: 'total_amount',
        title: '金额',
        width: 128,
        align: 'right',
        num: true,
        format: (value) => `¥${formatMoney(value)}`,
      },
      {
        key: 'items',
        title: '明细',
        width: 74,
        align: 'center',
        render: (row) => `${Array.isArray(row.items) ? row.items.length : 0} 行`,
      },
      {
        key: 'status',
        title: '状态',
        width: 96,
        render: (row) => (
          <span className={`cledger__badge cledger__badge--${row.status || 'draft'}`}>
            {statusLabel(row.status)}
          </span>
        ),
      },
      {
        key: 'source_file_name',
        title: '原件',
        width: 84,
        render: (row) => (row.source_file_path ? '已上传' : '—'),
      },
      {
        key: 'actions',
        title: '操作',
        width: 300,
        align: 'right',
        sticky: 'right',
        render: (row) => (
          <span className="cledger__row-actions">
            <button type="button" className="secondary-btn small-btn" onClick={() => openDetail(row.id)}>
              详情
            </button>
            <button type="button" className="secondary-btn small-btn" onClick={() => printContract(row)}>
              打印
            </button>
            {/* 任务 E：Word 导出。列表里直接给按钮 —— 用户最常见的动作是"把这份合同发给对方" */}
            <button
              type="button"
              className="secondary-btn small-btn"
              data-word-export="contract"
              onClick={() => exportWordFile(row)}
            >
              Word
            </button>
            {/* 删除（2026-10-22）：唯一会真正抹掉一条合同的入口 —— 必须二次确认 */}
            <button
              type="button"
              className="secondary-btn small-btn cledger__danger"
              data-contract-delete={row.id}
              onClick={(event) => {
                event.stopPropagation(); // 别把"删除"当成"点开详情"
                removeContract(row);
              }}
            >
              删除
            </button>
          </span>
        ),
      },
    ],
    // openDetail / printContract 都是稳定语义（不闭包外部可变状态），
    // 只在方向变化（列标题「客户/供应商」）时重建即可
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [direction],
  );

  const rowProps = (row) => ({
    tabIndex: 0,
    style: { cursor: 'pointer' },
    onKeyDown: (event) => {
      if (event.key === 'Enter' || event.key === ' ') {
        event.preventDefault();
        openDetail(row.id);
      }
    },
  });

  const formTotal = contractTotal(form.items);
  const acceptAttr = (meta?.file?.accept_attr) || '.pdf,.doc,.docx,.png,.jpg,.jpeg';
  const maxMb = meta?.file?.max_bytes ? Math.round(Number(meta.file.max_bytes) / 1024 / 1024) : 20;

  return (
    <section className="cledger">
      <header className="cledger__head">
        <div className="cledger__title-block">
          <h2>合同台账</h2>
          <p className="cledger__sub">
            进 / 出双向台账 · 挂原件与识别结果 · 一键导出台账（Excel 主表 + 明细两张工作表）
          </p>
        </div>
        <div className="cledger__head-actions">
          <button
            type="button"
            className="secondary-btn"
            onClick={exportExcel}
            disabled={exporting}
            title="按当前方向导出全部合同（xlsx）"
          >
            {exporting ? '导出中…' : '导出 Excel'}
          </button>
          <button type="button" className="primary-btn" onClick={openCreate}>
            新增{tab.shortLabel}合同
          </button>
        </div>
      </header>

      <div className="cledger__tabs" role="tablist" aria-label="合同方向">
        {CONTRACT_TABS.map((item) => (
          <button
            key={item.key}
            type="button"
            role="tab"
            aria-selected={direction === item.key}
            className={`cledger__tab${direction === item.key ? ' is-active' : ''}`}
            onClick={() => switchDirection(item.key)}
          >
            <span className="cledger__tab-label">{item.label}</span>
            <span className="cledger__tab-hint">{item.hint}</span>
          </button>
        ))}
      </div>

      <div className="cledger__toolbar">
        <input
          className="cledger__search"
          value={keywordInput}
          onChange={(event) => setKeywordInput(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === 'Enter') setKeyword(keywordInput.trim());
          }}
          placeholder="按合同号 / 标题 / 对方单位搜索"
        />
        <button type="button" className="secondary-btn small-btn" onClick={() => setKeyword(keywordInput.trim())}>
          查询
        </button>
        <button
          type="button"
          className="secondary-btn small-btn"
          onClick={() => {
            setKeywordInput('');
            setKeyword('');
          }}
        >
          重置
        </button>
        <span className="status-badge">{rows.length} 份</span>
        <span className="cledger__toolbar-spacer" />
        {notice ? <span className="cledger__notice">{notice}</span> : null}
      </div>

      {listError ? <div className="cledger__error">{listError}</div> : null}

      <ErpTable
        columns={columns}
        rows={rows}
        rowKey="id"
        loading={loading}
        onRowClick={(row) => openDetail(row.id)}
        rowProps={rowProps}
        emptyProps={{
          variant: keyword ? 'search' : 'data',
          title: keyword ? '没有匹配的合同' : `还没有${tab.label}`,
          description: keyword
            ? '换个合同号、标题或对方单位再试一次'
            : `点右上角「新增${tab.shortLabel}合同」建第一份`,
        }}
      />

      {/* ---------------- 新建合同 ---------------- */}
      {formOpen ? (
        <div className="modal-backdrop" role="dialog" aria-modal="true" aria-label={`新增${tab.label}`}>
          <div className="modal-card modal-wide cledger__modal">
            <div className="modal-header">
              <h3>
                新增{tab.label}
                <span className="cledger__modal-tag">{isInbound ? '应付口径' : '应收口径'}</span>
              </h3>
              <button type="button" className="close-btn" onClick={closeCreate} aria-label="关闭">
                ×
              </button>
            </div>
            <form onSubmit={submitForm}>
              <div className="modal-body">
                {formError ? <div className="cledger__error">{formError}</div> : null}

                {/* ---- 智能优先：先传原件 → 先识别 → 按策略回填 → 最后一次性保存 ---- */}
                <div className="cledger__section cledger__draft">
                  <div className="cledger__section-head">
                    <h4>合同原件与智能识别</h4>
                    <span
                      className={`cledger__badge cledger__badge--${
                        draftFile ? 'active' : 'none'
                      }`}
                    >
                      {draftUploading ? '上传中…' : draftFile ? '原件已就绪' : '未上传（可跳过）'}
                    </span>
                  </div>
                  <p className="cledger__muted">
                    ① 选原件 → ② 点「开始识别」→ ③ 核对识别结果并选择怎么填 → ④ 最后点「保存合同」。
                    不用先建合同，原件会跟着合同一起保存。
                  </p>
                  {draftWordHint ? (
                    <div className="cledger__draft-hint" data-draft-word-hint role="status">
                      <strong>这份原件暂时没法识别</strong>
                      <span>{draftWordHint}</span>
                    </div>
                  ) : null}
                  <div className="cledger__draft-row">
                    <label className="cledger__draft-pick">
                      <input
                        ref={draftInputRef}
                        type="file"
                        accept={acceptAttr}
                        data-draft-file
                        disabled={draftUploading || draftOcrRunning}
                        onChange={(event) => pickDraftFile(event.target.files?.[0] ?? null)}
                      />
                      <span className="cledger__muted">
                        支持 PDF / 图片（Word 可存档但不能识别），单个不超过 {maxMb}MB
                      </span>
                    </label>
                    <button
                      type="button"
                      className="secondary-btn"
                      data-draft-ocr
                      onClick={startDraftOcr}
                      disabled={!draftFile || draftUploading || draftOcrRunning}
                      title={draftFile ? '对刚上传的原件执行识别' : '请先选择原件'}
                    >
                      {draftOcrRunning ? '识别中…' : '开始识别'}
                    </button>
                  </div>

                  {draftFile ? (
                    <p className="cledger__muted" data-draft-file-name>
                      已暂存：{draftFile.file_name}（{formatFileSize(draftFile.file_size)}），
                      保存合同时转为正式原件
                    </p>
                  ) : null}

                  {draftUploading ? (
                    <div className="cledger__ocr-skeleton" data-draft-uploading aria-hidden="true">
                      <span />
                      <span />
                      <span />
                    </div>
                  ) : null}

                  {draftError ? (
                    <div className="cledger__ocr-error" data-draft-error>
                      {draftError}
                    </div>
                  ) : null}

                  {draftOcrRunning ? (
                    <div
                      className="cledger__ocr-skeleton"
                      data-draft-running
                      aria-label="正在识别原件"
                    >
                      <span />
                      <span />
                      <span />
                    </div>
                  ) : null}

                  {draftOcr && !draftOcrRunning ? (
                    <div className="cledger__draft-result" data-draft-fields>
                      <p className="cledger__muted">
                        认出 {Object.keys(draftOcr.fields || {}).length} 项字段、
                        {(draftOcr.items || []).length} 行明细
                        {draftOcr.page_count ? `（${draftOcr.page_count} 页）` : ''}
                        {draftOcr.truncated ? '，只识别了前 10 页' : ''}
                      </p>

                      {draftChips.length ? (
                        <div className="cledger__ocr-fields">
                          {draftChips.map(([label, value]) => (
                            <span className="cledger__ocr-field" key={label}>
                              <i>{label}</i>
                              <b>{value}</b>
                            </span>
                          ))}
                        </div>
                      ) : (
                        <p className="cledger__muted">
                          没有认出可填字段（原件可能是空白页或太模糊），可以换一份更清晰的再试。
                        </p>
                      )}

                      {(draftOcr.items || []).length ? (
                        <div className="cledger__draft-items-wrap">
                          <table className="cledger__draft-items">
                            <thead>
                              <tr>
                                <th>识别到的明细</th>
                                <th>单位</th>
                                <th>数量</th>
                                <th>单价</th>
                                <th>金额</th>
                              </tr>
                            </thead>
                            <tbody>
                              {(draftOcr.items || []).map((row, index) => (
                                <tr key={index}>
                                  <td>{row.product_name || '—'}</td>
                                  <td>{row.unit || '—'}</td>
                                  <td>{row.quantity ?? '—'}</td>
                                  <td>
                                    {row.unit_price != null
                                      ? `¥${formatMoney(row.unit_price)}`
                                      : '—'}
                                  </td>
                                  <td>
                                    {row.amount != null ? `¥${formatMoney(row.amount)}` : '—'}
                                  </td>
                                </tr>
                              ))}
                            </tbody>
                          </table>
                        </div>
                      ) : (
                        /* 扫描件的表格常被拆成散落的单元格，认不出时**明确说一声** ——
                           否则用户看到"0 行明细"会以为系统坏了，其实头部字段都是好的。 */
                        <div className="cledger__draft-hint" data-draft-items-empty role="status">
                          <strong>未提取到明细行，请手动添加</strong>
                          <span>
                            头部字段（编号、标题、客户、金额、日期）已识别，可直接用；
                            明细这张表扫描件没认出来，请在下面「明细」区自己加行，不会影响保存。
                          </span>
                        </div>
                      )}

                      {draftConflict && draftConflict.length ? (
                        <div className="cledger__draft-conflict" data-draft-conflict>
                          <strong>检测到你已填写：{draftConflict.join('、')}</strong>
                          <p>
                            识别结果不会自动盖掉你填的内容。请选择怎么处理（推荐只填空白项）：
                          </p>
                          <div className="cledger__draft-actions">
                            <button
                              type="button"
                              className="primary-btn small-btn"
                              data-draft-apply="empty-only"
                              onClick={() => applyDraftOcr(draftOcr, 'empty-only')}
                            >
                              仅填充空白字段
                            </button>
                            <button
                              type="button"
                              className="secondary-btn small-btn"
                              data-draft-apply="overwrite"
                              onClick={() => applyDraftOcr(draftOcr, 'overwrite')}
                            >
                              用识别结果覆盖
                            </button>
                            <button
                              type="button"
                              className="secondary-btn small-btn"
                              data-draft-apply="skip"
                              onClick={() => {
                                setDraftConflict(null);
                                setDraftApplied('skip');
                                setNotice('已保留你填写的内容，识别结果不会填入表单');
                              }}
                            >
                              暂不填充
                            </button>
                          </div>
                        </div>
                      ) : null}

                      {draftApplied ? (
                        <p className="cledger__draft-applied" data-draft-applied>
                          {draftApplied === 'skip'
                            ? '已跳过填充：保留你填写的内容'
                            : draftApplied === 'overwrite'
                              ? '已用识别结果覆盖表单，请逐项核对'
                              : draftApplied === 'auto'
                                ? '表单原为空，已自动填入识别结果，请核对'
                                : '已只填入空白项，你填写的内容未改动'}
                        </p>
                      ) : null}

                      <details className="cledger__ocr-raw">
                        <summary>原始识别记录（排查用）</summary>
                        <pre>{draftOcr.ocr_json}</pre>
                      </details>
                    </div>
                  ) : null}
                </div>

                <div className="cledger__grid">
                  <label className="cledger__field cledger__field--full">
                    <span>合同标题 *</span>
                    <input
                      value={form.title}
                      onChange={(event) => patchForm('title', event.target.value)}
                      placeholder={isInbound ? '如：2026 年度钢材采购合同' : '如：某某项目设备销售合同'}
                    />
                  </label>

                  {/* ⚠️ 这里用 div 不用 label：label 里放 button 时，点按钮会连带
                      触发 label 的默认行为（聚焦/激活关联控件）→ 点「新建」反而把下拉顶开。
                      要放交互元素就不能用 label 包。 */}
                  <div className="cledger__field">
                    <span>{tab.partyLabel} *</span>
                    {/* 触发器是 div[role=combobox]，原生 required 拦不住 → 校验在 validateContractForm 里 */}
                    <ErpSearchSelect
                      options={isInbound ? suppliers : customers}
                      value={String(form.party_id ?? '')}
                      onChange={(nextId, item) => {
                        setForm((prev) => ({
                          ...prev,
                          party_id: nextId || '',
                          party_name: item?.name || '',
                        }));
                        // 用户亲手选了一次 → 之前的"未匹配/请确认"提示必须消失，
                        // 否则他会以为还没选成功，反复点保存
                        setPartyHint(null);
                        // 红条同理：这条红条本来就是"对方单位没选中"引起的，选完还挂着
                        // 会让人以为没生效。只清这一类错误 —— 用白名单正则而非直接
                        // setFormError('')，否则"请填写合同标题"之类的无关错误也被抹掉，
                        // 用户以为整张表都没问题了。
                        setFormError((prev) =>
                          prev && /只是显示的文字|请选择(客户|供应商)/.test(prev) ? '' : prev,
                        );
                      }}
                      getOptionValue={(item) => String(item.id)}
                      placeholder={`搜索${tab.partyLabel}名称 / 编码`}
                      displayValue={form.party_name || ''}
                    />
                    {partyHint ? (
                      <div
                        className={`cledger__party-hint cledger__party-hint--${partyHint.tone}`}
                        data-party-hint={partyHint.tone}
                      >
                        <span role="status">{partyHint.text}</span>
                        {/* 只在"未匹配"（warn）时给新建入口：蓝色模糊匹配时档案是存在的，
                            再让用户建一条只会多一份重复 */}
                        {partyHint.tone === 'warn' ? (
                          <button
                            type="button"
                            className="cledger__party-hint-link"
                            data-party-quick-create
                            onClick={() => openQuickCreate(form.party_name)}
                          >
                            + 一键新建该{tab.partyLabel}
                          </button>
                        ) : null}
                      </div>
                    ) : null}
                  </div>

                  <label className="cledger__field">
                    <span>签订日期</span>
                    <input
                      type="date"
                      value={form.sign_date}
                      onChange={(event) => patchForm('sign_date', event.target.value)}
                    />
                  </label>

                  <label className="cledger__field">
                    <span>有效期起</span>
                    <input
                      type="date"
                      value={form.valid_from}
                      onChange={(event) => patchForm('valid_from', event.target.value)}
                    />
                  </label>

                  <label className="cledger__field">
                    <span>有效期止</span>
                    <input
                      type="date"
                      value={form.valid_to}
                      onChange={(event) => patchForm('valid_to', event.target.value)}
                    />
                  </label>

                  <label className="cledger__field">
                    <span>税率 %</span>
                    <input
                      type="number"
                      /* 税率可能是 13、13.5、0.5 —— 写死两位小数会让原生校验报红 */
                      step="any"
                      min="0"
                      value={form.tax_rate}
                      onChange={(event) => patchForm('tax_rate', event.target.value)}
                    />
                  </label>

                  <label className="cledger__field cledger__field--check">
                    <input
                      type="checkbox"
                      checked={form.is_tax_included}
                      onChange={(event) => patchForm('is_tax_included', event.target.checked)}
                    />
                    <span>金额为含税价</span>
                  </label>

                  <label className="cledger__field cledger__field--full">
                    <span>付款条款</span>
                    <input
                      value={form.payment_terms}
                      onChange={(event) => patchForm('payment_terms', event.target.value)}
                      placeholder="如：货到验收合格后 30 日内付清全款"
                    />
                  </label>

                  <label className="cledger__field cledger__field--full">
                    <span>备注</span>
                    <input
                      value={form.note}
                      onChange={(event) => patchForm('note', event.target.value)}
                      placeholder="补充说明（可选）"
                    />
                  </label>
                </div>

                <div className="cledger__section">
                  <div className="cledger__section-head">
                    <h4>合同明细</h4>
                    <span className="status-badge">{cleanItems(form.items).length} 行</span>
                    <span className="cledger__toolbar-spacer" />
                    <span className="cledger__total">
                      合计 <strong>¥{formatMoney(formTotal)}</strong>
                    </span>
                  </div>

                  {/* 列宽用 <colgroup> 而不是写在 <th> 上：
                      ① `table-layout: fixed` 只认**第一行**的宽度声明，写 th 与 col 等效，
                         但 colgroup 一处改完全表对齐（th/td 不会各写一遍）；
                      ② ⚠️ fixed 布局下 `min-width` **完全无效** —— 之前写成 `minWidth: 220`，
                         商品列拿不到任何宽度，只能分到"剩余空间"（弹窗被 640px 卡住后只剩 38px）。
                      ③ 容器 `.cledger__items-wrap` 负责横滚：宁可左右滚，也不把搜索框挤成方块。 */}
                  <div className="cledger__items-wrap">
                    <table className="cledger__items">
                      <colgroup>
                        <col />
                        <col style={{ width: 88 }} />
                        <col style={{ width: 80 }} />
                        <col style={{ width: 100 }} />
                        <col style={{ width: 100 }} />
                        <col style={{ width: 120 }} />
                        <col style={{ width: 48 }} />
                      </colgroup>
                      <thead>
                        <tr>
                          <th>商品 *</th>
                          <th>规格</th>
                          <th>单位</th>
                          <th>数量</th>
                          <th>单价</th>
                          <th style={{ textAlign: 'right' }}>金额</th>
                          <th />
                        </tr>
                      </thead>
                      <tbody>
                        {form.items.map((row, index) => (
                          <tr key={index}>
                            <td>
                            <ErpSearchSelect
                              options={products}
                              value={String(row.product_id ?? '')}
                              onChange={(_nextId, item) => pickProduct(index, item)}
                              getOptionValue={(item) => String(item.id)}
                              placeholder="搜索商品名称 / SKU / 助记码"
                              displayValue={row.product_name || ''}
                            />
                          </td>
                          <td>
                            <input
                              value={row.standards}
                              onChange={(event) => patchItem(index, 'standards', event.target.value)}
                            />
                          </td>
                          <td>
                            <input
                              value={row.unit}
                              onChange={(event) => patchItem(index, 'unit', event.target.value)}
                            />
                          </td>
                          <td>
                            <input
                              type="number"
                              min="0"
                              /* 数量可能带小数（0.5 米 / 1.25 吨），
                                 写死 step 会让浏览器弹「请输入有效的值」 */
                              step="any"
                              value={row.quantity}
                              onChange={(event) => patchItem(index, 'quantity', event.target.value)}
                            />
                          </td>
                          <td>
                            <input
                              type="number"
                              min="0"
                              /* ⚠️ 单价是"费率"不是"钱"，常是 73.901 这种三位小数（含税换算出来的）。
                                 原来写 step="0.01" 会让浏览器原生校验报红「请输入有效的值」，
                                 用户被逼着把价格改成 73.90 —— 580 米就少 0.58 元（Bug 1 + Bug 3 的根）。 */
                              step="any"
                              value={row.unit_price}
                              onChange={(event) => patchItem(index, 'unit_price', event.target.value)}
                            />
                          </td>
                          <td className="cledger__items-amount">¥{formatMoney(row.amount)}</td>
                          <td>
                            <button
                              type="button"
                              className="secondary-btn small-btn"
                              onClick={() => removeItem(index)}
                              disabled={form.items.length <= 1}
                              aria-label={`删除第 ${index + 1} 行`}
                            >
                              ×
                            </button>
                          </td>
                        </tr>
                      ))}
                      </tbody>
                    </table>
                  </div>
                  <button type="button" className="secondary-btn small-btn" onClick={addItem}>
                    + 加一行
                  </button>
                </div>
              </div>

              <div className="modal-actions">
                <button type="button" className="secondary-btn" onClick={closeCreate} disabled={saving}>
                  取消
                </button>
                {/* 按标准范本生成正文：先看后存，不占合同号 */}
                <button
                  type="button"
                  className="secondary-btn"
                  data-contract-doc
                  onClick={openContractDocument}
                  disabled={docBusy === 'preview'}
                  title="按内置《产品买卖合同（简易版）》，把上面的客户、明细、金额、交货信息自动填进正文"
                >
                  {docBusy === 'preview' ? '生成中…' : '生成合同正文'}
                </button>
                <button type="submit" className="primary-btn" disabled={saving}>
                  {saving ? '保存中…' : '保存合同'}
                </button>
              </div>
            </form>
          </div>
        </div>
      ) : null}

      {/* 《工矿产品购销合同》正文预览（2026-10-22）
          挂在合同弹窗同层而不是嵌在里面：内层会被 .modal-card 的 overflow 裁掉，
          而合同正文天生就是"一张长纸"，必须自己滚。 */}
      {docPreview ? (
        <div
          className="modal-overlay cledger__doc-overlay"
          onClick={() => {
            if (!docBusy) setDocPreview(null);
          }}
        >
          <div
            className="modal-card cledger__doc"
            data-contract-doc-preview
            onClick={(event) => event.stopPropagation()}
          >
            <div className="modal-header">
              <h3>
                {docPreview.document.title}
                <span className="cledger__doc-no">合同编号：{docPreview.document.contract_no}</span>
              </h3>
              <button
                type="button"
                className="secondary-btn small-btn"
                onClick={() => setDocPreview(null)}
                disabled={Boolean(docBusy)}
              >
                关闭
              </button>
            </div>

            <div className="modal-body cledger__doc-body">
              <div className="cledger__doc-parties">
                {['buyer', 'seller'].map((side) => {
                  const party = docPreview.document.parties[side];
                  return (
                    <div key={side} className="cledger__doc-party">
                      <div className="cledger__doc-party-role">
                        {side === 'buyer' ? '甲方（购货单位）' : '乙方（供货单位）'}
                      </div>
                      <div className="cledger__doc-party-name">{party.name || '（待填写）'}</div>
                      <dl>
                        <dt>税号</dt><dd>{party.tax_no || '—'}</dd>
                        <dt>法定代表人</dt><dd>{party.legal || '—'}</dd>
                        <dt>地址</dt><dd>{party.address || '—'}</dd>
                        <dt>开户行</dt><dd>{party.bank_name || '—'}</dd>
                        <dt>账号</dt><dd>{party.bank_account || '—'}</dd>
                      </dl>
                    </div>
                  );
                })}
              </div>

              <table className="cledger__doc-items">
                <thead>
                  <tr>
                    <th>序号</th><th>产品名称</th><th>规格型号</th><th>单位</th>
                    <th>数量</th><th>单价</th><th>金额</th>
                  </tr>
                </thead>
                <tbody>
                  {docPreview.document.items.map((item) => (
                    <tr key={item.no}>
                      <td>{item.no}</td>
                      <td>{item.product_name}</td>
                      <td>{item.standards || '—'}</td>
                      <td>{item.unit || '—'}</td>
                      <td className="is-num">{item.quantity}</td>
                      <td className="is-num">{item.unit_price.toFixed(2)}</td>
                      <td className="is-num">{item.amount.toFixed(2)}</td>
                    </tr>
                  ))}
                </tbody>
                <tfoot>
                  <tr>
                    <td colSpan={6}>
                      合计（{docPreview.document.totals.tax_note}）
                      大写：{docPreview.document.totals.chinese}
                    </td>
                    <td className="is-num">{docPreview.document.totals.amount_text}</td>
                  </tr>
                </tfoot>
              </table>

              <div className="cledger__doc-clauses">
                {docPreview.document.clauses.map((clause) => (
                  <section key={clause.no}>
                    <h4>
                      {clause.no} {clause.heading}
                    </h4>
                    {clause.paragraphs.map((text) => (
                      <p key={text}>{text}</p>
                    ))}
                  </section>
                ))}
              </div>

              <div className="cledger__doc-sign">
                {docPreview.document.signatures.map((row) => (
                  <div key={row.role}>
                    <div className="cledger__doc-sign-role">{row.role}</div>
                    <p>单位名称：{row.name || '—'}</p>
                    <p>法定代表人：{row.legal || '—'}</p>
                    <p>开户行：{row.bank_name || '—'}</p>
                    <p>账号：{row.bank_account || '—'}</p>
                    <p>日期：{row.date || '—'}</p>
                  </div>
                ))}
              </div>

              <p className="cledger__doc-note">
                本文按《{docPreview.document.template_name}》标准范本自动生成，未填项已按行业常规兜底；
                正式签署前请逐条核对。此动作**不会**保存合同，满意后再点「保存合同」。
              </p>
            </div>

            <div className="modal-actions">
              <button
                type="button"
                className="secondary-btn"
                onClick={() => setDocPreview(null)}
                disabled={Boolean(docBusy)}
              >
                关闭
              </button>
              {/* 次按钮：PDF = 最终盖章版（有防呆确认，见 exportContractDocumentPdf） */}
              <button
                type="button"
                className="secondary-btn"
                data-contract-doc-pdf
                onClick={exportContractDocumentPdf}
                disabled={docBusy === 'pdf'}
              >
                {docBusy === 'pdf' ? '生成中…' : '下载 PDF（最终盖章版）'}
              </button>
              {/* 主按钮：先出 Word 供客户确认修改 */}
              <button
                type="button"
                className="primary-btn"
                data-contract-doc-word
                onClick={exportContractDocumentWord}
                disabled={docBusy === 'word'}
              >
                {docBusy === 'word' ? '生成中…' : '导出 Word (.docx) 供确认'}
              </button>
            </div>
          </div>
        </div>
      ) : null}

      {/* 就地补档案：挂在合同弹窗**外面**（同层），否则会嵌进那个可滚动的
          .modal-card 里跟着一起滚，还会被 overflow 裁掉。 */}
      <PartyQuickCreate
        open={Boolean(quickCreate)}
        kind={quickCreate?.kind || 'customer'}
        defaultName={quickCreate?.name || ''}
        onClose={() => setQuickCreate(null)}
        onCreated={handleQuickCreated}
        findExisting={(name) =>
          findPartyByName(quickCreate?.kind === 'supplier' ? suppliers : customers, name)?.item || null
        }
      />

      {/* ---------------- 详情 ---------------- */}
      {detail ? (
        <div className="modal-backdrop" role="dialog" aria-modal="true" aria-label="合同详情">
          <div className="modal-card modal-wide cledger__modal">
            <div className="modal-header">
              <h3>
                {detail.contract_no}
                <span className={`cledger__badge cledger__badge--${detail.status || 'draft'}`}>
                  {statusLabel(detail.status)}
                </span>
              </h3>
              <span className="cledger__inline-actions">
                <button
                  type="button"
                  className="secondary-btn small-btn"
                  data-word-export="contract-detail"
                  onClick={() => exportWordFile(detail)}
                  disabled={wordBusy}
                >
                  {wordBusy ? '导出中…' : '导出 Word'}
                </button>
                <button type="button" className="close-btn" onClick={closeDetail} aria-label="关闭">
                  ×
                </button>
              </span>
            </div>
            <div className="modal-body">
              {detailBusy ? <div className="cledger__muted">加载中…</div> : null}

              <div className="cledger__detail-grid">
                <div>
                  <span>标题</span>
                  <strong>{detail.title || '—'}</strong>
                </div>
                <div>
                  <span>{detail.direction === 'in' ? '供应商' : '客户'}</span>
                  <strong>{detail.party_name || '—'}</strong>
                </div>
                <div>
                  <span>签订日期</span>
                  <strong>{detail.sign_date || '—'}</strong>
                </div>
                <div>
                  <span>有效期</span>
                  <strong>
                    {detail.valid_from || '—'} ~ {detail.valid_to || '—'}
                  </strong>
                </div>
                <div>
                  <span>合同金额</span>
                  <strong>¥{formatMoney(detail.total_amount)}</strong>
                </div>
                <div>
                  <span>税率 / 含税</span>
                  <strong>
                    {detail.tax_rate ?? '—'}% / {detail.is_tax_included ? '含税' : '不含税'}
                  </strong>
                </div>
                <div className="cledger__detail-full">
                  <span>付款条款</span>
                  <strong>{detail.payment_terms || '—'}</strong>
                </div>
                <div className="cledger__detail-full">
                  <span>备注</span>
                  <strong>{detail.note || '—'}</strong>
                </div>
              </div>

              <div className="cledger__section">
                <div className="cledger__section-head">
                  <h4>明细</h4>
                  <span className="status-badge">{cleanItems(detail.items).length} 行</span>
                  <span className="cledger__toolbar-spacer" />
                  <span className="cledger__total">
                    合计 <strong>¥{formatMoney(contractTotal(detail.items))}</strong>
                  </span>
                </div>
                <div className="cledger__items-wrap">
                  <table className="cledger__items cledger__items--readonly">
                    <colgroup>
                      <col />
                      <col style={{ width: 120 }} />
                      <col style={{ width: 80 }} />
                      <col style={{ width: 90 }} />
                      <col style={{ width: 110 }} />
                      <col style={{ width: 120 }} />
                    </colgroup>
                    <thead>
                      <tr>
                        <th>商品</th>
                        <th>规格</th>
                        <th>单位</th>
                        <th style={{ textAlign: 'right' }}>数量</th>
                        <th style={{ textAlign: 'right' }}>单价</th>
                        <th style={{ textAlign: 'right' }}>金额</th>
                      </tr>
                    </thead>
                    <tbody>
                    {cleanItems(detail.items).map((row, index) => (
                      <tr key={row.id ?? index}>
                        <td>{row.product_name}</td>
                        <td>{row.standards || '—'}</td>
                        <td>{row.unit || '—'}</td>
                        <td className="cledger__items-amount">{row.quantity}</td>
                        <td className="cledger__items-amount">¥{formatMoney(row.unit_price)}</td>
                        <td className="cledger__items-amount">¥{formatMoney(row.amount)}</td>
                      </tr>
                    ))}
                    </tbody>
                  </table>
                </div>
              </div>

              <div className="cledger__section">
                <div className="cledger__section-head">
                  <h4>合同原件</h4>
                  <span className={`cledger__badge${detail.source_file_path ? ' cledger__badge--active' : ''}`}>
                    {detail.source_file_path ? '已上传' : '未上传'}
                  </span>
                </div>
                {detail.source_file_path ? (
                  <>
                    <p className="cledger__file-line">
                      {detail.source_file_name || '原件'}　
                      <span className="cledger__muted">{formatFileSize(detail.source_file_size)}</span>
                    </p>
                    <div className="cledger__inline-actions">
                      <button type="button" className="secondary-btn small-btn" onClick={() => downloadSource(detail)}>
                        下载原件
                      </button>
                    </div>
                  </>
                ) : (
                  <p className="cledger__muted">还没有扫描件。上传后可直接下载或随合同一起归档。</p>
                )}
                <div className="cledger__inline-actions">
                  <input
                    type="file"
                    accept={acceptAttr}
                    onChange={(event) => {
                      const file = event.target.files?.[0];
                      if (file) reuploadSource(file);
                      event.target.value = '';
                    }}
                  />
                </div>
              </div>

              {/* OCR 识别结果（任务 B）：触发 → 骨架屏 → 字段候选 + 原始 JSON + 回填/核对 */}
              <div className="cledger__section cledger__ocr-panel">
                <div className="cledger__section-head">
                  <h4>OCR 识别结果</h4>
                  <span className={`cledger__badge cledger__badge--${detail.ocr_status || 'none'}`}>
                    {ocrLabel(detail.ocr_status)}
                  </span>
                  <span className="cledger__toolbar-spacer" />
                  <button
                    type="button"
                    className="secondary-btn small-btn"
                    onClick={requestOcr}
                    disabled={ocrRunning}
                    title={
                      !detail.source_file_path
                        ? '请先上传合同原件'
                        : detail.ocr_status === 'reviewed'
                          ? '重新识别会覆盖「已人工核对」的结果，点击后会再确认一次'
                          : '对已上传的原件执行识别'
                    }
                    data-ocr-start
                    data-ocr-rerun={detail.ocr_status === 'reviewed' ? '1' : '0'}
                  >
                    {ocrRunning ? '识别中…' : detail.ocr_status === 'reviewed' ? '重新识别' : '开始识别'}
                  </button>
                </div>

                {ocrRunning ? (
                  <>
                    {/* 骨架屏扫光：识别一页约 1-2 秒，多页扫描件要十几秒，
                        必须让用户知道"在动"，否则会觉得是卡死了 */}
                    <div className="cledger__ocr-skeleton" aria-hidden="true">
                      <span />
                      <span />
                      <span />
                    </div>
                    <p className="cledger__muted" data-ocr-running>
                      正在对原件逐页识别，可能需要十几秒，请不要关闭窗口…
                    </p>
                  </>
                ) : null}

                {ocrError ? (
                  <div className="cledger__ocr-error" role="alert" data-ocr-error>
                    {ocrError}
                  </div>
                ) : null}

                {!ocrRunning && !ocrError && (detail.ocr_status === 'none' || !detail.ocr_status) ? (
                  <>
                    <div className="cledger__ocr-skeleton" aria-hidden="true">
                      <span />
                      <span />
                      <span />
                    </div>
                    <p className="cledger__muted">
                      {OCR_STATUS_LABELS.none}：上传原件后点「开始识别」，这里会显示认出的
                      合同号 / 对方单位 / 金额 / 签订日期，以及引擎的原始 JSON（便于人工逐项核对）。
                    </p>
                  </>
                ) : null}

                {!ocrRunning && detail.ocr_status === 'failed' ? (
                  <p className="cledger__muted">识别失败：没有认出任何文字。请换一张更清晰的原件再试。</p>
                ) : null}

                {!ocrRunning && detail.ocr_status && detail.ocr_status !== 'none' && detail.ocr_status !== 'failed'
                  ? (
                    <>
                      <p className="cledger__muted">
                        状态：{ocrLabel(detail.ocr_status)}
                        {detail.ocr_status === 'parsed' ? ' —— 识别完成但不代表正确，请逐项核对后再点「确认无误」。' : null}
                      </p>

                      {ocrFieldChips.length ? (
                        <div className="cledger__ocr-fields" data-ocr-fields>
                          {ocrFieldChips.map((chip) => (
                            <span key={chip.label} className="cledger__ocr-field">
                              <i>{chip.label}</i>
                              <b>{chip.value}</b>
                            </span>
                          ))}
                        </div>
                      ) : null}

                      {ocrDiffs.length ? (
                        <table className="cledger__ocr-diff" data-ocr-diff>
                          <thead>
                            <tr>
                              <th>项目</th>
                              <th>识别结果</th>
                              <th>合同当前值</th>
                            </tr>
                          </thead>
                          <tbody>
                            {ocrDiffs.map((row) => (
                              <tr key={row.label} className={row.same ? 'is-same' : 'is-diff'}>
                                <td>{row.label}</td>
                                <td>{row.ocr}</td>
                                <td>{row.current}</td>
                              </tr>
                            ))}
                          </tbody>
                        </table>
                      ) : null}

                      {detail.ocr_json ? (
                        <details className="cledger__ocr-raw">
                          <summary>查看识别原始 JSON</summary>
                          <pre>{detail.ocr_json}</pre>
                        </details>
                      ) : null}

                      {detail.ocr_status === 'reviewed' ? (
                        <p className="cledger__muted" data-ocr-done-hint>
                          识别结果已人工核对完成，无需再确认；如需重做请点上方「重新识别」。
                        </p>
                      ) : null}

                      <div className="cledger__ocr-actions">
                        <button
                          type="button"
                          className="secondary-btn small-btn"
                          onClick={applyOcrToForm}
                          disabled={!ocrFieldChips.length}
                          title="把识别出的客户 / 金额 / 明细填进新增合同表单，核对后再保存"
                          data-ocr-apply
                        >
                          一键回填表单
                        </button>
                        {/* ⚠️ 已核对后必须"看着也不能点"：光有 disabled 属性、没样式，
                            按钮还是一片纯蓝，用户会当成死链（2026-10-19 实测）。 */}
                        <button
                          type="button"
                          className={`primary-btn small-btn${
                            detail.ocr_status === 'reviewed' ? ' is-done' : ''
                          }`}
                          onClick={reviewOcr}
                          disabled={reviewing || detail.ocr_status === 'reviewed'}
                          aria-disabled={detail.ocr_status === 'reviewed' ? 'true' : 'false'}
                          data-ocr-review
                          data-ocr-reviewed={detail.ocr_status === 'reviewed' ? '1' : '0'}
                          title={
                            detail.ocr_status === 'reviewed'
                              ? '已是「已人工核对」，无需再点；如需重做请先点「重新识别」'
                              : '核对完成后，识别状态变为「已人工核对」'
                          }
                        >
                          {reviewing
                            ? '提交中…'
                            : detail.ocr_status === 'reviewed'
                              ? '已完成核对'
                              : '确认无误'}
                        </button>
                      </div>
                    </>
                  )
                  : null}
              </div>
            </div>
            <div className="modal-actions">
              <button type="button" className="secondary-btn" onClick={closeDetail}>
                关闭
              </button>
              <button type="button" className="secondary-btn" onClick={() => printContract(detail)}>
                打印合同
              </button>
              {/* 只在"还没生效"的状态上出现：active/signed/executing/finished/void
                  都不该被一键拉回生效（后端 PATCH 是直写，不会替我们挡）。 */}
              {['draft', 'pending'].includes(String(detail.status || '')) ? (
                <button
                  type="button"
                  className="primary-btn"
                  onClick={activateContract}
                  disabled={statusBusy}
                  title="把合同状态置为「生效」"
                  data-contract-activate
                >
                  {statusBusy ? '处理中…' : '确认生效'}
                </button>
              ) : null}
            </div>
          </div>
        </div>
      ) : null}

      {/* 重新识别二次确认：挂在详情弹窗**外面**（.modal-card 有 overflow:auto，塞进去会被裁） */}
      {ocrConfirm ? (
        <div
          className="modal-backdrop"
          role="dialog"
          aria-modal="true"
          aria-label="重新识别确认"
          onMouseDown={(event) => {
            if (event.target === event.currentTarget) setOcrConfirm(false);
          }}
        >
          <div className="modal-card cledger__confirm">
            <div className="modal-header">
              <h3>重新识别这份合同？</h3>
              <button
                type="button"
                className="close-btn"
                onClick={() => setOcrConfirm(false)}
                aria-label="关闭"
              >
                ×
              </button>
            </div>
            <div className="modal-body">
              <p className="cledger__confirm-text" data-ocr-confirm-text>
                当前识别状态是「已人工核对」——也就是说有人已经拿着原件逐项核对过。
                重新识别会用机器的结果覆盖这些数据，并把状态退回「已识别待核对」。
                <br />
                如果只是想看一眼原件，点「取消」即可。
              </p>
            </div>
            <div className="modal-actions">
              <button
                type="button"
                className="secondary-btn"
                onClick={() => setOcrConfirm(false)}
                data-ocr-confirm-cancel
              >
                取消
              </button>
              <button
                type="button"
                className="danger-btn"
                onClick={() => {
                  setOcrConfirm(false);
                  startOcr();
                }}
                data-ocr-confirm-ok
              >
                继续重新识别
              </button>
            </div>
          </div>
        </div>
      ) : null}
    </section>
  );
}
