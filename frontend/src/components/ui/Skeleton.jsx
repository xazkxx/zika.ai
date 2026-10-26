/**
 * Skeleton —— 带渐变扫光的骨架屏（零依赖）
 *
 * 替换掉全站那句"加载中..."。三种角色：
 *   · 占位：数据还没回来时，先把版式撑出来，内容到了不跳版
 *   · 感知：扫光动画让人知道"在动"，比静止灰块的心理等待更短
 *   · 质感：可选液态玻璃底（backdrop-filter: blur(8px)）
 *
 * 变体：
 *   text    多行文字（最后一行自然收短，像真段落）
 *   title   一行标题
 *   avatar  圆形头像
 *   block   任意尺寸的块
 *   table   表头 + N 行 × M 列
 *   card    卡片外形（头部两块 + 若干内容行）
 *
 * 用法：
 *   <Skeleton />                                  // 3 行文字
 *   <Skeleton variant="table" rows={6} columns={5} />
 *   <Skeleton glass />                            // 液态玻璃底
 *
 * ⚠️ 玻璃效果只作用在**容器**上：backdrop-filter 模糊的是"元素背后的内容"，
 *    加在内层小方块上什么也看不到。
 */

const SKEL = 'erp-skel';

export default function Skeleton({
  variant = 'text',
  lines = 3,
  rows = 5,
  columns = 4,
  width,
  height,
  radius,
  size = 40,
  animated = true,
  glass = false,
  className = '',
  style,
}) {
  const rootClass = [
    'erp-skel-root',
    glass ? 'erp-skel-glass' : '',
    animated ? '' : 'erp-skel--static',
    className,
  ]
    .filter(Boolean)
    .join(' ');

  // 单块骨架的通用盒子：宽高/圆角可以直接覆盖
  const box = (extra = {}) => (
    <span className={SKEL} style={{ width, height, borderRadius: radius, ...extra }} />
  );

  let content;

  if (variant === 'title') {
    content = (
      <div className="erp-skel-group">
        {box({ width: width || '38%', height: height || '18px' })}
      </div>
    );
  } else if (variant === 'avatar') {
    content = (
      <div className="erp-skel-group">
        {box({ width: `${size}px`, height: `${size}px`, borderRadius: '50%' })}
      </div>
    );
  } else if (variant === 'block') {
    content = (
      <div className="erp-skel-group">{box({ width: '100%', height: height || '120px' })}</div>
    );
  } else if (variant === 'table') {
    const cols = Math.max(1, columns);
    const bodyRows = Math.max(1, rows);
    content = (
      <div className="erp-skel-table" style={{ '--skel-cols': cols }}>
        <div className="erp-skel-table__row erp-skel-table__row--head">
          {Array.from({ length: cols }).map((_, i) => (
            <span key={`h${i}`} className={SKEL} style={{ height: '12px' }} />
          ))}
        </div>
        {Array.from({ length: bodyRows }).map((_, r) => (
          <div className="erp-skel-table__row" key={`r${r}`}>
            {Array.from({ length: cols }).map((_, c) => (
              <span
                key={`c${c}`}
                className={SKEL}
                /* 每列错开一点宽度，比"整整齐齐的灰条"更像真数据 */
                style={{ height: '14px', width: c === 0 ? '72%' : `${52 + ((r + c) % 4) * 10}%` }}
              />
            ))}
          </div>
        ))}
      </div>
    );
  } else if (variant === 'card') {
    content = (
      <div className="erp-skel-card">
        <div className="erp-skel-card__head">
          <span className={SKEL} style={{ width: '44%', height: '16px' }} />
          <span className={SKEL} style={{ width: '64px', height: '28px' }} />
        </div>
        <div className="erp-skel-card__body">
          {Array.from({ length: Math.max(1, lines) }).map((_, i) => (
            <span
              key={i}
              className={SKEL}
              style={{ height: '12px', width: i === lines - 1 ? '58%' : '100%' }}
            />
          ))}
        </div>
      </div>
    );
  } else {
    // text（默认）
    const count = Math.max(1, lines);
    content = (
      <div className="erp-skel-group">
        {Array.from({ length: count }).map((_, i) => (
          <span
            key={i}
            className={SKEL}
            style={{
              height: height || '13px',
              /* 最后一行收短，是"像真文字"的关键；单行时不收，否则像断句 */
              width: count > 1 && i === count - 1 ? '62%' : width || '100%',
              borderRadius: radius,
            }}
          />
        ))}
      </div>
    );
  }

  return (
    <div className={rootClass} style={style} role="status" aria-busy="true" aria-live="polite">
      {content}
      <span className="erp-sr-only">加载中</span>
    </div>
  );
}
