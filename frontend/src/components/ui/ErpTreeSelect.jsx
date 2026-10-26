/**
 * ErpTreeSelect —— 层级下拉（TreeSelect），零依赖、纯 JS
 *
 * 为什么要自己写：
 *   客户/供应商的「所属分类」原来用的是把树**平铺成路径字符串**的 <select>
 *   （「集团客户 / 华东分公司 / 上海分部」）。三级以上时选项会变成
 *   "集团客户 / 华东分公司 / 上海分部 / 浦东新区 / 陆家嘴" 这种一眼看不完的长串，
 *   而且同名前缀重复几十遍，滚动条拖到手指抽筋。
 *   AntD 的 TreeSelect 会带进 rc-tree + rc-virtual-list，gzip 约 60KB，
 *   与"首屏极快"这条硬约束冲突。本组件 ~300 行，CSS 只认 `.tsel-` 前缀。
 *
 * 交互设计（对应用户的四条要求）：
 *   ① **默认折叠**：面板打开时只渲染第一级节点，子级一个都不展开。
 *   ② **点父级 = 展开/收起**，不选中；**只有末级节点才能选中**。
 *      展开是"就地向下展开一层"，不是把整棵树摊平 —— 父级左侧的箭头会转向。
 *   ③ **搜索时自动展开匹配链路**：输入关键词后，命中的节点及其**所有祖先**都展开，
 *      保证命中项一定可见；同时只显示命中节点 + 它们的祖先（其余剪掉）。
 *   ④ **回显完整路径**：选中子节点后，输入框里显示「集团客户 / 华东分公司」，
 *      库里存的仍然是节点 id —— 显示与存储分离。
 *
 * 数据形状（`nodes`）：
 *   [{ id, name, children: [...] }, ...]
 *   允许 children 为 undefined / [] / null —— 都当叶子处理。
 *   默认取 id 用 `node.id`、文案用 `node.name`，两类档案都是这个形状；
 *   形状不同时用 getNodeValue / getNodeLabel / getNodeChildren 覆盖。
 *
 * ⚠️ 与 ErpSearchSelect 一致的三条硬规则（同一个爹踩出来的坑）：
 *   ① 触发器是 `div[role="combobox"]` 而非 <button> —— 常被塞进 <label> 里，
 *      <button> 会被 label 的"转发点击"触发两次开合。
 *   ② 选项用 `onMouseDown` 而非 `onClick` —— onClick 要等 mousedown→mouseup，
 *      期间输入框先失焦、面板可能已重算，选中会"点空"。
 *   ③ `required` 在这类组件上**完全失效**（不是可标注控件），
 *      必填校验必须在提交函数里自己做。
 */

import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import './erp-tree-select.css';

const VIEWPORT_MARGIN = 12;
const PANEL_MIN_WIDTH = 280;
const PANEL_MAX_HEIGHT = 340;

const normalize = (text) => String(text ?? '').toLowerCase().replace(/\s+/g, '');

const defaultGetValue = (node) => (node ? node.id : '');
const defaultGetLabel = (node) => (node ? node.name : '');
const defaultGetChildren = (node) => (node && Array.isArray(node.children) ? node.children : []);

/** 深度优先遍历，回调 (node, path[], depth)。path 含自身。 */
const walkTree = (nodes, getChildren, visit, path = []) => {
  for (const node of nodes || []) {
    const nextPath = [...path, node];
    visit(node, nextPath);
    const children = getChildren(node);
    if (children.length) walkTree(children, getChildren, visit, nextPath);
  }
};

/**
 * 搜索剪枝：返回 { visible, expand }（两个 Set<string>，元素是节点的路径 key）
 *   - 命中的节点 + 其全部祖先进入 visible（其余分支被剪掉，避免几百行噪声）
 *   - 祖先链全部进 expand，保证命中项一定可见，不用手点
 *
 * ⚠️ key 必须在这里自己算，不能依赖外面打的 `__key` —— 外面 `indexed` 是
 *    展开后的扁平副本，`nodes` 仍是原始对象，拿不到标记（踩过一次：
 *    搜索时 visible 永远为空 → 面板一片空白）。
 */
const buildSearchState = (nodes, keyword, getChildren, getLabel, getValue) => {
  const visible = new Set();
  const expand = new Set();
  const key = normalize(keyword);
  if (!key) return { visible, expand };

  const visit = (node, ancestors) => {
    const label = getLabel(node);
    const selfHit = normalize(label).includes(key);
    const myKey = `${ancestors.length ? ancestors[ancestors.length - 1].k : ''}/${getValue(node)}`;

    let childHit = false;
    const children = getChildren(node);
    const childAncestors = [...ancestors, { k: myKey, node }];
    for (const child of children) {
      if (visit(child, childAncestors)) childHit = true;
    }

    const hit = selfHit || childHit;
    if (hit) {
      // 自己与整条祖先链都要显示；祖先链全部展开
      ancestors.forEach((a) => {
        visible.add(a.k);
        expand.add(a.k);
      });
      visible.add(myKey);
      // 自己命中时也展开自己一层，让用户看到命中项的上下文
      if (selfHit && children.length) expand.add(myKey);
    }
    return hit;
  };

  nodes.forEach((node) => visit(node, []));
  return { visible, expand };
};

