// 增强版对账单编辑器（第 13 批 · 第三阶段 · 第三步）
//
// 定位：一张对账单 = 一个往来单位 × 一个账期。这一页负责「生成 → 勾选核对 → 改数 →
// 保存 → 打印/导出」的完整闭环。
//
// 和现有「销售对账单」（`selectedTab === 'sales-statement'`，App.jsx 里的老页面）
// 是**两个东西**：老页面按销售单据实时聚合、只读、不可存草稿；这一页操作的是
// `statements` / `statement_items` 两张真表，头部 10 个金额是**冗余快照**，
// 一旦确认就是法律凭证 —— 所以"重算"必须是一个显式动作（后端 `/recalc`）。
//
// 三条刻意的取舍：
//
// 1. **前端算的金额只用于预览，绝不提交**
//    `lib/statementEditor.js::computeTotals()` 是后端 `compute_totals()` 的镜像，
//    只为了勾选/改数时立刻看到"期末应收"变化。保存时提交的是**行级原始金额**，
//    头部 10 个数字全部由后端重算 —— 两边各算一份但只有一份落库，避免"界面 100、库里 98"。
//
// 2. **勾选 = 是否纳入本单**
//    未勾选的行不会写进对账单（不是"置灰"）。这是需求里"根据勾选明细动态计算
//    已开票/剩余未收"最诚实的实现 —— 界面上要明确告诉用户少了几行。
//
// 3. **自己取数，不依赖 appCtx**
//    与合同台账、客户文件抽屉同一套约定：token 走 `localStorage.erp_token`，
//    组件在任何页面里都能直接复用；挂载只改 App.jsx 的 5 件套。

import { useCallback, useEffect, useMemo, useRef, useState } from 'react';

import ErpCard from '../ui/ErpCard.jsx';
import ErpDrawer from '../ui/ErpDrawer.jsx';
import ErpMoreMenu from '../ui/ErpMoreMenu.jsx';
import ErpSearchSelect from '../ui/ErpSearchSelect.jsx';
import ErpTable from '../ui/ErpTable.jsx';
import SmartCommandBar from '../agent/SmartCommandBar.jsx';
import { API_BASE, STATEMENT_SCOPES, statementScope } from '../../lib/appLib.js';
import {
  allRowKeys,
  amount,
  buildSavePayload,
  computeTotals,
  defaultPeriod,
  deriveRow,
  directionOf,
  exportQuery,
  headerCards,
  invoiceStatusLabel,
  itemKey,
  money,
  normalizeItem,
  printPath,
  sourceLabel,
  statementOptionLabel,
  statusLabel,
  toNumber,
  validateGenerate,
  validateSave,
} from '../../lib/statementEditor.js';
import { base64ToBlob, fileNameFromDisposition, saveBlob } from '../../lib/download.js';
import { exportWord } from '../../lib/wordExport.js';
// 打印二次确认（2026-10-18，需求 3）：本组件自带一份 printPdf（不走 App 的 ctx.printPdf），
// 所以这里要单独接一次，否则「增强对账单」的打印会绕过全局确认。
import { confirmPrint } from '../../lib/printConfirm.js';
import './statementEditor.css';

// ---------------------------------------------------------------------------
// 请求工具
// ---------------------------------------------------------------------------

function authHeaders() {
  const token = localStorage.getItem('erp_token') || '';
  return token ? { Authorization: `Bearer ${token}` } : {};
}

/** FastAPI 的 422 是数组 detail，直接弹出去用户只看到一坨 JSON → 压成中文 */
async function api(path, options = {}) {
  const response = await fetch(`${API_BASE}${path}`, {
    ...options,
    headers: { ...authHeaders(), ...(options.headers || {}) },
  });
  if (!response.ok) {
    const data = await response.json().catch(() => ({}));
    const detail = data.detail;
    let message = `请求失败（HTTP ${response.status}）`;
    if (typeof detail === 'string') message = detail;
    else if (Array.isArray(detail) && detail.length) {
      message = detail
        .map((item) => `${(item.loc || []).slice(1).join('.') || '参数'}：${item.msg || '不合法'}`)
        .join('；');
    }
    throw new Error(message);
  }
  if (response.status === 204) return null;
  return response.json();
}

const jsonHeaders = { 'Content-Type': 'application/json' };

// ---------------------------------------------------------------------------
// 主组件
// ---------------------------------------------------------------------------

