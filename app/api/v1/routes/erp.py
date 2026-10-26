"""ERP 业务路由聚合入口。

原先这里是一个 1.1 万行的单体 `erp.py`（224 个路由 + 144 个辅助函数），
已按业务域拆分到同目录下的 `erp_*.py`（见 scripts/split_erp_routes.py）。
本文件只保留两件事：

1. 把各域 router 按**原定义顺序**聚合起来 —— FastAPI 按注册顺序匹配，
   顺序一变 `/invoices/export/files` 就会被 `/invoices/{id}` 吃掉；
2. re-export 外部仍按老路径 `routes.erp` 导入的名字（`routes/system.py`、
   `main.py` 与若干测试依赖），外部代码一行都不用改。
"""

from fastapi import APIRouter

from app.api.v1.routes.erp_invoice import router as erp_invoice_router
from app.api.v1.routes.erp_archive import router as erp_archive_router
# 客户 / 供应商分类树（真实物理表，2026-10-17 第二阶段）。
# 路径是 /customer-categories、/supplier-categories，与既有 /customers、/suppliers
# 完全不同的字面段，不存在"被 /{id} 吃掉"的风险。
from app.api.v1.routes.erp_partner_category import router as erp_partner_category_router
from app.api.v1.routes.erp_inventory import router as erp_inventory_router
from app.api.v1.routes.erp_purchase import router as erp_purchase_router
from app.api.v1.routes.erp_sales import router as erp_sales_router
from app.api.v1.routes.erp_misc import router as erp_misc_router
from app.api.v1.routes.erp_finance import router as erp_finance_router
from app.api.v1.routes.erp_print import router as erp_print_router
from app.api.v1.routes.erp_production import router as erp_production_router
from app.api.v1.routes.erp_project import router as erp_project_router
from app.api.v1.routes.erp_dataio import router as erp_dataio_router
from app.api.v1.routes.erp_stock_alert import router as erp_stock_alert_router
from app.api.v1.routes.erp_upload import router as erp_upload_router
# 第 13 批：客户文件归档 / 增强版对账单。
# 路径前缀分别是 /customer(s)/...-files 与 /statements，与既有路由零重合
# （`/customers/{customer_id}/files` 比 `/customers/{customer_id}` 多一段，
#   FastAPI 按段匹配，不会被吃掉）。
from app.api.v1.routes.erp_customer_file import router as erp_customer_file_router
from app.api.v1.routes.erp_statement import router as erp_statement_router
from app.api.v1.routes.erp_contract_payment import router as erp_contract_payment_router
from app.api.v1.routes.erp_storage import router as erp_storage_router
# 多文件智能识别（2026-10-23）：把营业执照/名片/报价单读成档案字段。
# 路径 /smart-upload/*，与既有路由零重合；只读不写库，档案仍由用户点保存落库。
from app.api.v1.routes.erp_smart_upload import router as erp_smart_upload_router
from app.api.v1.routes.erp_three_way import router as erp_three_way_router
from app.api.v1.routes.erp_contract_template import router as erp_contract_template_router
# 第 13 批（第三阶段）：单据台账导出（合同 / 报价单 / 对账单 → xlsx）。
# 路径前缀 /exports，与既有 /excel/* 是**两套**（那边是可导入的档案模板，这边只出不进）。
from app.api.v1.routes.erp_export import router as erp_export_router
# 任务 E（2026-10-19）：全单据 Word 导出（合同 / 报价单 / 入库单 / 对账单 → .docx）。
# 路径 /exports/word/kinds 与 /exports/word/{kind}/{doc_id}：都是**四段以上**的字面路径，
# 与上面 `/exports/{kind}`（两段）段数不同，不存在被吃掉的顺序问题。
from app.api.v1.routes.erp_word import router as erp_word_router

router = APIRouter(prefix="", tags=["erp"])

router.include_router(erp_invoice_router)
router.include_router(erp_archive_router)
router.include_router(erp_partner_category_router)
router.include_router(erp_inventory_router)
router.include_router(erp_purchase_router)
router.include_router(erp_sales_router)
router.include_router(erp_misc_router)
router.include_router(erp_finance_router)
router.include_router(erp_print_router)
router.include_router(erp_production_router)
router.include_router(erp_project_router)
router.include_router(erp_dataio_router)
# 库存预警看板（路径 /erp/stock-alert，前端 src/components/stock-alert/ 消费）
# 纯只读聚合，与业务单据零写操作，放在最后注册即可 —— 路径不与任何既有路由重合。
router.include_router(erp_stock_alert_router)

# 商品图片上传 / 读取（路径 /upload/product-image、/uploads/products/{文件名}，
# 前端 src/components/product-edit/ProductEditModal.jsx 消费）。
# 同样放在最后：路径与既有路由零重合（全仓 grep 过，此前没有任何 /upload* 路由）。
router.include_router(erp_upload_router)

# 第 13 批（第二阶段）：客户文件归档 + 增强版对账单。
# 放在最后注册 —— 两者都是**新增字面段**（/customer-files、/statements、
# /customers/{id}/files），不与任何既有路径重合，顺序不影响匹配。
router.include_router(erp_customer_file_router)
router.include_router(erp_statement_router)
# 合同模板库（2026-10-22）：上传自己的范本，新建合同时套用
router.include_router(erp_contract_template_router)
# 合同付款计划（2026-10-23）：多期次计划 + 每期实际付款与回单
router.include_router(erp_contract_payment_router)
# 三单匹配（2026-10-23）：合同 / 发票 / 付款 三方对账看板
router.include_router(erp_three_way_router)
# 附件归档（2026-10-23）：占用统计 + 一键备份
router.include_router(erp_storage_router)
# 多文件智能识别（2026-10-23）：新增客户/供应商/商品弹窗顶部的识别区
router.include_router(erp_smart_upload_router)

# 第 13 批（第三阶段）：/exports/kinds、/exports/{kind}。
# 新增字面段，不与任何既有路径重合；`kinds` 在模块内先于 `{kind}` 注册，
# 否则 `GET /exports/kinds` 会被当成 kind="kinds" 去吃 404。
router.include_router(erp_export_router)
router.include_router(erp_word_router)

# 向后兼容：以下名字历史上是从 routes.erp 导入的（外部模块与测试依赖），
# 拆分后它们住在各域模块里，这里统一转发，外部代码无需改动。
from app.api.v1.routes.erp_common import (  # noqa: E402,F401
    amount_to_chinese,
)
from app.api.v1.routes.erp_invoice import (  # noqa: E402,F401
    _extract_invoice_items,
    _extract_invoice_summary,
)
from app.api.v1.routes.erp_print import (  # noqa: E402,F401
    printable_doc_types,
)
