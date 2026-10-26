/**
 * SmartUploadPanel —— 「📄 智能识别上传（支持多选）」面板
 *
 * 挂在「新增客户 / 供应商 / 商品」弹窗**最顶部**：把营业执照、名片、报价单丢进来，
 * 后端读出文字并认出字段，这里弹一个**核对框**（识别值高亮 + 原文出处），
 * 用户点「应用到表单」才真正填进下面的输入框。
 *
 * ## 三个刻意的设计
 *
 * 1. **先核对、后回填**。识别是会错的（"类型：有限责任公司" 曾被当成公司名）。
 *    直接把值写进表单，用户会以为是系统"自动填好的"而不再看；
 *    弹一个核对框，把值用 `<mark>` 标出来，等于强迫看一眼。
 * 2. **两种模式**：
 *    · 识别并填表（默认）：调 `/smart-upload/parse`，只读不落库；
 *    · 仅上传作为附件：不 OCR，文件先存在本地列表里，**等档案保存成功**
 *      再由父组件挂到 `customer_id` 上（那时候才有 id 可用）。
 * 3. **不碰表单状态**。组件自己不写 `form`，只把 `fields` 交给 `onFill`；
 *    父组件决定怎么合并（现在客户弹窗用 `{...prev, ...patch}`）。
 *
 * ⚠️ 按钮一律 `type="button"`：这个面板在 `<form>` 里面，
 *    默认的 submit 按钮会在点「识别」时把整个档案表单提交掉。
 */

import { useCallback, useRef, useState } from 'react';
import { API_BASE } from '../../lib/appLib.js';
import './smartUpload.css';

// 与后端 `smart_upload.ACCEPT_SUFFIXES` 对齐；`accept` 只影响选择框的默认过滤，
// 拖拽进来的文件仍按后缀再校验一遍（后端也会再挡一次）。
const ACCEPT = '.jpg,.jpeg,.png,.bmp,.webp,.tif,.tiff,.pdf,.doc,.docx';
const MAX_FILES = 6;

const MODES = [
  { key: 'parse', label: '识别并填表', hint: '读文字 → 认字段 → 核对后填进表单' },
  { key: 'attach', label: '仅上传作为附件', hint: '不识别，保存档案后自动归档' },
];

const KIND_NOUN = { customer: '客户', supplier: '供应商', product: '商品' };

const fmtSize = (bytes) => {
  const value = Number(bytes || 0);
  if (value >= 1024 * 1024) return `${(value / 1024 / 1024).toFixed(1)} MB`;
  if (value >= 1024) return `${(value / 1024).toFixed(0)} KB`;
  return `${value} B`;
};

