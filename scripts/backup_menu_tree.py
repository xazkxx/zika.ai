# -*- coding: utf-8 -*-
"""菜单树备份脚本 —— 把 public.menus 导出成可直接重放的 menu_tree.sql

为什么单独备菜单树：
    菜单是全局表，只存在于 public 一个 schema（co_02 / co_03 没有副本），
    改一次覆盖三个账套。菜单被改坏 / 误删 / 菜单管理页点错，整套导航就乱了，
    而整库 dump 太大、回滚太重，需要一个「只回滚菜单」的轻量快照。

产物：
    backup\\menu_tree\\menu_tree.sql              最新一份（每次覆盖）
    backup\\menu_tree\\history\\menu_tree_<时间戳>.sql   历史留档（默认留最近 30 份）

用法（必须用项目自带的 venv，别用系统 python）：
    E:\\AI\\ERP软件\\.venv\\Scripts\\python.exe scripts\\backup_menu_tree.py
    ... --out D:\\menu_tree.sql          指定输出路径
    ... --no-history                     不写历史留档
    ... --no-truncate                    生成的文件不含 TRUNCATE（会与现存行主键冲突）
    ... --with-roles                     顺带把 public.roles 也写进同一个文件（第二段）
    ... --keep 60                        历史留档保留份数
    ... --no-verify                      跳过「生成后空跑重放」自检
    ... --check                          只自检现有文件，不重新生成

还原（二选一）：
    psql -h 127.0.0.1 -U erp -d erp -f menu_tree.sql
    或在 pgAdmin 里打开这个 .sql 直接执行

注意：
    · 连接串优先取 --dsn，其次环境变量 DATABASE_URL，其次项目根 .env，最后内置默认值
    · 全程只读数据库（SELECT），唯一的写操作是生成后那次「开事务→重放→ROLLBACK」自检
    · 生成的文件是 UTF-8 无 BOM（带 BOM 会让 psql 把首行当成非法语句）
"""

from __future__ import annotations

import argparse
import datetime as dt
import os
import re
import shutil
import sys
from pathlib import Path

import psycopg
from psycopg.rows import dict_row
from psycopg.sql import Literal

# ── 路径与默认值 ────────────────────────────────────────────────────────────
ROOT = Path(__file__).resolve().parent.parent
DEFAULT_OUT = ROOT / "backup" / "menu_tree" / "menu_tree.sql"
from db_config import libpq_dsn  # noqa: E402

DEFAULT_DSN = libpq_dsn()

TABLE = "public.menus"
COLUMNS = [
    "id",
    "parent_id",
    "label",
    "page_key",
    "sort_order",
    "is_enabled",
    "is_builtin",
    "note",
    "created_at",
    "updated_at",
]


def parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser(
        description="把 public.menus 导出成可直接重放的 menu_tree.sql",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT, help=f"输出文件（默认 {DEFAULT_OUT}）")
    ap.add_argument("--dsn", default=None, help="PostgreSQL 连接串，覆盖 .env / 内置默认值")
    ap.add_argument("--keep", type=int, default=30, help="历史留档保留份数（默认 30）")
    ap.add_argument("--no-history", action="store_true", help="不写 history 留档")
    ap.add_argument("--no-truncate", action="store_true", help="生成的文件不含 TRUNCATE 语句")
    ap.add_argument("--with-roles", action="store_true", help="顺带导出 public.roles（文件第二段）")
    ap.add_argument("--no-verify", action="store_true", help="跳过生成后的空跑重放自检")
    ap.add_argument("--check", action="store_true", help="只自检现有文件，不重新生成")
    ap.add_argument("--quiet", action="store_true", help="只输出一行结果")
    return ap.parse_args()


def resolve_dsn(explicit: str | None) -> str:
    """--dsn > 环境变量 DATABASE_URL > 项目根 .env > 内置默认值"""
    if explicit:
        return explicit
    env = os.environ.get("DATABASE_URL")
    if env:
        return env
    env_file = ROOT / ".env"
    if env_file.is_file():
        for line in env_file.read_text(encoding="utf-8", errors="ignore").splitlines():
            line = line.strip()
            if line.startswith("DATABASE_URL="):
                return line.split("=", 1)[1].strip().strip('"').strip("'")
    return DEFAULT_DSN


