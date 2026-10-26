/**
 * 菜单树 —— 接口封装
 *
 * 与项目既有约定保持一致（见 App.jsx:1484）：
 *   · API_BASE = '/api/v1'
 *   · authHeaders = () => (authToken ? { Authorization: `Bearer ${authToken}` } : {})
 * 这里不 import appLib，而是把 apiBase / authHeaders 作为参数传入 ——
 * 这样组件可以脱离 App 独立挂载（能放进测试环境单跑，也能被别的页面复用）。
 */

const DEFAULT_BASE = '/api/v1';

function headers(authHeaders, extra) {
  const base = typeof authHeaders === 'function' ? authHeaders() || {} : {};
  return { Accept: 'application/json', ...base, ...(extra || {}) };
}

/** 从 FastAPI 的错误体里挖出给人看的 detail（它可能是字符串，也可能是校验错误数组）。 */
export function readErrorDetail(payload, fallback = '请求失败') {
  if (!payload) return fallback;
  const detail = payload.detail ?? payload.message ?? payload.error;
  if (!detail) return fallback;
  if (typeof detail === 'string') return detail;
  if (Array.isArray(detail)) {
    return detail
      .map((d) => d?.msg || d?.detail || JSON.stringify(d))
      .filter(Boolean)
      .join('；') || fallback;
  }
  return JSON.stringify(detail);
}

/**
 * 拉取完整菜单树。
 * @returns {Promise<{tree: Array, flat: Array, pages: Array, max_depth: number, total: number}>}
 */
export async function fetchMenuTree({ apiBase = DEFAULT_BASE, authHeaders } = {}) {
  const res = await fetch(`${apiBase}/system/menus`, { headers: headers(authHeaders) });
  if (!res.ok) {
    const body = await res.json().catch(() => null);
    throw new Error(readErrorDetail(body, `加载菜单失败（HTTP ${res.status}）`));
  }
  const data = await res.json();
  return {
    tree: Array.isArray(data?.tree) ? data.tree : [],
    flat: Array.isArray(data?.flat) ? data.flat : [],
    pages: Array.isArray(data?.pages) ? data.pages : [],
    max_depth: Number(data?.max_depth) || 8,
    total: Number(data?.total) || 0,
  };
}

/**
 * 保存一次拖拽结果（批量移动/重排）。
 *
 * 对应后端 `POST /system/menus/reorder`（见 _menu_tree_refactor/step1_backend/02_menu_reorder.py）。
 * items 由 menuTreeUtils.planDrop() 产出，形状：
 *   [{ id, parent_id, sort_order }]
 *
 * ⚠️ 后端那次改动**还没合并**时这个接口会 404。组件会把这种情况明确提示出来，
 *    而不是静默失败（见 MenuTreeEditor 的 supportsReorderApi 探测）。
 */
export async function saveMenuOrder({ apiBase = DEFAULT_BASE, authHeaders, items } = {}) {
  if (!Array.isArray(items) || items.length === 0) {
    return { skipped: true };
  }
  const res = await fetch(`${apiBase}/system/menus/reorder`, {
    method: 'POST',
    headers: headers(authHeaders, { 'Content-Type': 'application/json' }),
    body: JSON.stringify({ items }),
  });
  if (res.status === 404) {
    throw new Error(
      '后端还没有 /system/menus/reorder 接口。请先合并 _menu_tree_refactor/step1_backend/02_menu_reorder.py（见 INTEGRATION.md）。',
    );
  }
  if (!res.ok) {
    const body = await res.json().catch(() => null);
    throw new Error(readErrorDetail(body, `保存失败（HTTP ${res.status}）`));
  }
  const data = await res.json().catch(() => null);
  return {
    skipped: false,
    tree: Array.isArray(data?.tree) ? data.tree : null,
    max_depth: Number(data?.max_depth) || null,
  };
}

/** 探测后端是否已经支持批量重排（用于在界面上给出准确提示）。 */
export async function probeReorderApi({ apiBase = DEFAULT_BASE, authHeaders } = {}) {
  try {
    const res = await fetch(`${apiBase}/system/menus/reorder`, {
      method: 'POST',
      headers: headers(authHeaders, { 'Content-Type': 'application/json' }),
      body: JSON.stringify({ items: [] }), // 空 items 在后端是合法的 no-op
    });
    return res.status !== 404 && res.status !== 405;
  } catch {
    return false;
  }
}
