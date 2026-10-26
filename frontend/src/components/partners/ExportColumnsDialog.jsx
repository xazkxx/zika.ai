// 导出选列弹窗（第二阶段 P2-5）
//
// 用户原话：「点击导出不能直接下载，必须弹出一个弹窗，让用户勾选要导出的列」。
//
// 三条硬约束：
//   ① **至少勾一列**：一列都不勾导出来是无表头空文件，等于给了个坏文件；
//   ② 勾选状态**自己管**，且每次打开都重置成默认六列 ——
//      上次勾过的列留在这一次，用户拿到的是"上上张表"的列，反而更迷惑；
//   ③ 弹窗里要**实时显示行数**：让用户点导出前就知道"这份是 61 行还是 6000 行"。
import { useEffect, useMemo, useState } from 'react';

export default function ExportColumnsDialog({
  open = false,
  kind = 'customer',
  title = '导出档案',
  columns = [],
  defaultKeys = [],
  rowCount = 0,
  busy = false,
  onClose,
  onConfirm,
}) {
  const [keys, setKeys] = useState(defaultKeys);

  // 每次打开重置成默认列：不复用上一次的勾选（见文件头 ②）
  useEffect(() => {
    if (open) setKeys(defaultKeys);
  }, [open, defaultKeys]);

  const allKeys = useMemo(() => columns.map((column) => column.key), [columns]);
  const selectedCount = keys.length;
  const allSelected = selectedCount === allKeys.length;

  if (!open) return null;

  const toggle = (key) => {
    setKeys((prev) => (prev.includes(key) ? prev.filter((item) => item !== key) : [...prev, key]));
  };

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div
        className="modal-card export-columns"
        role="dialog"
        aria-label={title}
        data-export-dialog={kind}
        onClick={(event) => event.stopPropagation()}
      >
        <div className="modal-header">
          <h3>{title}</h3>
          <button type="button" className="close-btn" onClick={onClose}>
            ×
          </button>
        </div>

        <div className="modal-body">
          <p className="export-columns__hint">
            勾选要写进 Excel 的列（共 <b>{rowCount}</b> 行数据）。
            默认只勾常用六列，其余按需勾选。
          </p>

          <div className="export-columns__quick">
            <button
              type="button"
              className="link-btn"
              onClick={() => setKeys(allSelected ? [] : allKeys)}
              data-export-toggle-all
            >
              {allSelected ? '全部取消' : '全选'}
            </button>
            <button type="button" className="link-btn" onClick={() => setKeys(defaultKeys)}>
              恢复默认
            </button>
            <span className="export-columns__count" data-export-selected-count={selectedCount}>
              已选 <b>{selectedCount}</b> / {allKeys.length} 列
            </span>
          </div>

          <div className="export-columns__grid">
            {columns.map((column) => (
              <label key={column.key} className="export-columns__item">
                <input
                  type="checkbox"
                  checked={keys.includes(column.key)}
                  onChange={() => toggle(column.key)}
                  data-export-column={column.key}
                />
                <span>{column.label}</span>
              </label>
            ))}
          </div>

          {selectedCount === 0 && (
            <p className="export-columns__warn" role="alert">
              至少要勾一列才能导出。
            </p>
          )}
        </div>

        <div className="modal-actions">
          <button type="button" className="secondary-btn" onClick={onClose}>
            取消
          </button>
          <button
            type="button"
            className="primary-btn"
            data-export-confirm
            disabled={selectedCount === 0 || busy || rowCount === 0}
            onClick={() => onConfirm && onConfirm(keys)}
          >
            {busy ? '导出中…' : '导出 Excel'}
          </button>
        </div>
      </div>
    </div>
  );
}