export default function ErpTreeSelect({
  nodes = [],
  value = '',
  onChange,
  placeholder = '请选择',
  emptyText = '没有匹配的节点',
  disabled = false,
  allowClear = true,
  clearLabel = '不选（置空）',
  getNodeValue = defaultGetValue,
  getNodeLabel = defaultGetLabel,
  getNodeChildren = defaultGetChildren,
  testId,
  dataAttr,
}) {
  const anchorRef = useRef(null);
  const panelRef = useRef(null);
  const [open, setOpen] = useState(false);
  const [keyword, setKeyword] = useState('');
  const [expanded, setExpanded] = useState(() => new Set());
  const [panelPos, setPanelPos] = useState({ top: 0, left: 0, width: PANEL_MIN_WIDTH });

  /* —— 搜索剪枝依赖原始 nodes 的路径 key，这里不再需要扁平副本 —— */

  /** value → 完整路径文案（选中回显用）。
   *  ⚠️ 兜底：value 在树里找不到时（历史自由文本类别，如手填的「陕送机具公司」
   *  在别人删掉该分类后就成了孤儿），回显 value 原文而不是空白 —— 空白会让用户
   *  以为没选过，一保存就把历史值清掉了。 */
  const selectedLabel = useMemo(() => {
    const target = String(value ?? '');
    if (!target) return '';
    let found = '';
    walkTree(nodes, getNodeChildren, (node, path) => {
      if (found) return;
      if (String(getNodeValue(node)) === target) {
        found = path.map(getNodeLabel).join(' / ');
      }
    });
    // 兜底：树里没有 → 显示原值（ getNodeLabel 可能 ≠ value，比如 value 是名称）
    return found || target;
  }, [nodes, value, getNodeValue, getNodeLabel, getNodeChildren]);

  /** 搜索态：剪枝集合 + 需要强制展开的祖先链 */
  const searchState = useMemo(
    () => buildSearchState(nodes, keyword, getNodeChildren, getNodeLabel, getNodeValue),
    [nodes, keyword, getNodeChildren, getNodeLabel, getNodeValue],
  );
  const searching = Boolean(normalize(keyword));

  /** 浮层定位 */
  const reposition = useCallback(() => {
    const el = anchorRef.current;
    if (!el) return;
    const rect = el.getBoundingClientRect();
    const width = Math.max(rect.width, PANEL_MIN_WIDTH);
    const spaceBelow = window.innerHeight - rect.bottom - VIEWPORT_MARGIN;
    const spaceAbove = rect.top - VIEWPORT_MARGIN;
    // 下面放不下就往上翻（跟 ErpSearchSelect 一致的手感）
    const openUp = spaceBelow < 200 && spaceAbove > spaceBelow;
    const maxH = Math.min(PANEL_MAX_HEIGHT, openUp ? spaceAbove : spaceBelow);
    setPanelPos({
      top: openUp ? Math.max(VIEWPORT_MARGIN, rect.top - maxH - 4) : rect.bottom + 4,
      left: Math.min(rect.left, window.innerWidth - width - VIEWPORT_MARGIN),
      width,
      maxHeight: Math.max(120, maxH),
    });
  }, []);

  useEffect(() => {
    if (!open) return undefined;
    reposition();
    const onScrollOrResize = () => reposition();
    window.addEventListener('scroll', onScrollOrResize, true);
    window.addEventListener('resize', onScrollOrResize);
    return () => {
      window.removeEventListener('scroll', onScrollOrResize, true);
      window.removeEventListener('resize', onScrollOrResize);
    };
  }, [open, reposition]);

  /** 点外面关闭。用 capture 阶段的 mousedown，避免被内层 stopPropagation 吃掉 */
  useEffect(() => {
    if (!open) return undefined;
    const onDown = (event) => {
      const anchor = anchorRef.current;
      const panel = panelRef.current;
      if (anchor && anchor.contains(event.target)) return;
      if (panel && panel.contains(event.target)) return;
      setOpen(false);
      setKeyword('');
    };
    window.addEventListener('mousedown', onDown, true);
    return () => window.removeEventListener('mousedown', onDown, true);
  }, [open]);

  const close = useCallback(() => {
    setOpen(false);
    setKeyword('');
  }, []);

  const toggleExpand = (key) => {
    setExpanded((prev) => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });
  };

  const pick = (node) => {
    onChange?.(String(getNodeValue(node)));
    close();
  };

  /** 面板里要渲染的「顶层行」：搜索态 = 命中集合里的无祖先可见者；常态 = 第一级 */
  const rows = useMemo(() => {
    const result = [];
    const visit = (list, depth, parentPath) => {
      for (const node of list) {
        const key = `${parentPath}/${getNodeValue(node)}`;
        const children = getNodeChildren(node);
        const isLeaf = children.length === 0;

        if (searching) {
          if (!searchState.visible.has(key)) continue;
        }

        // 常态下用 expanded 控制；搜索态一律展开（searchState.expand 已兜住祖先）
        const isExpanded = searching ? true : expanded.has(key);

        result.push({
          key,
          node,
          depth,
          isLeaf,
          isExpanded,
          label: getNodeLabel(node),
          childCount: children.length,
        });

        if (!isLeaf && isExpanded) visit(children, depth + 1, key);
      }
    };
    visit(nodes, 0, '');
    return result;
  }, [nodes, searching, searchState, expanded, getNodeValue, getNodeLabel, getNodeChildren]);

  const panel = open ? (
    <div
      ref={panelRef}
      className="tsel-panel"
      style={{ top: panelPos.top, left: panelPos.left, width: panelPos.width, maxHeight: panelPos.maxHeight }}
      role="tree"
      data-erp-tree-select-panel={testId || ''}
      /* 面板内的 mousedown 不要冒到 window 的关闭逻辑（虽然上面已判定 contains，
         这里再兜一下，避免 portal 在极端场景下事件目标对不上） */
      onMouseDown={(event) => event.stopPropagation()}
    >
      {/* 搜索框是面板的固定表头：不跟着列表滚，也不另开一个绝对定位层
          （踩过：两个绝对定位元素互相盖住，搜索框被面板压掉了） */}
      <div className="tsel-search-wrap">
        <input
          className="tsel-search"
          autoFocus
          value={keyword}
          placeholder="搜索分类名称…"
          data-tsel-search
          onChange={(event) => setKeyword(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === 'Escape') {
              event.stopPropagation();
              close();
            }
          }}
        />
      </div>

      <div className="tsel-list">
        {allowClear && (
          <div
            className={`tsel-row tsel-row--clear ${String(value ?? '') === '' ? 'is-on' : ''}`}
            onMouseDown={() => {
              onChange?.('');
              close();
            }}
          >
            <span className="tsel-row__label">{clearLabel}</span>
          </div>
        )}

        {rows.length === 0 ? (
          <div className="tsel-empty">{searching ? emptyText : '暂无分类'}</div>
        ) : (
          rows.map((row) => (
            <div
              key={row.key}
              className={`tsel-row ${row.isLeaf ? 'is-leaf' : 'is-branch'} ${
                String(value ?? '') === String(getNodeValue(row.node)) ? 'is-on' : ''
              }`}
              style={{ paddingLeft: 10 + row.depth * 18 }}
              role="treeitem"
              aria-expanded={row.isLeaf ? undefined : row.isExpanded}
              data-tsel-key={row.key}
              data-tsel-leaf={row.isLeaf ? '1' : '0'}
              /* 点父级 = 开合（不选中）；点末级 = 选中 */
              onMouseDown={(event) => {
                event.preventDefault();
                if (row.isLeaf) {
                  pick(row.node);
                  return;
                }
                toggleExpand(row.key);
              }}
            >
              <span
                className={`tsel-row__caret ${row.isLeaf ? 'is-hidden' : ''} ${row.isExpanded ? 'is-open' : ''}`}
                data-tsel-caret={row.key}
              >
                ▸
              </span>
              <span className="tsel-row__label">{row.label}</span>
              {!row.isLeaf && <span className="tsel-row__count">{row.childCount}</span>}
            </div>
          ))
        )}
      </div>
    </div>
  ) : null;

  return (
    <div className="tsel" data-erp-tree-select={testId || ''} data-erp-tree-select-field={dataAttr || ''}>
      <div
        ref={anchorRef}
        className={`tsel-trigger ${disabled ? 'is-disabled' : ''} ${open ? 'is-open' : ''}`}
        role="combobox"
        aria-expanded={open}
        aria-haspopup="tree"
        tabIndex={disabled ? -1 : 0}
        onClick={() => {
          if (disabled) return;
          setOpen((prev) => !prev);
          if (open) setKeyword('');
        }}
        onKeyDown={(event) => {
          if (disabled) return;
          if (event.key === 'Enter' || event.key === ' ') {
            // 在 <form> 里 Enter 默认会提交，必须拦
            event.preventDefault();
            setOpen((prev) => !prev);
          }
          if (event.key === 'Escape') {
            event.stopPropagation();
            close();
          }
        }}
      >
        <span className={`tsel-trigger__text ${selectedLabel ? '' : 'is-placeholder'}`}>
          {selectedLabel || placeholder}
        </span>
        {allowClear && String(value ?? '') !== '' && (
          <span
            className="tsel-trigger__clear"
            title="清除"
            onMouseDown={(event) => {
              event.preventDefault();
              event.stopPropagation();
              onChange?.('');
            }}
          >
            ×
          </span>
        )}
        <span className="tsel-trigger__caret">▾</span>
      </div>

      {open && createPortal(panel, document.body)}
    </div>
  );
}
