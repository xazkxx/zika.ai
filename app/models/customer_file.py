"""客户文件归档（第 13 批 · 模块 2）。

设计口径：

1. **一个客户一条档案，N 个文件** —— 合同扫描件、营业执照、资质证书、发票、对账单
   全挂在客户下，列表页按分类筛选。
2. **磁盘上不信任用户文件名**：`original_name` 是给用户看的原始名，
   `stored_name` 是落盘用的（`uuid4().hex + 扩展名`），两者分开存。
   这样同名文件不会互相覆盖，中文名/特殊字符也不会把路径搞坏。
3. **路径存相对 storage_root**（与 `invoices.source_path` 同口径）：
   存绝对路径换台机器/换盘就全部失效。
4. **`customer_id` 用 `ON DELETE RESTRICT`（重点）**：
   需求原话是"防止删除客户导致文件丢失"。四种外键行为的取舍：

   | 行为 | 删客户时 | 是否符合本需求 |
   | --- | --- | --- |
   | CASCADE | 文件记录连同物理文件一起没了 | ❌ 正是要防止的事故 |
   | SET NULL | 记录变成"孤儿"，谁都找不到 | ❌ 文件变垃圾 |
   | NO ACTION/RESTRICT | **直接拒绝删除** | ✅ 选它 |

   代价：删除有文件的客户会抛 `IntegrityError`。这是**有意的**——
   路由层必须先查一次 `count_customer_files()`，返回 409 + 中文原因
   （"该客户下还有 N 个归档文件，请先移走或删除"），而不是把 500 抛给用户。
   这一步属于第二阶段（路由），模型层先把数据库护栏立起来。

5. 物理文件与数据库记录**不同生共死**：删记录时不自动删磁盘文件
   （误删不可恢复；磁盘清理由"回收站/归档"策略处理）。
"""

from datetime import datetime

from sqlalchemy import BigInteger, DateTime, ForeignKey, Index, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class CustomerFile(Base):
    """客户归档文件。"""

    __tablename__ = "customer_files"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)

    # ON DELETE RESTRICT：有归档文件的客户删不掉（见文件头 4）
    customer_id: Mapped[int] = mapped_column(
        ForeignKey("customers.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )

    # —— 文件标识 ——
    original_name: Mapped[str] = mapped_column(String(255), nullable=False)  # 用户上传时的文件名
    stored_name: Mapped[str] = mapped_column(String(255), nullable=False)  # 磁盘文件名（uuid + 扩展名）
    file_path: Mapped[str | None] = mapped_column(String(500), nullable=True)  # 相对 storage_root
    file_size: Mapped[int | None] = mapped_column(BigInteger, nullable=True)  # 字节（>2GB 也不溢出）
    mime_type: Mapped[str | None] = mapped_column(String(100), nullable=True)
    # SHA-256：同一份合同被重复上传时能认出来，也便于校验文件是否被替换
    checksum: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)

    # —— 业务分类 ——
    # contract 合同 / qualification 资质 / invoice 发票 / statement 对账单 / other 其他
    category: Mapped[str] = mapped_column(
        String(20), default="other", server_default="other", nullable=False
    )

    # —— 审计 ——
    uploaded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    uploaded_by: Mapped[str | None] = mapped_column(String(50), nullable=True)
    note: Mapped[str | None] = mapped_column(String(255), nullable=True)

    # 关系只用于「删客户前先数一下」这类查询；不要在 cascade 上做文章（见文件头 4）
    customer = relationship("Customer", lazy="joined", viewonly=True)

    __table_args__ = (
        # 客户 + 分类 是列表页最常用的过滤组合
        Index("ix_customer_files_customer_category", "customer_id", "category"),
    )


# 分类字典 —— 前端下拉与后端校验共用
CUSTOMER_FILE_CATEGORIES: dict[str, str] = {
    "contract": "合同",
    "qualification": "资质",
    "invoice": "发票",
    "statement": "对账单",
    "other": "其他",
}

# 允许上传的 MIME（第二阶段上传接口用；放这里避免前后端各写一份）
CUSTOMER_FILE_MIME_WHITELIST: tuple[str, ...] = (
    "application/pdf",
    "application/msword",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "application/vnd.ms-excel",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "image/jpeg",
    "image/png",
    "image/webp",
    "image/tiff",
)


def count_customer_files(session, customer_id: int) -> int:
    """删客户前先调用它：返回该客户名下归档文件数。

    第二阶段的路由必须写成：
        n = count_customer_files(db, customer_id)
        if n: raise HTTPException(409, f"该客户下还有 {n} 个归档文件，请先处理")
    否则外键 RESTRICT 会以 `IntegrityError` 形式抛 500，用户只看到"服务器错误"。
    """
    return int(
        session.query(CustomerFile).filter(CustomerFile.customer_id == customer_id).count()
    )
