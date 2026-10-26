/**
 * ProductEditModal —— 商品「新增 / 编辑」弹窗（从 App.jsx 内联 JSX 抽离）
 *
 * ## 为什么要抽出来
 *
 * 抽离前这里是 App.jsx 里的两段内联 JSX（约 240 行），分别对应「新增产品」和
 * 「编辑商品」。两者字段几乎相同却各写一遍，于是长期不同步 —— 实测的后果：
 *
 *   · 编辑弹窗**没有图片字段**，也不认图片（`image_url` 只能新增时填）
 *   · 编辑弹窗写的是 `list="lookup-product-category"`，但那个 `<datalist>`
 *     只定义在新增弹窗里 —— 单独打开编辑弹窗时类别下拉**静默失效**
 *
 * 抽成一个组件后，这类"两边漏一处"的问题才有了唯一的修改点。
 *
 * ## 职责边界（刻意的）
 *
 *   · **不持有任何状态**：表单对象由外部传入（`form`）、改动通过 `onChange` 回调出去。
 *     因为新增态和编辑态的状态住在 App.jsx 的两个不同 state 里
 *     （`productForm` / `productEdit`），而保存接口也分别由 App.jsx 提供。
 *   · **不直接调保存接口**：`onSubmit` 把表单的 submit 事件原样透传给 App.jsx 的
 *     `submitProduct` / `submitProductEdit`，保存逻辑一行都没搬。
 *   · **只有两处例外，都是"读/传一个跟表单无关的东西"**：
 *     ① 图片上传（`ImageField`）—— 必须在"表单提交之前"独立完成并拿回地址；
 *     ② 辅助单位加载（`ProductUnitsField`）—— 只需要 `productId`，不需要任何外部状态。
 *     这两处的**值**仍然全部通过 `onChange` 交回 App.jsx，组件自己只留
 *     "上传中 / 加载中"这种转瞬即逝的界面状态。
 *
 * ## 与原来"一字不差"的保证
 *
 * 两个变体的字段 JSX 是从 App.jsx 原文逐条誊过来的：相同的 `className`
 * （`form-row two-col` / `label.span-2`）、相同的标签文案、相同的 `type`/`step`、
 * 相同的 `required`、相同的按钮文案。**唯一的一处差异**是每个输入框把
 * `value={form.xxx}` 换成了 `value={form.xxx ?? ''}` —— 仅用于避免 React 在
 * 字段为 undefined 时把受控组件降级成非受控（并在控制台报警），
 * 对真实数据（各字段恒为字符串或数字）行为完全一致。
 *
 * 依赖：只依赖 React 和 `../../lib/productImage`、`../../lib/productCategory`、
 * `../../lib/productUnits`（以及同目录的 `ProductUnitsField.jsx`）。
 * 无第三方库，无全局污染。样式在 `src/styles.css`：
 * 「商品弹窗 · 图片上传」一节前缀 `.pimg-`，「商品弹窗 · 辅助单位」一节前缀 `.punit-`。
 */

import { useEffect, useRef, useState } from 'react';

import { validateUnits } from '../../lib/productUnits';
import {
  IMAGE_ACCEPT,
  IMAGE_MAX_BYTES,
  formatBytes,
  resolveImageSrc,
  uploadProductImage,
  validateImageFile,
} from '../../lib/productImage';

import ProductUnitsField from './ProductUnitsField.jsx';
import SmartUploadPanel from '../partners/SmartUploadPanel.jsx';
// 生产厂家改可搜索下拉：数据源是供应商档案（本地 filter，不发请求）
import ErpSearchSelect from '../ui/ErpSearchSelect.jsx';
// 表单栅格 / 表单行 / 按钮条（第二步示范重构）
import { ErpFormActions, ErpFormGrid, ErpFormRow } from '../ui/ErpForm.jsx';
import ErpTreeSelect from '../ui/ErpTreeSelect.jsx';

// ═══════════════════════════════════════════════════════════════════════════
// 图片字段：本地上传 + 即时预览
// ═══════════════════════════════════════════════════════════════════════════

