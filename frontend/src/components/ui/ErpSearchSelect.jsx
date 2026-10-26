/**
 * ErpSearchSelect —— 轻量可搜索下拉（零依赖、纯 JS、无 UI 库）
 *
 * 为什么自己写：
 *   原生 <select> 在 260+ 个商品时基本不可用（要一路滚），而 Ant Design 的
 *   Select 会带进 ~120KB 的 gzip，跟"首屏极快"这条硬约束直接冲突。
 *   这个组件只有 ~200 行、CSS 只认 `.ssel-` 前缀，全部逻辑是本地 filter ——
 *   **一次请求都不发**，输入每个字符只做一次数组遍历（260 项量级可忽略）。
 *
 * 设计要点（都是踩过的坑）：
 *   ① **触发器不是 <button>，而是 `role="combobox"` 的 div**。
 *      组件常被塞进 <label> 里（商品弹窗、明细行都是），而 <label> 的默认行为
 *      会把点击转发给"第一个可标注控件"。用 button 时点一下可能触发两次开合。
 *      div 不是可标注控件，天然没有这个问题。
 *   ② **选项用 onMouseDown 而不是 onClick**：onClick 要等 mousedown→mouseup，
 *      期间输入框先失焦、面板状态可能已被重算，选中会"点空"。
 *   ③ **Enter 必须 preventDefault**：这些组件都在 <form> 里，不拦截就直接提交单据。
 *   ④ 默认取值/文案函数覆盖两类数据：商品（id/name/sku/mnemonic）与
 *      供应商（id/name/code/short_name），调用处不写配置也能用。
 *   ⑤ **`allowFreeText`：允许"库里没有的文本"直接落库**（默认关）。
 *      因为「生产厂家」≠「供应商」—— 现有 72 条商品填的是大疆、华诺迈、
 *      西安寨卡这类真实厂家，一个都匹配不上 suppliers。若下拉强制只能选供应商，
 *      用户就再也录不进「大疆」了（历史值虽在，但一编辑就被替换掉）。
 *      开启后：搜索词没有任何同名命中时，末尾多一条「使用「xxx」」，
 *      选中回传 `('', { name })` —— id 空、文本保留，与老数据同构。
 *
 * 用法：
 *   <ErpSearchSelect
 *     options={products}
 *     value={String(row.product_id ?? '')}
 *     onChange={(nextId) => handleItemChange(index, 'product_id')(nextId)}
 *     placeholder="搜索商品名称 / SKU / 助记码"
 *   />
 *
 * ⚠️ 两条替换原生 <select> 时必须遵守的硬规则：
 *
 *   ① **`required` 会失效**。触发器是 `div[role="combobox"]`（见 ①），不是可标注控件，
 *      HTML5 表单校验完全拦不到它。凡是原来靠 `required` 拦的字段，必须在提交函数里
 *      自己补守卫 —— 否则 `Number('') === 0` 会把脏值当合法 id 发给后端。
 *      先例：`App.jsx` 的 `makeSubmitOrder`（注释「往来对象必选…」）。
 *
 *   ② **值必须锁成字符串**。原生 select 的 `event.target.value` 恒为字符串，本组件的
 *      `getOptionValue` 默认返回 `item.id`（数字）。替换时一律显式写
 *      `getOptionValue={(item) => String(item.id)}`，否则 `row.product_id === ''`
 *      这类判空会失效、"半填空行"识别会漂。
 */

import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import './erp-search-select.css';

const normalize = (text) => String(text ?? '').toLowerCase().replace(/\s+/g, '');

/** 浮层定位参数：面板比触发器宽才好读；但绝不超出视口 */
const PANEL_MIN_WIDTH = 360;
const PANEL_MAX_HEIGHT = 320;
const VIEWPORT_MARGIN = 12;

