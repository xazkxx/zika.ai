/**
 * PartnerModal —— 客户 / 供应商档案的**新增 + 编辑**弹窗（一套代码，两种 kind × 两种 mode）
 *
 * 改造前：这段 JSX 在 App.jsx 里写了两份（客户/供应商各 ≈40 行），
 * 结构逐字相同、只有标题和字段名不同，而且用的是旧 `.erp-form` +
 * `.form-row.two-col`，跟商品弹窗那两套表单一样长期各走各的。
 * 现在：一份 `ErpFormGrid` + `ErpFormRow`，字段**声明成数组**（FIELDS），只写一次。
 *
 * 2026-10-17 补「编辑」：列表原来只有删除，档案建错一个字就没法改。
 *   · 新增 `mode`（'create' | 'edit'）：只影响标题/提交文案；
 *   · **`code` 在 edit 态强制 `readOnly`** —— 编码是档案的业务主键，单据/对账/
 *     打印模板都存着它，改了历史数据就指向另一个人。后端 PATCH 也挡了一道
 *     （传了且不同 → 400），两层都留着：UI 防误触，API 防绕过。
 *   · 字段集合与 `emptyCustomerForm` / `emptySupplierForm` 严格一致，
 *     否则 reset 之后会留下幽灵字段。
 *
 * 职责边界（刻意的）：
 *   · **完全受控**：`form` / `fieldChange` / `onSubmit` 全部由 App.jsx 传入，
 *     组件自己不持有任何业务状态、不发请求、不知道接口长什么样。
 *   · 不 import App.jsx、不读 `ctx` —— 同 `sales-units` 那套约束。
 *
 * ⚠️ `fieldChange` 是**柯里化**的：`handleCustomerChange('code')` 返回 onChange。
 *    这里原样转发 `fieldChange('code')`，所以 App.jsx 那边一行逻辑都不用改。
 *
 * 2026-10-23 加「📄 智能识别上传」：只在**新增**态显示（编辑态改档案名/税号时，
 * 用一张新执照去覆盖历史档案是危险的，宁可让用户自己改那一个字段）。
 * 面板自己发请求、自己做核对弹窗，只通过 `onSmartFill` / `onSmartFiles` 往回传结果，
 * 所以本组件"不持有业务状态"的约定没被破坏。
 */

import { ErpFormActions, ErpFormGrid, ErpFormRow } from '../ui/ErpForm.jsx';
import SmartUploadPanel from './SmartUploadPanel.jsx';
import ErpTreeSelect from '../ui/ErpTreeSelect.jsx';
import './partners.css';

const COPY = {
  customer: {
    noun: '客户',
    codeLabel: '客户编码',
    codePlaceholder: '留空自动生成（如 CUS20261018001）',
    nameLabel: '客户名称',
    namePlaceholder: '如 西安明珠电力安装工程有限公司',
  },
  supplier: {
    noun: '供应商',
    codeLabel: '供应商编码',
    codePlaceholder: '留空自动生成（如 SUP20261018001）',
    nameLabel: '供应商名称',
    namePlaceholder: '如 深圳市凯歌电子有限公司',
  },
};

/**
 * 字段声明。顺序 = 两列网格里的摆放顺序。
 * `lockedInEdit: true` 的字段在编辑态只读（编码）；
 * `autoCode: true` 的新增态编码框：**不必填** —— 留空由后端生成（CUS/SUP+日期+流水）。
 */
