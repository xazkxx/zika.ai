/**
 * 商品类别树 —— 纯逻辑层
 *
 * 为什么单独一个文件（而不是塞在 App.jsx 里）：
 * 这几个纯函数是这一步唯一有判断逻辑的地方，放进 App.jsx（11000 行）就只能靠
 * "打开浏览器点点看"，回归不了。拆出来后
 *   node --test src/lib/productCategory.test.mjs
 * 秒级跑完，与项目里 alertRules.js / menuTreeUtils.js 是同一套做法。
 *
 * 不依赖 React、不碰 window，标准 ESM 导出，不污染全局。
 *
 * ─────────────────────────────────────────────────────────────────────────
 * ⚠️ 匹配策略（重要，决定了过滤准不准）
 * `products.category` 存的是类别的**名称字符串**，不是外键
 * （见 app/models/product_category.py 的类注释：为了不迁移 261 个存量商品。
 *   实测库里存的也确实是节点名，如「五金」「劳保」，不是路径）。
 * 而类别名的唯一性只在**同一个父级下**保证（后端 `_assert_category_name_unique`），
 * **跨分支允许重名** —— 比如「中铁→中铁一局→劳保鞋」和「中建→中建一局→劳保鞋」，
 * 两个「劳保鞋」都合法。这种情况下只按名称过滤会把另一个分支的商品也带出来。
 *
 * 所以这里做成双通道，**优先精确、缺失才回落**：
 *   1. 商品带 `category_id`（后端加列 + 回填之后才有）→ 按 **id 集合**精确匹配；
 *      此时如果 id 不在子树里就**明确排除**，不再按名字兜底（否则等于没修）。
 *   2. 商品没有 `category_id`（今天全是这种）→ 按 **名称集合**回落匹配。
 *
 * 也就是说：今天不加列也**完全能用**（真实库里目前没有跨分支重名）；
 * 哪天后端把 `products.category_id` 补上，这边**一行都不用改**就自动变精确。
 * 加列的 SQL 与回填脚本见本文件末尾的注释。
 */

/** 「未分类」这个伪节点的 id。下划线前缀保证不会和真实的数字 id 相撞。 */
export const UNCATEGORIZED = '__uncategorized__';

/**
 * 收集一个节点自身 + 全部子孙的类别名（深度优先，层数不限）。
 * @param {{name: string, children?: Array}} node
 * @param {string[]} acc
 * @returns {string[]}
 */
export function collectCategoryNames(node, acc = []) {
  if (!node) return acc;
  acc.push(node.name);
  for (const child of node.children || []) collectCategoryNames(child, acc);
  return acc;
}

/**
 * 收集一个节点自身 + 全部子孙的 id（深度优先，层数不限）。
 * @param {{id: number, children?: Array}} node
 * @param {number[]} acc
 * @returns {number[]}
 */
export function collectCategoryIds(node, acc = []) {
  if (!node) return acc;
  acc.push(node.id);
  for (const child of node.children || []) collectCategoryIds(child, acc);
  return acc;
}

/**
 * 按 id 深度优先找节点；找不到返回 null（不抛错 —— 节点可能刚被删掉）。
 * @param {Array} nodes
 * @param {number} id
 */
export function findCategoryNode(nodes, id) {
  for (const n of nodes || []) {
    if (n.id === id) return n;
    const hit = findCategoryNode(n.children, id);
    if (hit) return hit;
  }
  return null;
}

/** 商品身上的类别名（去首尾空白；null/undefined → 空串）。 */
export function categoryNameOf(product) {
  const raw = product?.category;
  return raw == null ? '' : String(raw).trim();
}

/** 商品身上的类别 id（没有 / 非法 → null）。 */
export function categoryIdOf(product) {
  const raw = product?.category_id;
  if (raw === null || raw === undefined || raw === '') return null;
  const num = Number(raw);
  return Number.isFinite(num) ? num : null;
}

/** 这个商品是否落在「选中节点及其子树」里。 */
function matchesSubtree(product, ids, names) {
  const id = categoryIdOf(product);
  if (id !== null) return ids.has(id); // 有 id：精确判定，不在子树里就是不在
  const name = categoryNameOf(product);
  return name !== '' && names.has(name); // 没 id：按名称回落
}

