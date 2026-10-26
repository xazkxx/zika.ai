// 客户 / 供应商「导出选列」的列定义与取数口径（第二阶段 P2-5）
//
// 为什么列定义放在 lib 而不是组件里：
//   1) 后端 Excel 导入模板的列名要和导出一致（用户导出→改两格→再导回去），
//      两边各写一份必然漂移；
//   2) 拒绝在弹窗里"动态拼列"：可导出的列必须是**白名单**，
//      否则对方传来一个 `fields=password` 之类的东西就顺着导出了。
//
// 默认勾选的是"打出来就能用"的六列：编码 / 名称 / 联系人 / 电话 / 税号 / 开户行。

const CUSTOMER_COLUMNS = [
  { key: 'code', label: '客户编码', width: 14 },
  { key: 'name', label: '客户名称', width: 26 },
  { key: 'short_name', label: '简称', width: 16 },
  { key: 'contact', label: '联系人', width: 12 },
  { key: 'phone', label: '电话', width: 16 },
  { key: 'contact_phone', label: '联系人手机', width: 16 },
  { key: 'tax_no', label: '税号', width: 22 },
  { key: 'bank_name', label: '开户行', width: 24 },
  { key: 'bank_account', label: '银行账号', width: 24 },
  { key: 'account_name', label: '开户名', width: 22 },
  { key: 'address', label: '地址', width: 30 },
  { key: 'email', label: '邮箱', width: 22 },
  { key: 'businesser', label: '业务员', width: 12 },
  { key: 'level', label: '等级', width: 10 },
  { key: 'credit_limit', label: '信用额度', width: 14, money: true },
  { key: 'init_receivable', label: '期初应收', width: 14, money: true },
  { key: 'relation_date', label: '建立日期', width: 14 },
  { key: 'note', label: '备注', width: 24 },
];

const SUPPLIER_COLUMNS = [
  { key: 'code', label: '供应商编码', width: 14 },
  { key: 'name', label: '供应商名称', width: 26 },
  { key: 'short_name', label: '简称', width: 16 },
  { key: 'contact', label: '联系人', width: 12 },
  { key: 'phone', label: '电话', width: 16 },
  { key: 'mobile', label: '手机', width: 16 },
  { key: 'tax_no', label: '税号', width: 22 },
  { key: 'bank_name', label: '开户行', width: 24 },
  { key: 'bank_account', label: '银行账号', width: 24 },
  { key: 'account_name', label: '开户名', width: 22 },
  { key: 'address', label: '地址', width: 30 },
  { key: 'email', label: '邮箱', width: 22 },
  { key: 'init_payable', label: '期初应付', width: 14, money: true },
  { key: 'postcode', label: '邮编', width: 12 },
  { key: 'note', label: '备注', width: 24 },
];

export const PARTNER_EXPORT_COLUMNS = {
  customer: CUSTOMER_COLUMNS,
  supplier: SUPPLIER_COLUMNS,
};

export const PARTNER_EXPORT_DEFAULT_KEYS = {
  customer: ['code', 'name', 'contact', 'phone', 'tax_no', 'bank_name'],
  supplier: ['code', 'name', 'contact', 'phone', 'tax_no', 'bank_name'],
};

export const PARTNER_EXPORT_TITLE = {
  customer: '导出客户档案',
  supplier: '导出供应商档案',
};

export function partnerColumns(kind) {
  return PARTNER_EXPORT_COLUMNS[kind] || CUSTOMER_COLUMNS;
}

export function partnerDefaultKeys(kind) {
  return PARTNER_EXPORT_DEFAULT_KEYS[kind] || PARTNER_EXPORT_DEFAULT_KEYS.customer;
}

/**
 * 生成导出用的二维表（第一行是表头）。
 * ⚠️ 空值一律写空串而不是 `null`/`undefined`：SheetJS 会把 undefined 写成空单元格、
 *    把 null 写成 "null" 字符串（用户拿去做 VLOOKUP 会匹配不上）。
 */
export function buildPartnerSheet(rows, kind, keys) {
  const selected = partnerColumns(kind).filter((column) => keys.includes(column.key));
  const header = selected.map((column) => column.label);
  const body = (rows || []).map((row) =>
    selected.map((column) => {
      const value = row ? row[column.key] : '';
      if (value === null || value === undefined) return '';
      return value;
    }),
  );
  return [header, ...body];
}

export function partnerExportFileName(kind, today = new Date()) {
  const pad = (n) => String(n).padStart(2, '0');
  const stamp = `${today.getFullYear()}${pad(today.getMonth() + 1)}${pad(today.getDate())}`;
  return `${kind === 'supplier' ? '供应商档案' : '客户档案'}_${stamp}.xlsx`;
}
