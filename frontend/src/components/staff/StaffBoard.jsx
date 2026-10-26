/**
 * StaffBoard —— 员工档案的两栏看板（左侧部门树 ↔ 右侧名册）
 *
 * ## 这一页以前长什么样
 *
 * `pages/StaffPage.jsx`（自动生成）是一个 `ResizableLayout` 套**一个** `<section>`，
 * 顶部三件套：关键词输入 + 「部门」下拉 + 「状态」下拉 + 查询按钮。
 * 一进页面 `employees` 全量铺开，左侧那半屏空着 —— 和客户/供应商页完全两种手感。
 *
 * ## 现在
 *
 * · 左侧 = **部门树**（不是硬造的：部门在后端就是 `level` 层级，
 *   `/employees/meta` 已按 `level, sort_order` 排序返回，这里按 level 还原成树）；
 * · 未选中 → 右表空 + 「请在左侧选择一个分类」；
 * · 点「全部员工」或某个部门 → 才去拉数据（首点触发一次 `refreshEmployees`），
 *   之后按部门子树 + 状态 + 关键词在本地过滤。
 *
 * ## 为什么过滤放本地
 *
 * 员工名册是个几十条的小表，本地过滤是**同一帧生效**的（下拉选完就变），
 * 而走服务端要经历"改 state → 再请求 → 回来再渲染"，中间会闪一次旧数据。
 * 首次点击时把全量拉一次即可，顺带解决了"进页面就请求一次"的浪费。
 *
 * ## 刻意没动的
 *
 * 新增 / 编辑 / 删除仍走 App.jsx 的原有链路（`resetEmployeeForm`、`startEditEmployee`、
 * `setConfirmDelete`），这一层只负责"显示谁"，不碰写操作。
 */

import { useMemo, useRef, useState } from 'react';

import ResizableLayout from '../resizable-layout/ResizableLayout.jsx';
import ErpCard from '../ui/ErpCard.jsx';
import ErpTable from '../ui/ErpTable.jsx';
import ErpTree from '../ui/ErpTree.jsx';
import { ALL, isAll, isPicked, pickPrompt } from '../../lib/treeSelection.js';
import './staff-board.css';
import ArchiveImportDialog from '../dataio/ArchiveImportDialog.jsx';

/** 「未分配部门」不是树里的节点（department_id 为空），但它必须能被一键捞出来 */
const UNASSIGNED = 'dept:__none__';

/**
 * 扁平部门列表（带 `level`）→ 树。
 *
 * 后端 `/employees/meta` 返回的是 `[{ id, name, level, label }]`，按 `level, sort_order`
 * 排好序（先序）。所以只要维护一个"当前路径栈"就能还原父子关系，
 * 不需要 parent_id —— 也不必为了做一棵树去改后端接口。
 */
function buildDeptTree(rows = []) {
  const roots = [];
  const stack = [];
  rows.forEach((row) => {
    const level = Number(row.level) || 0;
    const node = { key: `dept:${row.id}`, label: row.name, children: [] };
    while (stack.length && stack[stack.length - 1].level >= level) stack.pop();
    if (stack.length === 0) roots.push(node);
    else stack[stack.length - 1].node.children.push(node);
    stack.push({ level, node });
  });
  return roots;
}

/** 收集树里某个 key 及其所有子孙的部门 id */
function subtreeDeptIds(nodes, targetKey) {
  const ids = new Set();
  const walk = (list, inside) => {
    (list || []).forEach((node) => {
      const hit = inside || node.key === targetKey;
      if (hit) {
        const id = Number(String(node.key).slice('dept:'.length));
        if (Number.isFinite(id)) ids.add(id);
      }
      walk(node.children, hit);
    });
  };
  walk(nodes, false);
  return ids;
}

