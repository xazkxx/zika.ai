/**
 * ArchiveImportDialog —— 档案 Excel 导入弹窗（2026-10-20，问题 2：导入导出内嵌到业务页）
 *
 * 背景：原来左侧有独立的「导入导出」菜单，用户点进去像进了一个孤岛 ——
 * 我在客户档案里想导客户，却要先跑到另一个菜单里再找"客户档案"那一行。
 * 现在把导入搬到**每个档案列表页的右上角**，「导入」按钮在哪个页面，
 * 导的就是那类档案，不需要再选一次类别。
 *
 * 三步流程（刻意做成"看得见的三步"，不是一点就写库）：
 *   ① 下载模板 → 用户填数据；
 *   ② 选文件 → **先预检（dry_run）**，把"新增几条 / 更新几条 / 跳过几条 / 失败几条"
 *      摆在桌面上；
 *   ③ 用户看清楚了再点「确认导入」才真正写库。
 * 预检这一步是防呆的核心：Excel 导入最容易出的事故是"列错位了还点了导入"，
 * 结果是几百条脏数据进库。多一次确认，少一次半夜清数据。
 *
 * 职责边界：
 *   · 只认 `kind`（products/customers/suppliers/warehouses/employees）；
 *   · 预检结论**不落库**，`dry_run=true` 由后端保证；
 *   · 导入成功后调 `onImported()`，由页面薄壳负责刷新自己的列表
 *     （本组件不知道 App 里有哪些 state，也不该知道）。
 */

import { useCallback, useEffect, useRef, useState } from 'react';

import { API_BASE } from '../../lib/appLib.js';
import { saveBlobSmart } from '../../lib/download.js';
import './archive-import.css';

/** 类别 → 中文名。文案与后端 `excel_io.TITLES` 对齐（去掉"导入模板"四个字）。
 *  `sales-orders`（2026-10-20）走的是**单据**导入引擎：多行合一张单、整单阻断、
 *  没有更新语义 —— 统计位"更新"恒为 0，结果区会追加生成的系统单号。 */
const KIND_LABEL = {
  products: '商品档案',
  customers: '客户档案',
  suppliers: '供应商档案',
  warehouses: '仓库档案',
  employees: '员工档案',
  'sales-orders': '历史销售单',
};

/** 单据导入和档案导入的文案差异（避免"条/张"混着说让用户看不懂） */
const KIND_NOUN = {
  'sales-orders': '张单',
};

function authHeaders() {
  // 与全站一致：token 存 localStorage（`erp_token`），后端无 token 时业务接口也放行，
  // 但**有 token 就必须带**，否则多账套会串到 public 账套去。
  const token = typeof window !== 'undefined' ? window.localStorage.getItem('erp_token') : '';
  return token ? { Authorization: `Bearer ${token}` } : {};
}