const FIELDS = {
  customer: [
    { key: 'code', label: 'codeLabel', placeholder: 'codePlaceholder', autoCode: true, lockedInEdit: true },
    { key: 'name', label: 'nameLabel', placeholder: 'namePlaceholder', required: true },
    // 税号整行：开票、对账、进项票匹配都靠它，肉眼核对时数字长，占整行更好读
    { key: 'tax_no', label: '纳税人识别号', span: 2, placeholder: '开票信息里的「统一社会信用代码」，如 91610103MA6TX****' },
    { key: 'category_id', label: '所属分类', type: 'category' },
    // 「客户级别 level」2026-10-23 从表单移除：业务上没人维护，还是自由文本。
    // 换成了开票真正用得到的三列（开户行 / 账号 / 开票电话）。
    { key: 'bank_name', label: '开户行', placeholder: '如 招商银行西安分行' },
    { key: 'bank_account', label: '银行账号', placeholder: '对公账号' },
    { key: 'invoice_phone', label: '开票电话', placeholder: '开票信息上的电话（可与联系电话不同）' },
    { key: 'businesser', label: '业务员', placeholder: '如 范先生' },
    { key: 'contact', label: '联系人', placeholder: '如 张经理' },
    { key: 'phone', label: '联系电话', placeholder: '座机或手机' },
    { key: 'email', label: '邮箱', type: 'email', placeholder: 'name@example.com' },
    { key: 'address', label: '地址', span: 2, multiline: true, placeholder: '省 / 市 / 区 + 详细地址' },
  ],
  supplier: [
    { key: 'code', label: 'codeLabel', placeholder: 'codePlaceholder', autoCode: true, lockedInEdit: true },
    { key: 'name', label: 'nameLabel', placeholder: 'namePlaceholder', required: true },
    // 税号放在名称旁边：进项票就是靠它认人。占了整行，因为税号长、肉眼要能核对
    { key: 'tax_no', label: '纳税人识别号', span: 2, placeholder: '进项发票上的「销售方识别号」，如 91610103MA6TX****' },
    { key: 'category_id', label: '所属分类', type: 'category' },
    { key: 'short_name', label: '简称', placeholder: '拼音首字母，决定左侧分组' },
    { key: 'contact', label: '联系人', placeholder: '如 李工' },
    { key: 'mobile', label: '手机', placeholder: '11 位手机号' },
    { key: 'phone', label: '联系电话', placeholder: '座机，可带分机' },
    // 开票信息（2026-10-23）：开户行/账号库里一直有，表单以前没放出来
    { key: 'bank_name', label: '开户行', placeholder: '如 建设银行深圳科技园支行' },
    { key: 'bank_account', label: '银行账号', placeholder: '对公账号' },
    { key: 'invoice_phone', label: '开票电话', placeholder: '开票信息上的电话（可与联系电话不同）' },
    { key: 'email', label: '邮箱', type: 'email', placeholder: 'name@example.com' },
    { key: 'address', label: '地址', span: 2, multiline: true, placeholder: '省 / 市 / 区 + 详细地址' },
  ],
};