export default function SmartUploadPanel({
  kind = 'customer',
  /** App.jsx 传进来的鉴权头工厂（与其它上传组件同一套写法） */
  authHeaders,
  /** 核对通过后把字段交给父组件合并进表单：(fields) => void */
  onFill,
  /** 「仅上传作为附件」时要留到保存后再传的文件：(files) => void */
  onPendingFiles,
  /** 商品专用（2026-10-23）：报价单识别出的**全部明细行**一次交给父组件
   *  批量生成商品。(items: Array<{name,spec,unit,quantity,unit_price}>) => void */
  onBulkItems,
  /**
   * 是否提供「仅上传作为附件」模式（2026-10-23）。
   * 目前只有客户有 `/customers/{id}/files` 附件库 —— 供应商/商品没有对应端点，
   * 打开这个开关就是给了用户一个"点了没反应"的假功能，所以默认 true、
   * 供应商与商品弹窗显式传 false（只保留「识别并填表」）。
   */
  allowAttach = true,
  disabled = false,
}) {
  const inputRef = useRef(null);
  const [files, setFiles] = useState([]);
  const [mode, setMode] = useState('parse');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [hint, setHint] = useState('');
  const [dragging, setDragging] = useState(false);
  const [result, setResult] = useState(null);
  const [confirmOpen, setConfirmOpen] = useState(false);

  const noun = KIND_NOUN[kind] || '档案';
  /** 实际展示的模式：没有附件库的档案（供应商/商品）只留「识别并填表」 */
  const modes = allowAttach ? MODES : MODES.filter((item) => item.key === 'parse');

  const reset = useCallback(() => {
    setFiles([]);
    setResult(null);
    setConfirmOpen(false);
    setError('');
    setHint('');
    if (inputRef.current) inputRef.current.value = '';
  }, []);

  /** 真正的识别请求（只在 mode=parse 时走） */
  const runParse = useCallback(
    async (list) => {
      if (!list.length) return;
      setBusy(true);
      setError('');
      setHint('');
      try {
        const body = new FormData();
        list.forEach((item) => body.append('files', item, item.name));
        body.append('kind', kind);
        body.append('mode', 'parse');
        const response = await fetch(`${API_BASE}/smart-upload/parse`, {
          method: 'POST',
          headers: authHeaders ? authHeaders() : {},
          body,
        });
        const data = await response.json().catch(() => ({}));
        if (!response.ok) {
          throw new Error(typeof data.detail === 'string' ? data.detail : '识别失败，请稍后重试');
        }
        const recognized = Object.keys(data.fields || {}).length;
        if (!recognized && !(data.items || []).length) {
          setError(data.message || '没认出可填的字段，可以换一张更清晰的图，或手填。');
          setResult(data);
          return;
        }
        setResult(data);
        setConfirmOpen(true);
      } catch (err) {
        setError(err.message || '识别失败');
      } finally {
        setBusy(false);
      }
    },
    [authHeaders, kind],
  );

  const acceptFiles = useCallback(
    (incoming) => {
      const list = Array.from(incoming || []);
      if (!list.length) return;
      const merged = [...files];
      for (const file of list) {
        if (merged.length >= MAX_FILES) {
          setError(`一次最多 ${MAX_FILES} 个文件，多出来的已忽略`);
          break;
        }
        // 同名同大小视为同一个文件（防止重复点选/重复拖拽）
        if (merged.some((item) => item.name === file.name && item.size === file.size)) continue;
        merged.push(file);
      }
      setFiles(merged);
      setError('');
      if (mode === 'attach') {
        setHint(`已选中 ${merged.length} 个文件，保存${noun}后自动归档`);
        onPendingFiles?.(merged);
      } else {
        runParse(merged);
      }
    },
    [files, mode, noun, onPendingFiles, runParse],
  );

  const switchMode = (next) => {
    if (next === mode) return;
    setMode(next);
    setError('');
    setResult(null);
    setConfirmOpen(false);
    if (next === 'attach') {
      setHint(files.length ? `已选中 ${files.length} 个文件，保存${noun}后自动归档` : '');
      onPendingFiles?.(files);
    } else {
      setHint('');
      onPendingFiles?.([]);
      if (files.length) runParse(files);
    }
  };

  const removeFile = (index) => {
    const next = files.filter((_, i) => i !== index);
    setFiles(next);
    setResult(null);
    if (mode === 'attach') onPendingFiles?.(next);
  };

  /** 商品专用：把"识别到的某一行明细"直接填成商品字段。
   *  报价单里通常有多行，用户要的是"这一行"，让他在核对框里点一下比让他抄快。 */
  const applyItemRow = (row) => {
    const patch = {
      name: row.name || '',
      standards: row.spec || '',
      unit: row.unit || '',
    };
    if (row.unit_price !== null && row.unit_price !== undefined) {
      patch.sale_price = String(row.unit_price);
    }
    onFill?.(patch);
    setConfirmOpen(false);
    setHint(`已用「${row.name || '该行'}」填入商品信息，请核对后保存。`);
  };

  const applyResult = () => {
    const fields = result?.fields || {};
    onFill?.(fields);
    setConfirmOpen(false);
    const count = Object.keys(fields).length;
    setHint(
      count
        ? `已填入 ${count} 项，请核对后保存。黄色标记的值来自资料原文，建议逐项确认。`
        : '没有可填的字段',
    );
  };

  const onDrop = (event) => {
    event.preventDefault();
    event.stopPropagation();
    setDragging(false);
    if (disabled || busy) return;
    acceptFiles(event.dataTransfer?.files);
  };

  const fieldRows = result ? Object.entries(result.fields || {}) : [];
  const evidence = result?.evidence || {};
  const labels = result?.field_labels || {};
  const items = result?.items || [];
  const warnings = result?.warnings || [];

  return (
    <div className="smart-upload" data-smart-upload={kind}>
      <div className="smart-upload__head">
        <span className="smart-upload__title">📄 智能识别上传（支持多选）</span>
        <div className="smart-upload__modes" data-su-modes>
          {modes.map((item) => (
            <label key={item.key} className={`smart-upload__mode ${mode === item.key ? 'is-on' : ''}`}>
              <input
                type="radio"
                name={`smart-upload-mode-${kind}`}
                value={item.key}
                checked={mode === item.key}
                onChange={() => switchMode(item.key)}
                data-su-mode={item.key}
                disabled={disabled || busy}
              />
              <span>{item.label}</span>
            </label>
          ))}
        </div>
      </div>

      <div
        className={`smart-upload__drop ${dragging ? 'is-drag' : ''} ${busy ? 'is-busy' : ''}`}
        data-su-drop
        onDragOver={(event) => {
          event.preventDefault();
          event.stopPropagation();
          if (!disabled && !busy) setDragging(true);
        }}
        onDragLeave={(event) => {
          event.preventDefault();
          event.stopPropagation();
          setDragging(false);
        }}
        onDrop={onDrop}
        onClick={() => !disabled && !busy && inputRef.current?.click()}
        role="button"
        tabIndex={0}
        onKeyDown={(event) => {
          if (event.key === 'Enter' || event.key === ' ') {
            event.preventDefault();
            if (!disabled && !busy) inputRef.current?.click();
          }
        }}
      >
        <input
          ref={inputRef}
          type="file"
          multiple
          accept={ACCEPT}
          className="smart-upload__input"
          data-su-input
          disabled={disabled || busy}
          onChange={(event) => {
            acceptFiles(event.target.files);
            // 允许重复选同一个文件（不改 value 的话第二次选同一张不会再触发 change）
            event.target.value = '';
          }}
        />
        <div className="smart-upload__drop-main">
          {busy ? '识别中…（图片 OCR 需要几秒）' : '点击选择，或把文件拖到这里'}
        </div>
        <div className="smart-upload__drop-sub">
          营业执照 / 名片 / 报价单 · 图片(JPG/PNG) · PDF · Word(.docx)，一次最多 {MAX_FILES} 个
        </div>
      </div>

      {files.length ? (
        <ul className="smart-upload__files">
          {files.map((file, index) => (
            <li key={`${file.name}-${file.size}`} className="smart-upload__file" data-su-file={file.name}>
              <span className="smart-upload__file-name" title={file.name}>
                {file.name}
              </span>
              <span className="smart-upload__file-size">{fmtSize(file.size)}</span>
              <button
                type="button"
                className="smart-upload__file-x"
                aria-label={`移除 ${file.name}`}
                onClick={(event) => {
                  event.stopPropagation();
                  removeFile(index);
                }}
              >
                ×
              </button>
            </li>
          ))}
        </ul>
      ) : null}

      {files.length && mode === 'parse' ? (
        <div className="smart-upload__actions">
          <button
            type="button"
            className="secondary-btn small-btn"
            data-su-run
            disabled={busy || disabled}
            onClick={() => runParse(files)}
          >
            {busy ? '识别中…' : '重新识别'}
          </button>
          <button type="button" className="link-btn" onClick={reset} disabled={busy}>
            清空
          </button>
        </div>
      ) : null}

      {hint ? (
        <p className="smart-upload__hint" data-su-hint>
          {hint}
        </p>
      ) : null}
      {error ? (
        <p className="smart-upload__error" data-su-error>
          {error}
        </p>
      ) : null}

      {/* ================= 核对弹窗 ================= */}
      {confirmOpen && result ? (
        <div
          className="smart-upload__mask"
          data-su-result
          onClick={(event) => {
            event.stopPropagation();
          }}
        >
          <div className="smart-upload__dialog" role="dialog" aria-modal="true" aria-label="识别结果核对">
            <div className="smart-upload__dialog-head">
              <strong>识别完成，请核对信息</strong>
              <span className="smart-upload__dialog-sub">
                {result.files?.length || 0} 个文件 · {result.elapsed_ms || 0} ms ·
                共 {fieldRows.length} 项
              </span>
            </div>

            <div className="smart-upload__dialog-body">
              {fieldRows.length ? (
                <table className="smart-upload__table">
                  <thead>
                    <tr>
                      <th style={{ width: '28%' }}>字段</th>
                      <th>识别结果（请核对）</th>
                    </tr>
                  </thead>
                  <tbody>
                    {fieldRows.map(([key, value]) => (
                      <tr key={key} data-su-field={key}>
                        <td className="smart-upload__label">{labels[key] || key}</td>
                        <td>
                          <mark className="smart-upload__mark">{value}</mark>
                          {evidence[key] && evidence[key] !== value ? (
                            <small className="smart-upload__evidence">原文：{evidence[key]}</small>
                          ) : null}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              ) : (
                <p className="smart-upload__empty">没有认出可填的字段。</p>
              )}

              {items.length ? (
                <div className="smart-upload__items">
                  <div className="smart-upload__items-head">
                    识别到 <strong>{items.length}</strong> 行明细
                    {kind === 'product'
                      ? '（点「用这一行」填成单个商品，或用下方「全部追加为商品」批量入库）'
                      : '（保存商品/报价单时可用）'}
                  </div>
                  <table className="smart-upload__table">
                    <thead>
                      <tr>
                        <th>名称</th>
                        <th>规格</th>
                        <th>单位</th>
                        <th className="is-num">数量</th>
                        <th className="is-num">单价</th>
                        {kind === 'product' ? <th style={{ width: '18%' }}>操作</th> : null}
                      </tr>
                    </thead>
                    <tbody>
                      {items.slice(0, 8).map((row, index) => (
                        <tr key={`${row.name}-${index}`}>
                          <td>{row.name}</td>
                          <td>{row.spec || ''}</td>
                          <td>{row.unit || ''}</td>
                          <td className="is-num">{row.quantity ?? ''}</td>
                          <td className="is-num">{row.unit_price ?? ''}</td>
                          {kind === 'product' ? (
                            <td>
                              <button
                                type="button"
                                className="link-btn"
                                data-su-item={index}
                                onClick={() => applyItemRow(row)}
                              >
                                用这一行
                              </button>
                            </td>
                          ) : null}
                        </tr>
                      ))}
                    </tbody>
                  </table>
                  {items.length > 8 ? (
                    <p className="smart-upload__empty">还有 {items.length - 8} 行未显示</p>
                  ) : null}
                </div>
              ) : null}

              {warnings.length ? (
                <ul className="smart-upload__warnings" data-su-warning>
                  {warnings.map((warning) => (
                    <li key={warning}>{warning}</li>
                  ))}
                </ul>
              ) : null}

              <details className="smart-upload__raw">
                <summary>看看读到的原文</summary>
                {(result.files || []).map((file) => (
                  <div key={file.name} className="smart-upload__raw-item">
                    <div className="smart-upload__raw-head">
                      <span>{file.name}</span>
                      <span>
                        {file.ok ? `${file.engine} · ${file.chars} 字` : file.error || '读取失败'}
                      </span>
                    </div>
                    {file.preview ? <pre>{file.preview}</pre> : null}
                  </div>
                ))}
              </details>
            </div>

            <div className="smart-upload__dialog-actions">
              {kind === 'product' && items.length && onBulkItems ? (
                <button
                  type="button"
                  className="primary-btn"
                  data-su-bulk
                  onClick={() => {
                    onBulkItems(items);
                    setConfirmOpen(false);
                  }}
                >
                  全部追加为商品（{items.length} 行）
                </button>
              ) : null}
              <button
                type="button"
                className={
                  kind === 'product' && items.length && onBulkItems ? 'secondary-btn' : 'primary-btn'
                }
                data-su-apply
                onClick={applyResult}
                disabled={!fieldRows.length}
              >
                应用到表单
              </button>
              <button type="button" className="secondary-btn" data-su-cancel onClick={() => setConfirmOpen(false)}>
                继续手填
              </button>
            </div>
          </div>
        </div>
      ) : null}
    </div>
  );
}