/**
 * 商品图片：预览 + 选本地文件上传 + 拖拽上传 + 移除。
 *
 * 两条"看起来多余但必须做"的细节：
 *   1. **选中文件后立刻用 `URL.createObjectURL` 本地预览**，不等上传返回。
 *      上传再快也要几百毫秒，等回来才显示会像卡死；而且用户此时已经能确认
 *      "选对了没"。
 *   2. **objectURL 必须显式释放**。它会把整个文件钉在内存里，弹窗反复开关
 *      就会持续累积 —— 这是不会报错、只涨内存的那类问题。
 */
function ImageField({ value, onChange, apiBase, authHeaders, onError }) {
  const inputRef = useRef(null);
  const objectUrlRef = useRef('');
  const [localPreview, setLocalPreview] = useState('');
  const [uploading, setUploading] = useState(false);
  const [dragging, setDragging] = useState(false);

  const releaseObjectUrl = () => {
    const url = objectUrlRef.current;
    objectUrlRef.current = '';
    if (url && typeof URL !== 'undefined' && typeof URL.revokeObjectURL === 'function') {
      URL.revokeObjectURL(url);
    }
  };

  // 卸载时释放（jsdom 里没有 createObjectURL，所以这里也要判存在）
  useEffect(() => releaseObjectUrl, []);

  const previewSrc = localPreview || resolveImageSrc(value);

  const startUpload = async (file) => {
    const check = validateImageFile(file);
    if (!check.ok) {
      if (onError) onError(check.error);
      return;
    }

    releaseObjectUrl();
    if (typeof URL !== 'undefined' && typeof URL.createObjectURL === 'function') {
      objectUrlRef.current = URL.createObjectURL(file);
      setLocalPreview(objectUrlRef.current);
    }

    setUploading(true);
    try {
      const url = await uploadProductImage(file, { apiBase, authHeaders });
      onChange('image_url', url);
      // 服务器地址已到手，本地预览可以放掉了（否则它会一直盖在上面）
      releaseObjectUrl();
      setLocalPreview('');
    } catch (err) {
      if (onError) onError(err.message || '图片上传失败');
      releaseObjectUrl();
      setLocalPreview('');
    } finally {
      setUploading(false);
    }
  };

  const handlePick = (event) => {
    const file = event.target.files && event.target.files[0];
    // 清空 value：否则"连续选同一个文件"不会再触发 change，用户会以为按钮坏了
    event.target.value = '';
    if (file) startUpload(file);
  };

  const handleRemove = () => {
    releaseObjectUrl();
    setLocalPreview('');
    onChange('image_url', '');
  };

  return (
    <div className="pimg">
      <div
        className={`pimg-preview${dragging ? ' is-dragging' : ''}`}
        onDragOver={(event) => {
          event.preventDefault();
          setDragging(true);
        }}
        onDragLeave={() => setDragging(false)}
        onDrop={(event) => {
          event.preventDefault();
          setDragging(false);
          const file = event.dataTransfer && event.dataTransfer.files && event.dataTransfer.files[0];
          if (file) startUpload(file);
        }}
      >
        {previewSrc ? (
          <img className="pimg-img" src={previewSrc} alt="商品图片预览" />
        ) : (
          <span className="pimg-empty">暂无图片</span>
        )}
        {uploading ? <span className="pimg-uploading">上传中…</span> : null}
      </div>

      <div className="pimg-side">
        <button
          type="button"
          className="secondary-btn"
          disabled={uploading}
          onClick={() => {
            if (inputRef.current) inputRef.current.click();
          }}
        >
          {uploading ? '上传中…' : previewSrc ? '更换图片' : '选择图片'}
        </button>
        {value ? (
          <button type="button" className="link-btn danger" onClick={handleRemove}>
            移除
          </button>
        ) : null}
        <span className="pimg-hint">
          png / jpg / webp / bmp，不超过 {formatBytes(IMAGE_MAX_BYTES)}
          <br />
          也可以把图片直接拖进左边的方框
        </span>
      </div>

      {/* 真正的文件选择框藏起来，由上面的按钮代点。
          用「视觉隐藏」而不是 display:none —— 后者在部分读屏软件里会被整个忽略。 */}
      <input
        ref={inputRef}
        className="pimg-file"
        type="file"
        accept={IMAGE_ACCEPT}
        onChange={handlePick}
        aria-label="选择商品图片"
      />
    </div>
  );
}

