// 客户文件抽屉（第 13 批 · 第三阶段 · 第二步）
//
// 入口：「客户档案」列表操作列的「📁 文件」按钮 → 右侧滑出。
//
// 为什么挂在 `PartnersBoard` 内部而不是走 App.jsx：
//   · PartnersBoard 的职责边界写得很清楚 —— "只吃 props、不 import App.jsx、不读 ctx"。
//     抽屉需要的只有「客户 id / 名字」，这两样就在 `row` 上；文件接口又是自包含的
//     （token 从 localStorage 取，与 partnerTreeApi 同一套约定）。
//   · 走 App.jsx 要多加 1 个 state + 1 处渲染 + 传给薄壳，跨 3 个文件；
//     挂在这里，改动只在 PartnersBoard 一个文件里，且**供应商页天然不受影响**。
//   · 依赖方向也顺：partners → (自己目录下的) CustomerFilesDrawer，没有反向引用。
//
// 与后端 8 个接口的对应关系（`app/api/v1/routes/erp_customer_file.py`）：
//   GET    /customer-files/meta               → 分类字典 + 大小上限（模块级缓存，只拉一次）
//   GET    /customers/{id}/files              → 列表（分类 / 关键词都在后端过滤）
//   GET    /customers/{id}/files/stats        → 每个 Tab 的角标
//   POST   /customers/{id}/files              → 上传（同内容去重，命中返回 200 + duplicate:true）
//   GET    /customer-files/{id}/download      → 下载（blob + 解析中文名）
//   DELETE /customer-files/{id}?purge=true    → 删除（默认连磁盘文件一起删）
//
// 没接的两个（PATCH 改名改备注、GET .../files/count）：本步只做用户点名的四件事
// （上传 / 列表 / 下载 / 删除），接口留着，等下一轮需要再加，避免一次做太多。

import { useCallback, useEffect, useMemo, useRef, useState } from 'react';

import { API_BASE } from '../../lib/appLib.js';
import {
  CATEGORY_ALL,
  base64ToBlob,
  buildListPath,
  categoryLabel,
  categoryTabs,
  checkUpload,
  fileKindOf,
  fileNameFromDisposition,
  formatFileSize,
  formatUploadedAt,
} from '../../lib/customerFiles.js';
import './customerFilesDrawer.css';

// ---------------------------------------------------------------------------
// 请求工具（与 ContractsLedger 同一套口径，但各自独立，不互相 import）
// ---------------------------------------------------------------------------

function authHeaders() {
  const token = localStorage.getItem('erp_token') || '';
  return token ? { Authorization: `Bearer ${token}` } : {};
}

async function api(path, options = {}) {
  const response = await fetch(`${API_BASE}${path}`, {
    ...options,
    headers: { ...authHeaders(), ...(options.headers || {}) },
  });
  if (!response.ok) {
    const data = await response.json().catch(() => ({}));
    const detail = data.detail;
    throw new Error(typeof detail === 'string' ? detail : `请求失败（HTTP ${response.status}）`);
  }
  return response.json();
}

