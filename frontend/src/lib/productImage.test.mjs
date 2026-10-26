/**
 * productImage 纯逻辑单测（Node 直接跑，不需要浏览器 / 不需要装测试框架）
 *
 * 跑法： E:\AI\ERP软件\frontend 下
 *   node --test src/lib/productImage.test.mjs
 *
 * 覆盖重点：图片这块最容易出错的都不是"渲染"，而是判断和拼装 ——
 * 大小上限、MIME 缺失、历史脏数据的前缀、以及 multipart 里那条
 * **绝不能自己设的 Content-Type**。这些靠点界面很难点全，全部在这里钉死。
 */

import test from 'node:test';
import assert from 'node:assert/strict';

import {
  IMAGE_ACCEPT,
  IMAGE_MAX_BYTES,
  errorDetail,
  formatBytes,
  resolveImageSrc,
  uploadProductImage,
  validateImageFile,
} from './productImage.js';

const MB = 1024 * 1024;

/**
 * 造一个真的 `File`。
 * ⚠️ 不能用 `{ name, size, type }` 这种朴素对象凑数 —— Node 的 FormData
 * （undici 实现）比规范更严：`append` 只认真正的 Blob/File，
 * 给普通对象会抛 "parameter 2 is not of type 'Blob'"，
 * 于是"发请求"这条路径上的用例全部会以 TypeError 假失败。
 */
const file = (name, size, type) => new File([new Uint8Array(size)], name, { type: type || '' });

// ── 伪造的 fetch：记录每次调用，方便断言"到底发了什么" ─────────────────────

const okFetch = (body = { url: '/api/v1/uploads/products/abc-a.png' }) => {
  const calls = [];
  const impl = async (url, options) => {
    calls.push({ url, options });
    return { ok: true, status: 201, json: async () => body };
  };
  impl.calls = calls;
  return impl;
};

const errFetch = (status, body) => {
  const calls = [];
  const impl = async (url, options) => {
    calls.push({ url, options });
    return { ok: false, status, json: async () => body };
  };
  impl.calls = calls;
  return impl;
};

// ═══════════════════════════════════════════════════════════════════════════
// formatBytes
// ═══════════════════════════════════════════════════════════════════════════

test('formatBytes：B / KB / MB 三档都给人能读的形式', () => {
  assert.equal(formatBytes(0), '0 B');
  assert.equal(formatBytes(512), '512 B');
  assert.equal(formatBytes(1024), '1.0 KB');
  assert.equal(formatBytes(1536), '1.5 KB');
  assert.equal(formatBytes(MB), '1.0 MB');
  assert.equal(formatBytes(5 * MB), '5.0 MB');
});

test('formatBytes：非法输入不抛错，退回 0 B', () => {
  assert.equal(formatBytes(undefined), '0 B');
  assert.equal(formatBytes(null), '0 B');
  assert.equal(formatBytes('abc'), '0 B');
  assert.equal(formatBytes(-1), '0 B');
});

// ═══════════════════════════════════════════════════════════════════════════
// validateImageFile
// ═══════════════════════════════════════════════════════════════════════════

test('validateImageFile：没选文件 / 空文件都能被拦下', () => {
  assert.equal(validateImageFile(null).ok, false);
  assert.match(validateImageFile(null).error, /没有选择图片/);
  assert.equal(validateImageFile(file('a.png', 0, 'image/png')).ok, false);
  assert.match(validateImageFile(file('a.png', 0, 'image/png')).error, /是空的/);
});

test('validateImageFile：四种允许的格式都放行', () => {
  for (const [name, type] of [
    ['a.png', 'image/png'],
    ['a.jpg', 'image/jpeg'],
    ['a.jpeg', 'image/jpeg'],
    ['a.webp', 'image/webp'],
    ['a.bmp', 'image/bmp'],
  ]) {
    assert.equal(validateImageFile(file(name, 1024, type)).ok, true, `${name} 应该放行`);
  }
});

test('validateImageFile：大写扩展名与大写 MIME 也要放行', () => {
  assert.equal(validateImageFile(file('PHOTO.PNG', 1024, 'IMAGE/PNG')).ok, true);
});

test('validateImageFile：正好等于 5MB 放行，多一个字节就拦', () => {
  assert.equal(validateImageFile(file('a.png', IMAGE_MAX_BYTES, 'image/png')).ok, true);
  const over = validateImageFile(file('a.png', IMAGE_MAX_BYTES + 1, 'image/png'));
  assert.equal(over.ok, false);
  assert.match(over.error, /5\.0 MB/);
  assert.match(over.error, /超过/);
});

test('validateImageFile：错误提示里带上"你传了多大"，方便用户自己判断', () => {
  const result = validateImageFile(file('big.png', 8 * MB, 'image/png'));
  assert.equal(result.ok, false);
  assert.match(result.error, /8\.0 MB/);
});

