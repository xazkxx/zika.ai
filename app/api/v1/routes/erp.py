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
from app.api.v1.routes.erp_inventory import router as erp_inventory_router
from app.api.v1.routes.erp_purchase import router as erp_purchase_router
from app.api.v1.routes.erp_sales import router as erp_sales_router
from app.api.v1.routes.erp_misc import router as erp_misc_router
from app.api.v1.routes.erp_finance import router as erp_finance_router
from app.api.v1.routes.erp_print import router as erp_print_router
from app.api.v1.routes.erp_production import router as erp_production_router
from app.api.v1.routes.erp_project import router as erp_project_router
from app.api.v1.routes.erp_dataio import router as erp_dataio_router

router = APIRouter(prefix="", tags=["erp"])

router.include_router(erp_invoice_router)
router.include_router(erp_archive_router)
router.include_router(erp_inventory_router)
router.include_router(erp_purchase_router)
router.include_router(erp_sales_router)
router.include_router(erp_misc_router)
router.include_router(erp_finance_router)
router.include_router(erp_print_router)
router.include_router(erp_production_router)
router.include_router(erp_project_router)
router.include_router(erp_dataio_router)

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