def to_libpq(dsn: str) -> str:
    """把 SQLAlchemy 风格的 URL 转成 libpq 连接串（脚本可能直接读到 .env 里的 URL）"""
    if "://" not in dsn:
        return dsn
    m = re.match(r"^[^:]+://(?P<user>[^:@/]+)(?::(?P<pw>[^@/]*))?@(?P<host>[^:/]+)(?::(?P<port>\d+))?/(?P<db>[^?]+)", dsn)
    if not m:
        return dsn
    g = m.groupdict()
    parts = [f"host={g['host']}", f"dbname={g['db']}", f"user={g['user']}"]
    if g.get("port"):
        parts.append(f"port={g['port']}")
    if g.get("pw"):
        parts.append(f"password={g['pw']}")
    return " ".join(parts)


# ── 取数 ────────────────────────────────────────────────────────────────────
TREE_SQL = """
WITH RECURSIVE tree AS (
    SELECT m.id, m.parent_id, m.label, m.page_key, m.sort_order,
           m.is_enabled, m.is_builtin, m.note, m.created_at, m.updated_at,
           1 AS depth, lpad(m.sort_order::text, 6, '0') AS path
      FROM public.menus m
     WHERE m.parent_id IS NULL
    UNION ALL
    SELECT c.id, c.parent_id, c.label, c.page_key, c.sort_order,
           c.is_enabled, c.is_builtin, c.note, c.created_at, c.updated_at,
           t.depth + 1, t.path || '/' || lpad(c.sort_order::text, 6, '0')
      FROM public.menus c
      JOIN tree t ON c.parent_id = t.id
)
SELECT * FROM tree ORDER BY path, id
"""


def fetch_menus(conn) -> tuple[list[dict], list[dict], int]:
    """返回 (按树序落好的行, 孤立行, 最大深度)"""
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(TREE_SQL)
        ordered = cur.fetchall()
        cur.execute(f"SELECT {', '.join(COLUMNS)} FROM {TABLE}")
        all_rows = {r["id"]: r for r in cur.fetchall()}
    seen = {r["id"] for r in ordered}
    orphans = [r for rid, r in all_rows.items() if rid not in seen]
    orphans.sort(key=lambda r: (r["parent_id"] or 0, r["sort_order"], r["id"]))
    depth = max((r["depth"] for r in ordered), default=0)
    return ordered, orphans, depth


def fetch_roles(conn) -> list[dict]:
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute("SELECT id, code, name, description, permissions, is_builtin, sort_order, is_active, created_at FROM public.roles ORDER BY id")
        return cur.fetchall()


# ── 生成 SQL ────────────────────────────────────────────────────────────────
def render_tree_preview(rows: list[dict]) -> list[str]:
    """把菜单画成缩进树注释，方便肉眼核对结构"""
    out = []
    for r in rows:
        indent = "  " * max(0, int(r["depth"]) - 1)
        flags = []
        if not r["is_enabled"]:
            flags.append("停用")
        if r.get("page_key"):
            flags.append(r["page_key"])
        suffix = f"   ({' · '.join(flags)})" if flags else ""
        out.append(f"--   {indent}{r['label']}{suffix}")
    return out


