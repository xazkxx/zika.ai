// 全单据 Word 导出（任务 E · 2026-10-19）—— 前端唯一的调用点
//
// 四个页面（合同台账 / 报价单 / 入库单 / 对账单）都要"点一下拿到 .docx"，
// 所以收在一处：以后加第五种单据，只改后端 kinds 列表 + 这里的一行调用。
//
// 两个坑先记下：
//   ① **必须自己带 Authorization**：这些页面都是 fetch 取数，没有浏览器自动带的 cookie；
//      漏了就是 401，而 401 的表现是"点了没反应"（错误被 catch 成提示语）。
//   ② **文件名以响应头为准**：后端 `_attachment_response` 用 RFC 5987 传中文名，
//      退到 ASCII 兜底名时中文会变成下划线 —— 取错了用户看到的是 `_____.docx`。
//
// ⚠️ 不用 base64 通道：`application/vnd.openxmlformats-…wordprocessingml.document`
//    不是浏览器会接管的类型（那是 PDF 的毛病），二进制直取更省一次编解码。
//    真要给"下载被插件拦截"的机器兜底，后端留了 `?as_json=true`。

import { API_BASE } from './appLib.js';
import { fileNameFromDisposition, saveBlob } from './download.js';

export const WORD_KINDS = {
  contract: '购销合同',
  quotation: '报价单',
  inbound: '入库单',
  statement: '对账单',
};

/**
 * 下载一张单据的 Word 文件。
 * @param {'contract'|'quotation'|'inbound'|'statement'} kind
 * @param {number} docId
 * @returns {Promise<string>} 实际保存的文件名
 */
export async function exportWord(kind, docId, fallbackName = '单据.docx') {
  const id = Number(docId);
  if (!kind || !Number.isFinite(id) || id <= 0) {
    throw new Error('单据还没保存，无法导出');
  }
  const token = localStorage.getItem('erp_token') || '';
  const response = await fetch(`${API_BASE}/exports/word/${kind}/${id}`, {
    headers: {
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      // 明确要 docx；后端 ?as_json 旁路只给自测脚本用
      Accept:
        'application/vnd.openxmlformats-officedocument.wordprocessingml.document, application/octet-stream',
    },
  });
  if (!response.ok) {
    // FastAPI 的错误体是 JSON：能读就读出来，读不出来也别吞成 "HTTP 500"
    const data = await response.json().catch(() => ({}));
    const detail = data && data.detail;
    throw new Error(
      typeof detail === 'string' ? detail : `导出失败（HTTP ${response.status}）`,
    );
  }
  const blob = await response.blob();

  // ⭐ 关键一道闸：**只要不是 docx 二进制，就绝不落盘**。
  //   历史教训：错误信息（{"detail": …} 的 JSON、或代理返回的 HTML 登录页）被
  //   原样存成 .docx，用户双击打开 Word 报"文件已损坏"，比"下载失败"难排查十倍。
  //   docx 本质是 zip，前 4 个字节必然是 50 4B 03 04（PK\x03\x04）。
  if (!blob || blob.size === 0) {
    throw new Error('导出失败：服务端返回了空文件，请重试或联系管理员');
  }
  if (!(await looksLikeDocx(blob))) {
    const preview = (await blob.slice(0, 300).text()).replace(/\s+/g, ' ').trim();
    let detail = '';
    try {
      detail = JSON.parse(preview).detail || '';
    } catch {
      /* 不是 JSON 就算了，用原文预览 */
    }
    throw new Error(
      `导出失败：服务端返回的不是 Word 文件${detail ? `（${detail}）` : `（内容开头：${preview.slice(0, 60)}）`}`,
    );
  }

  const name = ensureDocxName(
    fileNameFromDisposition(response.headers.get('Content-Disposition'), fallbackName),
  );
  saveBlob(blob, name);
  return name;
}

/** docx = zip 包：前 4 字节必须是 PK\x03\x04（空 zip 的 PK\x05\x06 也算异常） */
async function looksLikeDocx(blob) {
  const head = new Uint8Array(await blob.slice(0, 4).arrayBuffer());
  return head[0] === 0x50 && head[1] === 0x4b && head[2] === 0x03 && head[3] === 0x04;
}

/** 文件名兜底补后缀：`报价单-BJ001` → `报价单-BJ001.docx`（少后缀 Windows 认不出） */
function ensureDocxName(name) {
  const clean = String(name || '').trim() || '单据.docx';
  return /\.docx$/i.test(clean) ? clean : `${clean}.docx`;
}
