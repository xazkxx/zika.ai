// 自动提取自 App.jsx（selectedTab='suppliers'）— 见 scripts/extract_pages.py
//
// ⚠️ 本文件已被降级为**薄壳**：整页 UI 搬到 components/partners/PartnersBoard.jsx。
//    重跑 scripts/extract_pages.py 会重新生成本文件的原文，需执行：
//        python scripts/patch_partners_pages.py --apply
//    把它压回下面这几行（脚本幂等，已压过则空操作）。
//
//   历史手工修改（内容已全部搬到 PartnersBoard）：
//     ① ResizableLayout 包裹 + 单面板整行（gridColumn: '1 / -1'）
//     ② 第三步：ErpCard × 2 + ErpTree 分组树 + ErpTable 声明式列
import PartnersBoard from '../components/partners/PartnersBoard.jsx';

export default function SuppliersPage({ ctx }) {
  return (
    <PartnersBoard
      kind="supplier"
      rows={ctx.suppliers}
      search={ctx.supplierSearch}
      onSearch={ctx.setSupplierSearch}
      focus={ctx.archiveFocus}
      onClearFocus={() => ctx.setArchiveFocus(null)}
      onAdd={() => ctx.setSupplierModalOpen(true)}
      onEdit={(row) => ctx.openSupplierEdit(row)}
      onDelete={(row) =>
        ctx.setConfirmDelete({
          id: row.id,
          endpoint: `/suppliers/${row.id}`,
          label: `供应商 ${row.name}`,
          kind: 'supplier',
        })
      }
      onBatchDelete={ctx.batchDeleteSuppliers}
      onImported={() => ctx.reloadAfterImport('suppliers')}
      // 拖拽归档：组件只把「拖了哪几个 id、丢到哪个分类」交回来，落库在 App
      onMoveToCategory={(ids, categoryId, name) => ctx.movePartnersToCategory('supplier', ids, categoryId, name)}
      // 行内编辑：双击格子直接改，落库仍走 App（组件自己不发请求）
      onPatchPartner={(id, patch) => ctx.patchPartner('supplier', id, patch)}
    />
  );
}
