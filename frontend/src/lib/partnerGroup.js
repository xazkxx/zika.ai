/**
 * partnerGroup —— 客户/供应商档案左侧「分组树」的纯逻辑（无 React、无 DOM）
 *
 * 为什么单独抽出来：
 *   树的分组、计数、过滤是这块唯一有边界条件的地方（空值归组、维度根节点语义、
 *   同名不同维度不冲突），靠鼠标点是点不全的。参考 `lib/productCategory.js` 的做法，
 *   这里做成纯函数并用 `node --test` 守着。
 *
 * 与 ProductCategoryTree 的关系：
 *   交互语义（点行选中 / 再点取消 / caret 折叠 / 计数徽标）完全一致，但**没有复用
 *   那个组件** —— 它绑死了 product-categories 的 id、`counts.byId`、增删改回调，
 *   而客户/供应商根本没有「类别」这张表，硬套只会得到一棵假树。
 *   通用部分在 `components/ui/ErpTree.jsx`（`.erp-tree`），本文件只负责"数据怎么分组"。
 *
 * 分组维度（来自真实数据，2026-10-17 三套账实测）：
 *   客户 25 条：level「零售价1」21 / 零售价2 1 / 零售价3 1 / 空 2；businesser「范先生」20 / 空 5
 *   供应商 61 条：short_name 是拼音首字母串（61/61 都有值，`szskgdzyxgs` → S），
 *                 按首字母分组比按地区/开户行有意义得多
 */

/** 空值归组用的哨兵值（不能与真实取值撞车，所以带双下划线） */
export const UNGROUPED = '__ungrouped__';

/**
 * 维度声明。
 * - `key`           字段名，同时也是「维度根节点」的树键
 * - `label`         维度显示名
 * - `ungroupedLabel` 该维度没填时的归组名
 */
const DIMENSIONS = {
  customer: [
    { key: 'level', label: '客户级别', ungroupedLabel: '未分级' },
    { key: 'businesser', label: '业务员', ungroupedLabel: '未指派' },
  ],
  supplier: [{ key: 'initial', label: '名称首字母', ungroupedLabel: '其他' }],
};

/** 拼音首字母：取 `short_name`（如 `szskgdzyxgs` → `S`），没有就退回名称首字符 */
function initialOf(row) {
  const src = String((row && (row.short_name || row.name)) || '').trim();
  if (!src) return '';
  const ch = src[0].toUpperCase();
  return /[A-Z]/.test(ch) ? ch : '#';
}

/** 取某一维度的原始值（去空白；没有就是空串） */
export function rawValueOf(row, dimKey) {
  if (!row) return '';
  if (dimKey === 'initial') return initialOf(row);
  const value = row[dimKey];
  return value === null || value === undefined ? '' : String(value).trim();
}

/** 叶子节点键：`level:零售价1` / `level:__ungrouped__` */
export function keyOf(dimKey, value) {
  return `${dimKey}:${value || UNGROUPED}`;
}

function dimsOf(kind) {
  return DIMENSIONS[kind] || DIMENSIONS.customer;
}

/** 从任意树键反查维度声明（维度根节点传 `level`，叶子传 `level:xx`） */
function dimOf(treeKey) {
  const key = String(treeKey || '');
  const idx = key.indexOf(':');
  const dimKey = idx === -1 ? key : key.slice(0, idx);
  for (const list of Object.values(DIMENSIONS)) {
    const hit = list.find((dim) => dim.key === dimKey);
    if (hit) return hit;
  }
  return null;
}

/**
 * 建树。
 *
 * @returns {{nodes: Array, counts: Map<string, number>, total: number}}
 *   nodes  = [{ key:'level', label:'客户级别', children:[{ key:'level:零售价1', label:'零售价1', count:21 }] }]
 *   counts = 树键 → 条数（维度根节点的计数**不含**未归组，所以 `level` 是 23 而不是 25）
 */
export function buildPartnerTree(rows = [], kind = 'customer') {
  const list = rows || [];
  const counts = new Map();

  const nodes = dimsOf(kind).map((dim) => {
    const buckets = new Map();
    let filled = 0;

    list.forEach((row) => {
      const value = rawValueOf(row, dim.key);
      if (value) filled += 1;
      const bucket = value || UNGROUPED;
      buckets.set(bucket, (buckets.get(bucket) || 0) + 1);
    });

    const children = [...buckets.entries()]
      .filter(([value]) => value !== UNGROUPED)
      .sort((a, b) => b[1] - a[1] || String(a[0]).localeCompare(String(b[0]), 'zh-Hans-CN'))
      .map(([value, count]) => ({ key: keyOf(dim.key, value), label: value, count }));

    // 「未分组」永远排在最后：它是兜底桶，混在中间会让人以为也是个正常分类
    if (buckets.has(UNGROUPED)) {
      children.push({
        key: keyOf(dim.key, ''),
        label: dim.ungroupedLabel,
        count: buckets.get(UNGROUPED),
      });
    }

    counts.set(dim.key, filled);
    children.forEach((child) => counts.set(child.key, child.count));

    return { key: dim.key, label: dim.label, children };
  });

  return { nodes, counts, total: list.length };
}

/**
 * 按树选中项过滤。
 *   null / ''          → 全部
 *   `level`            → 该维度**有值**的行（未归组的不算）
 *   `level:零售价1`    → 该取值的行
 *   `level:__ungrouped__` → 该维度为空的行
 */
export function filterPartnersByGroup(rows = [], kind = 'customer', selected = null) {
  const list = rows || [];
  if (!selected) return list;

  const key = String(selected);
  const idx = key.indexOf(':');
  const dimKey = idx === -1 ? key : key.slice(0, idx);
  const want = idx === -1 ? null : key.slice(idx + 1);

  return list.filter((row) => {
    const value = rawValueOf(row, dimKey);
    if (want === null) return Boolean(value);
    if (want === UNGROUPED) return !value;
    return value === want;
  });
}

/** 选中项的中文描述，用于卡片副标题（`客户级别 · 零售价1`）；未选中返回空串 */
export function partnerGroupLabel(selected) {
  if (!selected) return '';
  const key = String(selected);
  const idx = key.indexOf(':');
  const dim = dimOf(key);
  if (!dim) return '';
  if (idx === -1) return dim.label;
  const want = key.slice(idx + 1);
  return `${dim.label} · ${want === UNGROUPED ? dim.ungroupedLabel : want}`;
}
