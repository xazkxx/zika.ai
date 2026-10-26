/**
 * 商品图片 —— 上传前的校验、地址归一、上传调用。
 *
 * 为什么单独抽成一个 lib（而不是写在组件里）：
 *   这四条判断（大小 / 格式 / MIME 缺失 / 历史脏数据的前缀）出错的代价是
 *   "图片传不上去"或者"传上去了显示不出来"，而组件本身要用 jsdom 才能跑。
 *   抽出来就能用 `node --test` 直接钉死，跟前一步的 `productCategory.js` 一个路数。
 *
 * 与后端的对齐关系（**改一边必须改另一边**）：
 *   上限 5MB、格式 png/jpg/jpeg/webp/bmp —— 见 `app/api/v1/routes/erp_upload.py`
 *   的 `MAX_IMAGE_BYTES` / `ACCEPTED_IMAGE_SUFFIXES`。
 *   前端校验只是为了"不让人白等一次上传"，**最终把关在后端**：那边按文件头
 *   嗅探真实格式，不信扩展名也不信 Content-Type。
 */

/** 单张图片上限，与后端 MAX_IMAGE_BYTES 一致 */
export const IMAGE_MAX_BYTES = 5 * 1024 * 1024;

/** 文件选择框的 accept。刻意不含 gif —— 后端会明确拒绝（file_storage 的后缀白名单里没有 .gif） */
export const IMAGE_ACCEPT = '.png,.jpg,.jpeg,.webp,.bmp';

const ALLOWED_TYPES = ['image/png', 'image/jpeg', 'image/webp', 'image/bmp'];
const ALLOWED_SUFFIXES = ['.png', '.jpg', '.jpeg', '.webp', '.bmp'];

/** 字节数 → 人能读的字符串（用于错误提示里的"你传了多大"） */
export function formatBytes(bytes) {
  const n = Number(bytes);
  if (!Number.isFinite(n) || n < 0) return '0 B';
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`;
  return `${(n / 1024 / 1024).toFixed(1)} MB`;
}

/**
 * 上传前校验。返回 `{ ok: true }` 或 `{ ok: false, error }`（error 是要直接给用户看的中文）。
 *
 * 刻意**放宽**的一处：`file.type` 为空时按后缀放行。
 * 实测有些来源（U 盘、网络盘、部分 Linux 桌面拖拽）给不出 MIME，
 * 严格按 type 判断会把真图片误杀成"不是图片"。宁可放过去让后端按文件头判，
 * 也不要让用户对着完全正常的图片反复重试。
 */
export function validateImageFile(file) {
  if (!file) return { ok: false, error: '没有选择图片' };
  if (!file.size) return { ok: false, error: '这个文件是空的，请换一张图片' };
  if (file.size > IMAGE_MAX_BYTES) {
    return {
      ok: false,
      error: `图片 ${formatBytes(file.size)} 超过 ${formatBytes(IMAGE_MAX_BYTES)} 上限，请压缩后再传`,
    };
  }

  const name = String(file.name || '').toLowerCase();
  if (name.endsWith('.gif')) {
    // 后端会拒绝并给出同样的理由，这里先说一遍，省掉一次白跑的请求
    return { ok: false, error: '暂不支持 GIF 动图，请换成 png / jpg / webp / bmp' };
  }

  const typeOk = ALLOWED_TYPES.includes(String(file.type || '').toLowerCase());
  const suffixOk = ALLOWED_SUFFIXES.some((suffix) => name.endsWith(suffix));
  if (!typeOk && !suffixOk) {
    return { ok: false, error: '只支持 png / jpg / webp / bmp 格式的图片' };
  }
  return { ok: true };
}

/**
 * 把 `products.image_url` 里存的值变成可以直接放进 `<img src>` 的地址。
 *
 * 三种历史/合法形态都要认：
 *   1. `http(s)://…`、`data:…`、`blob:…` —— 原样返回（外部图床、本地即时预览）
 *   2. `/api/v1/uploads/products/xxx.png` —— 本系统上传的，原样返回
 *   3. `uploads/products/xxx.png` —— 补上前导斜杠。
 *      早期手填「图片链接」时很容易漏掉开头的 `/`，那时不显示也无所谓
 *      （反正没人渲染它）；现在有了预览，漏斜杠就会变成相对当前路由的地址而 404。
 */
export function resolveImageSrc(url) {
  const value = String(url || '').trim();
  if (!value) return '';
  if (/^[a-z][a-z0-9+.-]*:/i.test(value)) return value; // 带 scheme：http: / https: / data: / blob:
  if (value.startsWith('//')) return value; // 协议相对地址
  return value.startsWith('/') ? value : `/${value}`;
}

/** 从 FastAPI 的错误体里取一条能给人看的中文信息（422 会给 detail 数组） */
export function errorDetail(data, fallback) {
  const detail = data && data.detail;
  if (typeof detail === 'string' && detail) return detail;
  if (Array.isArray(detail) && detail.length) {
    const first = detail[0];
    if (first && typeof first.msg === 'string' && first.msg) return first.msg;
  }
  return fallback;
}

/**
 * 把一张图片传到后端，返回可写进 `products.image_url` 的地址。
 *
 * ⚠️ **绝对不要自己设 `Content-Type`**：multipart 的 boundary 是浏览器生成并写在
 * `Content-Type` 里的，手工指定会把 boundary 覆盖掉，后端解不出文件字段，
 * 表现为一个很难查的 422（"field required"）。所以这里只合并 Authorization。
 */
export async function uploadProductImage(file, { apiBase, authHeaders, fetchImpl } = {}) {
  if (!file) throw new Error('没有选择图片');
  const doFetch = fetchImpl || (typeof fetch === 'function' ? fetch : null);
  if (!doFetch) throw new Error('当前环境不支持上传（缺少 fetch）');

  const body = new FormData();
  body.append('file', file, file.name || 'image');

  const response = await doFetch(`${apiBase}/upload/product-image`, {
    method: 'POST',
    headers: { ...(authHeaders ? authHeaders() : {}) },
    body,
  });

  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    throw new Error(errorDetail(data, `图片上传失败（HTTP ${response.status}）`));
  }
  if (!data || typeof data.url !== 'string' || !data.url) {
    throw new Error('上传接口没有返回图片地址');
  }
  return data.url;
}