/**
 * 统计每个类别（**含其全部子孙**）下的商品数，以及未分类数 / 总数。
 * 树上显示角标用；顺带让"点进去是空的"在点之前就能看出来。
 *
 * @returns {{ byId: Map<number, number>, uncategorized: number, all: number }}
 */
export function countProductsByCategory(products, nodes) {
  const rows = products || [];
  const countById = new Map(); // 已回填 id 的商品：按 id 归堆
  const countByNameOnly = new Map(); // 还没 id 的商品：按名称归堆
  let uncategorized = 0;

  for (const row of rows) {
    const id = categoryIdOf(row);
    if (id !== null) {
      countById.set(id, (countById.get(id) || 0) + 1);
      continue;
    }
    const name = categoryNameOf(row);
    if (!name) {
      uncategorized += 1;
      continue;
    }
    countByNameOnly.set(name, (countByNameOnly.get(name) || 0) + 1);
  }

  const byId = new Map();
  const walk = (list) => {
    for (const n of list || []) {
      let total = 0;
      // ⚠️ 必须去重：跨分支重名时 collectCategoryNames 会返回重复的名字
      // （「中铁」子树里「劳保鞋」出现两次），不去重就会把它数两遍。
      for (const id of new Set(collectCategoryIds(n))) total += countById.get(id) || 0;
      for (const name of new Set(collectCategoryNames(n))) total += countByNameOnly.get(name) || 0;
      byId.set(n.id, total);
      walk(n.children);
    }
  };
  walk(nodes);

  return { byId, uncategorized, all: rows.length };
}

/**
 * 按左侧类别树的选中项过滤商品。
 *   filter === null / undefined  → 全部（不做任何过滤）
 *   filter === UNCATEGORIZED     → 只留类别名空白的
 *   filter === <数字 id>         → 该类别**及其全部子孙**下的商品
 *
 * 选中的节点如果已经被删掉，退回"全部"而不是给空列表 ——
 * 列表突然清空会让人以为商品丢了。
 */
export function filterProductsByCategory(products, nodes, filter) {
  const rows = products || [];
  if (filter === null || filter === undefined) return rows;

  if (filter === UNCATEGORIZED) {
    return rows.filter((row) => categoryNameOf(row) === '' && categoryIdOf(row) === null);
  }

  const node = findCategoryNode(nodes, filter);
  if (!node) return rows;

  const ids = new Set(collectCategoryIds(node));
  const names = new Set(collectCategoryNames(node));
  return rows.filter((row) => matchesSubtree(row, ids, names));
}

/* ─────────────────────────────────────────────────────────────────────────
 * 附：将来要「跨分支重名也精确」时，后端要做的事（本步未执行）
 *
 *   -- 1) 加列（可空，不动存量数据）
 *   ALTER TABLE products ADD COLUMN category_id INTEGER;
 *   CREATE INDEX ix_products_category_id ON products (category_id);
 *
 *   -- 2) 只回填"名称在整棵树里唯一"的商品（有歧义的留空，靠名称回落，
 *   --    宁可按名字多带一个，也不要挂错分支）
 *   UPDATE products p
 *      SET category_id = c.id
 *     FROM product_categories c
 *    WHERE p.category IS NOT NULL
 *      AND btrim(p.category) = c.name
 *      AND (SELECT count(*) FROM product_categories x WHERE x.name = c.name) = 1;
 *
 *   -- 3) 核对：还剩多少没回填、其中有多少是因为重名
 *   SELECT count(*) FILTER (WHERE category_id IS NULL) AS 未回填,
 *          count(*) FILTER (WHERE category IS NOT NULL AND btrim(category) <> '') AS 有类别名
 *     FROM products;
 *
 * 加完列之后本文件的 filterProductsByCategory / countProductsByCategory
 * **不需要改**（它们已经优先认 id）。另外商品表单的"类别"输入要改成从树里选
 * （现在是个自由文本 datalist，只会写名称，写不进 id）—— 那属于第二步的表单改造。
 * ───────────────────────────────────────────────────────────────────────── */