export default function ArchiveImportDialog({
  open = false,
  kind = 'customers',
  onClose,
  /** 导入成功回调：让页面自己刷新列表（参数是后端的导入结果） */
  onImported,
}) {
  const label = KIND_LABEL[kind] || '档案';
  const noun = KIND_NOUN[kind] || '条';
  const isDocs = kind === 'sales-orders';

  const [busy, setBusy] = useState('');
  const [error, setError] = useState('');
  const [file, setFile] = useState(null);
  const [preview, setPreview] = useState(null);
  const [result, setResult] = useState(null);
  const fileRef = useRef(null);

  // 每次打开复位：上一次的预检结论留在框里，用户会以为"这次也预检过了"
  useEffect(() => {
    if (!open) return;
    setBusy('');
    setError('');
    setFile(null);
    setPreview(null);
    setResult(null);
  }, [open, kind]);

  // Esc 关闭 —— 与全站其他弹窗（合同、打印、导出选列）保持同一个手感。
  // 用捕获阶段并 stopPropagation：App 里有全局 Esc 处理（关抽屉等），
  // 不拦一下会出现"弹窗关了、后面的抽屉也一起关了"。
  useEffect(() => {
    if (!open) return undefined;
    const onKeyDown = (event) => {
      if (event.key !== 'Escape') return;
      // 正在下载/预检/写库时不许中途关：请求已经发出去了，关掉弹窗用户
      // 就看不到结果，还以为"没导进去"（其实可能已经写了一半）。
      if (busy) return;
      event.stopPropagation();
      onClose?.();
    };
    window.addEventListener('keydown', onKeyDown, true);
    return () => window.removeEventListener('keydown', onKeyDown, true);
  }, [open, busy, onClose]);

  const downloadTemplate = useCallback(async () => {
    setError('');
    setBusy('template');
    try {
      const response = await fetch(`${API_BASE}/excel/templates/${kind}`, { headers: authHeaders() });
      if (!response.ok) {
        const detail = await response.json().catch(() => ({}));
        throw new Error(typeof detail.detail === 'string' ? detail.detail : '模板下载失败');
      }
      const blob = await response.blob();
      // 文件名优先取 filename*=（后端用 UTF-8 编码，中文名不会乱码）
      const disposition = response.headers.get('content-disposition') || '';
      const utf8Match = /filename\*=UTF-8''([^;]+)/i.exec(disposition);
      const plainMatch = /filename="?([^";]+)"?/i.exec(disposition);
      const name = utf8Match
        ? decodeURIComponent(utf8Match[1])
        : plainMatch
          ? plainMatch[1]
          : `${label}导入模板.xlsx`;
      // 模板也是 Excel：走统一落盘口，否则用户下完模板填好、再导入时
      // 我们自己的导出文件反而"打不开"（带来源标记 → 受保护视图）
      await saveBlobSmart(blob, name);
    } catch (err) {
      setError(err.message || '模板下载失败');
    } finally {
      setBusy('');
    }
  }, [kind, label]);

  const runImport = useCallback(
    async (target, dryRun) => {
      const form = new FormData();
      form.append('file', target);
      const response = await fetch(
        `${API_BASE}/excel/import/${kind}?mode=upsert&dry_run=${dryRun ? 'true' : 'false'}`,
        { method: 'POST', headers: authHeaders(), body: form },
      );
      const data = await response.json().catch(() => ({}));
      if (!response.ok) {
        throw new Error(typeof data.detail === 'string' ? data.detail : '导入失败');
      }
      return data;
    },
    [kind],
  );

  const pickFile = useCallback(
    async (event) => {
      const picked = event.target.files && event.target.files[0];
      // 立刻清空 input.value：否则用户改完同一个文件再选一次不会触发 change
      event.target.value = '';
      if (!picked) return;
      setError('');
      setResult(null);
      setPreview(null);
      setFile(picked);
      setBusy('preview');
      try {
        // ⚠️ dry_run=true：这一步**不写库**，只回一份"会发生什么"
        const data = await runImport(picked, true);
        setPreview(data);
      } catch (err) {
        setFile(null);
        setError(err.message || '预检失败');
      } finally {
        setBusy('');
      }
    },
    [runImport],
  );

  const confirmImport = useCallback(async () => {
    if (!file) return;
    setError('');
    setBusy('commit');
    try {
      const data = await runImport(file, false);
      setResult(data);
      setPreview(null);
      if (typeof onImported === 'function') onImported(data);
    } catch (err) {
      setError(err.message || '导入失败');
    } finally {
      setBusy('');
    }
  }, [file, runImport, onImported]);

  if (!open) return null;

  const previewFailed = preview && Number(preview.failed || 0) > 0;

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div
        className="modal-card archive-import"
        role="dialog"
        aria-modal="true"
        aria-label={`导入${label}`}
        data-archive-import={kind}
        onClick={(event) => event.stopPropagation()}
      >
        <div className="modal-header">
          <h3>导入{label}</h3>
          <button type="button" className="close-btn" onClick={onClose} aria-label="关闭">
            ×
          </button>
        </div>

        <div className="modal-body">
          {/* ① 下载模板 */}
          <section className="archive-import__step" data-import-step="template">
            <span className="archive-import__no">1</span>
            <div className="archive-import__body">
              <h4>先下载模板，按表头填数据</h4>
            {isDocs ? (
              <p>
                模板第 3 行是示例（不会导入），请从第 4 行开始填写。同一个「单据编号」的多行会合成
                一张单；客户 / 商品 / 仓库名必须和档案里的名字对得上（全角半角、空格差异没关系），
                <b>有一行认不出，那一整张单都不会导入</b>。已导入过的单据编号重复导入会自动跳过。
              </p>
            ) : (
              <p>
                模板里第 3 行是示例（不会导入），请从第 4 行开始填写。
                编码/型号这类"识别谁是谁"的列不要留空 —— 留空会被当成新记录。
              </p>
            )}
              <button
                type="button"
                className="secondary-btn small-btn"
                data-import-template
                disabled={busy === 'template'}
                onClick={downloadTemplate}
              >
                {busy === 'template' ? '下载中…' : '下载导入模板'}
              </button>
            </div>
          </section>

          {/* ② 选文件 → 预检 */}
          <section className="archive-import__step" data-import-step="preview">
            <span className="archive-import__no">2</span>
            <div className="archive-import__body">
              <h4>选择填好的 Excel，先做预检</h4>
              <p>预检只统计"会新增/更新/跳过多少条"，不会写进系统。看清了再确认。</p>
              <input
                ref={fileRef}
                type="file"
                accept=".xlsx,.xls"
                onChange={pickFile}
                data-import-file
                className="archive-import__file"
              />
              {busy === 'preview' ? <p className="archive-import__busy">正在预检…</p> : null}
              {preview ? (
                <div className="archive-import__stats" data-import-preview>
                  <span className="archive-import__stat archive-import__stat--new">
                    将建 <b>{preview.created ?? 0}</b>{noun}
                  </span>
                  <span className="archive-import__stat archive-import__stat--upd">
                    更新 <b>{preview.updated ?? 0}</b>
                  </span>
                  <span className="archive-import__stat">
                    跳过 <b>{preview.skipped ?? 0}</b>
                  </span>
                  <span
                    className={`archive-import__stat${previewFailed ? ' archive-import__stat--bad' : ''}`}
                  >
                    失败 <b>{preview.failed ?? 0}</b>
                  </span>
                </div>
              ) : null}
              {previewFailed ? (
                <p className="archive-import__warn">
                  有 {preview.failed} 行没通过校验（常见原因：编码重复、必填列空着、数字列填了文字）。
                  这些行不会导入，其余行照常导入。逐行原因可以导入完成后看结果。
                </p>
              ) : null}
              {Array.isArray(preview?.errors) && preview.errors.length > 0 ? (
                <ul className="archive-import__errors" data-import-errors>
                  {preview.errors.slice(0, 8).map((item, index) => (
                    <li key={index}>
                      第 {item.row ?? '?'} 行：{item.message || item.error || '校验未通过'}
                    </li>
                  ))}
                  {preview.errors.length > 8 ? <li>…还有 {preview.errors.length - 8} 条</li> : null}
                </ul>
              ) : null}
            </div>
          </section>

          {/* ③ 结果 */}
          {result ? (
            <section className="archive-import__step archive-import__step--done" data-import-result>
              <span className="archive-import__no archive-import__no--ok">✓</span>
              <div className="archive-import__body">
                <h4>导入完成</h4>
                <p>
                  新建 <b>{result.created ?? 0}</b> {noun}、跳过 <b>{result.skipped ?? 0}</b> {noun}、
                  失败 <b>{result.failed ?? 0}</b> {isDocs ? '张' : '条'}。
                  列表已经刷新，可以直接核对。
                </p>
                {/* 单据导入：把生成的系统单号直接报出来，用户不用去列表里翻 */}
                {isDocs && Array.isArray(result.created_orders) && result.created_orders.length > 0 ? (
                  <p data-import-created-orders>
                    生成单号：
                    {result.created_orders.map((item) => item.order_no).join('、')}
                  </p>
                ) : null}
              </div>
            </section>
          ) : null}

          {error ? (
            <p className="archive-import__error" role="alert" data-import-error>
              {error}
            </p>
          ) : null}
        </div>

        <div className="modal-actions">
          <button type="button" className="secondary-btn" onClick={onClose}>
            {result ? '关闭' : '取消'}
          </button>
          <button
            type="button"
            className="primary-btn"
            data-import-confirm
            disabled={!preview || busy === 'commit'}
            onClick={confirmImport}
            title={preview ? '确认后才会真正写进系统' : '请先选择文件做预检'}
          >
            {busy === 'commit' ? '导入中…' : '确认导入'}
          </button>
        </div>
      </div>
    </div>
  );
}
