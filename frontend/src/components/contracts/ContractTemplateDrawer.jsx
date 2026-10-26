/**
 * 合同模板库抽屉（2026-10-22）
 *
 * 用户自己的范本（Word / PDF / 扫描件）在这里上传、查看、删除；
 * 「新增购销合同」表单顶部的「选择合同模板」下拉就读这份列表。
 *
 * 三个实现要点：
 *   1. **预览走 fetch + blob**，不用 `<iframe src>`：
 *      文件接口要 Bearer 令牌，而 iframe/img 的 src 带不了请求头（令牌在 localStorage）。
 *   2. **上传用 FormData**，name/note 是表单字段，file 是文件；顺便把"同一次上传"的
 *      名称与备注绑在一起，避免先上传后补名字导致两条记录对不上。
 *   3. 删除前二次确认（`confirmDanger`），失败原样提示 —— 模板文件是用户的资产，
 *      删错了没法从系统里找回来。
 */
import { useCallback, useEffect, useState } from 'react';
import { API_BASE } from '../../lib/appLib.js';
import { confirmDanger } from '../../lib/printConfirm.js';
import { saveBlob } from '../../lib/download.js';

const KIND_LABEL = { word: 'Word', pdf: 'PDF', image: '图片', other: '其他' };

function humanSize(bytes) {
  const value = Number(bytes || 0);
  if (!value) return '—';
  if (value < 1024) return `${value} B`;
  if (value < 1024 * 1024) return `${(value / 1024).toFixed(0)} KB`;
  return `${(value / 1024 / 1024).toFixed(1)} MB`;
}

