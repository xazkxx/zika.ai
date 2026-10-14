"""打印模板 —— 系统管理第 5 批第 3 轮。

**刻意不照抄浩技云的「字段表管理 / 打印字段表」**。那套机制把标题、抬头、
明细列、字段顺序全部做成数据库里的动态元数据，再交由一个通用表单引擎拼装。
代价是：

- 列宽、合计位置、换页阈值这些**只有渲染器才掌握的东西**被搬进了数据库，
  数据库里多一个字段，渲染器就多一个可能猜错的组合；
- 出一张格式错乱的发票 / 送货单，比"模板不能随便改"严重得多。

所以这里采用「**模板配置表 + 固定渲染器**」：

- 渲染逻辑（`app/services/pdf_render.py`）完全静态，永远只认它显式支持的 key；
- 模板表**只放渲染器明确支持、且改完立刻看得见**的外观项：
  模板名 / 标题 / 抬头附加文字 / 页脚文字 / 是否打印公司抬头 / 是否打印签章栏；
- `doc_type` 不由用户输入，而是**从打印注册表推导**（见
  `app/api/v1/routes/erp.py::printable_doc_types`）。新增一张单据的打印，
  就自动多一条模板记录，不需要在两处维护清单 —— 一旦有人加了打印但忘了
  归类，`tests/test_system_templates_and_logs.py` 会挡住。

页脚的三层优先级在这里落地：**模板 > 系统参数 `print.footer_text` > 默认页码**。
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, Session

from app.db.base import Base
from app.models.system_config import get_param


class PrintTemplate(Base):
    """一张单据类型对应一条模板记录（`doc_type` 唯一）。"""

    __tablename__ = "print_templates"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    # 与打印注册表的 key 一致：purchase-order / sales-order / contract ...
    doc_type: Mapped[str] = mapped_column(String(40), unique=True, index=True, nullable=False)
    # 注册表里的中文名快照：列表页不必回查代码；播种时同步，不覆盖用户填的 name
    doc_label: Mapped[str] = mapped_column(String(60), default="", nullable=False)
    # 模板名：默认等于 doc_label，用户可以改成"销售开单（带价格）"之类
    name: Mapped[str] = mapped_column(String(80), default="", nullable=False)
    # 标题覆盖：空 = 用单据自带的标题（不要把单据标题清掉，所以只在非空时覆盖）
    title: Mapped[str] = mapped_column(String(80), default="", nullable=False)
    # 抬头附加文字：公司名下的一行/多行（地址、电话、税号），支持 \n
    header_text: Mapped[str] = mapped_column(Text, default="", nullable=False)
    # 页脚文字：空 = 回落到系统参数 print.footer_text
    footer_text: Mapped[str] = mapped_column(Text, default="", nullable=False)
    # 是否打印公司抬头（来自 company.json）
    show_company: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    # 是否打印签章栏（制单 / 审核 / 仓管 …）
    show_signatures: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    note: Mapped[str | None] = mapped_column(String(255), nullable=True)
    sort_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=func.now(), onupdate=func.now(), nullable=False
    )


# 不在 `_PRINT_KINDS` 里、但有独立打印路由的单据类型：
# 对账单 / 余额确认单是按往来单位 + 期间打印的，不是"某一张单据"，故单独登记。
STANDALONE_DOC_TYPES: list[tuple[str, str]] = [
    ("statement", "往来对账单"),
    ("balance-confirm", "往来余额确认单"),
]

# 模板列表的展示顺序（业务顺序，不是字母序）。
# 打印注册表里出现、但不在这份清单里的 doc_type 会排到末尾 ——
# 测试会断言"注册表里的类型必须都在这里归类"，所以实际不会发生。
DOC_TYPE_ORDER: list[str] = [
    "purchase-order",
    "purchase-inbound",
    "purchase-return",
    "sales-order",
    "delivery-note",
    "quotation",
    "sales-return",
    "contract",
    "statement",
    "balance-confirm",
    "inventory-transfer",
    "stocktaking",
    "assembly",
    "inventory-scrap",
    "inventory-overflow",
    "production-plan",
    "material-issue",
    "material-return",
    "finished-goods",
    "outsourcing",
]

# 用户可改的字段（PUT/PATCH 只认这些，其余一律忽略）
TEMPLATE_EDITABLE_FIELDS: tuple[str, ...] = (
    "name",
    "title",
    "header_text",
    "footer_text",
    "show_company",
    "show_signatures",
    "note",
)


def sort_doc_types(pairs: list[tuple[str, str]]) -> list[tuple[str, str]]:
    """按 DOC_TYPE_ORDER 排序；未归类的排到末尾（按原顺序稳定）。"""
    rank = {key: index for index, key in enumerate(DOC_TYPE_ORDER)}
    return sorted(pairs, key=lambda item: (rank.get(item[0], len(rank)),))


def get_print_template(db: Session, doc_type: str) -> PrintTemplate | None:
    row = db.query(PrintTemplate).filter(PrintTemplate.doc_type == doc_type).first()
    return row


def template_to_spec(template: PrintTemplate, spec: dict) -> dict:
    """把一条模板叠加到打印 spec 上（纯 dict 变换，不做任何渲染）。

    每条规则都是"非空才覆盖"或"关了才删除"：模板留空 = 不干预单据自带内容，
    这样管理员只想改个页脚时，不会顺手把单据标题清成空白。
    """
    result = dict(spec)
    if template.title:
        result["title"] = template.title
    if template.header_text:
        result["header_text"] = template.header_text
    if not template.show_company:
        # 渲染器只认 `company` 这个 key，删掉就是不打印公司抬头
        result.pop("company", None)
    if not template.show_signatures:
        result.pop("signatures", None)
    if template.footer_text:
        result["footer_text"] = template.footer_text
    return result


def resolve_print_spec(db: Session, doc_type: str | None, spec: dict) -> dict:
    """打印 spec 的最终组装：单据自带 → 打印模板 → 系统参数。

    `doc_type` 为空（或没配模板）时退回"只注入系统参数页脚"，
    保证老调用方与未登记的单据类型行为不变。
    """
    result = dict(spec)
    if doc_type:
        template = get_print_template(db, doc_type)
        if template is not None:
            result = template_to_spec(template, result)

    if not str(result.get("footer_text") or "").strip():
        fallback = get_param(db, "print.footer_text", "")
        if fallback:
            result["footer_text"] = fallback
    return result