def build_sql(
    menus: list[dict],
    orphans: list[dict],
    depth: int,
    roles: list[dict] | None,
    *,
    dsn_label: str,
    truncate: bool,
    generated_at: dt.datetime,
) -> str:
    L: list[str] = []
    A = L.append
    total = len(menus) + len(orphans)

    A("-- " + "=" * 76)
    A("-- menu_tree.sql —— 菜单树备份（public.menus）")
    A("-- " + "=" * 76)
    A(f"-- 生成时间 : {generated_at:%Y-%m-%d %H:%M:%S}")
    A(f"-- 来源库   : {dsn_label}")
    A(f"-- 菜单行数 : {total}（树内 {len(menus)}" + (f"，孤立节点 {len(orphans)}" if orphans else "") + f"）")
    A(f"-- 树最大深度: {depth} 层")
    A(f"-- 启用 / 停用: {sum(1 for r in menus if r['is_enabled'])} / {sum(1 for r in menus if not r['is_enabled'])}")
    if roles is not None:
        A(f"-- 附：public.roles {len(roles)} 行（见文件末尾第二段）")
    A("-- 编码     : UTF-8 无 BOM")
    A("-- ")
    A("-- 用法： psql -h 127.0.0.1 -U erp -d erp -f menu_tree.sql")
    A("--        （或在 pgAdmin 里打开本文件直接执行）")
    A("-- ")
    if truncate:
        A("-- ⚠️ 本文件含 TRUNCATE public.menus，执行后菜单表会被替换成快照内容。")
        A("--    想「只补不删」请重新生成并加 --no-truncate，或手动删掉 TRUNCATE 那一行。")
    else:
        A("-- 本文件不含 TRUNCATE：直接执行会与现存行主键冲突，")
        A("-- 只适合在空表 / 已清空 menus 的库上还原。")
    A("-- " + "=" * 76)
    A("")
    A("-- ── 菜单结构预览（注释，仅供核对）────────────────────────────────")
    L.extend(render_tree_preview(menus))
    for r in orphans:
        A(f"--   [孤立] {r['label']}   (id={r['id']}, parent_id={r['parent_id']})")
    A("")
    A("BEGIN;")
    A("SET client_encoding = 'UTF8';")
    A("")
    if truncate:
        A("-- 先清空再插入：保证还原后与快照逐行一致（菜单表无外键指向，CASCADE 只是保险）")
        A(f"TRUNCATE TABLE {TABLE} CASCADE;")
        A("")
    A(f"-- 菜单数据：{total} 行（按树序排列，父节点一定在子节点之前）")
    cols = ", ".join(COLUMNS)
    for r in menus + orphans:
        if orphans and r is orphans[0]:
            A("-- ── 以下为孤立节点（parent_id 指向不存在 / 已停用的父级）──")
        elif int(r.get("depth", 1)) == 1:
            A(f"-- ▼ {r['label']}")
        vals = ", ".join(Literal(r[c]).as_string(_ADAPTER[0]) for c in COLUMNS)
        A(f"INSERT INTO {TABLE} ({cols}) VALUES ({vals});")
    A("")
    A("-- 序列对齐：不重置的话，新增菜单会从旧的最大值继续，可能撞主键")
    A(f"SELECT setval('public.menus_id_seq', COALESCE((SELECT MAX(id) FROM {TABLE}), 1), true);")
    A("")

    if roles is not None:
        A("-- " + "=" * 76)
        A(f"-- 第二段：public.roles（{len(roles)} 行）")
        A("-- 角色里的 permissions 是 JSON 文本，按页面 key 授予访问权；")
        A("-- 菜单结构调整后如果想让权限跟着回滚，把这一段也执行掉。")
        A("-- " + "=" * 76)
        A("")
        RCOLS = ["id", "code", "name", "description", "permissions", "is_builtin", "sort_order", "is_active", "created_at"]
        rcols = ", ".join(RCOLS)
        if truncate:
            A("TRUNCATE TABLE public.roles CASCADE;")
            A("")
        for r in roles:
            vals = ", ".join(Literal(r[c]).as_string(_ADAPTER[0]) for c in RCOLS)
            A(f"INSERT INTO public.roles ({rcols}) VALUES ({vals});")
        A("")
        A("SELECT setval('public.roles_id_seq', COALESCE((SELECT MAX(id) FROM public.roles), 1), true);")
        A("")

    A("COMMIT;")
    A("")
    A(f"-- 文件结束（{generated_at:%Y-%m-%d %H:%M:%S}）")
    return "\n".join(L) + "\n"


# Literal().as_string(conn) 需要一个连接做类型适配；连一次共享即可
_ADAPTER: list = []


# ── 自检：开事务重放一遍再回滚 ────────────────────────────────────────────────
def verify_replay(conn, sql_text: str, expected_rows: int | None = None) -> tuple[bool, str]:
    """把生成的文件放进一个事务里真跑一遍，核对行数后 ROLLBACK。

    这样能在「还没出事」的时候就知道这份 .sql 到底能不能用 —— 不是靠肉眼看格式。
    expected_rows 为 None 时，按文件里的 INSERT 条数推断。
    """
    stmts = split_statements(sql_text)
    if expected_rows is None:
        expected_rows = sum(
            1 for s in stmts if s.upper().startswith(f"INSERT INTO {TABLE.upper()}")
        )
    try:
        with conn.cursor() as cur:
            # 不用显式 BEGIN：psycopg 默认自动开事务，显式写会收到 "already in transaction" 告警
            cur.execute("SET LOCAL client_encoding = 'UTF8'")
            # 文件里没有 TRUNCATE（--no-truncate）时，自检先自己清一次，否则必撞主键
            ups = [s.upper() for s in stmts]
            if not any(u.startswith("TRUNCATE") for u in ups):
                cur.execute(f"TRUNCATE TABLE {TABLE} CASCADE")
                if any(u.startswith("INSERT INTO PUBLIC.ROLES") for u in ups):
                    cur.execute("TRUNCATE TABLE public.roles CASCADE")
            for stmt in stmts:
                cur.execute(stmt)
            cur.execute(f"SELECT count(*) FROM {TABLE}")
            got = cur.fetchone()[0]
            cur.execute("ROLLBACK")
        if got != expected_rows:
            return False, f"重放后行数 {got} != 期望 {expected_rows}"
        return True, f"重放 {expected_rows} 行无误"
    except Exception as exc:  # noqa: BLE001
        try:
            conn.rollback()
        except Exception:  # noqa: BLE001
            pass
        return False, f"{type(exc).__name__}: {exc}"