test('validateImageFile：GIF 给出专门的理由，而不是笼统的"格式不对"', () => {
  const result = validateImageFile(file('ani.gif', 1024, 'image/gif'));
  assert.equal(result.ok, false);
  assert.match(result.error, /GIF/);
  // 替换方案要在提示里说清楚，否则用户只知道"不行"
  assert.match(result.error, /png \/ jpg \/ webp \/ bmp/);
});

test('validateImageFile：MIME 为空但后缀认识 → 放行（U 盘/网络盘上很常见）', () => {
  assert.equal(validateImageFile(file('照片.png', 2048, '')).ok, true);
  assert.equal(validateImageFile(file('照片.png', 2048, undefined)).ok, true);
});

test('validateImageFile：MIME 对但后缀不认识 → 放行（最终由后端按文件头把关）', () => {
  // 这一条是**刻意**的宽松：后端的嗅探才是权威，前端只负责挡住明显不对的
  assert.equal(validateImageFile(file('noext', 2048, 'image/png')).ok, true);
});

test('validateImageFile：既不是图片 MIME、后缀也不认识 → 拦下', () => {
  const result = validateImageFile(file('doc.txt', 2048, 'text/plain'));
  assert.equal(result.ok, false);
  assert.match(result.error, /只支持/);
});

test('validateImageFile：拿 .exe 冒充图片，光看名字也能被拦（MIME 也没有）', () => {
  assert.equal(validateImageFile(file('setup.exe', 2048, 'application/x-msdownload')).ok, false);
});

test('IMAGE_ACCEPT 与后端白名单一致（不含 gif）', () => {
  assert.equal(IMAGE_ACCEPT, '.png,.jpg,.jpeg,.webp,.bmp');
  assert.ok(!IMAGE_ACCEPT.includes('gif'));
});

// ═══════════════════════════════════════════════════════════════════════════
// resolveImageSrc
// ═══════════════════════════════════════════════════════════════════════════

test('resolveImageSrc：空值一律给空串（<img src=""> 不会去发请求）', () => {
  assert.equal(resolveImageSrc(''), '');
  assert.equal(resolveImageSrc(null), '');
  assert.equal(resolveImageSrc(undefined), '');
  assert.equal(resolveImageSrc('   '), '');
});

test('resolveImageSrc：带 scheme 的一律原样返回', () => {
  assert.equal(resolveImageSrc('https://cdn.example.com/a.png'), 'https://cdn.example.com/a.png');
  assert.equal(resolveImageSrc('http://cdn.example.com/a.png'), 'http://cdn.example.com/a.png');
  assert.equal(resolveImageSrc('data:image/png;base64,iVBORw0KGgo='), 'data:image/png;base64,iVBORw0KGgo=');
  assert.equal(resolveImageSrc('blob:http://127.0.0.1:8010/abc-123'), 'blob:http://127.0.0.1:8010/abc-123');
});

test('resolveImageSrc：协议相对地址（//cdn/...）原样返回', () => {
  assert.equal(resolveImageSrc('//cdn.example.com/a.png'), '//cdn.example.com/a.png');
});

test('resolveImageSrc：本系统上传的绝对路径原样返回', () => {
  const url = '/api/v1/uploads/products/150498bc3e97-a.png';
  assert.equal(resolveImageSrc(url), url);
});

test('resolveImageSrc：历史脏数据漏了开头的斜杠要补上', () => {
  // 早期「图片链接」是手填的，很容易少打一个 /
  assert.equal(resolveImageSrc('uploads/products/a.png'), '/uploads/products/a.png');
  assert.equal(resolveImageSrc('  /api/v1/uploads/products/a.png  '), '/api/v1/uploads/products/a.png');
});

test('resolveImageSrc：百分号编码过的中文名不会被破坏', () => {
  const url = '/api/v1/uploads/products/150498bc3e97-%E6%B5%8B%E8%AF%95.png';
  assert.equal(resolveImageSrc(url), url);
});

// ═══════════════════════════════════════════════════════════════════════════
// errorDetail
// ═══════════════════════════════════════════════════════════════════════════

test('errorDetail：字符串 detail 直接用（后端业务错误的常态）', () => {
  assert.equal(errorDetail({ detail: '这不是一张图片' }, '兜底'), '这不是一张图片');
});

test('errorDetail：422 的 detail 数组取第一条 msg（否则会拼出 [object Object]）', () => {
  const body = { detail: [{ loc: ['body', 'file'], msg: 'field required', type: 'value_error.missing' }] };
  assert.equal(errorDetail(body, '兜底'), 'field required');
});

test('errorDetail：形式不认识时退回兜底文案', () => {
  assert.equal(errorDetail(undefined, '兜底'), '兜底');
  assert.equal(errorDetail({}, '兜底'), '兜底');
  assert.equal(errorDetail({ detail: '' }, '兜底'), '兜底');
  assert.equal(errorDetail({ detail: [] }, '兜底'), '兜底');
  assert.equal(errorDetail({ detail: [{ nope: 1 }] }, '兜底'), '兜底');
});