// ═══════════════════════════════════════════════════════════════════════════
// 弹窗本体
// ═══════════════════════════════════════════════════════════════════════════

/**
 * @param {object}   props
 * @param {'create'|'edit'} props.mode  新增 / 编辑。**两者现在共用同一套排版**
 *                                      （ErpFormGrid + ErpFormRow），唯一差异是
 *                                      编辑态不显示 SKU（主键，标题里已展示）。
 *                                      2026-10-17 第二步重构前，两个变体是两套
 *                                      完全不同的 DOM，导致了"编辑态漏字段"的长期不同步。
 * @param {object}   props.form         受控表单对象（新增时是 productForm，编辑时是 productEdit）
 * @param {(field: string, value: string) => void} props.onChange 字段变更
 * @param {(event) => void} props.onSubmit 直接透传给原来那两个 submit 处理函数
 * @param {() => void} props.onCancel
 * @param {string}   props.busy          忙碌标记，'edit' 时编辑弹窗的保存按钮显示「保存中…」
 * @param {Array}    props.categories    类别树（供 <datalist> 的候选）
 * @param {string}   props.apiBase       图片上传接口前缀
 * @param {() => object} props.authHeaders
 * @param {(msg: string) => void} props.onError 错误交给 App.jsx 的 notice 展示
 */
