// 合同台账 · 就地新建往来单位（客户 / 供应商）
//
// 为什么单独做成组件：
//   合同弹窗已经 700 多行（识别、明细、冲突条全在里面），再塞一张表单就是灾难。
//   这里只做一件事：把"缺档案"这个断点补上 —— 名称已经由 OCR 填好，用户按一下保存。
//
// 设计要点（每一条都是防呆，不是装饰）：
//   ① 名称**预填且聚焦全选**：用户多半只想按一下保存，不想再找输入框；
//   ② 编码留空 = 后端自动生成（`CUS` + 日期 + 3 位流水，与单号同一套 `_next_doc_no`），
//      所以编码框的 placeholder 必须写"留空自动生成"，否则用户会以为必填而卡住；
//   ③ 保存前先问父组件"这名字是不是已经存在了" —— 存在就直接选中，**不重复建档**
//      （两家同名客户是最难查的一类脏数据）；
//   ④ 只提交用户真填了的字段：空串提交上去会把档案的默认值覆盖成空。
//
// 与合同页的关系：本组件**不碰**合同表单，建完把整条档案 `onCreated(item)` 交回去，
// 由父组件决定怎么填下拉、怎么清提示。

import { useEffect, useRef, useState } from 'react';

import { API_BASE } from '../../lib/appLib.js';

function authHeaders() {
  const token = localStorage.getItem('erp_token') || '';
  return token ? { Authorization: `Bearer ${token}` } : {};
}

const KINDS = {
  customer: { endpoint: '/customers', label: '客户', codePrefix: 'CUS' },
  supplier: { endpoint: '/suppliers', label: '供应商', codePrefix: 'SUP' },
};

const EMPTY = { code: '', name: '', contact: '', phone: '', address: '', note: '' };

export default function PartyQuickCreate({ open, kind, defaultName, onClose, onCreated, findExisting }) {
  const meta = KINDS[kind] || KINDS.customer;
  const [form, setForm] = useState(EMPTY);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');
  const nameRef = useRef(null);

  // 每次打开都重置：名称用 OCR 识别出来的那个，其余留空
  useEffect(() => {
    if (!open) return undefined;
    setForm({ ...EMPTY, name: String(defaultName || '').trim() });
    setSaving(false);
    setError('');
    // 聚焦 + 全选：用户想改名可以直接打，想不改就直接 Tab 到保存。
    // ⚠️ 不要用 setTimeout 推迟 —— effect 跑的时候 DOM 已经提交，同步聚焦就行；
    //    加延时反而留出一段"打字掉到地上"的窗口（界面台第一版就是被这 30ms 卡红的）。
    nameRef.current?.focus();
    nameRef.current?.select();
    return undefined;
  }, [open, defaultName, kind]);

  // Esc 关闭（弹窗套弹窗时，Esc 只关最上面这一层）
  useEffect(() => {
    if (!open) return undefined;
    const onKeyDown = (event) => {
      if (event.key === 'Escape') {
        event.stopPropagation();
        onClose();
      }
    };
    window.addEventListener('keydown', onKeyDown, true);
    return () => window.removeEventListener('keydown', onKeyDown, true);
  }, [open, onClose]);

  if (!open) return null;

  const patch = (key, value) => setForm((prev) => ({ ...prev, [key]: value }));

  const submit = async (event) => {
    event.preventDefault();
    if (saving) return;
    const name = form.name.trim();
    if (!name) {
      setError(`请填写${meta.label}名称`);
      nameRef.current?.focus();
      return;
    }

    // 同名已存在 → 直接用那条，不再建一条一模一样的（父组件传进来的查找函数）
    const existing = findExisting?.(name);
    if (existing) {
      setSaving(false);
      onCreated(existing, { reused: true });
      return;
    }

    setSaving(true);
    setError('');
    try {
      // 只提交非空字段：空串会把档案里的手机/地址覆盖成空
      const payload = { name };
      for (const key of ['code', 'contact', 'phone', 'address', 'note']) {
        const value = String(form[key] || '').trim();
        if (value) payload[key] = value;
      }
      const response = await fetch(`${API_BASE}${meta.endpoint}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...authHeaders() },
        body: JSON.stringify(payload),
      });
      const data = await response.json().catch(() => ({}));
      if (!response.ok) {
        const detail = data.detail;
        const message =
          typeof detail === 'string'
            ? detail
            : Array.isArray(detail) && detail[0]?.msg
              ? `${meta.label}保存失败：${detail[0].msg}`
              : `保存失败（HTTP ${response.status}）`;
        throw new Error(message);
      }
      onCreated(data, { reused: false });
    } catch (err) {
      setError(err.message || '保存失败，请重试');
      setSaving(false);
    }
  };

  return (
    <div
      className="modal-backdrop cledger__quick-backdrop"
      role="dialog"
      aria-modal="true"
      aria-label={`新建${meta.label}`}
      onMouseDown={(event) => {
        if (event.target === event.currentTarget && !saving) onClose();
      }}
    >
      <div className="modal-card cledger__quick">
        <div className="modal-header">
          <h3>新建{meta.label}</h3>
          <button type="button" className="close-btn" onClick={onClose} aria-label="关闭" disabled={saving}>
            ×
          </button>
        </div>
        <form onSubmit={submit}>
          <div className="modal-body">
            <p className="cledger__quick-lead" data-quick-lead>
              这个{meta.label}会直接建到档案里，保存后自动选中，不用再跑一趟基础资料。
            </p>
            {error ? (
              <div className="cledger__error" data-quick-error>
                {error}
              </div>
            ) : null}

            <div className="cledger__quick-grid">
              <div className="cledger__field cledger__field--full">
                <span>
                  {meta.label}名称 <b className="cledger__req">*</b>
                </span>
                <input
                  ref={nameRef}
                  value={form.name}
                  data-quick-name
                  onChange={(event) => patch('name', event.target.value)}
                  placeholder={`识别到的${meta.label}名称`}
                />
              </div>

              <div className="cledger__field cledger__field--full">
                <span>{meta.label}编码</span>
                <input
                  value={form.code}
                  data-quick-code
                  onChange={(event) => patch('code', event.target.value)}
                  placeholder={`留空自动生成（${meta.codePrefix} + 日期 + 流水，如 ${meta.codePrefix}20261019001）`}
                />
              </div>

              <div className="cledger__field">
                <span>联系人</span>
                <input value={form.contact} onChange={(event) => patch('contact', event.target.value)} />
              </div>

              <div className="cledger__field">
                <span>联系电话</span>
                <input value={form.phone} onChange={(event) => patch('phone', event.target.value)} />
              </div>

              <div className="cledger__field cledger__field--full">
                <span>地址</span>
                <input value={form.address} onChange={(event) => patch('address', event.target.value)} />
              </div>

              <div className="cledger__field cledger__field--full">
                <span>备注</span>
                <input
                  value={form.note}
                  onChange={(event) => patch('note', event.target.value)}
                  placeholder="可留空，比如「合同 OCR 时补建」"
                />
              </div>
            </div>

            <p className="cledger__quick-note">
              只有名称是必填。别的字段以后可以到「基础资料 → {meta.label}档案」里补。
            </p>
          </div>

          <div className="modal-actions">
            <button type="button" className="secondary-btn" onClick={onClose} disabled={saving}>
              取消
            </button>
            <button type="submit" className="primary-btn" data-quick-save disabled={saving}>
              {saving ? '保存中…' : `保存并使用该${meta.label}`}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