// ═══════════════════════════════════════════════════════════════════════════
// uploadProductImage
// ═══════════════════════════════════════════════════════════════════════════

test('uploadProductImage：成功时返回后端给的 url', async () => {
  const impl = okFetch({ url: '/api/v1/uploads/products/abc-a.png' });
  const url = await uploadProductImage(file('a.png', 1024, 'image/png'), {
    apiBase: '/api/v1',
    fetchImpl: impl,
  });
  assert.equal(url, '/api/v1/uploads/products/abc-a.png');
});

test('uploadProductImage：请求地址、方法、FormData 字段都对', async () => {
  const impl = okFetch();
  await uploadProductImage(file('a.png', 1024, 'image/png'), { apiBase: '/api/v1', fetchImpl: impl });
  assert.equal(impl.calls.length, 1);
  assert.equal(impl.calls[0].url, '/api/v1/upload/product-image');
  assert.equal(impl.calls[0].options.method, 'POST');
  assert.ok(impl.calls[0].options.body instanceof FormData);
  assert.equal(impl.calls[0].options.body.get('file') !== null, true);
});

test('uploadProductImage：**绝不自己设 Content-Type**（设了 boundary 就没了，后端解不出文件）', async () => {
  const impl = okFetch();
  await uploadProductImage(file('a.png', 1024, 'image/png'), { apiBase: '/api/v1', fetchImpl: impl });
  const headers = impl.calls[0].options.headers || {};
  const keys = Object.keys(headers).map((k) => k.toLowerCase());
  assert.ok(!keys.includes('content-type'), `不该出现 Content-Type，实际有：${keys.join(',')}`);
});

test('uploadProductImage：authHeaders 会被带上', async () => {
  const impl = okFetch();
  await uploadProductImage(file('a.png', 1024, 'image/png'), {
    apiBase: '/api/v1',
    authHeaders: () => ({ Authorization: 'Bearer tok-123' }),
    fetchImpl: impl,
  });
  assert.equal(impl.calls[0].options.headers.Authorization, 'Bearer tok-123');
});

test('uploadProductImage：没有 authHeaders 也能跑（未登录场景不该在拼装阶段就崩）', async () => {
  const impl = okFetch();
  await uploadProductImage(file('a.png', 1024, 'image/png'), { apiBase: '/api/v1', fetchImpl: impl });
  assert.deepEqual(impl.calls[0].options.headers, {});
});

test('uploadProductImage：400 的中文 detail 直接透传给用户', async () => {
  const impl = errFetch(400, { detail: '这不是一张图片（只支持 png / jpg / webp / bmp）' });
  await assert.rejects(
    () => uploadProductImage(file('a.png', 1024, 'image/png'), { apiBase: '/api/v1', fetchImpl: impl }),
    /这不是一张图片/,
  );
});

test('uploadProductImage：413 的"超过 5MB"也能透传', async () => {
  const impl = errFetch(413, { detail: '图片 8.0MB 超过 5MB 上限' });
  await assert.rejects(
    () => uploadProductImage(file('a.png', 8 * MB, 'image/png'), { apiBase: '/api/v1', fetchImpl: impl }),
    /超过 5MB 上限/,
  );
});

test('uploadProductImage：422 的数组 detail 取第一条 msg，不出现 [object Object]', async () => {
  const impl = errFetch(422, { detail: [{ loc: ['body', 'file'], msg: 'field required' }] });
  await assert.rejects(
    () => uploadProductImage(file('a.png', 1024, 'image/png'), { apiBase: '/api/v1', fetchImpl: impl }),
    (err) => {
      assert.match(err.message, /field required/);
      assert.ok(!err.message.includes('[object Object]'));
      return true;
    },
  );
});

test('uploadProductImage：500 且没有 detail 时给出带状态码的兜底文案', async () => {
  const impl = errFetch(500, {});
  await assert.rejects(
    () => uploadProductImage(file('a.png', 1024, 'image/png'), { apiBase: '/api/v1', fetchImpl: impl }),
    /HTTP 500/,
  );
});

test('uploadProductImage：响应体没有 url 时明确报错，而不是把 undefined 存进表单', async () => {
  const impl = okFetch({});
  await assert.rejects(
    () => uploadProductImage(file('a.png', 1024, 'image/png'), { apiBase: '/api/v1', fetchImpl: impl }),
    /没有返回图片地址/,
  );
});

test('uploadProductImage：没给文件时直接抛错，不发请求', async () => {
  const impl = okFetch();
  await assert.rejects(
    () => uploadProductImage(null, { apiBase: '/api/v1', fetchImpl: impl }),
    /没有选择图片/,
  );
  assert.equal(impl.calls.length, 0);
});

test('uploadProductImage：文件名缺失时用 image 兜底，不传 undefined 给 FormData', async () => {
  const impl = okFetch();
  const unnamed = new File([new Uint8Array(1024)], '', { type: 'image/png' });
  await uploadProductImage(unnamed, { apiBase: '/api/v1', fetchImpl: impl });
  assert.equal(impl.calls.length, 1);
});
