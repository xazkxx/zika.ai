/**
 * EmptyState —— 通用空状态（轻量 SVG 插画 + 说明 + 行动按钮）
 *
 * 替换全站那句"暂无数据"。空状态是用户最容易"卡住"的地方：
 * 光说"没有数据"，用户不知道是自己筛错了、还是真的没有、还是没权限。
 * 所以这里强制三件套：**一张图说是什么情况、一句话说为什么、一个按钮给出路**。
 *
 * 插画全部是手写 SVG（viewBox 160×120），单套 < 1KB，无外部资源、无图标库。
 * 走 currentColor + 两个语义变量，所以换主题色只需改 CSS。
 *
 * 用法：
 *   <EmptyState />                                            // 默认「暂无数据」
 *   <EmptyState variant="search" title="没有找到匹配的商品"
 *               description="换个关键词试试" action={{ label: '清空筛选', onClick }} />
 *   <EmptyState variant="error" size="sm" compact />           // 嵌在表格里
 */

import './empty-state.css';

const ART = {
  /** 真空：什么数据都还没有 */
  data: (
    <g>
      <ellipse cx="80" cy="101" rx="44" ry="7" fill="var(--empty-ink-soft)" />
      <path
        d="M38 52 L80 40 L122 52 L122 87 L80 100 L38 87 Z"
        fill="#fff"
        stroke="currentColor"
        strokeWidth="2"
        strokeLinejoin="round"
      />
      <path d="M38 52 L80 64 L122 52" stroke="currentColor" strokeWidth="2" strokeLinejoin="round" />
      <path d="M80 64 L80 100" stroke="currentColor" strokeWidth="2" />
      <path d="M62 77 h8 M90 77 h8" stroke="var(--empty-accent)" strokeWidth="3" strokeLinecap="round" />
    </g>
  ),

  /** 搜索无结果 */
  search: (
    <g>
      <ellipse cx="80" cy="105" rx="34" ry="5" fill="var(--empty-ink-soft)" />
      <circle cx="72" cy="56" r="26" fill="#fff" stroke="currentColor" strokeWidth="2.5" />
      <path d="M91 75 L110 94" stroke="currentColor" strokeWidth="5" strokeLinecap="round" />
      <path d="M60 50 h24 M60 61 h14" stroke="var(--empty-accent)" strokeWidth="3" strokeLinecap="round" />
    </g>
  ),

  /** 筛选条件太窄 */
  filter: (
    <g>
      <ellipse cx="80" cy="106" rx="30" ry="5" fill="var(--empty-ink-soft)" />
      <path
        d="M46 42 h68 l-24 30 v22 l-20 8 V72 Z"
        fill="#fff"
        stroke="currentColor"
        strokeWidth="2.5"
        strokeLinejoin="round"
      />
      <path d="M58 55 h44" stroke="var(--empty-accent)" strokeWidth="3" strokeLinecap="round" />
    </g>
  ),

  /** 加载失败 */
  error: (
    <g>
      <path d="M40 96 h80" stroke="var(--empty-ink-soft)" strokeWidth="4" strokeLinecap="round" />
      <circle cx="80" cy="58" r="28" fill="#fff" stroke="currentColor" strokeWidth="2.5" />
      <path d="M80 44 v18" stroke="var(--color-danger)" strokeWidth="4" strokeLinecap="round" />
      <circle cx="80" cy="72" r="2.8" fill="var(--color-danger)" />
    </g>
  ),

  /** 无权限 */
  permission: (
    <g>
      <ellipse cx="80" cy="102" rx="30" ry="5" fill="var(--empty-ink-soft)" />
      <rect
        x="56"
        y="57"
        width="48"
        height="39"
        rx="9"
        fill="#fff"
        stroke="currentColor"
        strokeWidth="2.5"
      />
      <path
        d="M67 57 v-8 a13 13 0 0 1 26 0 v8"
        stroke="currentColor"
        strokeWidth="2.5"
        strokeLinecap="round"
      />
      <circle cx="80" cy="74" r="4" fill="var(--empty-accent)" />
      <path d="M80 78 v7" stroke="var(--empty-accent)" strokeWidth="3" strokeLinecap="round" />
    </g>
  ),
};

const DEFAULT_TEXT = {
  data: { title: '还没有数据', description: '新增第一条记录后，这里会显示列表' },
  search: { title: '没有找到匹配的结果', description: '换个关键词，或清空筛选条件再试一次' },
  filter: { title: '当前筛选条件下没有数据', description: '放宽筛选范围，可能会看到更多结果' },
  error: { title: '数据加载失败', description: '可能是网络或服务暂时不可用，请稍后重试' },
  permission: { title: '没有查看权限', description: '请联系管理员为你开通该模块的访问权限' },
};

/** 动作既可以传 { label, onClick }，也可以直接传一个已经写好的按钮节点 */
function renderAction(action, tone) {
  if (!action) return null;
  if (typeof action === 'object' && action.label !== undefined) {
    const { label, onClick, href, disabled = false } = action;
    if (href) {
      return (
        <a className={`erp-empty__btn erp-empty__btn--${tone}`} href={href} onClick={onClick}>
          {label}
        </a>
      );
    }
    return (
      <button
        type="button"
        className={`erp-empty__btn erp-empty__btn--${tone}`}
        onClick={onClick}
        disabled={disabled}
      >
        {label}
      </button>
    );
  }
  return action;
}

export default function EmptyState({
  variant = 'data',
  title,
  description,
  action = null,
  secondaryAction = null,
  size = 'md',
  compact = false,
  illustration = true,
  className = '',
  children = null,
}) {
  const key = ART[variant] ? variant : 'data';
  const fallback = DEFAULT_TEXT[key];
  const sizeClass = `erp-empty--${size}`;

  return (
    <div
      className={[
        'erp-empty',
        sizeClass,
        compact ? 'erp-empty--compact' : '',
        className,
      ]
        .filter(Boolean)
        .join(' ')}
    >
      {illustration && (
        <svg
          className="erp-empty__art"
          viewBox="0 0 160 120"
          fill="none"
          role="img"
          aria-hidden="true"
          focusable="false"
        >
          {ART[key]}
        </svg>
      )}
      <p className="erp-empty__title">{title || fallback.title}</p>
      {(description || fallback.description) && (
        <p className="erp-empty__desc">{description || fallback.description}</p>
      )}
      {(action || secondaryAction) && (
        <div className="erp-empty__actions">
          {renderAction(action, 'primary')}
          {renderAction(secondaryAction, 'ghost')}
        </div>
      )}
      {children}
    </div>
  );
}
