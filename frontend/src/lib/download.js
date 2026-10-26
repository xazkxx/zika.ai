// 下载相关的小工具：把"拿到二进制 → 存成用户看得见的文件"这件事收在一处。
//
// 为什么单开这个文件（而不是继续往各页面里复制）：本仓库现在有三处需要它
// （合同原件、客户归档文件、对账单 PDF/Excel），而它踩的坑是同一批：
//
//   ① **浏览器会把 `application/pdf` 的响应从 `fetch()` 手里接管走** ——
//      拿到的是 204 + 空 body，`response.ok` 却仍是 true。所以 PDF 一律走后端
//      `_wants_json` 的 base64 通道（`Accept: application/json`）。见 `erp_print.py:106`。
//   ② `Content-Disposition` 里有两个名字（ASCII 兜底 + RFC 5987），**必须优先取后者**。
//   ③ 0 字节的 blob 一定要报错：静默存一个空文件，用户会以为"下载成功了"。
//
// ⚠️ `lib/contractsLedger.js` 与 `lib/customerFiles.js` 里各有一份同类实现，
//    是它们交付时还没有这个文件。收口需要两边一起改 + 双跑验证台，
//    不在"新增对账单"这一步顺手做（改动已验收模块的风险大于收益）。

/** 0 字节直接抛错，别静默存一个空文件 */
export function saveBlob(blob, filename) {
  if (!blob || blob.size === 0) throw new Error('下载到的文件是空的，请重试');
  const url = URL.createObjectURL(blob);
  const link = document.createElement('a');
  link.href = url;
  link.download = filename || '下载文件';
  document.body.appendChild(link);
  link.click();
  link.remove();
  // 立刻 revoke 在 Chrome 上偶发"下载中断"，隔一拍更稳
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

/* ── 「另存为」直写磁盘：绕开浏览器的下载管道 ────────────────────────────────
 *
 * 为什么不能只用上面的 `saveBlob`（2026-10-26 排到的大坑）：
 *   浏览器里**任何**走下载管道落地的文件都会被打上来源标记
 *   （NTFS 备用数据流 `Zone.Identifier: ZoneId=3`，即 Mark-of-the-Web）。
 *   Office 2019 对带这个标记的文件一律先扔进「受保护视图」沙箱再打开；
 *   沙箱起不来（实测这台机器装着火绒安全软件，PV 容器启动失败）时，
 *   Excel 报的却是**"文件已损坏 / 文件格式或扩展名无效"** —— 用户以为是文件坏了，
 *   其实是标记的问题。WPS 不做受保护视图，所以永远能开，这个不对称就是根因。
 *
 * 解法：Chromium 的 File System Access API（`showSaveFilePicker`）由页面**直接写盘**，
 *   文件不经过下载管道，天生没有这个标记。它只在**安全上下文**里可用
 *   （localhost / 127.0.0.1 算安全上下文；局域网 `http://192.168.x.x` 不算）。
 *
 * 所以策略是「能直写就直写，不能就照旧下载」：
 *   · 不支持 / 非安全上下文 → 退回 `saveBlob`，行为与从前完全一致，同事用 IP 访问不受影响；
 *   · 用户在另存为对话框里点「取消」→ **不要再偷偷下一份**（否则等于惩罚用户）；
 *   · 手势过期（`NotAllowedError`：接口等太久，浏览器的用户手势已失效）或写入失败
 *     → 退回 `saveBlob`，用户至少拿到文件（这时文件带标记，靠系统侧「受信任位置」兜底）。
 */

/** 扩展名 → MIME。写文件对话框的类型下拉需要它。 */
const MIME_BY_EXTENSION = {
  xlsx: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
  xls: 'application/vnd.ms-excel',
  docx: 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
  pdf: 'application/pdf',
  zip: 'application/zip',
  csv: 'text/csv',
  png: 'image/png',
  jpg: 'image/jpeg',
  jpeg: 'image/jpeg',
  json: 'application/json',
  txt: 'text/plain',
  html: 'text/html',
};

/** `发票清单_20261026_1840.xlsx` → `xlsx`（没有扩展名给 ''）。 */
function extensionOf(filename) {
  const match = /\.([A-Za-z0-9]{1,8})$/.exec(String(filename || ''));
  return match ? match[1].toLowerCase() : '';
}

/** 当前环境能否「另存为」直写磁盘。非安全上下文（局域网 IP）一律 false。 */
export function canSaveWithPicker() {
  return (
    typeof window !== 'undefined' &&
    typeof window.showSaveFilePicker === 'function' &&
    window.isSecureContext !== false
  );
}

/**
 * 优先「另存为」直写磁盘，退路是普通下载。
 *
 * @returns {Promise<{saved: 'picker'|'download'|'cancelled', filename: string, reason?: string}>}
 *   `saved` 让调用方能说人话：取消 ≠ 失败，退回下载也不必报错。
 */
export async function saveBlobSmart(blob, filename) {
  const name = String(filename || '下载文件');
  if (!blob || blob.size === 0) throw new Error('下载到的文件是空的，请重试');
  if (!canSaveWithPicker()) {
    saveBlob(blob, name);
    return { saved: 'download', filename: name };
  }

  const extension = extensionOf(name);
  const accept = extension
    ? { [MIME_BY_EXTENSION[extension] || 'application/octet-stream']: [`.${extension}`] }
    : undefined;

  let handle;
  try {
    handle = await window.showSaveFilePicker({
      suggestedName: name,
      types: accept ? [{ description: extension.toUpperCase() + ' 文件', accept }] : undefined,
    });
  } catch (err) {
    // 用户主动取消：悄悄再下一次只会让人莫名其妙
    if (err && err.name === 'AbortError') return { saved: 'cancelled', filename: name };
    saveBlob(blob, name);
    return { saved: 'download', filename: name, reason: err && err.name };
  }

  try {
    const writable = await handle.createWritable();
    await writable.write(blob);
    await writable.close();
  } catch (err) {
    saveBlob(blob, name);
    return { saved: 'download', filename: name, reason: err && err.name };
  }
  return { saved: 'picker', filename: handle.name || name };
}

/**
 * base64 → Blob。
 * ⚠️ 不能 `new Blob([atob(x)])`（会把二进制当文本）；也不能把 20MB 的数组 spread 进
 *    `Uint8Array.from`（打爆调用栈）。逐字节填最稳。
 */
export function base64ToBlob(base64, mime = 'application/octet-stream') {
  const binary = atob(String(base64 || ''));
  const bytes = new Uint8Array(binary.length);
  for (let i = 0; i < binary.length; i += 1) bytes[i] = binary.charCodeAt(i);
  return new Blob([bytes], { type: mime || 'application/octet-stream' });
}

/**
 * 解析 `Content-Disposition`：优先 `filename*=UTF-8''…`（真中文名），
 * 退到 `filename="…"`（ASCII 兜底，中文已被替换成下划线）。
 */
export function fileNameFromDisposition(header, fallback = '下载文件') {
  const raw = String(header || '');
  const encoded = /filename\*=UTF-8''([^;]+)/i.exec(raw);
  if (encoded) {
    const value = encoded[1].trim().replace(/^"|"$/g, '');
    try {
      return decodeURIComponent(value) || fallback;
    } catch {
      // 百分号编码坏了 → 落到 ASCII 兜底名
    }
  }
  const plain = /filename="?([^";]+)"?/i.exec(raw);
  if (plain && plain[1].trim()) return plain[1].trim();
  return fallback;
}