def split_statements(sql_text: str) -> list[str]:
    """切出可执行的语句：丢掉注释空行、丢掉 BEGIN/COMMIT（自检时由脚本控事务）"""
    buf: list[str] = []
    cur: list[str] = []
    for raw in sql_text.splitlines():
        line = raw.strip()
        if not line or line.startswith("--"):
            continue
        cur.append(line)
        if line.endswith(";"):
            stmt = " ".join(cur).strip()
            cur = []
            head = stmt.split(None, 1)[0].upper() if stmt else ""
            if head in ("BEGIN;", "COMMIT;"):
                continue
            buf.append(stmt)
    return buf


# ── 主流程 ──────────────────────────────────────────────────────────────────
def prune_history(history_dir: Path, keep: int) -> int:
    files = sorted(history_dir.glob("menu_tree_*.sql"), key=lambda p: p.name, reverse=True)
    removed = 0
    for f in files[keep:]:
        try:
            f.unlink()
            removed += 1
        except OSError:
            pass
    return removed


def main() -> int:
    args = parse_args()
    dsn = to_libpq(resolve_dsn(args.dsn))
    label = re.sub(r"password=\S+", "password=***", dsn)

    out: Path = args.out
    if not out.is_absolute():
        out = (ROOT / out).resolve()

    if args.check and not out.is_file():
        print(f"[x] 要自检的文件不存在: {out}")
        return 2

    with psycopg.connect(dsn, connect_timeout=10) as conn:
        _ADAPTER.append(conn)

        if args.check:
            text = out.read_text(encoding="utf-8")
            ok, msg = verify_replay(conn, text)
            print(f"[{'OK' if ok else 'FAIL'}] 自检 {out.name}: {msg}")
            return 0 if ok else 1

        menus, orphans, depth = fetch_menus(conn)
        roles = fetch_roles(conn) if args.with_roles else None
        now = dt.datetime.now()
        sql_text = build_sql(
            menus,
            orphans,
            depth,
            roles,
            dsn_label=label,
            truncate=not args.no_truncate,
            generated_at=now,
        )

        expected = len(menus) + len(orphans)
        ok, msg = (True, "已跳过")
        if not args.no_verify:
            ok, msg = verify_replay(conn, sql_text, expected)

        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(sql_text, encoding="utf-8", newline="\n")

        hist_note = "未写历史留档"
        if not args.no_history:
            hdir = out.parent / "history"
            hdir.mkdir(parents=True, exist_ok=True)
            hfile = hdir / f"menu_tree_{now:%Y%m%d_%H%M%S}.sql"
            shutil.copy2(out, hfile)
            removed = prune_history(hdir, args.keep)
            hist_note = f"留档 {hfile.name}" + (f"，清理旧档 {removed} 份" if removed else "")
        print("")

    size_kb = out.stat().st_size / 1024
    if args.quiet:
        print(f"{'OK' if ok else 'FAIL'} {out} {expected} 行 {size_kb:.1f}KB")
    else:
        print(f"  [{'OK' if ok else 'FAIL'}] 空跑重放自检：{msg}")
        print(f"  菜单行数 : {expected}（树内 {len(menus)}" + (f"，孤立 {len(orphans)}" if orphans else "") + f"）")
        print(f"  树深     : {depth} 层")
        print(f"  输出     : {out}  ({size_kb:.1f} KB)")
        print(f"  历史留档 : {hist_note}")
        if orphans:
            print(f"  ⚠️ 有 {len(orphans)} 个孤立节点（parent_id 指向不存在的父级），已在文件末尾单列")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
