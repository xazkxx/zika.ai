// 客户文件抽屉的纯函数层（零 React 依赖，可单独跑单测）。
//
// 为什么单开一个文件而不是复用 `lib/contractsLedger.js` 里的同名小工具：
//   contractsLedger 是第三阶段第一步交付物，已经跑过 45 项 E2E + 4 组反证。
//   为了省 15 行代码去动它，属于"用一个已验收模块的稳定性换一点重复代码"，不划算。
//   `formatFileSize` / `fileNameFromDisposition` 这两个确实和合同原件那边重复，
//   将来若要收口，正确做法是两边一起抽到 `lib/fileUtils.js` —— 那时同步改两处、
//   两边的验证台一起复跑，而不是现在单方面改一边。

/** 后端 `CUSTOMER_FILE_CATEGORIES` 的兜底副本。
 *  正常路径是 `GET /customer-files/meta` 拿字典（唯一真相在后端），
 *  这份只在 meta 请求失败时用来渲染 Tab —— 有它用户至少还能看列表、能上传到「其他」。 */
export const FALLBACK_CATEGORIES = [
  { code: 'contract', label: '合同' },
  { code: 'qualification', label: '资质' },
  { code: 'invoice', label: '发票' },
  { code: 'statement', label: '对账单' },
  { code: 'other', label: '其他' },
];

/** 「全部」Tab 的 code。用空串而不是 'all'：后端 `category` 参数空 = 不过滤，正好对上，
 *  不需要前端再翻译一层（翻译层就是 bug 温床）。 */
export const CATEGORY_ALL = '';

/**
 * Tab 列表 = 全部 + 各分类。
 * `counts` 来自 `/customers/{id}/files/stats`；还没拿到时给 `null`，界面显示 `…` 而不是 0
 * —— 0 是"确实没有"，`…` 才是"还不知道"，这两个在用户眼里必须不一样。
 */
export function categoryTabs(meta, counts = null) {
  const cats =
    Array.isArray(meta?.categories) && meta.categories.length ? meta.categories : FALLBACK_CATEGORIES;
  const tabs = [{ code: CATEGORY_ALL, label: '全部', count: counts ? Number(counts.total || 0) : null }];
  for (const item of cats) {
    const code = String(item.code || '');
    if (!code) continue;
    tabs.push({
      code,
      label: item.label || code,
      count: counts?.by_category ? Number(counts.by_category[code] || 0) : null,
    });
  }
  return tabs;
}

/** 分类 code → 中文。未知 code 原样返回，绝不显示 `undefined`。 */
export function categoryLabel(meta, code) {
  if (!code) return '未分类';
  const found = (meta?.categories || FALLBACK_CATEGORIES).find((item) => item.code === code);
  return found ? found.label : String(code);
}

/**
 * 字节数 → 人话。
 * 1024 进制（与 Windows 资源管理器口径一致）；1 MB 以下保留一位小数，
 * 1 MB 以上保留两位 —— 「1.25 MB」比「1.3 MB」更能看出是同一份文件。
 */
export function formatFileSize(bytes) {
  const n = Number(bytes);
  if (!Number.isFinite(n) || n < 0) return '—';
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`;
  return `${(n / (1024 * 1024)).toFixed(2)} MB`;
}

/**
 * 解析 `Content-Disposition` 里的文件名。
 *
 * ⚠️ 后端同时发了两个名字：
 *      attachment; filename="____.pdf"; filename*=UTF-8''%E5%90%88%E5%90%8C.pdf
 *    前一个是 ASCII 兜底（中文全被替换成下划线），后一个才是真名。
 *    **必须优先取 `filename*`**，否则用户下载下来就是一堆下划线 —— 这正是用户点名要求
 *    "确保中文名不乱码"的地方。
 */
export function fileNameFromDisposition(header, fallback = '下载文件') {
  const raw = String(header || '');
  const encoded = /filename\*=UTF-8''([^;]+)/i.exec(raw);
  if (encoded) {
    const value = encoded[1].trim().replace(/^"|"$/g, '');
    try {
      return decodeURIComponent(value) || fallback;
    } catch {
      // 百分号编码坏了（极少见）→ 落到下面的 ASCII 兜底名
    }
  }
  const plain = /filename="?([^";]+)"?/i.exec(raw);
  if (plain) {
    const value = plain[1].trim();
    if (value) return value;
  }
  return fallback;
}

/**
 * 列表请求路径。分类/关键词都走 query，不做前端过滤 ——
 * 文件可能有几百个，前端只拿到分页结果，本地过滤会"筛出空列表但其实有"。
 */
export function buildListPath(customerId, { category = '', keyword = '' } = {}) {
  const params = new URLSearchParams();
  if (category) params.set('category', category);
  const kw = String(keyword || '').trim();
  if (kw) params.set('keyword', kw);
  const qs = params.toString();
  return `/customers/${customerId}/files${qs ? `?${qs}` : ''}`;
}

/**
 * ISO 时间 → `YYYY-MM-DD HH:mm`。
 * 故意不用 `new Date()`：后端给的是本地时间字符串（无时区后缀），
 * 走 Date 会按浏览器时区再折一次，跨时区就偏移几小时。
 */
export function formatUploadedAt(iso) {
  if (!iso) return '—';
  const m = /^(\d{4})-(\d{2})-(\d{2})[T ](\d{2}):(\d{2})/.exec(String(iso));
  return m ? `${m[1]}-${m[2]}-${m[3]} ${m[4]}:${m[5]}` : String(iso);
}

/** 名称右侧的格式角标：PDF / DOC / XLS / IMG。认不出就不显示（返回空串）。 */
export function fileKindOf(name) {
  const ext = String(name || '').split('.').pop()?.toLowerCase() || '';
  if (ext === 'pdf') return 'PDF';
  if (ext === 'doc' || ext === 'docx') return 'DOC';
  if (ext === 'xls' || ext === 'xlsx') return 'XLS';
  if (['png', 'jpg', 'jpeg', 'bmp', 'webp', 'tif', 'tiff'].includes(ext)) return 'IMG';
  return '';
}

/**
 * base64 → Blob。
 *
 * 为什么需要它：下载走的是后端 `_wants_json` 的 base64 通道（见组件里的长注释）。
 * ⚠️ 不要写成 `new Blob([atob(x)])`：那样每个字符会被当成**文本**，中文/二进制全坏；
 *    也不要 `Uint8Array.from(binary, c => c.charCodeAt(0))` 再 spread 展开 ——
 *    20MB 的文件会直接把调用栈打爆。这里逐字节填，稳。
 */
export function base64ToBlob(base64, mime = 'application/octet-stream') {
  const binary = atob(String(base64 || ''));
  const bytes = new Uint8Array(binary.length);
  for (let i = 0; i < binary.length; i += 1) bytes[i] = binary.charCodeAt(i);
  return new Blob([bytes], { type: mime || 'application/octet-stream' });
}

/**
 * 上传前的前端预检（**不是**安全边界，后端的文件头校验才是）。
 * 提前拦一下能在选错文件时立刻提示，不用等一个 20MB 的文件传完才报 400。
 * 返回中文原因，`null` = 放行。
 */
export function checkUpload(file, meta) {
  if (!file) return '没有选中文件';
  const maxBytes = Number(meta?.max_bytes || 0);
  if (maxBytes > 0 && file.size > maxBytes) {
    return `「${file.name}」${formatFileSize(file.size)} 超过 ${meta?.max_mb || Math.round(maxBytes / 1024 / 1024)}MB 上限`;
  }
  if (file.size === 0) return `「${file.name}」是空文件（0 字节）`;
  return null;
}