export default function ProductEditModal({
  mode = 'create',
  form,
  onChange,
  onSubmit,
  onCancel,
  busy = '',
  categories = [],
  // 生产厂家候选：供应商档案。默认 [] —— 老调用方不传也能渲染（只是下拉为空）
  suppliers = [],
  apiBase,
  authHeaders,
  onError,
  /** 智能识别上传（2026-10-23）：新增/编辑都开。
   *  编辑态识别结果仍走 onSmartFill 的"只覆盖认出字段"合并（核对框里
   *  逐项 <mark> 标出来源），用户看一眼再应用 —— 不存在"静默覆盖档案"。 */
  smartUpload = false,
  /** 识别结果回填：`(patch) => void`，由 App 合并进表单 */
  onSmartFill,
  /** 报价单明细批量入库（2026-10-23）：核对框里点「全部追加为商品」时触发。
   *  `(items) => void`，items = [{name, spec, unit, quantity, unit_price}]；
   *  批量 POST /products、SKU 自动生成，失败行单独报告。 */
  onSmartBulkItems,
}) {
  const isEdit = mode === 'edit';
  const values = form || {};

  // 表单字段的公共绑定。
  // `?? ''` 见文件头注释：只为避免 undefined 让受控输入降级成非受控。
  // `data-product-field`（2026-10-23）：商品弹窗原来没有任何字段级钩子，
  // 自动化/自测只能按"第几个 input"数，改一个字段顺序就全错。加一个稳定锚点。
  const bind = (field) => ({
    value: values[field] ?? '',
    onChange: (event) => onChange(field, event.target.value),
    'data-product-field': field,
  });

  // v76：类别候选的原 datalist/collectCategoryNames 已删 —— 类别改用
  // <ErpTreeSelect>（树形下拉），不再需要摊平的名字列表。

  const imageField = (
    <ImageField
      value={values.image_url ?? ''}
      onChange={onChange}
      apiBase={apiBase}
      authHeaders={authHeaders}
      onError={onError}
    />
  );

  // 辅助单位（第三阶段 3a）：值住在 form.units 里。
  //   · 新增态：`emptyProductForm.units = []`，跟商品一起 POST（后端一个事务落库）
  //   · 编辑态：进来时是 undefined，由 ProductUnitsField 自己去拉；
  //     拉回来之前 App.jsx 的序列化会**整个略过 units 键** —— 键不出现，
  //     后端 `exclude_unset` 就一个字段都不碰（绝不会误清空）
  const unitsField = (
    <ProductUnitsField
      units={values.units}
      baseUnit={values.unit ?? ''}
      productId={values.id}
      apiBase={apiBase}
      authHeaders={authHeaders}
      onChange={(next) => onChange('units', next)}
      onError={onError}
    />
  );

  // 提交前的第一道闸：辅助单位不合法就不放行。
  //
  // ⚠️ 必须在这里拦，**不能**靠输入框上的 `required` / `min` / `step`：
  // 原生校验会先弹一句英文气泡并阻止 submit，`onSubmit` 根本不触发，
  // 于是"第 2 行的换算率要填 ≥2 的整数"这句带定位的中文提示永远显示不出来。
  // 后端 `_validate_product_units` 是第二道闸（拦得住绕过界面的调用）。
  const guardedSubmit = (event) => {
    const check = validateUnits(values.units, values.unit);
    if (!check.ok) {
      event.preventDefault();
      if (onError) onError(check.error);
      return;
    }
    onSubmit(event);
  };
  return (
    <div className="modal-backdrop" onClick={onCancel}>
      <div className="modal-card modal-wide" onClick={(event) => event.stopPropagation()}>
        <div className="modal-header">
          <h3>{isEdit ? `编辑商品 · ${values.sku ?? ''}` : '新增产品'}</h3>
          <button type="button" className="close-btn" onClick={onCancel}>
            ×
          </button>
        </div>

        {/* 新增/编辑共用同一套排版。
            改造前是两套完全不同的 DOM（新增 .erp-form + .form-row.two-col，
            编辑 .invoice-edit-form 平铺 grid），同一批字段写了两遍 —— 于是编辑态
            一度漏了图片字段、类别下拉因为没有 datalist 而静默失效。
            现在只有一个字段清单，唯一的差异是编辑态不显示 SKU（它是主键，标题里已展示）。 */}
        <form onSubmit={guardedSubmit}>
          {smartUpload ? (
            <SmartUploadPanel
              kind="product"
              authHeaders={authHeaders}
              onFill={onSmartFill}
              onBulkItems={onSmartBulkItems}
              /* 商品没有附件库端点（同供应商），关掉"仅上传作为附件"的假功能 */
              allowAttach={false}
            />
          ) : null}

          <ErpFormGrid columns={2} gap="md">
            {!isEdit && (
              <ErpFormRow label="产品编号（SKU）" required>
                <input {...bind('sku')} required placeholder="如 SP-0001" />
              </ErpFormRow>
            )}

            <ErpFormRow label="产品名称" required>
              <input {...bind('name')} required />
            </ErpFormRow>

            <ErpFormRow label="类别">
              {/* v76：datalist 平铺 → 树形下拉。
                  ⚠️ products.category 存的是**类别名称字符串**不是 id（ProductCategory
                  模型注释：为避免迁移 262 个存量商品而保留的约定），所以 getNodeValue
                  取 node.name —— 选中后写回名字，与历史数据同构。
                  历史自由文本（不在树里的手填值）由组件兜底：回显原文不丢。 */}
              <ErpTreeSelect
                nodes={categories || []}
                value={values.category ?? ''}
                onChange={(next) => onChange('category', next)}
                placeholder="从类别树选择"
                emptyText="没有匹配的类别"
                clearLabel="未分类（清空类别）"
                getNodeValue={(node) => String(node.name ?? '')}
                getNodeLabel={(node) => String(node.name ?? '')}
                testId="product-category"
                dataAttr="category"
              />
            </ErpFormRow>

            <ErpFormRow label="单位">
              <input list="lookup-product-unit" {...bind('unit')} />
            </ErpFormRow>

            <ErpFormRow label="采购价（成本价）">
              <input type="number" step="any" {...bind('purchase_price')} />
            </ErpFormRow>

            <ErpFormRow label="销售价（零售价）">
              <input type="number" step="any" {...bind('sale_price')} />
            </ErpFormRow>

            <ErpFormRow label="默认税率" suffix="%">
              <input
                type="number"
                step="any"
                list="lookup-tax-rate"
                placeholder="如 13，留空则开单时手填"
                {...bind('tax_rate')}
              />
            </ErpFormRow>

            <ErpFormRow label="条码">
              <input {...bind('bar_code')} />
            </ErpFormRow>

            <ErpFormRow label="助记码">
              <input {...bind('mnemonic')} />
            </ErpFormRow>

            <ErpFormRow label="序列号">
              <input {...bind('serial_no')} />
            </ErpFormRow>

            <ErpFormRow label="规格">
              <input {...bind('standards')} />
            </ErpFormRow>

            <ErpFormRow label="型号">
              <input {...bind('brand')} />
            </ErpFormRow>

            <ErpFormRow label="颜色">
              <input {...bind('color')} />
            </ErpFormRow>

            <ErpFormRow label="尺码">
              <input {...bind('size')} />
            </ErpFormRow>

            <ErpFormRow label="生产商">
              <ErpSearchSelect
                options={suppliers}
                value={values.manufacturer_id ?? ''}
                displayValue={values.manufacturer ?? ''}
                placeholder="搜索供应商名称 / 编码 / 简称"
                /* ⚠️ 生产厂家 ≠ 供应商：现有 72 条商品填的是「大疆」「华诺迈」这类
                   真实厂家，一个都匹配不上 suppliers。允许自由文本，否则这些
                   历史值一编辑就被替换掉、而新厂家再也录不进去。 */
                allowFreeText
                onChange={(nextId, option) => {
                  onChange('manufacturer_id', nextId ?? '');
                  onChange('manufacturer', option ? option.name || '' : '');
                }}
              />
            </ErpFormRow>

            <ErpFormRow label="单位重量">
              <input type="number" step="any" {...bind('unit_weight')} />
            </ErpFormRow>

            <ErpFormRow label="库存上限">
              <input type="number" {...bind('stock_upper')} />
            </ErpFormRow>

            <ErpFormRow label="库存下限">
              <input type="number" {...bind('stock_lower')} />
            </ErpFormRow>

            <ErpFormRow label="包装数" hint="由「默认辅助单位」的换算率接管，这里只读">
              <input
                type="number"
                {...bind('pack_qty')}
                readOnly
                placeholder="由默认辅助单位同步"
              />
            </ErpFormRow>

            <ErpFormRow label="保质期" suffix="天">
              <input type="number" {...bind('shelf_life')} />
            </ErpFormRow>

            <ErpFormRow label="预警天数">
              <input type="number" {...bind('warn_days')} />
            </ErpFormRow>

            <ErpFormRow label="图片链接">
              <input {...bind('image_url')} placeholder="上传后自动填入，也可直接粘贴外链" />
            </ErpFormRow>

            {/* 这两行必须 as="div"：
                ImageField 内部藏着 <input type="file">，被 <label> 包住后
                点这个区域的任何位置都会弹出文件选择框；ProductUnitsField
                内部是张可编辑表格，同样不该被 label 抢焦点。 */}
            <ErpFormRow as="div" label="商品图片" span={2}>
              {imageField}
            </ErpFormRow>

            <ErpFormRow as="div" label="辅助单位与换算" span={2}>
              {unitsField}
            </ErpFormRow>

            <ErpFormRow label="备注" span={2}>
              <input {...bind('note')} />
            </ErpFormRow>
          </ErpFormGrid>

          <ErpFormActions>
            <button className="primary-btn" type="submit" disabled={busy === 'edit'}>
              {isEdit ? (busy === 'edit' ? '保存中…' : '保存') : '保存产品'}
            </button>
            <button type="button" className="secondary-btn" onClick={onCancel}>
              取消
            </button>
          </ErpFormActions>
        </form>
      </div>
    </div>
  );
}