const defaultGetValue = (item) => (item ? item.id : '');
const defaultGetLabel = (item) => (item ? item.name : '');
/** 右侧灰色小字：商品显示「SKU · 助记码」，供应商显示「编码 · 简称」。 */
const defaultGetMeta = (item) => {
  if (!item) return '';
  return [item.sku || item.code, item.mnemonic || item.short_name].filter(Boolean).join(' · ');
};
/** 参与模糊匹配的全部字段（名称 / SKU / 编码 / 助记码 / 简称 / 条码）。 */
const defaultGetSearchText = (item) => {
  if (!item) return '';
  return [item.name, item.sku, item.code, item.mnemonic, item.short_name, item.bar_code]
    .filter(Boolean)
    .join(' ');
};

export default function ErpSearchSelect({
  options = [],
  value = '',
  /** 没有匹配到选项时的回退显示（老数据只有文本、没有 id 时用） */
  displayValue = '',
  onChange,
  placeholder = '搜索…',
  disabled = false,
  allowClear = true,
  maxResults = 50,
  emptyText = '没有匹配项',
  /** 允许把"库里没有的文本"当值（见文件头 ⑤） */
  allowFreeText = false,
  freeTextPrefix = '使用',
  getOptionValue = defaultGetValue,
  getOptionLabel = defaultGetLabel,
  getOptionMeta = defaultGetMeta,
  getSearchText = defaultGetSearchText,
  className = '',
  ...rest
}) {
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState('');
  const [activeIndex, setActiveIndex] = useState(0);
  /** 浮层几何：挂到 body 后必须自己算位置（见文件头 ⑥） */
  const [rect, setRect] = useState(null);

  const rootRef = useRef(null);
  const inputRef = useRef(null);
  const listRef = useRef(null);
  const panelRef = useRef(null);

  const list = Array.isArray(options) ? options : [];
  const currentKey = String(value ?? '');

  const selected = useMemo(
    () => list.find((item) => String(getOptionValue(item)) === currentKey && currentKey !== '') || null,
    [list, currentKey, getOptionValue],
  );

  // 过滤只在本地的 list 上跑；上限 maxResults 同时限住渲染量
  const filtered = useMemo(() => {
    const keyword = normalize(query);
    const picked = keyword
      ? list.filter((item) => normalize(getSearchText(item)).includes(keyword))
      : list;
    return picked.slice(0, maxResults);
  }, [list, query, maxResults, getSearchText]);

  // 自由文本兜底：搜索词非空、且**没有任何选项的名字与它完全一致**时才出现。
  // 判"完全一致"而不是"有没有匹配项" —— 搜「大疆」若已匹配到「大疆创新科技」，
  // 用户很可能想要的是那一项，但也不能剥夺他坚持写「大疆」的权利；
  // 所以两条都给出来，位置在最后（前面的真实档案更好按）。
  const trimmedQuery = query.trim();
  const freeText = Boolean(allowFreeText)
    && trimmedQuery !== ''
    && !list.some((item) => normalize(getOptionLabel(item)) === normalize(trimmedQuery));
  const total = filtered.length + (freeText ? 1 : 0);

  // 打开时重置搜索词与高亮，并把焦点交给输入框
  useEffect(() => {
    if (!open) return;
    setQuery('');
    setActiveIndex(0);
    const timer = setTimeout(() => {
      if (inputRef.current) inputRef.current.focus();
    }, 0);
    return () => clearTimeout(timer);
  }, [open]);

  // 点外面关闭（面板挂在 body，必须连同 panelRef 一起判）
  useEffect(() => {
    if (!open) return undefined;
    const onDocumentDown = (event) => {
      const inRoot = rootRef.current && rootRef.current.contains(event.target);
      const inPanel = panelRef.current && panelRef.current.contains(event.target);
      if (!inRoot && !inPanel) setOpen(false);
    };
    document.addEventListener('mousedown', onDocumentDown);
    return () => document.removeEventListener('mousedown', onDocumentDown);
  }, [open]);

  // 键盘上下移动时把高亮项滚进可视区
  useEffect(() => {
    if (!open || !listRef.current) return;
    const node = listRef.current.querySelector(`[data-index="${activeIndex}"]`);
    if (node && typeof node.scrollIntoView === 'function') {
      node.scrollIntoView({ block: 'nearest' });
    }
  }, [open, activeIndex]);

  /**
   * ⑥ **面板用 Portal 挂到 body，`position: fixed` 定位**。
   *    明细行表格的容器全是 `overflow: auto/hidden`（.erp-table-wrap、.erp-card），
   *    绝对定位的面板会被裁成一条缝（实测 260px 高只剩 53px 可见），
   *    还会把滚动容器撑出横向滚动条。挂 body 后两个问题一起消失。
   *    代价是三件事必须自己做：
   *      a) 位置从触发器的 getBoundingClientRect 算，下方放不下就向上翻；
   *      b) 宽度取 max(触发器, 300) 并夹进视口，长商品名只出省略号不出横向滚动条；
   *      c) 「点外面关闭」的判断要把面板也算进去（面板已不在 rootRef 里）。
   *    z-index 必须压过弹窗（--z-modal: 1000）—— 商品弹窗、多单位弹窗里也用它。
   */
  const computeRect = useCallback(() => {
    const el = rootRef.current;
    if (!el) return;
    const box = el.getBoundingClientRect();
    if (box.width === 0 && box.height === 0) return; // 还没布局出来
    const vw = window.innerWidth;
    const vh = window.innerHeight;
    const width = Math.min(Math.max(Math.round(box.width), PANEL_MIN_WIDTH), vw - VIEWPORT_MARGIN * 2);
    const left = Math.min(Math.max(VIEWPORT_MARGIN, Math.round(box.left)), vw - width - VIEWPORT_MARGIN);
    const spaceBelow = Math.round(vh - box.bottom - VIEWPORT_MARGIN);
    const spaceAbove = Math.round(box.top - VIEWPORT_MARGIN);
    // 下方放得下就朝下；放不下且上方更宽裕才朝上翻
    const openUp = spaceBelow < 180 && spaceAbove > spaceBelow;
    const maxH = Math.max(140, Math.min(PANEL_MAX_HEIGHT, openUp ? spaceAbove - 8 : spaceBelow - 8));
    setRect({
      left,
      width,
      maxH,
      top: openUp ? undefined : Math.round(box.bottom + 4),
      bottom: openUp ? Math.round(vh - box.top + 4) : undefined,
    });
  }, []);

  // 打开时先算一次位置；之后监听滚动/缩放跟进（capture 才能吃到表格容器自己的滚动）
  useEffect(() => {
    if (!open) return undefined;
    computeRect();
    const onMove = () => computeRect();
    window.addEventListener('resize', onMove);
    window.addEventListener('scroll', onMove, true);
    return () => {
      window.removeEventListener('resize', onMove);
      window.removeEventListener('scroll', onMove, true);
    };
  }, [open, computeRect]);

  const commit = useCallback(
    (item) => {
      if (!item) return;
      setOpen(false);
      if (onChange) onChange(getOptionValue(item), item);
    },
    [onChange, getOptionValue],
  );

  /** 自由文本："id 留空、文本留下"，与老数据同构 */
  const commitFree = useCallback(() => {
    const text = query.trim();
    if (!text) return;
    setOpen(false);
    if (onChange) onChange('', { name: text, freeText: true });
  }, [onChange, query]);

  /** 回车 / 点击都走这里，统一按下标分发 */
  const commitAt = (index) => {
    if (index < filtered.length) commit(filtered[index]);
    else if (freeText) commitFree();
  };

  const handleKeyDown = (event) => {
    if (event.key === 'ArrowDown') {
      event.preventDefault();
      setActiveIndex((prev) => (total === 0 ? 0 : (prev + 1) % total));
      return;
    }
    if (event.key === 'ArrowUp') {
      event.preventDefault();
      setActiveIndex((prev) => (total === 0 ? 0 : (prev - 1 + total) % total));
      return;
    }
    if (event.key === 'Enter') {
      // ⚠️ 不拦截就直接提交表单了 —— 明细行全在 <form> 里
      event.preventDefault();
      commitAt(activeIndex);
      return;
    }
    if (event.key === 'Escape') {
      event.preventDefault();
      setOpen(false);
      return;
    }
    if (event.key === 'Tab') {
      setOpen(false);
    }
  };

  const openPanel = () => {
    if (disabled) return;
    setOpen(true);
  };

  const triggerLabel = selected ? getOptionLabel(selected) : displayValue;
  const hasValue = Boolean(selected) || Boolean(displayValue);

  const handleClear = (event) => {
    event.stopPropagation();
    event.preventDefault();
    if (onChange) onChange('', null);
  };

  return (
    <div
      className={`ssel${className ? ` ${className}` : ''}`}
      ref={rootRef}
      data-open={open ? 'true' : undefined}
      data-disabled={disabled ? 'true' : undefined}
      {...rest}
    >
      {open ? (
        <input
          ref={inputRef}
          className="ssel-input"
          value={query}
          onChange={(event) => {
            setQuery(event.target.value);
            setActiveIndex(0);
          }}
          onKeyDown={handleKeyDown}
          placeholder={placeholder}
          autoComplete="off"
          spellCheck={false}
        />
      ) : (
        <div
          className={`ssel-trigger${hasValue ? '' : ' is-placeholder'}`}
          role="combobox"
          aria-expanded={false}
          aria-haspopup="listbox"
          tabIndex={disabled ? -1 : 0}
          onClick={openPanel}
          onKeyDown={(event) => {
            if (event.key === 'Enter' || event.key === ' ') {
              event.preventDefault();
              openPanel();
            }
          }}
        >
          <span className="ssel-value">{triggerLabel || placeholder}</span>
          {allowClear && hasValue ? (
            <span
              className="ssel-clear"
              role="button"
              aria-label="清除"
              tabIndex={-1}
              onMouseDown={(event) => event.preventDefault()}
              onClick={handleClear}
            >
              ×
            </span>
          ) : (
            <span className="ssel-caret" aria-hidden="true">▾</span>
          )}
        </div>
      )}

      {open && rect && createPortal(
        <div
          className="ssel-panel"
          role="listbox"
          ref={(node) => {
            panelRef.current = node;
            listRef.current = node;
          }}
          style={{
            position: 'fixed',
            left: rect.left,
            width: rect.width,
            maxHeight: rect.maxH,
            ...(rect.top !== undefined ? { top: rect.top } : { bottom: rect.bottom }),
          }}
        >
          {filtered.length === 0 && !freeText ? (
            <div className="ssel-empty">{emptyText}</div>
          ) : (
            <>
              {filtered.map((item, index) => {
                const optionValue = getOptionValue(item);
                const meta = getOptionMeta(item);
                const isSelected = String(optionValue) === currentKey;
                return (
                  <div
                    key={`${optionValue}-${index}`}
                    data-index={index}
                    role="option"
                    aria-selected={isSelected}
                    className={`ssel-option${index === activeIndex ? ' is-active' : ''}${isSelected ? ' is-selected' : ''}`}
                    onMouseEnter={() => setActiveIndex(index)}
                    onMouseDown={(event) => {
                      // 用 mousedown 抢在 blur 之前，避免"点了但没选上"
                      event.preventDefault();
                      commit(item);
                    }}
                  >
                    <span className="ssel-option-label">{getOptionLabel(item)}</span>
                    {meta ? <span className="ssel-option-meta">{meta}</span> : null}
                  </div>
                );
              })}
              {freeText ? (
                <div
                  data-index={filtered.length}
                  role="option"
                  aria-selected={false}
                  className={`ssel-option is-free${filtered.length === activeIndex ? ' is-active' : ''}`}
                  onMouseEnter={() => setActiveIndex(filtered.length)}
                  onMouseDown={(event) => {
                    event.preventDefault();
                    commitFree();
                  }}
                >
                  <span className="ssel-option-label">{freeTextPrefix}「{trimmedQuery}」</span>
                  <span className="ssel-option-meta">不在档案里</span>
                </div>
              ) : null}
            </>
          )}
        </div>,
        document.body,
      )}
    </div>
  );
}
