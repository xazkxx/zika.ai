/**
 * 客户 / 供应商分类 —— 接口封装
 *
 * 与项目既有约定一致（见 `components/menu-tree/menuTreeApi.js`）：
 *   · API_BASE = '/api/v1'
 *   · 不 import appLib，`apiBase` / `authHeaders` 由调用方传入（组件可脱离 App 独立挂载）
 *   · 未传 `authHeaders` 时退回 `localStorage.erp_token`（同 `stockAlertApi.js`），
 *     否则多账套下请求会落到默认账套，树和表格的数据对不上
 *
 * 路由清单（后端 `app/api/v1/routes/erp_partner_category.py`，10 条，逐行同构）：
 *   GET    /{kind}-categories           整棵树（节点带 count / total）
 *   POST   /{kind}-categories           新建
 *   PATCH  /{kind}-categories/{id}      改名 / 改上级 / 改排序
 *   DELETE /{kind}-categories/{id}      删除（有子级或仍被引用 → 409）
 *   POST   /{kind}-categories/{id}/move 拖拽落点（改父级 + 兄弟重排 10/20/30）
 */

const DEFAULT_BASE = '/api/v1';

/** kind → 路由段。`customer` → `customer-categories` / `supplier` → `supplier-categories` */
export function routeOf(kind) {
  return kind === 'supplier' ? 'supplier-categories' : 'customer-categories';
}

function tokenHeaders(authHeaders) {
  if (typeof authHeaders === 'function') return authHeaders() || {};
  if (authHeaders && typeof authHeaders === 'object') return authHeaders;
  try {
    const token = localStorage.getItem('erp_token') || '';
    return token ? { Authorization: `Bearer ${token}` } : {};
  } catch (_error) {
    return {};
  }
}

function headers(authHeaders, extra) {
  return {
    Accept: 'application/json',
    ...tokenHeaders(authHeaders),
    ...(extra || {}),
  };
}

/** 从 FastAPI 的错误体里挖出给人看的话（detail 可能是字符串，也可能是校验错误数组） */
export function readErrorDetail(payload, fallback = '请求失败') {
  if (!payload) return fallback;
  const detail = payload.detail ?? payload.message ?? payload.error;
  if (!detail) return fallback;
  if (typeof detail === 'string') return detail;
  if (Array.isArray(detail)) {
    return (
      detail
        .map((item) => item?.msg || item?.detail || JSON.stringify(item))
        .filter(Boolean)
        .join('；') || fallback
    );
  }
  return JSON.stringify(detail);
}

async function request(url, options = {}) {
  let res;
  try {
    res = await fetch(url, options);
  } catch (cause) {
    // 网络层直接失败（后端没起、断网）：给一句人话，别把 "Failed to fetch" 甩给用户
    const error = new Error('连不上后端（服务可能没启动）');
    error.status = 0;
    error.cause = cause;
    throw error;
  }
  if (res.status === 204) return null;
  const body = await res.json().catch(() => null);
  if (!res.ok) {
    // ⚠️ 把状态码挂到 Error 上：调用方要能区分
    //    · 404 → 这个后端进程里**根本没有这条路由**（代码合并了但没重启，典型症状）
    //    · 401/403 → 权限
    //    · 5xx → 后端真的炸了
    //    三种该给的提示完全不同，只留一句 "Not Found" 等于把排查工作全丢给用户。
    const error = new Error(
      res.status === 404
        ? `${url} 不存在（HTTP 404）—— 后端没有这条路由，通常是改完代码没重启`
        : readErrorDetail(body, `请求失败（HTTP ${res.status}）`),
    );
    error.status = res.status;
    error.detail = readErrorDetail(body, '');
    throw error;
  }
  return body;
}

/** 整棵分类树 */
export async function fetchCategories(kind, { apiBase = DEFAULT_BASE, authHeaders } = {}) {
  const data = await request(`${apiBase}/${routeOf(kind)}`, {
    headers: headers(authHeaders),
  });
  return Array.isArray(data) ? data : [];
}

/**
 * 拖拽落点。
 * ⚠️ 只发 `parent_id` + `before_id` —— 顺序由**服务端**把该父级下的兄弟重排成 10/20/30，
 *    客户端不发 sort_order（发了就是两套排序规则，迟早不一致）。
 */
export async function moveCategory(
  kind,
  categoryId,
  { parentId = null, beforeId = null } = {},
  { apiBase = DEFAULT_BASE, authHeaders } = {},
) {
  return request(`${apiBase}/${routeOf(kind)}/${categoryId}/move`, {
    method: 'POST',
    headers: headers(authHeaders, { 'Content-Type': 'application/json' }),
    body: JSON.stringify({ parent_id: parentId, before_id: beforeId }),
  });
}

/** 新建（`parentId` 为空 = 顶级） */
export async function createCategory(
  kind,
  { name, parentId = null, note = null, sortOrder = null } = {},
  { apiBase = DEFAULT_BASE, authHeaders } = {},
) {
  const payload = { name, parent_id: parentId };
  if (note) payload.note = note;
  if (sortOrder !== null) payload.sort_order = sortOrder;
  return request(`${apiBase}/${routeOf(kind)}`, {
    method: 'POST',
    headers: headers(authHeaders, { 'Content-Type': 'application/json' }),
    body: JSON.stringify(payload),
  });
}

/**
 * 改名 / 改上级 / 改备注。
 * ⚠️ `parentId` 的三态：`undefined` = 不动；`null` = 移到顶级；数字 = 挂过去。
 *    这里用 `Object.prototype.hasOwnProperty` 判断，不写 `if (parentId)` ——
 *    `null` 是合法值，`if (null)` 会把"移到顶级"吞掉。
 */
export async function updateCategory(
  kind,
  categoryId,
  patch = {},
  { apiBase = DEFAULT_BASE, authHeaders } = {},
) {
  const payload = {};
  if (Object.prototype.hasOwnProperty.call(patch, 'name')) payload.name = patch.name;
  if (Object.prototype.hasOwnProperty.call(patch, 'note')) payload.note = patch.note;
  if (Object.prototype.hasOwnProperty.call(patch, 'parentId')) payload.parent_id = patch.parentId;
  if (Object.prototype.hasOwnProperty.call(patch, 'sortOrder')) payload.sort_order = patch.sortOrder;
  return request(`${apiBase}/${routeOf(kind)}/${categoryId}`, {
    method: 'PATCH',
    headers: headers(authHeaders, { 'Content-Type': 'application/json' }),
    body: JSON.stringify(payload),
  });
}

/** 删除（有子级或仍被档案引用时后端 409，`readErrorDetail` 会把原因原样给出来） */
export async function deleteCategory(
  kind,
  categoryId,
  { apiBase = DEFAULT_BASE, authHeaders } = {},
) {
  return request(`${apiBase}/${routeOf(kind)}/${categoryId}`, {
    method: 'DELETE',
    headers: headers(authHeaders),
  });
}