export default function StaffBoard({ ctx }) {
  const {
    employees = [],
    employeeMeta = {},
    refreshEmployees,
    resetEmployeeForm,
    setEmployeeModalOpen,
    startEditEmployee,
    setConfirmDelete,
    departmentLabel,
  } = ctx || {};

  const list = employees || [];
  // 导入弹窗（2026-10-21 恢复）
  const [importOpen, setImportOpen] = useState(false);
  /** null = 还没选；ALL = 全部员工；dept:<id> = 某个部门；UNASSIGNED = 未分配 */
  const [picked, setPicked] = useState(null);
  const [keyword, setKeyword] = useState('');
  const [statusFilter, setStatusFilter] = useState('');

  const deptRows = employeeMeta.departments || [];
  const deptTree = useMemo(() => buildDeptTree(deptRows), [deptRows]);

  // 首次点击才请求（进页面不拉数据 —— 左树是入口，右表先空着）
  const fetched = useRef(false);
  const pick = (key) => {
    setPicked(key);
    if (!fetched.current && refreshEmployees) {
      fetched.current = true;
      // 明确清掉 App.jsx 里那三个服务端筛选条件，否则会带着上次的部门/关键词去查。
      // 这里刻意**不用** ctx 里的状态值：setState 是异步的，先 set 再 refresh 会读到旧值。
      refreshEmployees({ keyword: '', department_id: '', status: '' });
    }
  };

  const unassignedCount = useMemo(
    () => list.filter((row) => row.department_id === null || row.department_id === undefined || row.department_id === '').length,
    [list],
  );

  const visible = useMemo(() => {
    if (!isPicked(picked)) return [];

    let base = list;
    if (!isAll(picked)) {
      if (picked === UNASSIGNED) {
        base = list.filter(
          (row) => row.department_id === null || row.department_id === undefined || row.department_id === '',
        );
      } else {
        const ids = subtreeDeptIds(deptTree, picked);
        base = list.filter((row) => ids.has(Number(row.department_id)));
      }
    }

    if (statusFilter) base = base.filter((row) => row.status === statusFilter);

    const q = keyword.trim().toLowerCase();
    if (!q) return base;
    return base.filter((row) =>
      [row.code, row.name, row.phone, row.position].some(
        (value) => value !== null && value !== undefined && String(value).toLowerCase().includes(q),
      ),
    );
  }, [list, picked, deptTree, statusFilter, keyword]);

  const columns = useMemo(
    () => [
      { key: 'code', title: '工号', mono: true, width: 110 },
      { key: 'name', title: '姓名', minWidth: 100 },
      { key: 'gender', title: '性别', fallback: '—', width: 72, hideBelow: 'md' },
      {
        key: 'department',
        title: '部门',
        fallback: '—',
        ellipsis: true,
        minWidth: 140,
        render: (row) => (
          <span className="cell-sub">
            {row.department_name || (departmentLabel ? departmentLabel(row.department_id) : '—')}
          </span>
        ),
      },
      { key: 'position', title: '岗位', fallback: '—', hideBelow: 'sm', ellipsis: true, minWidth: 100 },
      { key: 'phone', title: '手机', mono: true, nowrap: true, hideBelow: 'md', minWidth: 120 },
      { key: 'hire_date', title: '入职', fallback: '—', hideBelow: 'md', nowrap: true, width: 110 },
      {
        key: 'status',
        title: '状态',
        width: 84,
        align: 'center',
        render: (row) => (
          <span className={`status-badge ${row.status === 'active' ? 'ok' : 'muted'}`}>
            {row.status === 'active' ? '在职' : '离职'}
          </span>
        ),
      },
      {
        key: 'actions',
        title: '操作',
        width: 140,
        align: 'right',
        sticky: 'right',
        nowrap: true,
        render: (row) => (
          <div className="row-actions">
            <button
              type="button"
              className="link-btn"
              onClick={() => startEditEmployee && startEditEmployee(row)}
            >
              编辑
            </button>
            <button
              type="button"
              className="link-btn danger"
              onClick={() =>
                setConfirmDelete &&
                setConfirmDelete({
                  id: row.id,
                  endpoint: `/employees/${row.id}`,
                  label: `员工 ${row.name}（${row.code}）`,
                  kind: 'system-employee',
                })
              }
            >
              删除
            </button>
          </div>
        ),
      },
    ],
    [departmentLabel, setConfirmDelete, startEditEmployee],
  );

  const emptyProps =
    !isPicked(picked)
      ? pickPrompt('部门')
      : {
          variant: 'filter',
          title: list.length === 0 ? '还没有员工' : '这个范围里没有员工',
          description:
            list.length === 0 ? '点右上角「新增员工」建第一条。' : '换一个部门或状态，或点左侧「全部员工」。',
          action: list.length === 0 ? undefined : { label: '查看全部', onClick: () => pick(ALL) },
        };

  return (
    <ResizableLayout storageKey="erp:mgrid:staff" minLeft={240}>
      <ErpCard
        title="员工部门"
        subtitle={isPicked(picked) ? `共 ${list.length} 人` : `共 ${list.length} 人 · 点一下开始`}
      >
        {/* 部门树用 ErpTree 的通用交互：点行选中、再点取消、小三角折叠。
            「未分配」放在树外面单独一行（它不是部门）。 */}
        <ErpTree
          nodes={deptTree}
          value={picked}
          onChange={pick}
          total={list.length}
          allLabel="全部员工"
        />
        <div className="staff-unassigned">
          <button
            type="button"
            className={`link-btn${picked === UNASSIGNED ? ' is-active' : ''}`}
            onClick={() => pick(UNASSIGNED)}
            title="还没填部门的员工"
          >
            未分配部门（{unassignedCount}）
          </button>
        </div>
      </ErpCard>

      <ErpCard
        title="员工名册"
        subtitle={`${visible.length} / ${list.length} 人`}
        extra={
          <div className="board-extra-actions">
            <button
              type="button"
              className="secondary-btn small-btn"
              data-import-open
              onClick={() => setImportOpen(true)}
              title="从 Excel 批量导入员工档案（先预检，确认后才写库）"
            >
              导入
            </button>
            <button
              type="button"
              className="primary-btn small-btn"
              onClick={() => {
                if (resetEmployeeForm) resetEmployeeForm();
                if (setEmployeeModalOpen) setEmployeeModalOpen(true);
              }}
            >
              新增员工
            </button>
          </div>
        }
        flush
        divider
      >
        <div className="erp-card-toolbar">
          <input
            className="search-input"
            placeholder="搜工号 / 姓名 / 手机 / 岗位…"
            value={keyword}
            onChange={(event) => setKeyword(event.target.value)}
          />
          <select value={statusFilter} onChange={(event) => setStatusFilter(event.target.value)}>
            <option value="">全部状态</option>
            {(employeeMeta.statuses || []).map((item) => (
              <option key={item.value} value={item.value}>
                {item.label}
              </option>
            ))}
          </select>
        </div>

        <ErpTable
          columns={columns}
          rows={visible}
          rowKey="id"
          ariaLabel="员工名册"
          emptyProps={emptyProps}
        />
      </ErpCard>
      <ArchiveImportDialog
        open={importOpen}
        kind="employees"
        onClose={() => setImportOpen(false)}
        onImported={() => ctx && ctx.refreshEmployees && ctx.refreshEmployees()}
      />
    </ResizableLayout>
  );
}
