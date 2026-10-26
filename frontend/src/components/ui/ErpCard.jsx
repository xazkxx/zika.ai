/**
 * ErpCard —— 全站统一卡片容器（零依赖，纯 CSS 变量驱动）
 *
 * 为什么要有它：改造前 `.panel` / `.stat-card` / 各页手写的 `<section class="panel">`
 * 一共 31 个页面各写各的，标题字号、内边距、边框轻重全靠人记。这里把
 * 「标题 + 副标题 + 右侧操作 + 内容区」这套结构固化下来，页面只描述内容。
 *
 * 设计上的五个决定：
 *
 * ① **不再继承 `.panel`**。加了 panel 类就会被 `styles.css` 里的
 *    `.panel h2` / `.panel.form-panel:has(> [data-doc-form]) > .section-header`
 *    这些既有规则命中，等于换个方式继续打补丁。这里用全新的 `.erp-card` 命名空间，
 *    与现有样式零交叉 —— 所以它放在哪些页面都不需要动 styles.css。
 *
 * ② **不带 margin**。改造前 `.panel` 自带 `margin-top: 30px`，两个面板并排时会
 *    上下错位，还得靠 `:first-child` 之类的规则擦屁股。卡片的间距归父级 grid 的
 *    `gap` 管，组件自己只负责“我多大、里面怎么排”。
 *
 * ③ **loading / empty 内置**。这是抽离的真正价值：以前每个页面都要写
 *    `{loading ? '加载中...' : rows.length === 0 ? '暂无数据' : <table/>}`，
 *    现在由卡片统一接管，一处改完全站生效。
 *
 * ④ **body 可以 flush**（`padding="none"` 或 `flush`）。表格必须贴边才好看，
 *    否则要么表格自己加负 margin，要么卡片内外两套留白打架。
 *    `flush` 与 `padding` 的区别：`padding="none"` 连头部一起去掉内边距（整块贴边），
 *    `flush` 只让 **body** 归零、**头部保留内边距** —— 这是"带标题栏的表格卡"的形态。
 *
 * ⑤ **hoverable 只动 transform + box-shadow**，不用 `transition: all`。
 *    `all` 会把 padding / width 也拿去做动画，拖拽改列宽时会明显掉帧。
 *
 * 用法：
 *
 *   <ErpCard title="商品列表" subtitle="共 261 个商品" extra={<button>新增</button>}>
 *     <ErpTable … />
 *   </ErpCard>
 *
 *   <ErpCard loading skeletonRows={5} />                 // 加载中
 *   <ErpCard isEmpty emptyProps={{ variant: 'search', title: '没有匹配的商品' }} />
 */

import Skeleton from './Skeleton.jsx';
import EmptyState from './EmptyState.jsx';
import './erp-card.css';

const PADDING_CLASS = {
  none: 'erp-card--pad-none',
  sm: 'erp-card--pad-sm',
  md: 'erp-card--pad-md',
  lg: 'erp-card--pad-lg',
};

export default function ErpCard({
  as: Tag = 'section',
  title,
  subtitle,
  extra,
  icon = null,
  titleAs: TitleTag = 'h3',
  padding = 'md',
  hoverable = false,
  glass = false,
  divider = false,
  flush = false,
  loading = false,
  skeletonRows = 3,
  isEmpty = false,
  emptyProps = null,
  className = '',
  bodyClassName = '',
  children = null,
  ...rest
}) {
  const hasHead = Boolean(title || subtitle || extra || icon);

  const cardClass = [
    'erp-card',
    PADDING_CLASS[padding] || PADDING_CLASS.md,
    hoverable ? 'erp-card--hover' : '',
    glass ? 'erp-card--glass' : '',
    divider && hasHead ? 'erp-card--divider' : '',
    flush ? 'erp-card--flush' : '',
    loading ? 'erp-card--loading' : '',
    className,
  ]
    .filter(Boolean)
    .join(' ');

  let body = children;

  if (loading) {
    // 骨架屏的行数跟着卡片走：表格卡给得多，表单卡给得少
    body = <Skeleton variant="text" lines={skeletonRows} />;
  } else if (isEmpty) {
    body = <EmptyState {...(emptyProps || {})} />;
  }

  return (
    <Tag className={cardClass} {...rest}>
      {hasHead && (
        <header className="erp-card__head">
          <div className="erp-card__heading">
            {icon && (
              <span className="erp-card__icon" aria-hidden="true">
                {icon}
              </span>
            )}
            <div className="erp-card__titles">
              {title && <TitleTag className="erp-card__title">{title}</TitleTag>}
              {subtitle && <p className="erp-card__subtitle">{subtitle}</p>}
            </div>
          </div>
          {extra && <div className="erp-card__extra">{extra}</div>}
        </header>
      )}
      <div className={`erp-card__body${bodyClassName ? ` ${bodyClassName}` : ''}`}>{body}</div>
    </Tag>
  );
}
