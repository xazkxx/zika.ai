// 合同台账（第 13 批 · 第三阶段）—— 纯函数与常量
//
// 为什么单独一层：这些逻辑（金额换算、表单校验、建单载荷拼装）全部**不依赖 React**，
// 放在这里才能被 node 直接跑测试，也才能在两个页面（购销合同 / 合同台账）之间复用。
// 组件里只留"状态 + JSX"，别把业务算法写进组件 —— 一旦写进去就再也测不了。

// 两个方向 Tab。key 直接就是后端 `direction` 的取值，请求时原样带上，
// 前端不做任何 in/purchase 的翻译（翻译在后端 normalize_direction 里统一做，
// 两边各翻一套就会出现"前端按 purchase 筛、后端按方向筛"的对不上）。
export const CONTRACT_TABS = [
  {
    key: 'in',
    label: '采购合同（进）',
    shortLabel: '采购',
    partyLabel: '供应商',
    partyType: 'supplier',
    hint: '我方采购，对方是供应商；金额是应付口径',
  },
  {
    key: 'out',
    label: '销售合同（出）',
    shortLabel: '销售',
    partyLabel: '客户',
    partyType: 'customer',
    hint: '我方销售，对方是客户；金额是应收口径',
  },
];

// 与后端 CONTRACT_STATUS 一致；旧值 signed / executing 也留着，
// 老合同里有这两个值，缺了就会在表格里显示成裸的英文。
export const CONTRACT_STATUS_LABELS = {
  draft: '草稿',
  pending: '待审',
  active: '生效',
  signed: '已签订',
  executing: '执行中',
  finished: '完成',
  void: '作废',
};

// 与后端 CONTRACT_OCR_STATUS 一致
export const OCR_STATUS_LABELS = {
  none: '未识别',
  pending: '识别中',
  parsed: '已识别待核对',
  reviewed: '已人工核对',
  failed: '识别失败',
};

export function tabOf(direction) {
  return CONTRACT_TABS.find((tab) => tab.key === direction) ?? CONTRACT_TABS[1];
}

export function statusLabel(status) {
  return CONTRACT_STATUS_LABELS[status] ?? (status || '—');
}

export function ocrLabel(status) {
  return OCR_STATUS_LABELS[status] ?? (status || '未识别');
}

