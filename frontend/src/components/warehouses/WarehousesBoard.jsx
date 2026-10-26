/**
 * WarehousesBoard —— 仓库档案的两栏看板（左侧树 ↔ 右侧列表）
 *
 * ## 为什么有这个文件
 *
 * `pages/WarehousesPage.jsx` 是 `scripts/extract_pages.py` 整文件生成的，
 * 里面是一个 `ResizableLayout` 套**一个** `<section>`（只有一个子元素，
 * 拖拽手柄其实从来没生效过），右侧直接把 `warehouses` 全量铺出来。
 *
 * 这一版按统一交互契约重做（另外四页：客户 / 供应商 / 商品 / 员工）：
 *   · 左侧树 = 入口，未选中时右侧**空表** + 「请在左侧选择一个分类」；
 *   · 默认折叠（本页只有"启用/停用"两层，天然是折叠的）；
 *   · 选中「全部仓库」才显示全量。
 *
 * ## 刻意没动的
 *
 * 仓库**没有分类层级**（就一张平表：编码/名称/货位/负责人），所以树只有
 * 「全部 → 启用 / 停用」这一层 —— 按状态分流是真实业务需要的（停用仓不该混在
 * 可用仓里找），而给它硬造一棵"地区/类型"树就是造假数据。
 *
 * 数据仍由 App.jsx 提供（`warehouses` 是全量数组，开单页的下拉也用它，
 * 所以**不能**按页面延迟请求；这里只门控"显不显示"）。
 */

import { useMemo, useState } from 'react';

import ResizableLayout from '../resizable-layout/ResizableLayout.jsx';
import ErpCard from '../ui/ErpCard.jsx';
import ErpTable from '../ui/ErpTable.jsx';
import ErpTree from '../ui/ErpTree.jsx';
import { ALL, isAll, isPicked, pickPrompt } from '../../lib/treeSelection.js';
import ArchiveImportDialog from '../dataio/ArchiveImportDialog.jsx';

/** 树节点 key：与后端 `is_active` 布尔值一一对应 */
const ON = 'status:on';
const OFF = 'status:off';

const columns = [
  { key: 'code', title: '编码', mono: true, width: 140 },
  { key: 'name', title: '名称', ellipsis: true, minWidth: 160 },
  { key: 'location', title: '货位', fallback: '—', hideBelow: 'sm', ellipsis: true, minWidth: 120 },
  { key: 'manager', title: '负责人', fallback: '—', hideBelow: 'md', minWidth: 96 },
  { key: 'phone', title: '电话', mono: true, nowrap: true, hideBelow: 'md', minWidth: 120 },
  {
    key: 'is_active',
    title: '状态',
    width: 84,
    align: 'center',
    render: (row) => (
      <span className={`stock-tag ${row.is_active ? 'tag-on' : 'tag-off'}`}>
        {row.is_active ? '启用' : '停用'}
      </span>
    ),
  },
];

export default function WarehousesBoard({ ctx }) {
  const {
    warehouses = [],
    resetWarehouseForm,
    setWarehouseModalOpen,
    startEditWarehouse,
    setConfirmDelete,
  } = ctx || {};

  const list = warehouses || [];
  // 导入弹窗（2026-10-21 恢复：v72 加的「导入」入口被整树覆盖时丢了）
  const [importOpen, setImportOpen] = useState(false);
  /** null = 还没选；ALL = 全部；'status:on' / 'status:off' = 按状态 */
  const [status, setStatus] = useState(null);

  const onCount = useMemo(() => list.filter((row) => row.is_active).length, [list]);
  const offCount = list.length - onCount;

  const nodes = useMemo(
    () => [
      { key: ON, label: '启用', count: onCount },
      { key: OFF, label: '停用', count: offCount },
    ],
    [onCount, offCount],
  );

  const visible = useMemo(() => {
    if (!isPicked(status)) return []; // 还没选 → 空表
    if (isAll(status)) return list;
    return list.filter((row) => (status === ON ? Boolean(row.is_active) : !row.is_active));
  }, [list, status]);

  const actionColumn = {
    key: 'actions',
    title: '操作',
    width: 152,
    align: 'right',
    sticky: 'right',
    nowrap: true,
    render: (row) => (
      <div className="row-actions">
        <button
          type="button"
          className="secondary-btn small-btn"
          onClick={() => startEditWarehouse && startEditWarehouse(row)}
        >
          编辑
        </button>
        <button
          type="button"
          className="danger-btn"
          onClick={() =>
            setConfirmDelete &&
            setConfirmDelete({
              id: row.id,
              endpoint: `/warehouses/${row.id}`,
              label: `仓库 ${row.name}`,
              kind: 'warehouse',
            })
          }
        >
          删除
        </button>
      </div>
    ),
  };

  const emptyProps =
    list.length === 0
      ? {
          variant: 'data',
          title: '还没有仓库',
          description: '仓库是入库、出库、调拨的落点，先建一个主仓。',
          action: {
            label: '新增仓库',
            onClick: () => {
              if (resetWarehouseForm) resetWarehouseForm();
              if (setWarehouseModalOpen) setWarehouseModalOpen(true);
            },
          },
        }
      : !isPicked(status)
        ? pickPrompt('仓库')
        : {
            variant: 'filter',
            title: '这个状态下没有仓库',
            description: '换一个状态，或在左侧点「全部仓库」。',
            action: { label: '查看全部', onClick: () => setStatus(ALL) },
          };

  return (
    <ResizableLayout storageKey="erp:mgrid:warehouses" minLeft={240}>
      <ErpCard
        title="仓库状态"
        subtitle={isPicked(status) ? `共 ${list.length} 个` : `共 ${list.length} 个 · 点一下开始`}
      >
        <ErpTree
          nodes={nodes}
          value={status}
          onChange={setStatus}
          total={list.length}
          allLabel="全部仓库"
        />
      </ErpCard>

      <ErpCard
        title="仓库列表"
        subtitle={`${visible.length} / ${list.length} 个`}
        extra={
          <div className="board-extra-actions">
            <button
              type="button"
              className="secondary-btn small-btn"
              data-import-open
              onClick={() => setImportOpen(true)}
              title="从 Excel 批量导入仓库档案（先预检，确认后才写库）"
            >
              导入
            </button>
            <button
              type="button"
              className="primary-btn small-btn"
              onClick={() => {
                if (resetWarehouseForm) resetWarehouseForm();
                if (setWarehouseModalOpen) setWarehouseModalOpen(true);
              }}
            >
              新增仓库
            </button>
          </div>
        }
        flush
        divider
      >
        <ErpTable
          columns={[...columns, actionColumn]}
          rows={visible}
          rowKey="id"
          ariaLabel="仓库列表"
          emptyProps={emptyProps}
        />
      </ErpCard>
      <ArchiveImportDialog
        open={importOpen}
        kind="warehouses"
        onClose={() => setImportOpen(false)}
        onImported={() => ctx && ctx.refreshWarehouses && ctx.refreshWarehouses()}
      />
    </ResizableLayout>
  );
}