export default function StatementEditor({
  initialScope = 'all',
  /** 从智能指令跳过来时锁定的往来单位，形如 `c:12` / `s:45`（与页面内部 partyId 同一套前缀）。
   *  不传 = 正常进入，不预选。 */
  initialParty = '',
}) {
  // 三种范围：all = 台账全景（不能生成，只能打开）；out = 应收；in = 应付。
  // 从「采购对账单」进来 initialScope='in'，「销售对账单」='out'，「增强对账单」='all'。
  // ⚠️ 不要把它改回 direction('out'|'in') 两态：那会让「全部」没有落脚点，
  //    三个菜单入口就只能靠"记得点哪个菜单"来区分，一刷新就丢。
  const [scope, setScope] = useState(() =>
    STATEMENT_SCOPES.some((item) => item.code === initialScope) ? initialScope : 'all',
  );
  // 真正落账的方向：台账模式下没有方向（生成/取数都用不到），给个占位值免得处处判空。
  const direction = scope === 'all' ? 'out' : scope;
  const scopeConfig = statementScope(scope);
  const [partyId, setPartyId] = useState('');
  const [period, setPeriod] = useState(defaultPeriod);
  const [opening, setOpening] = useState('0');

  const [customers, setCustomers] = useState([]);
  const [suppliers, setSuppliers] = useState([]);
  const [recent, setRecent] = useState([]);
  const [statement, setStatement] = useState(null);
  const [rows, setRows] = useState([]);
  const [selectedKeys, setSelectedKeys] = useState([]);
  const [note, setNote] = useState('');

  // 往来账底稿（期初 → 逐笔 → 期末）：详情页内嵌预览用。
  // 命名刻意叫 ledgerPreview —— 下面的 `preview` 是对账单自身的合计预览，两者不是一回事。
  const [ledgerPreview, setLedgerPreview] = useState(null);
  const [ledgerBusy, setLedgerBusy] = useState(false);

  // —— 搜索预览（2026-10-22）——
  // 交互拆成「看」和「写」两步：`pool` 是**只读**聚合结果（接口不写库、不占 DZ 单号），
  // `poolPicked` 是用户勾选的单据 key（`order:<id>`）。只有点「确认生成对账单」才落库。
  // 这样"想看一眼这期有什么"不再需要先浪费一个对账单号。
  const [pool, setPool] = useState(null);
  const [poolPicked, setPoolPicked] = useState([]);

  const [loading, setLoading] = useState(false);
  const [busy, setBusy] = useState(''); // generate | save | recalc | print | export | load
  const [notice, setNotice] = useState('');
  const [error, setError] = useState('');

  const dirConfig = directionOf(direction);
  // 往来单位候选（2026-10-22）：
  //   · 应收 / 应付视角：第一项是「全部客户 / 全部供应商」，后面跟名单；
  //   · 全部视角：第一项「全部往来单位（应收 + 应付）」，然后客户(c:)与供应商(s:)混排。
  // 前缀是必须的 —— 客户和供应商是两张表，id 会撞，光靠数字分不清是谁。
  const parties = useMemo(() => {
    // ⚠️ 必须按 `scope` 判断，不能按 `direction` —— 台账模式下 direction 是占位的 'out'，
    //    按它判断会让「全部」视角的下拉只剩客户，永远选不到「全部往来单位」。
    if (scope === 'out') {
      return [{ id: 'ALL', name: '全部客户（应收 · 批量）' }, ...customers.map((row) => ({ ...row, id: `c:${row.id}` }))];
    }
    if (scope === 'in') {
      return [{ id: 'ALL', name: '全部供应商（应付 · 批量）' }, ...suppliers.map((row) => ({ ...row, id: `s:${row.id}` }))];
    }
    return [
      { id: 'ALL', name: '全部往来单位（应收 + 应付）' },
      ...customers.map((row) => ({ ...row, id: `c:${row.id}`, name: `${row.name}（客户）` })),
      ...suppliers.map((row) => ({ ...row, id: `s:${row.id}`, name: `${row.name}（供应商）` })),
    ];
  }, [scope, customers, suppliers]);

  // —— 从智能指令进来时锁定往来单位（2026-10-23）——
  // ⚠️ 这段必须放在 `parties` 的 useMemo **之后**：放前面会在 deps 里引用尚未初始化的
  //    `parties`，触发 "Cannot access 'parties' before initialization"（实测整页白屏）。
  const presetAppliedRef = useRef('');
  useEffect(() => {
    if (!initialParty) return;
    if (presetAppliedRef.current === initialParty) return;
    const hit = parties.find((item) => String(item.id) === String(initialParty));
    if (!hit) return; // 名单还没到，等下一轮
    presetAppliedRef.current = initialParty;
    setPartyId(String(initialParty));
  }, [initialParty, parties]);

  const editable = statement?.status === 'draft';
  // 「全部」视角能选客户也能选供应商 —— 标签写「客户」会让人以为选不到供应商。
  // 收/付视角才用各自的称谓（2026-10-26 顺手对齐文案，不改任何行为）。
  const partyLabel = scope === 'all' ? '往来单位' : dirConfig.partyLabel;
  // 单据上的 `party_name` 是**快照**（档案改名后老单据仍显示当时的名字）→ 优先用它
  const partyName =
    statement?.party_name ||
    (parties.find((item) => String(item.id) === String(partyId)) || {}).name ||
    '';

  // ---- 载入字典与往来单位 ----
  // ⚠️ 不拉 `/statements/meta`：它返回的是分类/状态字典，而本页要用的
  //    状态与来源文案已经在 `lib/statementEditor.js` 里（后端字典的镜像），
  //    多一次请求只是让首屏多等一个往返。
  useEffect(() => {
    let alive = true;
    (async () => {
      try {
        const [customerRows, supplierRows, recentRows] = await Promise.all([
          api('/customers'),
          api('/suppliers'),
          api('/statements?limit=50'),
        ]);
        if (!alive) return;
        setCustomers(Array.isArray(customerRows) ? customerRows : []);
        setSuppliers(Array.isArray(supplierRows) ? supplierRows : []);
        setRecent(Array.isArray(recentRows) ? recentRows : []);
      } catch (err) {
        if (alive) setError(`初始化失败：${err.message}`);
      }
    })();
    return () => {
      alive = false;
    };
  }, []);

  // ---- 单据载入后的统一落地：方向/单位/账期/期初/明细/勾选 ----
  const applyStatement = useCallback((data, { noticeText = '' } = {}) => {
    if (!data) return;
    const items = Array.isArray(data.items) ? data.items : [];
    const nextRows = items.map((item, index) => normalizeItem(item, index));
    setStatement(data);
    setScope(data.direction === 'in' ? 'in' : 'out');
    setPartyId(data.party_id === null || data.party_id === undefined ? '' : String(data.party_id));
    setPeriod({ start: data.period_start || '', end: data.period_end || '' });
    setOpening(String(toNumber(data.opening_balance)));
    setRows(nextRows);
    setSelectedKeys(allRowKeys(nextRows));
    setNote(data.note || '');
    setError('');
    if (noticeText) setNotice(noticeText);
  }, []);

  // ---- 往来账底稿预览：单据一换就跟着拉 ----
  // 这是**参考信息**：拉不到只在面板里说一句，绝不让它把详情页搞成打不开。
  useEffect(() => {
    if (!statement?.id) {
      setLedgerPreview(null);
      return undefined;
    }
    let alive = true;
    setLedgerBusy(true);
    api(`/statements/${statement.id}/preview`)
      .then((data) => {
        if (alive) setLedgerPreview(data);
      })
      .catch((err) => {
        if (alive) setLedgerPreview({ available: false, reason: err.message });
      })
      .finally(() => {
        if (alive) setLedgerBusy(false);
      });
    return () => {
      alive = false;
    };
  }, [statement?.id]);

  // ---- 搜索预览（只读）----
  // 以前这个位置是「生成草稿」：点一下就**占掉一个 DZ 单号并入库**。
  // 用户的直觉却是"先看看这期有什么"，于是台账里堆满没人要的草稿。
  // 现在：点它只查询 + 展示（all 勾选），要落库必须再点「确认生成对账单」。
  //
  // 2026-10-26：多接一个可选入参 —— AI 指令条认出往来单位后要**立刻**按这个单位
  // 跑一次预览，而 React 的 setPartyId 是异步的，那一刻读到的还是旧值。
  // 所以允许显式传 { party, period, scope } 覆盖；不传就是老行为（读当前 state）。
  // ⚠️ 必须挡住 React 传进来的事件对象：`onClick={previewPool}` 会把 SyntheticEvent
  //    当第一个参数塞进来，而它也有 `party`/`period` 这类属性，直接当覆盖参数用会炸。
  const previewPool = async (override) => {
    const opts = override && !override.nativeEvent ? override : {};
    const partyValue = opts.party != null ? String(opts.party) : String(partyId || '');
    const range = opts.period || period;
    const viewScope = opts.scope || scope;
    const rangeDir = viewScope === 'all' ? 'all' : viewScope;
    const partyType = directionOf(rangeDir === 'all' ? 'out' : rangeDir).partyType;

    const invalid = validateGenerate({ partyId: partyValue, period: range });
    if (invalid) {
      setError(invalid);
      setNotice('');
      return;
    }
    setBusy('preview');
    setError('');
    setNotice('');
    try {
      // 选中的值可能是 ALL / c:<id> / s:<id> / 纯数字（老视图）
      const picked = String(partyValue || '');
      const query = new URLSearchParams({ period_start: range.start, period_end: range.end });
      if (picked === 'ALL') {
        // 「全部」= 该视角下的全量：全部视角含应收+应付，收/付视角只含本方向
        query.set('party_type', viewScope === 'all' ? 'all' : partyType);
      } else if (picked.startsWith('c:')) {
        query.set('party_type', 'customer');
        query.set('party_id', picked.slice(2));
      } else if (picked.startsWith('s:')) {
        query.set('party_type', 'supplier');
        query.set('party_id', picked.slice(2));
      } else {
        query.set('party_type', partyType);
        query.set('party_id', picked);
      }
      const data = await api(`/statements/preview-pool?${query.toString()}`);
      const documents = Array.isArray(data.documents) ? data.documents : [];
      setPool(data);
      // 默认全选：绝大多数情况就是"这期的单全部要"
      setPoolPicked(documents.map((item) => item.key));
      // 预览是"看当期未生成的数"，先把已载入的对账单放掉，免得两张表混在一起看错
      setStatement(null);
      setRows([]);
      setSelectedKeys([]);
      setNotice(
        documents.length
          ? `已找到 ${documents.length} 张单据（金额 ¥${data.totals?.amount_sum ?? '0.00'}），核对无误后点「确认生成对账单」。`
          : '这一期没有找到任何单据，换个账期或先开单。',
      );
    } catch (err) {
      setError(err.message);
      setPool(null);
      setPoolPicked([]);
    } finally {
      setBusy('');
    }
  };

  // ---- 确认生成（唯一写库动作）----
  const generate = async () => {
    if (!pool) {
      setError('请先点「搜索预览」，核对要放进对账单的单据。');
      return;
    }
    if (!poolPicked.length) {
      setError('请至少勾选一张单据再生成。');
      return;
    }
    setBusy('generate');
    setError('');
    setNotice('');
    try {
      const data = await api('/statements/generate-selected', {
        method: 'POST',
        headers: jsonHeaders,
        body: JSON.stringify({
          // party_type=all：每个勾选键自带方向（sales:/purchase:），后端按往来单位分组，
          // 一组生成一张对账单 —— 勾了 3 个客户就得 3 张，绝不能混成一张。
          party_type: 'all',
          period_start: period.start,
          period_end: period.end,
          keys: poolPicked,
          opening_balance: opening === '' ? undefined : Number(opening),
        }),
      });
      const madeList = Array.isArray(data.statements) ? data.statements : [];
      setPool(null);
      setPoolPicked([]);
      if (madeList.length > 1) {
        // 批量：勾了几个往来单位就生成几张，没有"唯一那张"可载入 ——
        // 刷新台账让人在下面逐张点开核对即可。
        setNotice(
          data.message ||
            `已按 ${madeList.length} 个往来单位各生成一张对账单，请在台账里逐张核对。`,
        );
        const freshBatch = await api('/statements?limit=50');
        setRecent(Array.isArray(freshBatch) ? freshBatch : []);
      } else {
        applyStatement(data, {
          noticeText: data.message || `已生成对账单 ${data.statement_no}`,
        });
        const fresh = await api('/statements?limit=50');
        setRecent(Array.isArray(fresh) ? fresh : []);
      }
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy('');
    }
  };

  const togglePoolDoc = (key) => {
    setPoolPicked((prev) => (prev.includes(key) ? prev.filter((item) => item !== key) : [...prev, key]));
  };

  const togglePoolAll = () => {
    const all = (pool?.documents || []).map((item) => item.key);
    setPoolPicked((prev) => (prev.length === all.length ? [] : all));
  };

  // ---- 载入已存对账单 ----
  const loadStatement = async (id) => {
    if (!id) return;
    setBusy('load');
    setError('');
    setNotice('');
    setLoading(true);
    try {
      const data = await api(`/statements/${id}`);
      applyStatement(data, { noticeText: `已载入 ${data.statement_no}` });
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
      setBusy('');
    }
  };

  // ---- 智能指令 → 本页（2026-10-26 · AI 入口）
  // 从顶部 AI 指令条点「载入本页」时走这里，两条路：
  //   · 有 statementId：直接载入那张单（单号/账期/明细/勾选一次到位，与台账点行同一条路径）；
  //   · 只有往来单位：按「这个单位 + 当前账期」跑一次**只读**搜索预览，让用户先看再决定生成。
  // ⚠️ 不能 setPartyId 之后再调 previewPool()：那一刻 state 还是旧值，
  //    会把「某个客户」查成「全部往来单位」。参数必须显式传下去。
  const openFromAgent = (payload) => {
    if (!payload) return;
    if (payload.statementId) {
      loadStatement(payload.statementId);
      return;
    }
    const goto = payload.goto || {};
    const party = String(goto.party || '').trim();
    if (!party) {
      setError('这条指令里没认出往来单位。可以点上面「往来单位」手选，或把公司全名说得更完整一点。');
      return;
    }
    const nextScope = goto.scope === 'in' ? 'in' : 'out';
    if (nextScope !== scope) {
      // 与 switchScope 同一口径：换视角必须放掉上一张单，否则应收的数字会挂到供应商头上
      setScope(nextScope);
      setStatement(null);
      setRows([]);
      setSelectedKeys([]);
      setOpening('0');
      setNote('');
    }
    setPool(null);
    setPoolPicked([]);
    setPartyId(party);
    setNotice(
      `已按「${goto.party_name || '该往来单位'}」定位，正在查这一期的单据…`,
    );
    previewPool({ party, period, scope: nextScope });
  };

  // ---- 行内改数（只允许改两列，其余是后端派生）----
  const patchRow = (index, field, value) => {
    setRows((prev) => prev.map((row, i) => (i === index ? { ...row, [field]: value } : row)));
  };

  // ---- 勾选与合计 ----
  const selectedSet = useMemo(() => new Set(selectedKeys), [selectedKeys]);
  const checkedRows = useMemo(
    () => rows.filter((row) => selectedSet.has(row.key || itemKey(row, 0))),
    [rows, selectedSet],
  );
  const preview = useMemo(() => computeTotals(checkedRows, opening), [checkedRows, opening]);
  const cards = useMemo(() => headerCards(preview, direction), [preview, direction]);

  // 「载入已存对账单」下拉里只列当前方向的单。全部模式下列全部。
  // 刻意在本地过滤而不是再请求一次：`recent` 最多 50 条，多打一次接口只会让下拉慢半拍。
  const recentScoped = useMemo(
    () =>
      scope === 'all'
        ? recent
        : recent.filter((row) => (row.direction === 'in' ? 'in' : 'out') === scope),
    [recent, scope],
  );

  // 全部模式 = 台账。列只保留"能一眼认出是哪一单"的字段，
  // 金额用期末余额（应收余额 / 应付余额），不铺 10 个数字。
  const ledgerColumns = useMemo(
    () => [
      { key: 'statement_no', title: '对账单号', width: 150, mono: true },
      {
        key: 'direction',
        title: '方向',
        width: 78,
        align: 'center',
        render: (row) => (
          <span className={`stmt__dir stmt__dir--${row.direction === 'in' ? 'in' : 'out'}`}>
            {row.direction === 'in' ? '应付' : '应收'}
          </span>
        ),
      },
      { key: 'party_name', title: '往来单位', minWidth: 180, ellipsis: true },
      {
        key: 'period',
        title: '账期',
        width: 190,
        mono: true,
        render: (row) => `${row.period_start || '—'} ~ ${row.period_end || '—'}`,
      },
      {
        key: 'receivable_balance',
        title: '期末余额',
        width: 130,
        align: 'right',
        num: true,
        render: (row) => amount(row.receivable_balance),
      },
      {
        key: 'status',
        title: '状态',
        width: 92,
        align: 'center',
        render: (row) => (
          <span className={`stmt__status stmt__status--${row.status || 'none'}`}>
            {statusLabel(row.status)}
          </span>
        ),
      },
      {
        key: 'actions',
        title: '操作',
        width: 96,
        align: 'right',
        sticky: 'right',
        nowrap: true,
        render: (row) => (
          <button
            type="button"
            className="link-btn"
            onClick={(event) => {
              // 行本身也绑了打开，按钮这里必须停一下，否则会触发两次 loadStatement
              event.stopPropagation();
              loadStatement(row.id);
            }}
          >
            打开
          </button>
        ),
      },
    ],
    // loadStatement 是普通函数（每次渲染都新建），但只用到稳定的 setState，
    // 放进依赖会让 memo 每次失效；这里刻意不列它。
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [],
  );

  // 往来账底稿列
  const ledgerRowColumns = useMemo(
    () => [
      { key: 'date', title: '日期', width: 104, mono: true },
      { key: 'doc_no', title: '单号', width: 150, mono: true, ellipsis: true, fallback: '—' },
      { key: 'summary', title: '摘要', minWidth: 200, ellipsis: true, fallback: '—' },
      { key: 'increase', title: '本期增加', width: 118, align: 'right', num: true, render: (row) => amount(row.increase) },
      { key: 'decrease', title: '本期减少', width: 118, align: 'right', num: true, render: (row) => amount(row.decrease) },
      {
        key: 'balance',
        title: '余额',
        width: 126,
        align: 'right',
        num: true,
        render: (row) => <strong>{amount(row.balance)}</strong>,
      },
    ],
    [],
  );

  // ---- 保存（只提交勾选行；头部金额由后端重算）----
  const save = async () => {
    const invalid = validateSave({ statement, checkedCount: checkedRows.length });
    if (invalid) {
      setError(invalid);
      setNotice('');
      return;
    }
    setBusy('save');
    setError('');
    setNotice('');
    try {
      const data = await api(`/statements/${statement.id}`, {
        method: 'PATCH',
        headers: jsonHeaders,
        body: JSON.stringify(buildSavePayload({ period, opening, note }, checkedRows)),
      });
      applyStatement(data, {
        noticeText: `已保存：${data.statement_no}（${data.item_count} 行，头部金额已由服务端重算）`,
      });
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy('');
    }
  };

  // ---- 重算（唯一能让已发出对账单改变数字的显式入口）----
  const recalc = async () => {
    if (!statement) {
      setError('还没有载入对账单');
      return;
    }
    setBusy('recalc');
    setError('');
    setNotice('');
    try {
      // ⚠️ `/recalc` 只回 `{totals, item_count, message}`，**不是整张单据**。
      //    直接拿它去 applyStatement 会把 shape 弄乱（rows 变空、单号还在）→
      //    这里老老实实再 GET 一次完整单据。
      const result = await api(`/statements/${statement.id}/recalc`, { method: 'POST' });
      const fresh = await api(`/statements/${statement.id}`);
      applyStatement(fresh, { noticeText: result?.message || '已按当前明细重算头部金额' });
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy('');
    }
  };

  // ---- 打印 PDF（⚠️ 必须走 JSON base64 通道，PDF 会被浏览器接管走）----
  const printPdf = async () => {
    if (!statement) {
      setError('还没有载入对账单');
      return;
    }
    // 确认必须在 fetch 之前：点「取消」时不应该已经生成过 PDF
    const okToPrint = await confirmPrint({
      name: `${statement.statement_no}.pdf`,
      title: '确认打印此单据？',
    });
    if (!okToPrint) return;
    setBusy('print');
    setError('');
    setNotice('');
    try {
      const response = await fetch(`${API_BASE}${printPath(statement.id)}`, {
        headers: { Accept: 'application/json', ...authHeaders() },
      });
      if (!response.ok) {
        const data = await response.json().catch(() => ({}));
        throw new Error(typeof data.detail === 'string' ? data.detail : '生成 PDF 失败');
      }
      const payload = await response.json();
      saveBlob(
        base64ToBlob(payload.content_base64, payload.content_type || 'application/pdf'),
        payload.filename || `${statement.statement_no}.pdf`,
      );
      setNotice(`已生成 PDF：${payload.filename || statement.statement_no + '.pdf'}`);
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy('');
    }
  };

  // ---- 导出 Word（任务 E · 2026-10-19）：当前这张对账单，能盖章发对方 ----
  const exportWordFile = async () => {
    if (!statement?.id) return;
    setBusy('word');
    setError('');
    setNotice('');
    try {
      const name = await exportWord(
        'statement',
        statement.id,
        `对账单-${statement.statement_no || statement.id}.docx`,
      );
      setNotice(`已导出：${name}`);
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy('');
    }
  };

  // ---- 导出 Excel（对账单台账：头部 + 明细两张表）----
  const exportExcel = async () => {
    setBusy('export');
    setError('');
    setNotice('');
    try {
      const qs = exportQuery({ period, direction });
      const response = await fetch(`${API_BASE}/exports/statements?${qs}`, { headers: authHeaders() });
      if (!response.ok) {
        const data = await response.json().catch(() => ({}));
        throw new Error(typeof data.detail === 'string' ? data.detail : `导出失败（HTTP ${response.status}）`);
      }
      const blob = await response.blob();
      const filename = fileNameFromDisposition(
        response.headers.get('Content-Disposition'),
        `对账单台账_${period.start}_${period.end}.xlsx`,
      );
      saveBlob(blob, filename);
      setNotice(`已导出：${filename}`);
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy('');
    }
  };

  // ---- 切范围：应收/应付/全部是三个视角，不能混着看 ----
  const switchScope = (next) => {
    if (next === scope) return;
    setScope(next);
    setPartyId('');
    setStatement(null);
    setRows([]);
    setSelectedKeys([]);
    setOpening('0');
    setNote('');
    setNotice('');
    setError('');
  };

  // ---- 列定义 ----
  const columns = useMemo(
    () => [
      { key: 'line_no', title: '#', width: 52, align: 'right', mono: true },
      { key: 'business_date', title: '业务日期', width: 104, mono: true },
      {
        key: 'source_type',
        title: '来源',
        width: 84,
        render: (row) => <span className="stmt__source">{sourceLabel(row.source_type)}</span>,
      },
      {
        key: 'contract_no',
        title: '合同编号',
        width: 150,
        mono: true,
        ellipsis: true,
        render: (row) =>
          row.contract_no ? row.contract_no : <span className="stmt__muted">—</span>,
      },
      {
        key: 'summary',
        title: '摘要',
        minWidth: 200,
        ellipsis: true,
        render: (row) => (
          <span className="stmt__summary" title={row.summary}>
            {row.summary || <span className="stmt__muted">（未填摘要）</span>}
          </span>
        ),
      },
      {
        key: 'contract_amount',
        title: '合同金额',
        width: 118,
        align: 'right',
        num: true,
        render: (row) => amount(row.contract_amount),
      },
      {
        key: 'invoice_status',
        title: '发票状态',
        width: 100,
        render: (row) => {
          const status = deriveRow(row).invoiceStatus;
          return <span className={`stmt__badge stmt__badge--${status}`}>{invoiceStatusLabel(status)}</span>;
        },
      },
      {
        key: 'invoiced_amount',
        title: '已开票',
        width: 132,
        align: 'right',
        // 这一列是**可编辑**的：勾选联动要看得见立刻变化，否则"编辑器"就是只读表
        render: (row, index) => (
          <input
            className="stmt__input"
            type="number"
            step="any"
            min="0"
            aria-label={`第 ${row.line_no} 行已开票金额`}
            value={row.invoiced_amount}
            disabled={!editable}
            onChange={(event) => patchRow(index, 'invoiced_amount', event.target.value)}
          />
        ),
      },
      {
        key: 'uninvoiced_amount',
        title: '未开票',
        width: 112,
        align: 'right',
        num: true,
        render: (row) => amount(deriveRow(row).uninvoiced),
      },
      {
        key: 'received_amount',
        title: '已收 / 已付',
        width: 132,
        align: 'right',
        render: (row, index) => (
          <input
            className="stmt__input"
            type="number"
            step="any"
            min="0"
            aria-label={`第 ${row.line_no} 行已收金额`}
            value={row.received_amount}
            disabled={!editable}
            onChange={(event) => patchRow(index, 'received_amount', event.target.value)}
          />
        ),
      },
      {
        key: 'outstanding_amount',
        title: '剩余未收',
        width: 118,
        align: 'right',
        num: true,
        render: (row) => {
          const value = deriveRow(row).outstanding;
          return <strong className={value < 0 ? 'stmt__num stmt__num--neg' : 'stmt__num'}>{amount(value)}</strong>;
        },
      },
      {
        key: 'prepaid_applied',
        title: '预收核销',
        width: 104,
        align: 'right',
        num: true,
        render: (row) => amount(row.prepaid_applied),
      },
    ],
    [editable],
  );

  const uncheckedCount = rows.length - checkedRows.length;
  // 主按钮归属（2026-10-26）：只有「载入了一张还能改的草稿」时，保存才是主按钮。
  // 已确认/已发出的单不能保存（editable=false），这时候蓝按钮若给了保存，会变成
  // 一个永远是灰的"假主按钮" —— 反而没有焦点。所以那种情况仍由「搜索预览」占主位。
  const primaryIsSave = Boolean(statement) && editable;

  return (
    <section className="stmt">
      {/* ================= AI 指令入口（2026-10-26） =================
          把工作台同款「🤖 智能指令」嵌进本页顶部：一句人话认出往来单位，
          点「载入本页」直接把那张对账单拉进编辑区；还没生成的单位则按
          该单位 + 当前账期跑一次**只读**搜索预览。它自己只发查/预览/导出三类
          请求，不写库 —— 写库仍然只有「确认生成对账单」和「保存」两个入口。 */}
      <div className="stmt__ai" data-stmt-ai>
        <SmartCommandBar
          apiBase={API_BASE}
          authHeaders={authHeaders}
          compact
          placeholder="说一句话就能开单：给我湖南华邦这个月的对账单"
          onOpenStatement={openFromAgent}
        />
      </div>

      {/* ================= 顶部命令区 ================= */}
      <header className="stmt__cmd">
        {/* 左半：视角 + 查询条件。整体去边框 —— 这是"单据头"，不该看起来像
            一张套着卡片的表单（旧版卡片 + 字段 + 输入框三层边框，视觉上全是线）。 */}
        <div className="stmt__cmd-main">
        {/* 三视角：全部 = 台账（只看不改）；应收 / 应付 = 各自一本账。
            从「采购对账单」进来默认落在「应付」，从「销售对账单」进来落在「应收」。 */}
        <div className="stmt__seg" role="tablist" aria-label="对账范围">
          {STATEMENT_SCOPES.map((item) => (
            <button
              key={item.code}
              type="button"
              role="tab"
              aria-selected={scope === item.code}
              className={`stmt__seg-btn${scope === item.code ? ' is-active' : ''}`}
              data-scope={item.code}
              onClick={() => switchScope(item.code)}
            >
              {item.label}
            </button>
          ))}
        </div>

        {/* 三个视角都有搜索区（2026-10-22）：
            以前「全部」只有台账、没有入口，"想新开一张"必须先切到应收/应付 —— 反直觉。
            现在全部视角也能直接：选「全部往来单位」→ 搜索预览 → 勾选 → 确认生成。 */}
        {(
          <>
            <div className="stmt__field stmt__field--party">
              <span className="stmt__field-label">{partyLabel}</span>
              <ErpSearchSelect
                options={parties}
                value={partyId}
                onChange={(next) => setPartyId(String(next || ''))}
                getOptionValue={(item) => String(item.id)}
                getOptionLabel={(item) => item.name || ''}
                getOptionMeta={(item) => [item.code, item.phone].filter(Boolean).join(' · ')}
                placeholder={`搜索${partyLabel}名称 / 编码`}
                emptyText={`没有匹配的${partyLabel}`}
              />
            </div>

            <div className="stmt__field">
              <span className="stmt__field-label">对账期间</span>
              <input
                className="stmt__date"
                type="date"
                value={period.start}
                onChange={(event) => setPeriod((prev) => ({ ...prev, start: event.target.value }))}
                aria-label="对账期间开始"
              />
              <span className="stmt__tilde">~</span>
              <input
                className="stmt__date"
                type="date"
                value={period.end}
                onChange={(event) => setPeriod((prev) => ({ ...prev, end: event.target.value }))}
                aria-label="对账期间结束"
              />
            </div>

            {scope === 'all' ? null : (
              <div className="stmt__field stmt__field--opening">
                <span className="stmt__field-label">期初余额</span>
                <input
                  className="stmt__date stmt__date--money"
                  type="number"
                  step="any"
                  value={opening}
                  onChange={(event) => setOpening(event.target.value)}
                  aria-label="期初余额"
                />
              </div>
            )}

          </>
        )}
        </div>

        {/* 右半：动作区。**一屏只有一个蓝色主按钮**（2026-10-26 主次重排）：
              · 还没载入对账单 → 「搜索预览」是主（蓝）；
              · 载入草稿后 → 「保存」是主（蓝），搜索预览退为次按钮；
              · 打印 / 导出 Excel / 导出 Word 是收尾动作、频率远低于保存，
                收进 [⋯] 菜单 —— 以前六个按钮平铺成一行，主次全糊了。 */}
        <div className="stmt__cmd-right">
          <div className="stmt__field stmt__field--recent">
            <ErpSearchSelect
              options={recentScoped}
              value=""
              onChange={(id) => loadStatement(id)}
              getOptionValue={(item) => String(item.id)}
              getOptionLabel={statementOptionLabel}
              getOptionMeta={(item) => statusLabel(item.status)}
              placeholder={scope === 'all' ? '载入已存对账单（全部）' : '载入已存对账单'}
              emptyText="还没有保存过对账单"
            />
          </div>
          {/* 预览态（还没生成对账单）只留「搜索预览 + 载入已存」：保存/重算/打印/导出
              都是针对某一张已存在的对账单，摆在预览页纯属误导（2026-10-22 用户反馈）。 */}
          <button
            type="button"
            className={`${primaryIsSave ? 'secondary-btn' : 'primary-btn'} small-btn stmt__generate`}
            onClick={previewPool}
            disabled={busy === 'preview'}
            data-stmt-preview
            title="按「往来单位 + 账期」把这期的单据、发票、收款全查出来给你核对（不会生成对账单）"
          >
            {busy === 'preview' ? '查询中…' : '🔍 搜索预览'}
          </button>

          {!statement ? null : (
            <>
              <button
                type="button"
                className="secondary-btn small-btn"
                onClick={recalc}
                disabled={!statement || busy === 'recalc'}
                title="按当前明细重算头部金额（已发出/已确认的对账单只有这一个显式入口能改数）"
              >
                {busy === 'recalc' ? '重算中…' : '重算'}
              </button>
              <button
                type="button"
                className={`${primaryIsSave ? 'primary-btn' : 'secondary-btn'} small-btn`}
                data-stmt-save
                onClick={save}
                disabled={!editable || busy === 'save'}
                title={editable ? '保存勾选行（头部金额由服务端重算）' : '只有草稿可以保存'}
              >
                {busy === 'save' ? '保存中…' : '保存'}
              </button>
              {/* 收尾动作收进 [⋯]：打印与导出不可逆感强、频率低，不该和「保存」抢焦点。
                  保留 data-word-export="statement" 等旧钩子，验收脚本照旧能点到。 */}
              <ErpMoreMenu
                testId="statement"
                title="打印 / 导出"
                items={[
                  {
                    key: 'print',
                    label: busy === 'print' ? '正在生成 PDF…' : '打印 PDF',
                    hint: 'A4 横版 · 可直接发给对方',
                    disabled: !statement || busy === 'print',
                    onSelect: printPdf,
                  },
                  {
                    key: 'excel',
                    label: busy === 'export' ? '正在导出…' : '导出 Excel',
                    hint: '台账 + 明细两张表 · 含合计',
                    disabled: busy === 'export',
                    onSelect: exportExcel,
                  },
                  {
                    key: 'word',
                    label: busy === 'word' ? '正在导出…' : '导出 Word',
                    hint: '可盖章发送 · 适合存档',
                    disabled: !statement || busy === 'word',
                    attrs: { 'data-word-export': 'statement' },
                    onSelect: exportWordFile,
                  },
                ]}
              />
            </>
          )}
        </div>
      </header>

      {/* ================= 提示条 ================= */}
      {error ? (
        <div className="stmt__alert stmt__alert--error" role="alert">
          {error}
        </div>
      ) : null}
      {!error && notice ? <div className="stmt__alert stmt__alert--ok">{notice}</div> : null}

          {/* ================= 搜索预览（只读，2026-10-22） =================
              这一块是"还没生成"的账：查出来的单据默认全勾选，取消勾选的不进对账单。
              绿色的「确认生成对账单」是**唯一**写库入口 —— 与旧版「生成草稿」的
              区别就在于"先看后写"，不会再为看一眼白白消耗一个 DZ 单号。 */}
          {pool ? (
            <ErpCard
              title="搜索预览 · 待生成"
              subtitle={`${pool.party_name || ''} · ${pool.period?.from || ''} ~ ${pool.period?.to || ''} · ${pool.doc_count ?? 0} 张单据`}
              flush
              divider
            >
              <div className="stmt-pool" data-stmt-pool>
                <div className="stmt-pool__bar">
                  <span>
                    金额 <b>¥{pool.totals?.amount_sum ?? '0.00'}</b>
                  </span>
                  <span>
                    已开票 <b>¥{pool.totals?.invoiced_sum ?? '0.00'}</b>
                  </span>
                  <span>
                    已收 <b>¥{pool.totals?.paid_sum ?? '0.00'}</b>
                  </span>
                  <span>
                    欠款 <b>¥{pool.totals?.remaining_sum ?? '0.00'}</b>
                  </span>
                  <span className="stmt-pool__picked" data-stmt-picked-count>
                    已勾选 {poolPicked.length}/{pool.doc_count ?? 0} 张
                  </span>
                  <button
                    type="button"
                    className="secondary-btn small-btn"
                    onClick={togglePoolAll}
                    data-stmt-toggle-all
                  >
                    {poolPicked.length === (pool.doc_count ?? 0) ? '全不选' : '全选'}
                  </button>
                  <button
                    type="button"
                    className="primary-btn small-btn stmt-pool__confirm"
                    onClick={generate}
                    disabled={busy === 'generate' || !poolPicked.length}
                    data-stmt-confirm
                  >
                    {busy === 'generate' ? '生成中…' : '确认生成对账单'}
                  </button>
                  <button
                    type="button"
                    className="secondary-btn small-btn"
                    onClick={() => {
                      setPool(null);
                      setPoolPicked([]);
                    }}
                  >
                    取消预览
                  </button>
                </div>
                <FusionWideTable
                  columns={pool.columns || []}
                  rows={pool.rows || []}
                  totals={pool.totals}
                  selectable
                  selectedKeys={poolPicked}
                  onToggleDoc={togglePoolDoc}
                />
              </div>
            </ErpCard>
          ) : null}


      {/* ================= 全部模式：对账单台账 ================= */}
      {scope === 'all' ? (
        <ErpCard
          title={scopeConfig.title}
          subtitle={`共 ${recent.length} 张 · 应收 ${recent.filter((row) => row.direction !== 'in').length} 张 / 应付 ${recent.filter((row) => row.direction === 'in').length} 张`}
          flush
          divider
        >
          <ErpTable
            columns={ledgerColumns}
            rows={recent}
            rowKey="id"
            ariaLabel="对账单台账"
            loading={loading}
            dense
            striped
            hover
            onRowClick={(row) => loadStatement(row.id)}
            // 行可点就必须键盘可开：只给 onRowClick 等于把键盘用户挡在门外
            rowProps={(row) => ({
              tabIndex: 0,
              title: '点一下（或按回车）打开这张对账单',
              onKeyDown: (event) => {
                if (event.key === 'Enter' || event.key === ' ') {
                  event.preventDefault();
                  loadStatement(row.id);
                }
              },
            })}
            emptyProps={{
              variant: 'data',
              title: '还没有对账单',
              description:
                '对账单按「往来单位 + 账期」来：把上面的范围切到「应收」或「应付」，选好客户/供应商后点「🔍 搜索预览」，核对完再点「确认生成对账单」。',
            }}
          />
        </ErpCard>
      ) : (
        <>
          {/* ================= 单头信息 ================= */}
          <div className="stmt__meta">
            <span className="stmt__no" data-statement-no>
              {statement ? statement.statement_no : '未生成'}
            </span>
            <span className={`stmt__status stmt__status--${statement?.status || 'none'}`}>
              {statement ? statusLabel(statement.status) : '无单据'}
            </span>
            <span className="stmt__scope-title" data-scope-title>
              {scopeConfig.title}
            </span>
            <span className="stmt__meta-item">
              往来单位：<b>{partyName || '未选择'}</b>
            </span>
            <span className="stmt__meta-item">
              账期：<b>{period.start || '—'} ~ {period.end || '—'}</b>
            </span>
            <span className="stmt__meta-item">
              明细：<b>{statement ? `${statement.item_count || rows.length} 行` : '—'}</b>
            </span>
            <span className="stmt__meta-item stmt__meta-item--check" data-checked-count={checkedRows.length}>
              本单已勾选 <b>{checkedRows.length}</b> / {rows.length} 行
              {uncheckedCount > 0 ? <em className="stmt__warn">（未勾选的 {uncheckedCount} 行保存时不会写入）</em> : null}
            </span>
          </div>

          {/* ================= 头部汇总：6 张卡片 ================= */}
          <div className="stmt__cards">
            {cards.map((card) => (
              <div
                key={card.key}
                className={`stmt__card${card.key === 'receivable_balance' ? ' stmt__card--strong' : ''}`}
                data-card={card.key}
              >
                <span className="stmt__card-label">{card.label}</span>
                <strong className={toNumber(card.value) < 0 ? 'stmt__card-value stmt__card-value--neg' : 'stmt__card-value'}>
                  {money(card.value)}
                </strong>
                <span className="stmt__card-hint">{card.hint}</span>
              </div>
            ))}
          </div>

          {/* ================= 明细 =================
              预览态（pool 有值、statement 为空）不渲染这张卡：
              上面已经把这一期的单据摊开了，再挂一个"还没有对账单"的空盒子只会让人以为没数据。 */}
          {pool && !statement ? null : (
          <ErpCard
            title={scopeConfig.title.replace('对账单', '对账明细')}
            subtitle={
              rows.length
                ? `共 ${rows.length} 行 · 勾选的 ${checkedRows.length} 行参与本单合计`
                : '按合同 / 发票 / 收付款逐行核对'
            }
            extra={
              rows.length ? (
                <div className="stmt__card-extra">
                  <button
                    type="button"
                    className="link-btn"
                    onClick={() => setSelectedKeys(allRowKeys(rows))}
                    disabled={checkedRows.length === rows.length}
                  >
                    全选
                  </button>
                  <button type="button" className="link-btn" onClick={() => setSelectedKeys([])} disabled={!checkedRows.length}>
                    清空勾选
                  </button>
                </div>
              ) : null
            }
            flush
            divider
          >
            <ErpTable
              columns={columns}
              rows={rows}
              rowKey={(row) => row.key}
              ariaLabel="对账明细"
              loading={loading}
              // 编辑器里每行有输入框；默认间距（12/16）会把 12 行撑到一屏放不下 →
              // 用 dense 压到 8/12，与全站其它"单据明细表"同一密度
              dense
              striped
              hover
              selectable
              selectedKeys={selectedKeys}
              onSelectionChange={setSelectedKeys}
              emptyProps={{
                variant: 'data',
                title: '还没有对账单',
                description:
                  '先选好往来单位与对账期间，点「🔍 搜索预览」把这期的单据查出来核对，' +
                  '勾选要放进对账单的单据后再点「确认生成对账单」；也可以从右侧「载入已存对账单」继续核对。',
              }}
              footer={
                rows.length ? (
                  <tr className="stmt__foot">
                    <td />
                    <td className="stmt__foot-label" colSpan={5}>
                      本单合计（已勾选 {checkedRows.length} 行）
                    </td>
                    <td className="stmt__foot-num">{amount(preview.contract_amount)}</td>
                    <td />
                    <td className="stmt__foot-num">{amount(preview.invoiced_amount)}</td>
                    <td className="stmt__foot-num">{amount(preview.uninvoiced_amount)}</td>
                    <td className="stmt__foot-num">{amount(preview.received_amount)}</td>
                    <td className="stmt__foot-num stmt__foot-num--strong">{amount(preview.outstanding_amount)}</td>
                    <td className="stmt__foot-num">{amount(preview.prepaid_applied)}</td>
                  </tr>
                ) : null
              }
            />
          </ErpCard>
          )}

          {/* ================= 四流穿透明细（2026-10-21 大融合，超宽表） ================= */}
          {statement ? (
            <ErpCard
              title="四流穿透明细（业务 → 签收 → 发票 → 资金）"
              subtitle={
                ledgerBusy
                  ? '正在聚合四流数据…'
                  : ledgerPreview?.available
                    ? `${ledgerPreview.party_name || ''} · ${ledgerPreview.totals?.doc_count ?? 0} 张单据 · ${(Array.isArray(ledgerPreview.rows) ? ledgerPreview.rows : []).length} 行`
                    : '取不到穿透数据（不影响对账单本身）'
              }
              flush
              divider
            >
              {ledgerPreview?.available && !Array.isArray(ledgerPreview.rows) ? (
                /* available=true 但没有 rows：后端还是旧版本（重启 ERP 前启动的进程）。
                   旧结构只有往来账底稿，没有四流穿透 —— 给一句明确指引，绝不白屏。 */
                <p className="stmt__preview-empty">
                  四流穿透明细需要**重启 ERP 后端**才能生效：程序窗口关掉重新打开即可（后端还是旧版本时，界面与接口会对不上）。
                </p>
              ) : ledgerPreview?.available && Array.isArray(ledgerPreview.rows) && ledgerPreview.rows.length > 1 ? (
                <FusionWideTable
                  columns={ledgerPreview.columns}
                  rows={ledgerPreview.rows}
                  totals={ledgerPreview.totals}
                />
              ) : (
                <p className="stmt__preview-empty">
                  这一期的账面是空的：区间内没有单据、发票和收付款。换一个账期，或先去开单。
                </p>
              )}
            </ErpCard>
          ) : null}

{/* ================= 往来账底稿预览（内嵌，需求 3） ================= */}
          <ErpCard
            title="往来账底稿（期初 → 逐笔 → 期末）"
            subtitle={
              !statement
                ? '载入一张对账单后自动摊开同期往来账'
                : ledgerBusy
                  ? '正在取底稿…'
                  : ledgerPreview?.available
                    ? `${ledgerPreview.period?.from || '—'} ~ ${ledgerPreview.period?.to || '—'} · ${(ledgerPreview.ledger?.rows || []).length} 笔流水`
                    : '取不到底稿（不影响对账单本身）'
            }
            flush
            divider
          >
            {!statement ? (
              <p className="stmt__preview-empty">
                载入一张对账单后，这里会摊开**同一往来单位、同一账期**的往来账底稿，
                方便你直接核对"对账单期末"和"往来账期末"差在哪几笔。
              </p>
            ) : ledgerPreview && ledgerPreview.available === false ? (
              <p className="stmt__preview-empty">{ledgerPreview.reason || '取不到往来账底稿。'}</p>
            ) : (
              <>
                <div className="stmt__preview-cards">
                  {[
                    { key: 'opening', label: '往来账期初', value: ledgerPreview?.ledger?.opening_balance },
                    { key: 'increase', label: '本期增加', value: ledgerPreview?.ledger?.increase_total },
                    { key: 'decrease', label: '本期减少', value: ledgerPreview?.ledger?.decrease_total },
                    { key: 'closing', label: '往来账期末', value: ledgerPreview?.ledger?.closing_balance, strong: true },
                    { key: 'stmt', label: '对账单期末', value: statement.receivable_balance },
                  ].map((item) => (
                    <div key={item.key} className={`stmt__preview-card${item.strong ? ' is-strong' : ''}`} data-preview={item.key}>
                      <span>{item.label}</span>
                      <strong>{money(item.value)}</strong>
                    </div>
                  ))}
                  <div
                    className={`stmt__preview-card${Math.abs(Number(ledgerPreview?.diff || 0)) < 0.005 ? ' is-ok' : ' is-diff'}`}
                    data-preview="diff"
                  >
                    <span>两口径差额</span>
                    <strong>{money(ledgerPreview?.diff)}</strong>
                  </div>
                </div>

                <ErpTable
                  columns={ledgerRowColumns}
                  rows={ledgerPreview?.ledger?.rows || []}
                  rowKey="id"
                  ariaLabel="往来账底稿"
                  dense
                  striped
                  emptyProps={{
                    variant: 'data',
                    title: '这一期没有往来流水',
                    description: '该往来单位在这个账期内没有收付款记录，所以底稿是空的。',
                  }}
                />

                <p className="stmt__preview-note" data-diff-reason>
                  {ledgerPreview?.diff_reason || '对账单按开票口径、往来账按收付款流水口径，两个期末余额不一定相等。'}
                </p>
              </>
            )}
          </ErpCard>

          {/* ================= 备注 / 口径说明 ================= */}
          <footer className="stmt__foot-area">
            <label className="stmt__note">
              <span>备注</span>
              <input
                type="text"
                value={note}
                maxLength={255}
                placeholder="给对方的说明，会随对账单打印出来"
                onChange={(event) => setNote(event.target.value)}
                disabled={!editable}
              />
            </label>
            <p className="stmt__hint">
              口径：期末余额 = 期初 + 本期已开票 − 已收 − 预收核销；剩余未收 = 合同金额 − 已收 − 预收核销。
              头部金额是<b>快照</b>，保存时由服务端重算；已确认的对账单只能通过「重算」这个显式动作改变数字。
            </p>
          </footer>
        </>
      )}
    </section>
  );
}

