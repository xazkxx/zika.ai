# -*- coding: utf-8 -*-
"""第一阶段（需求 1、2）迁移执行器 —— 只执行"已经确认实施"的部分。

为什么单独写这个脚本，而不是直接 import app.main：
    `app.main` 在 import 期就会 create_app()，顺手对**所有**账套跑一遍建表与补列
    （见 MEMORY：验证脚本绝不 import app.main）。这里只做本阶段明确要做的几件事，
    做完打印前后对照，方便一眼确认改了哪些列。

执行内容（全部幂等）：
    1. 补字典分类 fund_account / settlement_method 及其字典项（全局表 public）
    2. customers.account_name / suppliers.tax_no / suppliers.account_name（每个账套）
    3. financial_transactions.flow_no + 索引（每个账套）

**不执行** print_templates 的纸张/边距/字号扩展 —— 那部分等用户确认表结构后
另行执行（SQL 见 scripts/sql/phase1_dictionary_and_print_template.sql 第 4 节）。
"""
from __future__ import annotations

import sys
from pathlib import Path

import psycopg

from db_config import psycopg_dsn  # noqa: E402

DSN = psycopg_dsn()

TENANT_COLUMNS = [
    ("customers", "account_name", "VARCHAR(150)"),
    ("suppliers", "tax_no", "VARCHAR(50)"),
    ("suppliers", "account_name", "VARCHAR(150)"),
    ("financial_transactions", "flow_no", "VARCHAR(40)"),
]

DICT_TYPES = [
    ("fund_account", "资金账户", "日常收支登记时的资金账户候选（真实余额以现金银行页的资金账户为准）",
     ["现金", "基本户", "一般户", "微信", "支付宝", "备用金"]),
    ("settlement_method", "结算方式", "单据上的结算方式候选（现结 / 月结 / 账期 …），与「付款方式」互补",
     ["现结", "月结", "货到付款", "预付款", "货到验收后付", "分期付款", "代收代付"]),
]


def tenant_schemas(cur) -> list[str]:
    cur.execute(
        "select schema_name from information_schema.schemata "
        "where schema_name = 'public' or schema_name like 'co\\_%' order by schema_name"
    )
    return [row[0] for row in cur.fetchall()]


def column_exists(cur, schema: str, table: str, column: str) -> bool:
    cur.execute(
        "select 1 from information_schema.columns "
        "where table_schema=%s and table_name=%s and column_name=%s",
        (schema, table, column),
    )
    return cur.fetchone() is not None


def table_exists(cur, schema: str, table: str) -> bool:
    cur.execute(
        "select 1 from information_schema.tables where table_schema=%s and table_name=%s",
        (schema, table),
    )
    return cur.fetchone() is not None


def main() -> int:
    sql_path = Path(__file__).resolve().parent / "sql" / "phase1_dictionary_and_print_template.sql"
    if not sql_path.exists():
        print(f"[FAIL] 找不到 SQL 文件：{sql_path}")
        return 1

    changed: list[str] = []
    with psycopg.connect(DSN) as conn:
        with conn.cursor() as cur:
            schemas = tenant_schemas(cur)
            print(f"账套 schema：{schemas}")

            # —— 1. 账套表补列 ——
            for schema in schemas:
                for table, column, ddl_type in TENANT_COLUMNS:
                    if not table_exists(cur, schema, table):
                        print(f"  [SKIP] {schema}.{table} 不存在")
                        continue
                    if column_exists(cur, schema, table, column):
                        continue
                    cur.execute(f'ALTER TABLE "{schema}"."{table}" ADD COLUMN {column} {ddl_type}')
                    changed.append(f"{schema}.{table}.{column}")
                    print(f"  [ADD ] {schema}.{table}.{column} {ddl_type}")

            # flow_no 索引（与模型 index=True 对齐；账套表每个 schema 各一个）
            for schema in schemas:
                if not column_exists(cur, schema, "financial_transactions", "flow_no"):
                    continue
                cur.execute(
                    f'CREATE INDEX IF NOT EXISTS "ix_{schema}_ft_flow_no" '
                    f'on "{schema}"."financial_transactions" (flow_no)'
                )

            # —— 2. 字典分类与字典项（全局表 public）——
            for dict_type, dict_name, description, items in DICT_TYPES:
                cur.execute("select 1 from data_dictionaries where dict_type=%s", (dict_type,))
                if cur.fetchone() is None:
                    cur.execute(
                        "insert into data_dictionaries (dict_type, dict_name, description, is_system, is_active) "
                        "values (%s,%s,%s,true,true)",
                        (dict_type, dict_name, description),
                    )
                    changed.append(f"dict:{dict_type}")
                    print(f"  [ADD ] 字典分类 {dict_type}（{dict_name}）")
                for index, item in enumerate(items, start=1):
                    cur.execute(
                        "select 1 from data_dictionary_items where dict_type=%s and item_value=%s",
                        (dict_type, item),
                    )
                    if cur.fetchone() is None:
                        cur.execute(
                            "insert into data_dictionary_items "
                            "(dict_type, item_value, item_label, sort_order, is_enabled) "
                            "values (%s,%s,%s,%s,true)",
                            (dict_type, item, item, index * 10),
                        )
                        changed.append(f"dict_item:{dict_type}/{item}")

        conn.commit()

        # —— 3. 后置自检 ——
        print("\n—— 自检 ——")
        ok = True
        with conn.cursor() as cur:
            for schema in tenant_schemas(cur):
                for table, column, _ in TENANT_COLUMNS:
                    if not table_exists(cur, schema, table):
                        continue
                    exists = column_exists(cur, schema, table, column)
                    ok = ok and exists
                    print(f"  {'[OK  ]' if exists else '[MISS]'} {schema}.{table}.{column}")
            cur.execute("select dict_type, count(*) from data_dictionary_items group by 1 order by 1")
            for dict_type, count in cur.fetchall():
                print(f"  [OK  ] 字典 {dict_type}: {count} 项")

    print(f"\n本次实际变更 {len(changed)} 处" + ("" if changed else "（已是最新，无需变更）"))
    print("结论：" + ("通过" if ok else "有列缺失，请检查"))
    return 0 if ok else 2


if __name__ == "__main__":
    sys.exit(main())