export default function PartnerModal({
  open = false,
  kind = 'customer',
  mode = 'create',
  form = {},
  fieldChange,
  onSubmit,
  onClose,
  busy = false,
  /** 「所属分类」的**分类树**（后端原样：`[{id, name, children}]`）。
   *  由 App.jsx 打开弹窗时拉取传入 —— 本组件保持"不发请求"的受控约定。
   *  ⚠️ v75 及以前这里是 `[{value,label}]` 扁平数组（label 拼全路径），
   *     v76 改成树形下拉后一并换成嵌套结构。 */
  categoryOptions = [],
  /** 是否显示「智能识别上传」区域（客户 / 供应商都已开） */
  smartUpload = false,
  /**
   * 「仅上传作为附件」模式开关（2026-10-23）。
   * 目前只有客户有附件库端点（/customers/{id}/files）—— 供应商没有，
   * 打开就是"点了没反应"的假功能，所以供应商弹窗传 false。
   */
  smartUploadAllowAttach = true,
  /** 后端上传接口的鉴权头工厂（App.jsx 的 authHeaders） */
  authHeaders,
  /** 识别结果回填：`(fields) => void`，由 App 合并进 form */
  onSmartFill,
  /** 「仅上传作为附件」时暂存文件：`(files) => void`，保存成功后由 App 归档 */
  onSmartFiles,
}) {
  if (!open) return null;

  const copy = COPY[kind] || COPY.customer;
  const fields = FIELDS[kind] || FIELDS.customer;
  const isEdit = mode === 'edit';

  const title = isEdit ? `编辑${copy.noun}` : `新增${copy.noun}`;
  const submitLabel = isEdit ? '保存修改' : `保存${copy.noun}`;

  const bind = (field) => (typeof fieldChange === 'function' ? fieldChange(field) : undefined);

  /** label / placeholder 允许是「直接文案」或「COPY 里的 key」 */
  const text = (value) => (value && copy[value] ? copy[value] : value);

  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div
        className="modal-card partner-modal"
        role="dialog"
        aria-modal="true"
        aria-label={title}
        data-partner-modal={kind}
        data-modal-mode={mode}
        onClick={(event) => event.stopPropagation()}
      >
        <div className="modal-header">
          <h3>{title}</h3>
          <button type="button" className="close-btn" onClick={onClose} aria-label="关闭">
            ×
          </button>
        </div>

        <form className="partner-modal__form" onSubmit={onSubmit}>
          {/* 客户保持「只在新增加」（编辑时盖档案危险）；供应商新增/编辑都开 ——
              编辑态识别结果仍走 onSmartFill 的"只覆盖认出字段"合并，用户可逐项核对。 */}
          {smartUpload && (!isEdit || kind === 'supplier') ? (
            <SmartUploadPanel
              kind={kind}
              authHeaders={authHeaders}
              onFill={onSmartFill}
              onPendingFiles={onSmartFiles}
              allowAttach={smartUploadAllowAttach}
            />
          ) : null}

          <ErpFormGrid columns={2} gap="md">
            {fields.map((field) => {
              const locked = isEdit && field.lockedInEdit;
              const rowProps = {
                key: field.key,
                label: text(field.label),
                required: field.required,
                span: field.span || 1,
              };
              if (locked) rowProps.hint = isEdit ? '编码创建后不可修改' : '留空由系统自动生成';

              return (
                <ErpFormRow {...rowProps}>
                  {field.type === 'category' ? (
                    /* 「所属分类」：值是分类 id（数字字符串），'' = 未分类（提交时归 null）。
                       2026-10-20 v76：从"平铺路径下拉"改成**树形下拉**。
                       原来把树摊平成 「集团客户 / 华东分公司 / 上海分部」这种长串灌进
                       ErpSearchSelect，三级以上前缀重复几十遍，选项列表根本没法读。
                       现在：默认只展开第一级 → 点父级逐层展开 → 末级才可选 → 搜索自动展开命中链路。

                       ⚠️ `categoryOptions` 的**形状变了**：v75 及以前是 `[{value,label}]`
                       扁平数组，现在是后端原样的 `[{id,name,children}]` 树。
                       改这里时务必同步 App.jsx 的 `loadPartnerCategoryOptions`。 */
                    <ErpTreeSelect
                      nodes={categoryOptions}
                      value={String(form[field.key] ?? '')}
                      onChange={(value) => {
                        const handler = bind(field.key);
                        if (handler) handler({ target: { value } });
                      }}
                      placeholder={text(field.placeholder) || '选择所属分类'}
                      emptyText="没有匹配的分类"
                      clearLabel="未分类（不归属任何分支）"
                      testId={`partner-${kind}-category`}
                      dataAttr={field.key}
                    />
                  ) : field.multiline ? (
                    <textarea
                      value={form[field.key] ?? ''}
                      onChange={bind(field.key)}
                      placeholder={text(field.placeholder) || ''}
                      rows="2"
                      data-partner-field={field.key}
                    />
                  ) : (
                    <input
                      type={field.type || 'text'}
                      value={form[field.key] ?? ''}
                      onChange={bind(field.key)}
                      placeholder={text(field.placeholder) || ''}
                      required={field.required && !field.autoCode}
                      readOnly={locked}
                      aria-readonly={locked || undefined}
                      autoComplete="off"
                      data-partner-field={field.key}
                      className={locked ? 'partner-modal__locked' : ''}
                    />
                  )}
                </ErpFormRow>
              );
            })}
          </ErpFormGrid>

          <ErpFormActions>
            <button type="submit" className="primary-btn" disabled={busy}>
              {submitLabel}
            </button>
            <button type="button" className="secondary-btn" onClick={onClose}>
              取消
            </button>
          </ErpFormActions>
        </form>
      </div>
    </div>
  );
}