/* eslint-disable react/prop-types */
/**
 * FusionWideTable —— 对账单「四流穿透明细」超宽表（2026-10-21 大融合）。
 *
 * 列由后端 columns 元数据驱动（34 列 / 5 组），前端**不硬编码列**：
 * 后天加一列（比如智能体电子签状态），这里一行不用改。
 * · 横向滚动 + 纵向滚动，表头 sticky；
 * · 前 3 列（业务日期/单据号/往来单位）冻结——拖到最右也认得出这一行是谁；
 * · 行类型着色：detail 白 / invoice 淡紫 / recv 淡绿 / pay 淡橙 / summary 灰加粗；
 * · 金额右对齐（值已是后端格式化的字符串，前端不做任何算术——算术进前端必然丢精度）。
 */
const FUSION_KIND_LABEL = { detail: '明细', invoice: '开票', recv: '收款', pay: '付款', summary: '小计' };
const FUSION_INVOICE_STATUS = { none: '未开票', partial: '部分开票', full: '已开票' };

const FUSION_KIND_WIDTH = 42;
const FUSION_WIDTH_KEY = 'erp:colw:stmt-fusion';

function FusionWideTable({
  columns,
  rows,
  totals,
  /** 可勾选（预览态）：勾选粒度 = 单据（小计行），不是商品行 */
  selectable = false,
  /** 已勾选的单据 key 数组（`order:<id>`） */
  selectedKeys = [],
  onToggleDoc,
}) {
  const pickedSet = useMemo(() => new Set(selectedKeys || []), [selectedKeys]);
  const docRows = useMemo(
    () => rows.filter((row) => row.row_kind === 'summary' && row.source_id),
    [rows],
  );
  // 勾选键必须与后端返回的 documents[].key 完全一致：
  //   · 单一客户/供应商：`order:<id>`
  //   · 全部往来单位：行上带 `doc_key`（`sales:<id>` / `purchase:<id>`，因为两张表 id 会撞）
  const docKey = (row) => row?.doc_key || (row && row.source_id ? `order:${row.source_id}` : null);
  const allPicked = docRows.length > 0 && docRows.every((row) => pickedSet.has(docKey(row)));
  // —— 列宽：用户拖出来的宽度存本地，刷新/重开还在；双击抓手复位 ——
  // 交互与 `ErpTable` 的 columnResize **同一套实现**（那是本项目验证过的版本）：
  //   · window 级监听：鼠标滑出表头甚至滑出表格，列宽还得跟着走；
  //   · **不能**在 pointerdown 上 preventDefault()——按规范会连带取消后续 click，
  //     双击复位就永远触发不了；
  //   · 双击靠"自己数 400ms 内的第二次按下"，不依赖 onDoubleClick，
  //     也不依赖 `event.detail`（PointerEvent 的 detail 恒为 0）。
  const [widths, setWidths] = useState(() => {
    try {
      const raw = localStorage.getItem(FUSION_WIDTH_KEY);
      const parsed = raw ? JSON.parse(raw) : null;
      return parsed && typeof parsed === 'object' ? parsed : {};
    } catch {
      return {};
    }
  });
  const widthsRef = useRef(widths);
  const lastClickRef = useRef({ field: null, at: 0 });

  const widthOf = useCallback(
    (col) => Math.max(56, Math.round(Number(widths[col.field]) || Number(col.width) || 100)),
    [widths],
  );

  const persist = (next) => {
    try {
      localStorage.setItem(FUSION_WIDTH_KEY, JSON.stringify(next));
    } catch {
      /* 隐私模式下 localStorage 会抛，忽略即可 —— 列宽丢了不影响数据 */
    }
  };

  const resetWidth = (field) => {
    setWidths((prev) => {
      if (prev[field] == null) return prev;
      const next = { ...prev };
      delete next[field];
      widthsRef.current = next;
      persist(next);
      return next;
    });
  };

  const beginResize = (event, col) => {
    if (event.button !== 0) return;
    const now = Date.now();
    const last = lastClickRef.current;
    if (last.field === col.field && now - last.at < 400) {
      lastClickRef.current = { field: null, at: 0 };
      event.stopPropagation();
      resetWidth(col.field);
      return;
    }
    lastClickRef.current = { field: col.field, at: now };
    event.stopPropagation(); // 抓手上按下不要连带触发列头点击

    const startWidth = widthOf(col);
    const startX = event.clientX;
    const onMove = (moveEvent) => {
      const next = Math.max(56, Math.round(startWidth + (moveEvent.clientX - startX)));
      widthsRef.current = { ...widthsRef.current, [col.field]: next };
      setWidths(widthsRef.current);
    };
    const onUp = () => {
      window.removeEventListener('pointermove', onMove);
      window.removeEventListener('pointerup', onUp);
      window.removeEventListener('pointercancel', onUp);
      document.body.classList.remove('is-col-resizing');
      persist(widthsRef.current);
    };
    document.body.classList.add('is-col-resizing');
    window.addEventListener('pointermove', onMove);
    window.addEventListener('pointerup', onUp);
    window.addEventListener('pointercancel', onUp);
  };

  // 冻结列的 left 偏移：第一列要先让开最左边那条「行类型」窄列（42px）。
  // ⚠️ 必须**逐列累加**，不能所有冻结列都钉在同一个 left ——
  //    那样第二列会盖住第一列（旧实现就是拿 frozenWidth 当 left，列宽一改就露馅）。
  const frozenOffsets = useMemo(() => {
    const offsets = {};
    let acc = FUSION_KIND_WIDTH;
    for (const col of columns) {
      if (!col.frozen) continue;
      offsets[col.field] = acc;
      acc += widthOf(col);
    }
    return offsets;
  }, [columns, widthOf]);

  const totalWidth = useMemo(
    () => FUSION_KIND_WIDTH + columns.reduce((sum, col) => sum + widthOf(col), 0),
    [columns, widthOf],
  );

  const groupCounts = useMemo(() => {
    const counts = [];
    for (const col of columns) {
      const last = counts[counts.length - 1];
      if (last && last.group === col.group) last.count += 1;
      else counts.push({ group: col.group, count: 1 });
    }
    return counts;
  }, [columns]);

  // —— 四流增强（2026-10-26）——
  // 1) 分组色调：按分组**出现顺序**取色，不按中文名硬编码 ——
  //    后天后端把「签收」改名成「签收/验收」，这里不用改一行。
  const toneOf = useMemo(() => {
    const map = new Map();
    groupCounts.forEach((item, index) => map.set(item.group, (index % 5) + 1));
    return map;
  }, [groupCounts]);

  // 2) 断流判定：**按单据块**聚合，而不是看 summary 行自己 ——
  //    后端给 summary（单据小计）行的 invoice_status 是空的，真正的开票状态挂在
  //    它上面的 detail 行上（每张单据 = 若干明细 + 收款 + 一行小计）。
  //    只看 summary 会让色条永远不出现（第一稿就是这样）。
  //      · 全部明细已开票        → 不断流
  //      · 有明细已开票/部分开票 → 黄条（部分断流，缺票）
  //      · 全部明细未开票        → 红条（发票流整个断掉）
  //    全表合计那行（没有 source_id）不参与判定。
  const gapByRow = useMemo(() => {
    const map = new Map();
    let block = [];
    for (const row of rows) {
      if (row.row_kind === 'summary') {
        if (row.source_id) {
          const statuses = block
            .filter((item) => item.row_kind === 'detail')
            .map((item) => item.invoice_status)
            .filter(Boolean);
          if (statuses.length && !statuses.every((status) => status === 'full')) {
            map.set(row.line_no, statuses.some((status) => status === 'full' || status === 'partial') ? 'warn' : 'stop');
          }
        }
        block = [];
      } else {
        block.push(row);
      }
    }
    return map;
  }, [rows]);
  const gapOf = (row) => (row && gapByRow.get(row.line_no)) || '';
  const gapCount = useMemo(
    () => [...gapByRow.values()].filter((value) => value === 'stop').length,
    [gapByRow],
  );

  // 3) 行穿透抽屉：只摊开**当前行已有的字段**（列元数据驱动），
  //    不额外请求、不拼接后端没有的东西 —— 抽屉里看到的和表里完全一致。
  const [detailRow, setDetailRow] = useState(null);

  // 4) 分组分隔线 / 冻结列右侧投影：都要逐列算（第一列没有前一组，
  //    最后一列没有后一列），写死下标会在后端加列时错位。
  const isGroupStart = (col) => {
    const index = columns.findIndex((item) => item.field === col.field);
    return index > 0 && columns[index - 1].group !== col.group;
  };
  const isFrozenEdge = (col) => {
    const index = columns.findIndex((item) => item.field === col.field);
    const next = columns[index + 1];
    return Boolean(col.frozen) && !(next && next.frozen);
  };

  const renderCell = (row, col) => {
    const raw = row[col.field];
    if (col.field === 'e_sign_status') return '—';
    if (col.field === 'invoice_status') {
      return raw ? FUSION_INVOICE_STATUS[raw] || raw : '';
    }
    if (raw == null || raw === '') {
      return row.row_kind === 'detail' ? '—' : '';
    }
    return String(raw);
  };

  return (
    <div className="stmt-fusion" data-stmt-fusion>
      {/* 四流对齐条（2026-10-26）：每个分组一个色点胶囊，色点与表头上沿颜色一一对应 ——
          不用读文字也知道这一屏是「业务 / 签收 / 发票 / 资金」四段拼起来的；
          出现断流（发票流没走完）时多一个红色胶囊，直接给张数。 */}
      <div className="stmt-fusion__legend">
        {groupCounts.map((item) => (
          <span
            key={item.group}
            className="stmt-fusion__legend-item"
            data-tone={toneOf.get(item.group) || 1}
          >
            <i className="stmt-fusion__legend-dot" aria-hidden="true" />
            {item.group}
            <b>{item.count}</b>
          </span>
        ))}
        {gapCount ? (
          <span className="stmt-fusion__legend-item is-gap" data-stmt-gap-count={gapCount}>
            <i className="stmt-fusion__legend-dot" aria-hidden="true" />
            断流
            <b>{gapCount}</b> 张
          </span>
        ) : null}
        <span className="stmt-fusion__legend-item stmt-fusion__legend-total" data-stmt-totals>
          合计 金额 ¥{totals?.amount_sum ?? '0.00'} · 开票 ¥{totals?.invoiced_sum ?? '0.00'} · 收付
          ¥{totals?.paid_sum ?? '0.00'} · 欠款 ¥{totals?.remaining_sum ?? '0.00'}
        </span>
        <span className="stmt-fusion__legend-hint">
          点任意一行看这张单据的四流明细 · 拖表头右缘调列宽（双击复位）
        </span>
      </div>
      <div className="stmt-fusion__scroll">
        {/* `table-layout: fixed` + colgroup 是"表头与表体严格对齐"的唯一可靠做法：
            auto 布局会让浏览器按内容二次分配列宽，thead 与 tbody 各算各的 →
            列宽一变（拖拽/内容长短不同）就错位，看起来就是"表头和数据挤成一团"。
            总宽显式写死，横向滚动条也才知道该滚多远。 */}
        <table
          className="stmt-fusion__table"
          style={{ tableLayout: 'fixed', width: totalWidth }}
        >
          <colgroup>
            <col style={{ width: FUSION_KIND_WIDTH }} />
            {columns.map((col) => (
              <col key={col.field} style={{ width: widthOf(col) }} />
            ))}
          </colgroup>
          <thead>
            <tr>
              <th className="stmt-fusion__kind" style={{ left: 0 }}>
                {selectable ? (
                  <input
                    type="checkbox"
                    checked={allPicked}
                    onChange={() => {
                      // 全选/全不选交给父级统一处理（它才知道完整的 documents 列表）
                      if (typeof onToggleDoc === 'function' && docRows.length) {
                        docRows.forEach((row) => {
                          const key = docKey(row);
                          const has = pickedSet.has(key);
                          if (allPicked ? has : !has) onToggleDoc(key);
                        });
                      }
                    }}
                    aria-label="全选/全不选单据"
                    data-stmt-check-all
                  />
                ) : (
                  '行'
                )}
              </th>
              {columns.map((col) => (
                <th
                  key={col.field}
                  data-col={col.field}
                  data-tone={toneOf.get(col.group) || 1}
                  className={`${col.frozen ? 'is-frozen' : ''} ${col.mono ? 'is-mono' : ''}${
                    isGroupStart(col) ? ' is-group-start' : ''
                  }${isFrozenEdge(col) ? ' is-frozen-edge' : ''}`.trim()}
                  style={{
                    width: widthOf(col),
                    minWidth: widthOf(col),
                    maxWidth: widthOf(col),
                    textAlign: col.align === 'right' ? 'right' : 'left',
                    left: col.frozen ? frozenOffsets[col.field] : undefined,
                  }}
                >
                  <span className="stmt-fusion__thtext">{col.label}</span>
                  <span
                    className="stmt-fusion__grip"
                    role="separator"
                    aria-label={`调整「${col.label}」列宽`}
                    data-col-grip={col.field}
                    onPointerDown={(event) => beginResize(event, col)}
                  />
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => (
              <tr
                key={row.line_no}
                className={`stmt-fusion__row stmt-fusion__row--${row.row_kind}${
                  selectable && docKey(row) && !pickedSet.has(docKey(row)) ? ' is-unpicked' : ''
                } is-clickable`}
                data-gap={gapOf(row) || undefined}
                // 5) 行穿透：整行可点 → 右侧抽屉摊开这一行的四流字段。
                //    只读，不改数据；键盘 Enter / 空格等价于点一下。
                tabIndex={0}
                aria-label={`查看第 ${row.line_no} 行四流明细`}
                onClick={() => setDetailRow(row)}
                onKeyDown={(event) => {
                  if (event.key !== 'Enter' && event.key !== ' ') return;
                  event.preventDefault();
                  setDetailRow(row);
                }}
              >
                {/* 断流色条：挂在冻结的「行类型」列左缘，横滚到哪儿都看得见 */}
                <td className="stmt-fusion__kind" style={{ left: 0 }}>
                  {gapOf(row) ? (
                    <i
                      className={`stmt-fusion__gap is-${gapOf(row)}`}
                      aria-hidden="true"
                      data-stmt-gap={gapOf(row)}
                    />
                  ) : null}
                  {selectable && row.row_kind === 'summary' && row.source_id ? (
                    <input
                      type="checkbox"
                      checked={pickedSet.has(docKey(row))}
                      onChange={() => onToggleDoc?.(docKey(row))}
                      // 勾选不该顺带打开抽屉：冒泡到 tr 的 onClick 会一起触发
                      onClick={(event) => event.stopPropagation()}
                      aria-label={`是否把 ${row.source_no || '该单据'} 放进对账单`}
                      data-stmt-check={row.source_no || ''}
                    />
                  ) : (
                    FUSION_KIND_LABEL[row.row_kind] || ''
                  )}
                </td>
                {columns.map((col) => {
                  const width = widthOf(col);
                  return (
                    <td
                      key={col.field}
                      className={`${col.frozen ? 'is-frozen' : ''} ${col.mono ? 'is-mono' : ''} ${
                        col.kind === 'money' || col.kind === 'qty' ? 'is-num' : ''
                      }${isGroupStart(col) ? ' is-group-start' : ''}${
                        isFrozenEdge(col) ? ' is-frozen-edge' : ''
                      }`.trim()}
                      style={{
                        left: col.frozen ? frozenOffsets[col.field] : undefined,
                        width,
                        minWidth: width,
                        maxWidth: width,
                      }}
                      title={renderCell(row, col) || undefined}
                    >
                      {renderCell(row, col)}
                    </td>
                  );
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {/* 行穿透抽屉（2026-10-26）：只摊开当前行**已有字段**，按四流分组排列。
          刻意不做"再去后端拉一次该单据详情"——抽屉和表格必须永远一致，
          两处取数就等于两处可能不一致（对账场景最忌讳）。 */}
      <ErpDrawer
        open={Boolean(detailRow)}
        size="lg"
        testId="stmt-fusion-detail"
        title="四流穿透 · 单据明细"
        subtitle={
          detailRow
            ? `${FUSION_KIND_LABEL[detailRow.row_kind] || '明细'}${
                detailRow.source_no ? ` · ${detailRow.source_no}` : ''
              }`
            : ''
        }
        onClose={() => setDetailRow(null)}
        footer={
          <button
            type="button"
            className="secondary-btn small-btn"
            data-stmt-detail-close
            onClick={() => setDetailRow(null)}
          >
            关闭
          </button>
        }
      >
        {detailRow ? (
          <div className="stmt-fusion__detail" data-stmt-detail>
            {groupCounts.map((group) => (
              <section key={group.group} className="stmt-fusion__detail-group">
                <h4>
                  <i
                    className="stmt-fusion__legend-dot"
                    data-tone={toneOf.get(group.group) || 1}
                    aria-hidden="true"
                  />
                  {group.group}
                </h4>
                <dl>
                  {columns
                    .filter((col) => col.group === group.group)
                    .map((col) => (
                      <div key={col.field} className="stmt-fusion__detail-row">
                        <dt>{col.label}</dt>
                        <dd className={col.kind === 'money' || col.kind === 'qty' ? 'is-num' : ''}>
                          {/* 后端在小计行的「商品名称」里带了 ◤ / ◢ 折叠标记（表格里是有用的），
                              抽屉里没有折叠概念，去掉标记只留内容 */}
                          {String(renderCell(detailRow, col) || '')
                            .replace(/^[◤◢▾▸▼◣]\s*/, '')
                            .trim() || '—'}
                        </dd>
                      </div>
                    ))}
                </dl>
              </section>
            ))}
          </div>
        ) : null}
      </ErpDrawer>
    </div>
  );
}

/* eslint-enable react/prop-types */
