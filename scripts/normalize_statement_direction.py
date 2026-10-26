# -*- coding: utf-8 -*-
"""对账单方向归一 —— 把 `statements.direction` 统一成 `out` / `in`。

为什么要单独跑一次
------------------
需求 3 把「采购对账单 / 销售对账单 / 增强对账单」三个入口归一到同一个页面，
页面按 `direction` 分三视角（全部 / 应收 / 应付）。规范值是 **`out` = 应收**、
**`in` = 应付**（与 `contracts.direction`、`invoices.direction` 同一套字典）。

历史上这个字段可能被写成下面这些同义词（导入、老版本前端、手工 SQL 都会留下）：

    out  ← outbound / sales / receivable / 应收 / 销项
    in   ← inbound  / purchase / payable   / 应付 / 进项

`normalize_direction()` 只认 `in` / `out`，其它值会**静默回落到 `out`** ——
也就是一张应付对账单会被显示成应收，而且看起来"有数据"，最难发现。
所以在切换页面之前，先把存量洗干净。

安全边界（刻意保守）
--------------------
1. **默认 dry-run**，只打印不写。加 `--apply` 才真的 UPDATE。
2. **只动方向列**，不碰金额、不碰明细、不碰状态。
3. **不猜语义相反的值**：`direction='out'` 但 `party_type='supplier'` 这种自相矛盾的
   行只**报告**，不自动改 —— 改哪一边都可能把业务账改错，得人来判断。
4. 幂等：已经是 `out` / `in` 的行不会被写（`--apply` 跑两次结果一样）。

用法（必须用项目自带 venv）
--------------------------
    E:\\AI\\ERP软件\\.venv\\Scripts\\python.exe scripts\\normalize_statement_direction.py
    ... --apply          真的写库
    ... --dsn "postgresql://erp:erp123456@127.0.0.1:5432/erp"
"""

from __future__ import annotations

import argparse
import os
import re
from pathlib import Path

import psycopg

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DSN = "postgresql://erp:erp123456@127.0.0.1:5432/erp"

# 同义词 → 规范值。键一律小写、去空格后比较。
TO_IN = {"in", "inbound", "purchase", "payable", "应付", "进项", "采购"}
TO_OUT = {"out", "outbound", "sales", "receivable", "应收", "销项", "销售"}

# 这些值和 party_type 的对应关系是硬约束（后端 generate 接口也这么校验）
PARTY_OF = {"out": "customer", "in": "supplier"}


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
    """SQLAlchemy 风格 URL → libpq 连接串（.env 里存的是前者）"""
    if "://" not in dsn:
        return dsn
    m = re.match(
        r"^[^:]+://(?P<user>[^:@/]+)(?::(?P<pw>[^@/]*))?@(?P<host>[^:/]+)(?::(?P<port>\d+))?/(?P<db>[^?]+)",
        dsn,
    )
    if not m:
        return dsn
    g = m.groupdict()
    parts = [f"host={g['host']}", f"dbname={g['db']}", f"user={g['user']}"]
    if g.get("pw"):
        parts.append(f"password={g['pw']}")
    if g.get("port"):
        parts.append(f"port={g['port']}")
    return " ".join(parts)


def normalize(value: object, party_type: object) -> tuple[str, str]:
    """返回 (规范方向, 说明)。说明为空表示本来就是规范值。"""
    original = str(value or "")
    raw = original.strip()
    key = raw.lower()
    # ⚠️ 只有"原样就是规范值"才算无需改动。`'OUT'` / `' in '` 也是要改的 ——
    #    后端一律用 `== 'in'` 精确比较，前后空格或大小写不同都会被当成"未知方向"。
    if key == "in":
        return "in", "" if original == "in" else f"大小写/空格 {original!r} → in"
    if key == "out":
        return "out", "" if original == "out" else f"大小写/空格 {original!r} → out"
    if key in TO_IN:
        return "in", f"同义词 {raw!r} → in"
    if key in TO_OUT:
        return "out", f"同义词 {raw!r} → out"
    # 空值 / 无法识别 → 按往来单位类型推（比一律 out 更接近真实业务）
    party = str(party_type or "").strip().lower()
    if party == "supplier":
        return "in", f"空/未知值 {raw!r} → 按 party_type=supplier 推为 in"
    if party == "customer":
        return "out", f"空/未知值 {raw!r} → 按 party_type=customer 推为 out"
    return "out", f"空/未知值 {raw!r} 且 party_type 不可用 → 回落 out（请人工复核）"


def main() -> int:
    parser = argparse.ArgumentParser(description="归一 statements.direction 为 out/in")
    parser.add_argument("--dsn", help="连接串，默认取环境变量 / .env / 内置值")
    parser.add_argument("--apply", action="store_true", help="真的写库（默认只预览）")
    args = parser.parse_args()

    dsn = to_libpq(resolve_dsn(args.dsn))
    mode = "APPLY（会写库）" if args.apply else "DRY-RUN（只预览，不写）"
    print(f"模式：{mode}")

    with psycopg.connect(dsn) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "select table_schema from information_schema.tables "
                "where table_name = 'statements' order by 1"
            )
            schemas = [row[0] for row in cur.fetchall()]
            if not schemas:
                print("没有找到任何 statements 表，退出。")
                return 0
            print(f"账套 schema：{', '.join(schemas)}")

            total_rows = 0
            changed = 0
            conflicts: list[str] = []
            unknown: list[str] = []

            for schema in schemas:
                cur.execute(
                    f'select id, statement_no, direction, party_type, status '
                    f'from "{schema}".statements order by id'
                )
                rows = cur.fetchall()
                total_rows += len(rows)
                if not rows:
                    print(f"  [{schema}] 0 张对账单")
                    continue

                print(f"  [{schema}] {len(rows)} 张对账单")
                for sid, no, direction, party_type, status in rows:
                    target, why = normalize(direction, party_type)
                    # 自相矛盾：方向与往来单位类型不匹配 → 只报告
                    expected_party = PARTY_OF[target]
                    if str(party_type or "").strip().lower() not in ("", expected_party):
                        conflicts.append(
                            f"{schema}.{no}(id={sid}) direction={direction!r} "
                            f"party_type={party_type!r} → 归一后应为 {target}/{expected_party}"
                        )
                    if why:
                        unknown.append(f"{schema}.{no}(id={sid}) {why}")
                    if why:
                        changed += 1
                        if args.apply:
                            cur.execute(
                                f'update "{schema}".statements set direction = %s '
                                f"where id = %s and coalesce(direction, '') <> %s",
                                (target, sid, target),
                            )
                        print(f"    改：{no}  {direction!r} → {target}   （{why}）")
                    elif target != str(direction or "").strip():
                        # 防御：normalize 已保证这里不会发生，留着好排查
                        print(f"    ⚠ {no} 规范化结果与现值不一致但未标记：{direction!r} → {target}")

            if args.apply:
                conn.commit()
                print(f"\n已提交。{'改了' if changed else '无需改动'} {changed} 行 / 共 {total_rows} 行。")
            else:
                print(f"\nDRY-RUN：将改 {changed} 行 / 共 {total_rows} 行。加 --apply 才会真正写库。")

            if conflicts:
                print(f"\n⚠ 方向与往来单位类型冲突 {len(conflicts)} 条（**未自动修改**，请人工判断）：")
                for line in conflicts:
                    print("   -", line)
            if unknown:
                print(f"\n归一明细 {len(unknown)} 条：")
                for line in unknown:
                    print("   -", line)
            if not conflicts and not unknown:
                print("\n全部已是规范值（out / in），无需处理。")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