function saveBlob(blob, filename) {
  if (!blob || blob.size === 0) throw new Error('下载到的文件是空的，请重试');
  const url = URL.createObjectURL(blob);
  const link = document.createElement('a');
  link.href = url;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  link.remove();
  // 立刻 revoke 在 Chrome 上偶发"下载中断"，隔一拍更稳
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

/** meta 是全局字典（不随客户变），拉一次就够；失败不缓存，下次重开会重试。 */
let metaCache = null;

// ---------------------------------------------------------------------------
// 主组件
// ---------------------------------------------------------------------------

export default function CustomerFilesDrawer({ customer, onClose }) {
  const customerId = customer?.id;
  const customerName = customer?.name || '客户';

  const [meta, setMeta] = useState(metaCache);
  const [stats, setStats] = useState(null);
  const [category, setCategory] = useState(CATEGORY_ALL);
  const [keywordInput, setKeywordInput] = useState('');
  const [keyword, setKeyword] = useState('');
  const [rows, setRows] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [busy, setBusy] = useState(''); // '' | 'upload' | `download:${id}` | `delete:${id}`
  const [dragOver, setDragOver] = useState(false);
  // 上传落到哪个分类：选中具体 Tab 时跟着 Tab 走；在「全部」下由用户自己挑
  const [uploadCategory, setUploadCategory] = useState('other');

  const inputRef = useRef(null);
  const closeRef = useRef(null);
  const searchTimer = useRef(null);

  const tabs = useMemo(() => categoryTabs(meta, stats), [meta, stats]);
  const maxMb = meta?.max_mb || 20;

  // ---- meta（只拉一次）----
  useEffect(() => {
    let alive = true;
    api('/customer-files/meta')
      .then((data) => {
        metaCache = data;
        if (alive) setMeta(data);
      })
      .catch((err) => {
        // 字典拉不到不阻断主流程：Tab 用兜底分类渲染，上传仍可提交（后端才是校验方）
        if (alive) setError(`分类字典加载失败：${err.message}（已用内置分类兜底）`);
      });
    return () => {
      alive = false;
    };
  }, []);

  // ---- 统计（角标）----
  const loadStats = useCallback(async () => {
    if (!customerId) return;
    try {
      const data = await api(`/customers/${customerId}/files/stats`);
      setStats(data);
    } catch {
      // 角标拿不到不影响列表，静默降级成 `…`
      setStats(null);
    }
  }, [customerId]);

  // ---- 列表 ----
  // ⚠️ 「只认最后一次请求」守卫：切 Tab / 打字搜索时会有多个请求在飞，
  //    没有它，先发后到的响应会把新分类的结果覆盖成旧分类的（表现为"切了 Tab 内容没变"）。
  const listTicket = useRef(0);
  const loadList = useCallback(
    async (nextCategory, nextKeyword) => {
      if (!customerId) return;
      const ticket = listTicket.current + 1;
      listTicket.current = ticket;
      setLoading(true);
      setError('');
      try {
        const data = await api(buildListPath(customerId, { category: nextCategory, keyword: nextKeyword }));
        if (ticket !== listTicket.current) return;
        setRows(Array.isArray(data) ? data : []);
      } catch (err) {
        if (ticket !== listTicket.current) return;
        setRows([]);
        setError(err.message);
      } finally {
        if (ticket === listTicket.current) setLoading(false);
      }
    },
    [customerId],
  );

  useEffect(() => {
    loadList(category, keyword);
  }, [loadList, category, keyword]);

  useEffect(() => {
    loadStats();
  }, [loadStats]);

  // 搜索防抖：每敲一个字就发请求，几百个文件时后端要扫全表
  useEffect(() => {
    if (searchTimer.current) clearTimeout(searchTimer.current);
    searchTimer.current = setTimeout(() => setKeyword(keywordInput), 250);
    return () => {
      if (searchTimer.current) clearTimeout(searchTimer.current);
    };
  }, [keywordInput]);

  // ---- 打开时锁滚动 + ESC 关闭 + 焦点落到关闭按钮 ----
  useEffect(() => {
    const previous = document.body.style.overflow;
    document.body.style.overflow = 'hidden';
    closeRef.current?.focus();
    const onKeyDown = (event) => {
      if (event.key === 'Escape') {
        event.stopPropagation();
        onClose?.();
      }
    };
    document.addEventListener('keydown', onKeyDown);
    return () => {
      document.body.style.overflow = previous;
      document.removeEventListener('keydown', onKeyDown);
    };
  }, [onClose]);

  // ---- 切 Tab：上传分类跟着走（在「全部」下保持用户上次的选择）----
  function switchCategory(code) {
    setCategory(code);
    if (code !== CATEGORY_ALL) setUploadCategory(code);
    setNotice('');
    setError('');
  }

  // ---- 上传 ----
  const uploadFiles = useCallback(
    async (fileList) => {
      const files = Array.from(fileList || []);
      if (!files.length) return;
      setNotice('');
      setError('');

      // 先整体预检：有一个不合格就整体不动，避免"传了 2 个第 3 个报错"的半截状态
      for (const file of files) {
        const reason = checkUpload(file, metaCache || meta);
        if (reason) {
          setError(reason);
          return;
        }
      }

      setBusy('upload');
      let added = 0;
      let duplicated = 0;
      try {
        for (let index = 0; index < files.length; index += 1) {
          const file = files[index];
          setNotice(`正在上传 ${index + 1}/${files.length}：${file.name}`);
          const body = new FormData();
          body.append('file', file, file.name);
          body.append('category', uploadCategory || 'other');
          body.append('uploaded_by', localStorage.getItem('erp_user_name') || 'admin');
          const result = await api(`/customers/${customerId}/files`, { method: 'POST', body });
          if (result?.duplicate) duplicated += 1;
          else added += 1;
        }
        const parts = [];
        if (added) parts.push(`新增 ${added} 个`);
        if (duplicated) parts.push(`${duplicated} 个内容重复已跳过`);
        setNotice(`上传完成：${parts.join('，')}`);
        await Promise.all([loadList(category, keyword), loadStats()]);
      } catch (err) {
        setError(err.message);
        // 已经成功的部分也要刷出来，不能让用户以为一个都没成
        await Promise.all([loadList(category, keyword), loadStats()]);
      } finally {
        setBusy('');
      }
    },
    [category, customerId, keyword, loadList, loadStats, meta, uploadCategory],
  );

  function onPick(event) {
    const files = event.target.files;
    uploadFiles(files);
    // 清空 value：否则同一个文件连选两次不触发 change
    event.target.value = '';
  }

  // ---- 下载（中文名靠后端 JSON 通道里的 filename 原值）----
  async function download(row) {
    setBusy(`download:${row.id}`);
    setError('');
    setNotice('');
    try {
      // ⚠️ 必须走 `Accept: application/json` 这条通道，原因与 `erp_print.py:106` 记的
      //    是同一个坑：浏览器（Edge/Chrome）会把 `application/pdf` 的响应从 JS 手里
      //    接管走，`fetch()` 拿到的是 **204 + 空 body**，而 `response.ok` 仍为 true ——
      //    于是前端会"成功"保存一个 0 字节的空文件。实测本抽屉第一版就撞上了。
      //    JSON 通道里 `filename` 是原文（不经过 Content-Disposition），中文天然不乱码。
      const response = await fetch(`${API_BASE}/customer-files/${row.id}/download`, {
        headers: { ...authHeaders(), Accept: 'application/json' },
      });
      if (!response.ok) {
        const data = await response.json().catch(() => ({}));
        throw new Error(typeof data.detail === 'string' ? data.detail : `下载失败（HTTP ${response.status}）`);
      }

      const contentType = response.headers.get('content-type') || '';
      if (contentType.includes('application/json')) {
        const data = await response.json();
        const blob = base64ToBlob(data.content_base64, data.content_type);
        const filename = data.filename || row.original_name || '下载文件';
        saveBlob(blob, filename);
        setNotice(`已开始下载：${filename}`);
      } else {
        // 兜底：万一后端版本较老不认 Accept（返回二进制），退回解析 Content-Disposition
        const blob = await response.blob();
        const filename = fileNameFromDisposition(
          response.headers.get('content-disposition'),
          row.original_name || '下载文件',
        );
        saveBlob(blob, filename);
        setNotice(`已开始下载：${filename}`);
      }
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy('');
    }
  }

  // ---- 删除 ----
  async function remove(row) {
    const ok = window.confirm(`确定删除「${row.original_name}」？\n磁盘上的文件会一起删掉，不可恢复。`);
    if (!ok) return;
    setBusy(`delete:${row.id}`);
    setError('');
    setNotice('');
    try {
      const result = await api(`/customer-files/${row.id}?purge=true`, { method: 'DELETE' });
      setNotice(result?.message || '已删除');
      await Promise.all([loadList(category, keyword), loadStats()]);
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy('');
    }
  }

  // ---- 拖拽 ----
  function onDrop(event) {
    event.preventDefault();
    setDragOver(false);
    if (busy === 'upload') return;
    uploadFiles(event.dataTransfer?.files);
  }

  const emptyText = keyword
    ? '没有匹配的文件，换个关键词试试'
    : category === CATEGORY_ALL
      ? '这个客户还没有归档文件'
      : `「${categoryLabel(meta, category)}」分类下还没有文件`;

  return (
    <div className="pcfd-root">
      <div className="pcfd-backdrop" onClick={() => onClose?.()} aria-hidden="true" />

      <aside
        className={`pcfd${dragOver ? ' is-dragover' : ''}`}
        role="dialog"
        aria-modal="true"
        aria-label={`${customerName} 的文件`}
        onDragOver={(event) => {
          event.preventDefault();
          if (busy !== 'upload') setDragOver(true);
        }}
        onDragLeave={(event) => {
          // 只有真正离开抽屉才收起提示：子元素之间移动也会触发 dragleave
          if (!event.currentTarget.contains(event.relatedTarget)) setDragOver(false);
        }}
        onDrop={onDrop}
      >
        {/* ---------------- 头部 ---------------- */}
        <header className="pcfd__head">
          {/* 2026-10-20 任务二：二级抽屉统一在左上角给「← 返回」。
              原先只有一个右上角的 × —— 那是"关闭"，不是"返回"；
              用户从客户列表点进来看完文件，下意识找的是左上角的返回。两者并存不冲突。 */}
          <button
            type="button"
            className="pcfd__back"
            data-drawer-back
            onClick={() => onClose?.()}
            title="返回客户列表"
          >
            ← 返回
          </button>
          <div className="pcfd__head-main">
            <h3 className="pcfd__title">
              文件归档
              <span className="pcfd__count">{stats ? `${stats.total} 个` : '…'}</span>
            </h3>
            <p className="pcfd__subtitle" title={customerName}>
              {customer?.code ? <span className="pcfd__code">{customer.code}</span> : null}
              {customerName}
            </p>
          </div>
          <button
            ref={closeRef}
            type="button"
            className="pcfd__close"
            onClick={() => onClose?.()}
            aria-label="关闭文件抽屉"
          >
            ×
          </button>
        </header>

        {/* ---------------- 分类 Tab ---------------- */}
        <nav className="pcfd__tabs" role="tablist" aria-label="文件分类">
          {tabs.map((tab) => (
            <button
              key={tab.code || 'all'}
              type="button"
              role="tab"
              aria-selected={category === tab.code}
              className={`pcfd__tab${category === tab.code ? ' is-active' : ''}`}
              data-category={tab.code || 'all'}
              onClick={() => switchCategory(tab.code)}
            >
              {tab.label}
              <span className="pcfd__tab-count">{tab.count === null ? '…' : tab.count}</span>
            </button>
          ))}
        </nav>

        {/* ---------------- 工具条 ---------------- */}
        <div className="pcfd__toolbar">
          <input
            className="pcfd__search"
            type="search"
            placeholder="搜索文件名 / 备注…"
            value={keywordInput}
            onChange={(event) => setKeywordInput(event.target.value)}
          />
          <button
            type="button"
            className="pcfd__upload"
            disabled={busy === 'upload'}
            onClick={() => inputRef.current?.click()}
          >
            {busy === 'upload' ? '上传中…' : '＋ 上传文件'}
          </button>
          {/* 不走 <label>：label 包住 file input 时点抽屉任何位置都可能弹框（踩过）。 */}
          <input
            ref={inputRef}
            type="file"
            multiple
            hidden
            data-pcfd-upload
            onChange={onPick}
            accept={meta?.accept_attr || undefined}
          />
        </div>

        {/* 归档到哪个分类：切了具体 Tab 就跟着 Tab，这里只在「全部」下出现 */}
        {category === CATEGORY_ALL ? (
          <div className="pcfd__target">
            <span className="pcfd__target-label">归档到</span>
            {(meta?.categories || []).map((item) => (
              <button
                key={item.code}
                type="button"
                className={`pcfd__chip${uploadCategory === item.code ? ' is-active' : ''}`}
                onClick={() => setUploadCategory(item.code)}
              >
                {item.label}
              </button>
            ))}
          </div>
        ) : null}

        {/* ---------------- 提示条 ---------------- */}
        {error ? (
          <div className="pcfd__alert pcfd__alert--error" role="alert">
            {error}
          </div>
        ) : null}
        {!error && notice ? <div className="pcfd__alert pcfd__alert--ok">{notice}</div> : null}

        {/* ---------------- 列表 ---------------- */}
        <div className="pcfd__list" role="tabpanel">
          <div className="pcfd__list-head">
            <span className="pcfd__col-name">名称</span>
            <span className="pcfd__col-size">大小</span>
            <span className="pcfd__col-time">上传时间</span>
            <span className="pcfd__col-ops">操作</span>
          </div>

          {loading ? (
            <div className="pcfd__skeleton" data-pcfd-skeleton>
              {[0, 1, 2].map((i) => (
                <span key={i} className="pcfd__skeleton-row" />
              ))}
            </div>
          ) : rows.length === 0 ? (
            <div className="pcfd__empty">
              <p className="pcfd__empty-title">{emptyText}</p>
              <p className="pcfd__empty-desc">
                支持 PDF / Word / Excel / 图片，单个不超过 {maxMb}MB。也可以直接把文件拖到这个面板里。
              </p>
            </div>
          ) : (
            <ul className="pcfd__rows">
              {rows.map((row) => {
                const kind = fileKindOf(row.original_name);
                const downloading = busy === `download:${row.id}`;
                const deleting = busy === `delete:${row.id}`;
                return (
                  <li className="pcfd__row" key={row.id} data-file-id={row.id}>
                    <span className="pcfd__col-name">
                      <span className="pcfd__name-line">
                        {kind ? <span className={`pcfd__kind pcfd__kind--${kind.toLowerCase()}`}>{kind}</span> : null}
                        <span className="pcfd__name" title={row.original_name}>
                          {row.original_name}
                        </span>
                      </span>
                      <span className="pcfd__meta-line">
                        <span className="pcfd__tag">{categoryLabel(meta, row.category)}</span>
                        {row.file_exists === false ? (
                          <span className="pcfd__tag pcfd__tag--missing">文件已丢失</span>
                        ) : null}
                        {row.note ? <span className="pcfd__note">{row.note}</span> : null}
                      </span>
                    </span>
                    <span className="pcfd__col-size">{formatFileSize(row.file_size)}</span>
                    <span className="pcfd__col-time">{formatUploadedAt(row.uploaded_at)}</span>
                    <span className="pcfd__col-ops">
                      <button
                        type="button"
                        className="pcfd__op"
                        disabled={row.file_exists === false || downloading}
                        onClick={() => download(row)}
                        title={row.file_exists === false ? '磁盘上已找不到这个文件' : '下载'}
                      >
                        {downloading ? '下载中' : '下载'}
                      </button>
                      <button
                        type="button"
                        className="pcfd__op pcfd__op--danger"
                        disabled={deleting}
                        onClick={() => remove(row)}
                      >
                        {deleting ? '删除中' : '删除'}
                      </button>
                    </span>
                  </li>
                );
              })}
            </ul>
          )}
        </div>

        {/* ---------------- 底部 ---------------- */}
        <footer className="pcfd__foot">
          {rows.length > 0 ? `当前显示 ${rows.length} 个${stats ? ` / 共 ${stats.total} 个` : ''}` : `单个文件上限 ${maxMb}MB`}
          <span className="pcfd__foot-dot">·</span>
          同一份文件重复上传会自动跳过
        </footer>

        {dragOver ? <div className="pcfd__dropzone">松手即上传</div> : null}
      </aside>
    </div>
  );
}