export default function ContractTemplateDrawer({ open, onClose, authHeaders, onChanged }) {
  const [rows, setRows] = useState([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [uploading, setUploading] = useState(false);
  const [name, setName] = useState('');
  const [note, setNote] = useState('');
  const [file, setFile] = useState(null);
  // 预览：{ title, url, kind }
  const [preview, setPreview] = useState(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError('');
    try {
      const response = await fetch(`${API_BASE}/contract-templates`, { headers: authHeaders() });
      if (!response.ok) throw new Error(`读取模板库失败（HTTP ${response.status}）`);
      const data = await response.json();
      setRows(Array.isArray(data) ? data : []);
    } catch (err) {
      setError(err.message || '读取模板库失败');
    } finally {
      setLoading(false);
    }
  }, [authHeaders]);

  useEffect(() => {
    if (open) load();
  }, [open, load]);

  // 关抽屉时释放预览 blob，避免内存泄漏（objectURL 不释放会一直占着）
  useEffect(
    () => () => {
      if (preview?.url) URL.revokeObjectURL(preview.url);
    },
    [preview],
  );

  const submit = async (event) => {
    event.preventDefault();
    if (!file) {
      setError('请选择要上传的模板文件（Word / PDF / 图片）');
      return;
    }
    setUploading(true);
    setError('');
    setNotice('');
    try {
      const form = new FormData();
      form.append('file', file);
      form.append('name', name.trim());
      form.append('note', note.trim());
      const response = await fetch(`${API_BASE}/contract-templates`, {
        method: 'POST',
        headers: authHeaders(), // 不要手动设 Content-Type，浏览器要自己带 boundary
        body: form,
      });
      if (!response.ok) {
        const data = await response.json().catch(() => ({}));
        throw new Error(typeof data.detail === 'string' ? data.detail : '上传失败');
      }
      const created = await response.json();
      setNotice(`模板「${created.name}」已上传`);
      setName('');
      setNote('');
      setFile(null);
      const input = document.getElementById('contract-template-file');
      if (input) input.value = '';
      await load();
      onChanged?.();
    } catch (err) {
      setError(err.message || '上传失败');
    } finally {
      setUploading(false);
    }
  };

  const openPreview = async (row) => {
    try {
      const response = await fetch(`${API_BASE}/contract-templates/${row.id}/file`, {
        headers: authHeaders(),
      });
      if (!response.ok) throw new Error(`模板文件打不开（HTTP ${response.status}）`);
      const blob = await response.blob();
      if (!blob.size) throw new Error('模板文件是空的');
      const url = URL.createObjectURL(blob);
      if (preview?.url) URL.revokeObjectURL(preview.url);
      setPreview({ title: row.name, url, kind: row.kind });
    } catch (err) {
      setError(err.message || '预览失败');
    }
  };

  const download = async (row) => {
    try {
      const response = await fetch(
        `${API_BASE}/contract-templates/${row.id}/file?download=true`,
        { headers: authHeaders() },
      );
      if (!response.ok) throw new Error(`下载失败（HTTP ${response.status}）`);
      const blob = await response.blob();
      saveBlob(blob, row.file_name || `${row.name}.bin`);
    } catch (err) {
      setError(err.message || '下载失败');
    }
  };

  const remove = async (row) => {
    const decision = await confirmDanger({
      title: '删除合同模板',
      name: row.name,
      hint: '模板文件会从磁盘删除，已有合同不受影响（但历史合同将无法再套用这份模板）。',
    });
    if (!decision.ok) return;
    try {
      const response = await fetch(`${API_BASE}/contract-templates/${row.id}`, {
        method: 'DELETE',
        headers: authHeaders(),
      });
      if (!response.ok && response.status !== 204) {
        const data = await response.json().catch(() => ({}));
        throw new Error(typeof data.detail === 'string' ? data.detail : '删除失败');
      }
      setNotice(`模板「${row.name}」已删除`);
      await load();
      onChanged?.();
    } catch (err) {
      setError(err.message || '删除失败');
    }
  };

  if (!open) return null;

  return (
    <>
      <div className="modal-overlay tpl-drawer__overlay" onClick={onClose}>
        <aside
          className="tpl-drawer"
          data-contract-template-drawer
          onClick={(event) => event.stopPropagation()}
        >
          <header className="tpl-drawer__head">
            <div>
              <h3>📁 合同模板库</h3>
              <p>上传一次、反复套用。支持的格式：Word（可变量替换）、PDF、图片（扫描件）。</p>
            </div>
            <button type="button" className="secondary-btn small-btn" onClick={onClose}>
              关闭
            </button>
          </header>

          <form className="tpl-drawer__upload" onSubmit={submit}>
            <div className="tpl-drawer__upload-row">
              <label>
                模板名称
                <input
                  value={name}
                  onChange={(event) => setName(event.target.value)}
                  placeholder="如：标准工矿产品购销合同（留空用文件名）"
                  maxLength={150}
                  data-tpl-name
                />
              </label>
              <label>
                备注
                <input
                  value={note}
                  onChange={(event) => setNote(event.target.value)}
                  placeholder="如：2026 版，含质量附件"
                  maxLength={200}
                />
              </label>
            </div>
            <div className="tpl-drawer__upload-row">
              <label className="tpl-drawer__file">
                模板文件
                <input
                  id="contract-template-file"
                  type="file"
                  accept=".doc,.docx,.pdf,.png,.jpg,.jpeg,.webp,.bmp"
                  onChange={(event) => setFile(event.target.files?.[0] || null)}
                  data-tpl-file
                />
              </label>
              <button type="submit" className="primary-btn" disabled={uploading} data-tpl-upload>
                {uploading ? '上传中…' : '上传模板'}
              </button>
            </div>
            <p className="tpl-drawer__hint">
              Word 模板里可以写变量：{'{{party_name}}'} {'{{total_amount}}'} {'{{delivery_place}}'} 等，
              生成完整合同时会自动替换成真实数据。
            </p>
          </form>

          {error ? (
            <p className="tpl-drawer__alert tpl-drawer__alert--error" role="alert">
              {error}
            </p>
          ) : null}
          {notice ? <p className="tpl-drawer__alert tpl-drawer__alert--ok">{notice}</p> : null}

          <div className="tpl-drawer__list">
            <div className="tpl-drawer__list-head">
              <span>已上传 {rows.length} 份</span>
              <button type="button" className="secondary-btn small-btn" onClick={load} disabled={loading}>
                {loading ? '刷新中…' : '刷新'}
              </button>
            </div>
            {rows.length === 0 && !loading ? (
              <p className="tpl-drawer__empty">还没有模板。上传一份 Word 或 PDF，之后新建合同时就能选它。</p>
            ) : null}
            {rows.map((row) => (
              <div className="tpl-drawer__item" key={row.id} data-tpl-id={row.id}>
                <div className="tpl-drawer__item-main">
                  <div className="tpl-drawer__item-title">
                    <span className={`tpl-drawer__badge tpl-drawer__badge--${row.kind}`}>
                      {KIND_LABEL[row.kind] || row.kind}
                    </span>
                    <strong>{row.name}</strong>
                  </div>
                  <div className="tpl-drawer__item-meta">
                    {row.file_name} · {humanSize(row.file_size)}
                    {row.note ? ` · ${row.note}` : ''}
                  </div>
                </div>
                <div className="tpl-drawer__item-actions">
                  {row.previewable ? (
                    <button
                      type="button"
                      className="secondary-btn small-btn"
                      onClick={() => openPreview(row)}
                      data-tpl-preview={row.id}
                    >
                      预览
                    </button>
                  ) : null}
                  <button
                    type="button"
                    className="secondary-btn small-btn"
                    onClick={() => download(row)}
                  >
                    下载
                  </button>
                  <button
                    type="button"
                    className="secondary-btn small-btn cledger__danger"
                    onClick={() => remove(row)}
                    data-tpl-delete={row.id}
                  >
                    删除
                  </button>
                </div>
              </div>
            ))}
          </div>
        </aside>
      </div>

      {preview ? (
        <div className="modal-overlay tpl-preview__overlay" onClick={() => setPreview(null)}>
          <div
            className="modal-card tpl-preview"
            data-tpl-preview-modal
            onClick={(event) => event.stopPropagation()}
          >
            <div className="modal-header">
              <h3>{preview.title}</h3>
              <button type="button" className="secondary-btn small-btn" onClick={() => setPreview(null)}>
                关闭
              </button>
            </div>
            <div className="tpl-preview__body">
              {preview.kind === 'image' ? (
                <img src={preview.url} alt={preview.title} />
              ) : (
                <iframe src={preview.url} title={preview.title} />
              )}
            </div>
          </div>
        </div>
      ) : null}
    </>
  );
}
