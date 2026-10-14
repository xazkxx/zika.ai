"""把 SQLite erp.db 的全部数据迁移到 PostgreSQL（按外键依赖顺序逐表复制）。"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import Integer, create_engine, text

from app.db.base import Base
from app.main import app  # noqa: F401  确保所有模型已注册到 Base.metadata

SRC_URL = "sqlite:///./erp.db"
DST_URL = "postgresql+psycopg://erp:erp123456@127.0.0.1:5432/erp"


def main() -> None:
    src = create_engine(SRC_URL)
    dst = create_engine(DST_URL)

    print("创建 PostgreSQL 表结构...")
    Base.metadata.create_all(bind=dst)

    # 清空目标表，保证脚本可重复执行（表是 erp 用户建的，TRUNCATE 无需超级权限）
    with dst.begin() as dconn:
        for table in reversed(Base.metadata.sorted_tables):
            dconn.execute(text(f'TRUNCATE TABLE "{table.name}" RESTART IDENTITY CASCADE'))

    total = 0
    for table in Base.metadata.sorted_tables:
        with src.connect() as sconn:
            rows = [dict(row._mapping) for row in sconn.execute(table.select())]
        if not rows:
            continue
        with dst.begin() as dconn:
            dconn.execute(table.insert(), rows)
        print(f"{table.name}: {len(rows)} 行")
        total += len(rows)

    # 同步自增序列：显式插入带 ID 的行不会推进序列，不处理会导致后续新增主键冲突
    with dst.begin() as dconn:
        for table in Base.metadata.sorted_tables:
            for pk in table.primary_key.columns:
                if pk.table is table and pk.autoincrement is not False and isinstance(pk.type, Integer):
                    dconn.execute(text(
                        f"SELECT setval(pg_get_serial_sequence('{table.name}', '{pk.name}'), "
                        f"COALESCE((SELECT MAX({pk.name}) FROM {table.name}), 1))"
                    ))

    print(f"迁移完成，共 {total} 行。")


if __name__ == "__main__":
    main()
