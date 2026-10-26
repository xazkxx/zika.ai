/**
 * ErpTree —— 通用分组树（零依赖，纯 CSS 变量驱动）
 *
 * 来源：商品档案左侧那棵 `.cat-node` 树的交互语义被验证好用（点行选中、
 * 再点同一行取消、caret 折叠、右侧计数徽标、姓名长了省略号），
 * 但那个组件 `ProductCategoryTree` 绑死了 product-categories 的 id、
 * `counts.byId` 和增删改回调 —— 客户/供应商没有"类别"这张表，套不上。
 * 所以把**交互**抽到这里，`节点从哪来`留给调用方。
 *
 * 交互约定（与 ProductCategoryTree 保持一致，用户不用重新学）：
 *   点整行     → 选中该节点；再点同一行 → 取消选中（回到「全部」）
 *   点小三角   → 折叠 / 展开（stopPropagation，不影响选中）
 *   Enter/空格 → 选中；← / → 折叠 / 展开
 *
 * 节点结构（由调用方决定，通常来自 `lib/partnerGroup.js` 的 buildPartnerTree）：
 *   { key: 'level', label: '客户级别', children: [{ key: 'level:零售价1', label: '零售价1', count: 21 }] }
 *   —— `count` 字段是可选的兜底；优先用 `counts`（Map<key, number>），
 *      这样计数可以在不改节点的情况下随数据变化。
 *
 * 样式在 `erp-tree.css`，类名前缀 `.erp-tree`，与 styles.css 零交叉。
 */

import { useEffect, useRef, useState } from 'react';

import { ALL } from '../../lib/treeSelection.js';
import './erp-tree.css';

/** 收集所有"有子节点"的 key —— 这些节点默认折叠起来，只露出一级目录 */
function groupKeys(nodes, out = []) {
  (nodes || []).forEach((node) => {
    if ((node.children || []).length > 0) {
      out.push(node.key);
      groupKeys(node.children, out);
    }
  });
  return out;
}

export default function ErpTree({
  nodes = [],
  value = null,
  onChange = null,
  counts = null,
  total = null,
  allLabel = '全部',
  allHint = '',
  className = '',
}) {
  // 折叠是纯展示状态，跟业务无关，留在组件内部（同 ProductCategoryTree）
  // 2026-10-19：初始**全部折叠**（只露出一级目录），不再是"全摊开"。
  // 数据是异步来的，所以还要一个 seed 效果：首次拿到节点时再折一次。
  const [collapsed, setCollapsed] = useState(() => groupKeys(nodes));
  const seeded = useRef((nodes || []).length > 0);

  useEffect(() => {
    if (seeded.current || !(nodes || []).length) return;
    seeded.current = true;
    setCollapsed(groupKeys(nodes));
  }, [nodes]);

  const countOf = (node) => {
    if (counts && typeof counts.get === 'function') {
      const hit = counts.get(node.key);
      if (hit !== undefined) return hit;
    }
    if (typeof node.count === 'number') return node.count;
    return (node.children || []).reduce((sum, child) => sum + countOf(child), 0);
  };

  const toggleCollapse = (key) =>
    setCollapsed((prev) => (prev.includes(key) ? prev.filter((x) => x !== key) : [...prev, key]));

  const select = (key) => {
    if (!onChange) return;
    // 再点同一节点 = 回到「全部」（不是回到"什么都没选"，
    // 那样会让人以为数据丢了 —— 见 lib/treeSelection.js 的三态说明）
    onChange(key === value ? ALL : key);
  };

  const onRowKeyDown = (event, node, hasChildren) => {
    if (event.key === 'Enter' || event.key === ' ') {
      event.preventDefault();
      select(node.key);
      return;
    }
    if (!hasChildren) return;
    if (event.key === 'ArrowRight' && collapsed.includes(node.key)) {
      event.preventDefault();
      toggleCollapse(node.key);
    }
    if (event.key === 'ArrowLeft' && !collapsed.includes(node.key)) {
      event.preventDefault();
      toggleCollapse(node.key);
    }
  };

  const renderNode = (node, depth) => {
    const children = node.children || [];
    const hasChildren = children.length > 0;
    const isCollapsed = collapsed.includes(node.key);
    const active = value === node.key;
    // 维度根节点（有子节点的一层）在视觉上做"分组标题"，但仍然可点选
    const isGroup = depth === 0 && hasChildren;

    return (
      <div key={node.key} className="erp-tree__node">
        <div
          className={[
            'erp-tree__row',
            isGroup ? 'erp-tree__row--group' : '',
            active ? 'is-active' : '',
          ]
            .filter(Boolean)
            .join(' ')}
          role="treeitem"
          aria-selected={active}
          aria-expanded={hasChildren ? !isCollapsed : undefined}
          tabIndex={0}
          style={{ paddingLeft: `${8 + depth * 14}px` }}
          onClick={() => select(node.key)}
          onKeyDown={(event) => onRowKeyDown(event, node, hasChildren)}
        >
          {hasChildren ? (
            <span
              className={`erp-tree__caret${isCollapsed ? ' is-collapsed' : ''}`}
              title={isCollapsed ? '展开' : '折叠'}
              aria-hidden="true"
              onClick={(event) => {
                event.stopPropagation();
                toggleCollapse(node.key);
              }}
            >
              {/* 手写 SVG 小三角：展开朝下，折叠时 CSS 转 -90° 朝右 */}
              <svg width="8" height="8" viewBox="0 0 8 8" aria-hidden="true">
                <path
                  d="M1 2.5 L4 6 L7 2.5"
                  fill="none"
                  stroke="currentColor"
                  strokeWidth="1.6"
                  strokeLinecap="round"
                  strokeLinejoin="round"
                />
              </svg>
            </span>
          ) : (
            <span className="erp-tree__caret erp-tree__caret--leaf" aria-hidden="true" />
          )}

          <span className="erp-tree__label" title={node.label}>
            {node.label}
          </span>
          <span className="erp-tree__count">{countOf(node)}</span>
        </div>

        {/* ⚠️ 子行必须套一层普通 div 再放 .erp-tree__row：
            .erp-tree__row 自己是 flex 行，把子行直接塞进去会被排成横排。 */}
        {hasChildren && !isCollapsed && (
          <div className="erp-tree__children" role="group">
            {children.map((child) => renderNode(child, depth + 1))}
          </div>
        )}
      </div>
    );
  };

  // 只有点过「全部」它才是激活态；null = 还没选，整棵树都不高亮
  // （初始态右侧是空表，若「全部」还亮着，用户会以为"已经看全部了却一条没有"）
  const allActive = value === ALL;

  return (
    <div className={`erp-tree${className ? ` ${className}` : ''}`} role="tree" aria-label={allLabel}>
      <div
        className={`erp-tree__row erp-tree__row--all${allActive ? ' is-active' : ''}`}
        role="treeitem"
        aria-selected={allActive}
        tabIndex={0}
        style={{ paddingLeft: '8px' }}
        onClick={() => onChange && onChange(ALL)}
        onKeyDown={(event) => {
          if (event.key === 'Enter' || event.key === ' ') {
            event.preventDefault();
            if (onChange) onChange(ALL);
          }
        }}
      >
        <span className="erp-tree__caret erp-tree__caret--leaf" aria-hidden="true" />
        <span className="erp-tree__label">
          {allLabel}
          {allHint && <span className="erp-tree__hint">{allHint}</span>}
        </span>
        {total !== null && <span className="erp-tree__count">{total}</span>}
      </div>

      {(nodes || []).map((node) => renderNode(node, 0))}
    </div>
  );
}
