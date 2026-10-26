/**
 * ErpForm —— 表单栅格 / 表单行 / 操作条（零依赖）
 *
 * 抽离动机：改造前同一个商品弹窗里有**两套完全不同的表单 DOM** ——
 *   新增态：`.erp-form` > `.form-row.two-col` > `<label>标题<input/></label>`
 *   编辑态：`.invoice-edit-form` > 平铺 `<label><span>标题</span><input/></label>`
 * 同一批字段写了两遍，于是长期不同步（编辑态一度漏了图片字段）。
 * 这里把它们统一成「网格 + 行」两层，字段只声明一次。
 *
 * 用法：
 *
 *   <ErpFormGrid columns={2}>
 *     <ErpFormRow label="产品编号（SKU）" required>
 *       <input value={…} onChange={…} required />
 *     </ErpFormRow>
 *     <ErpFormRow label="备注" span={2}>
 *       <input … />
 *     </ErpFormRow>
 *   </ErpFormGrid>
 *
 * 为什么不把 input 也封装成 `<ErpInput />`：
 * 控件形态太多（text / number / date / ErpSearchSelect / 只读镜像 / 自定义复合控件），
 * 一封就得到处开 `mode`/`as` 后门。这里只锁「排布」这一层，
 * 控件由调用方传进来 —— 但外的观感（40px 高、圆角、聚焦环、只读态）由
 * `.erp-form-grid` 统一接管，页面里**不需要**再给每个 input 写类名。
 */

import './erp-form.css';

const SPAN_CLASS = {
  1: '',
  2: 'erp-form-row--span-2',
  3: 'erp-form-row--span-3',
  4: 'erp-form-row--span-4',
  full: 'erp-form-row--span-full',
};

/** 表单栅格容器：一律 Grid，列数由 columns 决定，窄屏自动落回单列 */
export function ErpFormGrid({
  columns = 2,
  gap = 'md',
  className = '',
  children,
  ...rest
}) {
  return (
    <div
      className={`erp-form-grid erp-form-grid--gap-${gap} erp-form-grid--cols-${columns}${
        className ? ` ${className}` : ''
      }`}
      {...rest}
    >
      {children}
    </div>
  );
}

/**
 * 单个表单项。
 *
 * @param {string}  label     标题
 * @param {boolean} required  只控制「标题后的红星」；真正的 required 属性请写在控件上
 *                            （原生校验比 JS 拦截更早、也更无障碍）
 * @param {number|'full'} span 跨几列；默认 1
 * @param {string}  hint      标题下方的辅助说明
 * @param {string}  error     错误文案（有值即变红，优先级高于 hint）
 * @param {string}  suffix    控件右侧的单位后缀，如「天」「%」
 * @param {boolean} inline    标题与控件同一行（窄弹窗里省纵向空间）
 * @param {'label'|'div'} as  容器标签。默认 `label`，点标题即可聚焦控件；
 *                            **但包含复杂控件的行必须传 `div`** ——
 *                            比如内部有 `<input type="file">` 的图片上传区，
 *                            被 `label` 包住后点任何位置都会弹出文件选择框（实测）。
 */
export function ErpFormRow({
  as: Tag = 'label',
  label,
  required = false,
  span = 1,
  hint = '',
  error = '',
  suffix = '',
  inline = false,
  className = '',
  children,
  ...rest
}) {
  const spanClass = SPAN_CLASS[span] || '';
  const rowClass = [
    'erp-form-row',
    spanClass,
    inline ? 'erp-form-row--inline' : '',
    error ? 'erp-form-row--invalid' : '',
    className,
  ]
    .filter(Boolean)
    .join(' ');

  return (
    <Tag className={rowClass} {...rest}>
      {label && (
        <span className="erp-form-row__label">
          {label}
          {required && (
            <span className="erp-form-row__req" aria-hidden="true">
              *
            </span>
          )}
        </span>
      )}

      <span className="erp-form-row__control">
        {children}
        {suffix && <span className="erp-form-row__suffix">{suffix}</span>}
      </span>

      {error ? (
        <span className="erp-form-row__error" role="alert">
          {error}
        </span>
      ) : (
        hint && <span className="erp-form-row__hint">{hint}</span>
      )}
    </Tag>
  );
}

/** 表单底部按钮条 */
export function ErpFormActions({ align = 'right', className = '', children }) {
  return (
    <div className={`erp-form-actions erp-form-actions--${align}${className ? ` ${className}` : ''}`}>
      {children}
    </div>
  );
}

export default ErpFormGrid;
