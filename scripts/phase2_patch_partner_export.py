# -*- coding: utf-8 -*-
"""第二阶段 P2-5：客户/供应商「导出 Excel」先弹窗勾列。

改造前档案页**根本没有导出按钮**（第一阶段用户要求先做后端与字典，导出暂缓）。
现在补上：点「导出」→ 弹窗勾列 → 确认才生成 xlsx。
"""
import shutil
from datetime import datetime
from pathlib import Path

BOARD = Path(__file__).resolve().parents[1] / "frontend" / "src" / "components" / "partners" / "PartnersBoard.jsx"
shutil.copy2(BOARD, BOARD.with_suffix(f".jsx.bak-{datetime.now():%m%d%H%M%S}"))
text = BOARD.read_bytes().decode("utf-8").replace("\r\n", "\n")


def sub_once(source, old, new, label):
    n = source.count(old)
    assert n == 1, f"[{label}] 命中 {n} 次"
    return source.replace(old, new)


# ---------------------------------------------------------------- 1. 引入
text = sub_once(
    text,
    """import { useEffect, useMemo, useState } from 'react';""",
    """import { useEffect, useMemo, useState } from 'react';

import ExportColumnsDialog from './ExportColumnsDialog.jsx';
import {
  buildPartnerSheet,
  partnerColumns,
  partnerDefaultKeys,
  partnerExportFileName,
} from '../../lib/partnerExport.js';""",
    "imports",
)

# ------------------------------------------------------------ 2. props
text = sub_once(
    text,
    """  onBatchDelete,
}) {
  const config = CONFIG[kind] || CONFIG.customer;""",
    """  onBatchDelete,
  // SheetJS 实例由页面薄壳传入（`ctx.XLSX`）：这里不 import 第三方库，
  // 保住本组件"不依赖 App 内部"的边界，也避免多打一份 xlsx 进分包。
  xlsx = null,
}) {
  const config = CONFIG[kind] || CONFIG.customer;""",
    "props",
)

# ---------------------------------------------------------------- 3. 状态
text = sub_once(
    text,
    """  // 文件抽屉的目标客户（null = 关着）。只给客户页用：供应商没有归档接口。
  const [filesFor, setFilesFor] = useState(null);
""",
    """  // 文件抽屉的目标客户（null = 关着）。只给客户页用：供应商没有归档接口。
  const [filesFor, setFilesFor] = useState(null);
  // 导出选列弹窗（P2-5）：open 时才渲染，勾选状态由弹窗自己重置
  const [exportOpen, setExportOpen] = useState(false);
""",
    "state",
)

# ------------------------------------------------- 4. 导出动作（放在 visible 之后）
text = sub_once(
    text,
    """  const uncategorizedCount = useMemo(""",
    """  /** 把勾选的列写成 xlsx 并下载。没有 XLSX 实例时明确报错，不要静默什么都不做。 */
  const runExport = (keys) => {
    if (!xlsx) {
      window.alert('导出组件还没加载好（缺少 Excel 引擎），请刷新页面后重试。');
      return;
    }
    const sheetRows = buildPartnerSheet(visible, kind, keys);
    const worksheet = xlsx.utils.aoa_to_sheet(sheetRows);
    // 列宽：中文列不给宽度会被压成一串 ####，对方打开先得手动拉一遍
    const picked = partnerColumns(kind).filter((column) => keys.includes(column.key));
    worksheet['!cols'] = picked.map((column) => ({ wch: column.width || 16 }));
    const workbook = xlsx.utils.book_new();
    xlsx.utils.book_append_sheet(workbook, worksheet, kind === 'supplier' ? '供应商' : '客户');
    xlsx.writeFile(workbook, partnerExportFileName(kind));
    setExportOpen(false);
  };

  const uncategorizedCount = useMemo(""",
    "runExport",
)

# ------------------------------------------------- 5. 卡片头部按钮
text = sub_once(
    text,
    """          extra={
            <button type="button" className="primary-btn small-btn" onClick={onAdd}>
              {config.addLabel}
            </button>
          }
          flush
          divider
        >
          <div className="erp-card-toolbar">""",
    """          extra={
            <div className="partners-extra-actions">
              <button
                type="button"
                className="secondary-btn small-btn"
                data-export-open
                onClick={() => setExportOpen(true)}
                disabled={!visible.length}
                title={visible.length ? '勾选要导出的列再生成 Excel' : '当前没有可导出的记录'}
              >
                导出 Excel
              </button>
              <button type="button" className="primary-btn small-btn" onClick={onAdd}>
                {config.addLabel}
              </button>
            </div>
          }
          flush
          divider
        >
          <div className="erp-card-toolbar">""",
    "export-button",
)

# ---------------------------------------------------------------- 6. 弹窗挂载
text = sub_once(
    text,
    """      {canFiles && filesFor ? (
        <Suspense fallback={null}>
          <CustomerFilesDrawer customer={filesFor} onClose={() => setFilesFor(null)} />
        </Suspense>
      ) : null}
""",
    """      {canFiles && filesFor ? (
        <Suspense fallback={null}>
          <CustomerFilesDrawer customer={filesFor} onClose={() => setFilesFor(null)} />
        </Suspense>
      ) : null}

      <ExportColumnsDialog
        open={exportOpen}
        kind={kind}
        title={`导出${config.noun}档案`}
        columns={partnerColumns(kind)}
        defaultKeys={partnerDefaultKeys(kind)}
        rowCount={visible.length}
        onClose={() => setExportOpen(false)}
        onConfirm={runExport}
      />
""",
    "dialog",
)

BOARD.write_bytes(text.replace("\n", "\r\n").encode("utf-8"))
print("OK PartnersBoard 导出选列已接")