// 金额展示：千分位 + 两位小数。null / '' / 脏值一律 0.00 ——
// 合同列表里出现空白金额，用户会以为是"漏填的合同"。
export function formatMoney(value) {
  const num = Number(value);
  if (!Number.isFinite(num)) return '0.00';
  return num.toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

// ---------------------------------------------------------------------------
// 金额/单价/数量的精度规则（2026-10-19 修 Bug 1/3）
//
// **钱和费率是两种东西，不能共用一套精度：**
//   · 金额（amount / 合计 / 税额）是"分" —— 严格 2 位，多一位都不该给用户看；
//   · 单价是"费率" —— 必须保留原始精度。真实合同里 73.901 元/米这种三位单价很常见
//     （含税/不含税换算出来的），抹成 73.90 之后 73.90 × 580 = 42862.00，
//     而 73.901 × 580 = 42862.58 —— 差的 0.58 元就是用户看到的那笔尾差。
//   · 数量同理，最多保留 4 位（0.5 米、1.25 吨都要能填）。
// 所以这里**不给单价做 toFixed(2)**，只把它规整到「最多 4 位、去掉二进制噪声」。
// ---------------------------------------------------------------------------

/** 二进制噪声消除器：73.901 × 580 在 IEEE754 里是 42862.58000000001。 */
function stripFloatNoise(value) {
  const num = Number(value);
  if (!Number.isFinite(num)) return NaN;
  if (Math.abs(num) >= 1e15) return num; // 大到 toFixed 会转科学计数法，直接放弃
  return Number(num.toFixed(10));
}

/**
 * 四舍五入到 2 位小数（钱）。
 * ⚠️ 不用 `Math.round(n*100)/100`：`1.005` 在二进制里是 1.00499999…，
 * 乘 100 得 100.4999…，会舍成 1.00 而不是 1.01。
 * 走"十进制字符串 + e2"缩放，绕开这个坑。
 */
export function round2(value) {
  const num = stripFloatNoise(value);
  if (!Number.isFinite(num)) return 0;
  return Math.round(Number(`${num}e2`)) / 100;
}

/** 数字 → 金额字符串（两位，永不出现 0.30000000000000004）。空值给 ''。 */
export function toMoney2(value) {
  if (value === '' || value === null || value === undefined) return '';
  const num = stripFloatNoise(value);
  if (!Number.isFinite(num)) return '';
  return num.toFixed(2);
}

/** 数字 → 费率/数量字符串：最多 4 位，去掉尾随 0（73.9010 → "73.901"）。 */
export function toRate4(value) {
  if (value === '' || value === null || value === undefined) return '';
  const num = stripFloatNoise(value);
  if (!Number.isFinite(num)) return '';
  const text = num.toFixed(4).replace(/\.?0+$/, '');
  return text === '-0' ? '0' : text;
}

// 行金额 = 数量 × 单价，四舍五入到两位。返回**字符串**（直接回填 input，
// 不回数字：数字会丢掉用户正在输入的 "1." 这种中间态）。
// ⚠️ 单价这里**必须用原值**（73.901），不能先用 toRate4 截断再乘 —— 那样金额就少 0.58。
export function itemAmount(quantity, unitPrice) {
  const qty = Number(quantity);
  const price = Number(unitPrice);
  if (!Number.isFinite(qty) || !Number.isFinite(price)) return '0.00';
  return round2(qty * price).toFixed(2);
}

// 合计 = **逐行金额累加**（不是"总数量 × 平均单价"）。
// 行金额已经是 2 位的分，累加只会出现二进制噪声，round2 一次就干净。
export function itemsTotal(items) {
  const list = Array.isArray(items) ? items : [];
  const sum = list.reduce((acc, row) => acc + Number(row.amount || 0), 0);
  return round2(sum);
}

export function contractTotal(items) {
  return itemsTotal(items).toFixed(2);
}

// 一行空明细。quantity 默认 '1'：与全站单据一致（`emptyOrderItem` 也是预填 1），
// 但**判空行绝不能靠 quantity 非空**（见 lib/orderLines.js 的注释）——
// 这里的判空一律看 product_name。
export function emptyContractItem() {
  return {
    product_id: '',
    product_name: '',
    standards: '',
    unit: '',
    quantity: '1',
    unit_price: '',
    amount: '0.00',
    note: '',
  };
}

export function emptyContractForm(direction = 'out') {
  const tab = tabOf(direction);
  const today = new Date().toISOString().slice(0, 10);
  return {
    direction: tab.key,
    title: tab.key === 'in' ? '采购合同' : '销售合同',
    party_id: '',
    party_name: '',
    sign_date: today,
    valid_from: '',
    valid_to: '',
    tax_rate: '13',
    is_tax_included: true,
    payment_terms: '',
    note: '',
    items: [emptyContractItem()],
  };
}

// 有商品名就算一行有效明细。用户在最后一行还没选商品时不该被拦，
// 提交前把空行剔掉即可（与后端的空行清洗口径一致）。
export function isBlankItem(row) {
  return !String(row?.product_name ?? '').trim();
}

export function cleanItems(items) {
  const list = Array.isArray(items) ? items : [];
  return list.filter((row) => !isBlankItem(row));
}

// 校验：返回第一条中文错误，没问题返回 null。
// 顺序按"用户填表顺序"排，先报最上面的错，别让人从下往上找。
export function validateContractForm(form) {
  if (!form) return '表单数据缺失';
  if (!String(form.party_id || '').trim()) {
    const label = tabOf(form.direction).partyLabel;
    const typed = String(form.party_name || '').trim();
    // 最容易让人懵的一种：下拉框里明明显示着名字，却被拦"请选择客户"。
    // 那是 OCR 只填了文字、没填 id（"假选中"）。提示必须把这件事说出来，
    // 否则用户会以为是系统坏了、反复点保存。
    return typed
      ? `${label}「${typed}」只是显示的文字，还没选中系统档案 —— 请点开下拉，从列表里选一次`
      : `请选择${label}（必选，否则合同没有相对方）`;
  }
  if (!String(form.title || '').trim()) return '请填写合同标题';

  const rows = cleanItems(form.items);
  if (rows.length === 0) return '至少要有一行合同明细（商品不能为空）';
  for (let index = 0; index < rows.length; index += 1) {
    const row = rows[index];
    if (!(Number(row.quantity) > 0)) {
      return `第 ${index + 1} 行数量必须大于 0`;
    }
    if (!(Number(row.unit_price) >= 0)) {
      return `第 ${index + 1} 行单价不能是负数`;
    }
  }
  return null;
}

// 建单载荷。**direction 与 contract_type 一起发**：
// 新后端只认 direction，老后端只认 contract_type，两个都带就不用管服务端是哪一版。
export function buildCreatePayload(form) {
  const tab = tabOf(form.direction);
  const rows = cleanItems(form.items).map((row) => ({
    product_id: row.product_id ? Number(row.product_id) : null,
    product_name: String(row.product_name || '').trim(),
    standards: row.standards || null,
    unit: row.unit || null,
    quantity: Number(row.quantity || 0),
    unit_price: Number(row.unit_price || 0),
    amount: Number(row.amount || 0),
    note: row.note || null,
  }));

  return {
    direction: tab.key,
    contract_type: tab.key === 'in' ? 'purchase' : 'sales',
    party_type: tab.partyType,
    party_id: Number(form.party_id),
    title: String(form.title || '').trim(),
    sign_date: form.sign_date || null,
    valid_from: form.valid_from || null,
    valid_to: form.valid_to || null,
    total_amount: itemsTotal(rows),
    tax_rate: form.tax_rate === '' ? null : Number(form.tax_rate),
    is_tax_included: Boolean(form.is_tax_included),
    payment_terms: form.payment_terms || null,
    note: form.note || null,
    items: rows,
  };
}

// 选中商品时自动补全规格 / 单位 / 单价。
// 单价按方向取档案价：采购取进货价、销售取销售价 —— 带错了业务员会按错价开单，
// 所以宁可留空让人手填，也不拿反方向的价糊上去。
export function applyProductToRow(row, product, direction) {
  if (!product) return row;
  const price = direction === 'in' ? product.purchase_price : product.sale_price;
  const next = {
    ...row,
    product_id: String(product.id),
    product_name: product.name || '',
    standards: product.standards || '',
    unit: product.unit || '',
  };
  if ((row.unit_price === '' || row.unit_price === null) && price !== null && price !== undefined) {
    // 档案价可能是 100.81000000000001 这种浮点尾巴 —— 规整成最多 4 位再进 input
    next.unit_price = toRate4(price);
  }
  next.amount = itemAmount(next.quantity, next.unit_price);
  return next;
}

// ---------- 往来单位匹配（OCR 回填用）----------

// 名称归一：OCR 会把全角/半角括号、空格、书名号混着输出，
// 还有"（盖章）"这种版式噪声。不归一化的话，"西安寨卡信息技术有限公司"
// 和"西安寨卡信息技术有限公司 "（尾随空格）永远匹配不上 → 用户看到"假选中"。
const PARTY_NAME_NOISE = /[\s\u3000（）()【】[\]「」『』<>《》,，.。;；:：!！?？"'“”‘’`~\-—_/\\|*#]/g;

export function normalizePartyName(value) {
  return String(value || '')
    .replace(/[（(]\s*盖章\s*[）)]/g, '')
    .replace(PARTY_NAME_NOISE, '')
    .toUpperCase();
}

/**
 * 按名称在档案里找往来单位。
 *
 * 返回 `{ item, fuzzy }` 或 `null`：
 *   · 全等（归一化后）→ `fuzzy: false`，可以静默填；
 *   · 唯一包含 → `fuzzy: true`，**必须**让用户确认（"西安寨卡" vs "西安寨卡信息技术有限公司"）；
 *   · 找不到 / 命中多家 → `null`，前端保留识别文本 + 黄色提示，绝不硬猜。
 *
 * ⚠️ 为什么"唯一包含"要标 fuzzy：合同写错主体是要重开的，宁可多问一句。
 * 为什么"命中多家"直接放弃："西安"能同时包含在十家公司里，猜哪个都是事故。
 */
export function findPartyByName(list, name) {
  const target = normalizePartyName(name);
  if (!target) return null;
  const pool = Array.isArray(list) ? list : [];

  const exact = pool.find((item) => normalizePartyName(item.name) === target);
  if (exact) return { item: exact, fuzzy: false };

  if (target.length < 4) return null; // 太短的名字包含匹配没有意义
  const loose = pool.filter((item) => {
    const candidate = normalizePartyName(item.name);
    if (!candidate) return false;
    const shorter = Math.min(candidate.length, target.length);
    if (shorter < 4) return false;
    return candidate.includes(target) || target.includes(candidate);
  });
  if (loose.length === 1) return { item: loose[0], fuzzy: true };
  return null;
}

// ---------- 文件与下载 ----------

export function formatFileSize(bytes) {
  const size = Number(bytes);
  if (!Number.isFinite(size) || size <= 0) return '—';
  if (size < 1024) return `${size} B`;
  if (size < 1024 * 1024) return `${(size / 1024).toFixed(1)} KB`;
  return `${(size / 1024 / 1024).toFixed(1)} MB`;
}

// 从 Content-Disposition 里取文件名。后端同时给了 ASCII 兜底名与
// `filename*=UTF-8''<百分号编码>`，优先取后者，否则中文名会变成一串下划线。
export function fileNameFromDisposition(header, fallback) {
  const text = String(header || '');
  const star = text.match(/filename\*=UTF-8''([^;]+)/i);
  if (star && star[1]) {
    try {
      return decodeURIComponent(star[1].trim());
    } catch (err) {
      // 编码坏了就用兜底名，不要因为文件名解析失败让整个下载失败
    }
  }
  const plain = text.match(/filename="?([^";]+)"?/i);
  if (plain && plain[1]) return plain[1].trim();
  return fallback;
}

// 导出按钮的落点：后端已经支持 direction / from_date / to_date / status。
// 前端只传当前 Tab 的方向 —— 导出"看得见的这一批"，不导出另一个方向混进来。
export function exportQuery(direction) {
  const params = new URLSearchParams();
  if (direction) params.set('direction', direction);
  return params.toString();
}
