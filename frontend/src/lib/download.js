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
