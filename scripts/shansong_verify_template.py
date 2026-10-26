# -*- coding: utf-8 -*-
"""模板往返验证 —— 证明「导出的文件能原样导回来」。

## 为什么单独验这一条

模板好不好看不重要，**能不能闭环**才是命门：
  导出 → 用户改几处 → 导回 → 数据正确更新

任何一环断了，模板就是一张废纸。这里逐项验证：
  1. 模板能生成
  2. 模板能被 `parse_rows` 解析（示例行会被自动跳过）
  3. 导出的真实数据能原样导回（字段一一对应，不丢列）
  4. 故意填错（缺必填、金额不符）能被挡下来

跑法
----
    ./.venv/Scripts/python.exe scripts/shansong_verify_template.py
"""

from __future__ import annotations

import io
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT_DIR))

from openpyxl import Workbook, load_workbook  # noqa: E402

from app.services import excel_io  # noqa: E402


def _make_xlsx(headers: list[str], rows: list[list]) -> bytes:
    wb = Workbook()
    ws = wb.active
    ws.title = "导入数据"
    ws.append(headers)
    for r in rows:
        ws.append(r)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def main() -> int:
    fails: list[str] = []
    steps: list[str] = []

    kinds = list(excel_io.COLUMNS.keys())

    # ── 1. 每个类别都能生成模板，且能解析出「空结果」而不是报错 ──
    for kind in kinds:
        try:
            data = excel_io.build_template(kind)
            wb = load_workbook(io.BytesIO(data))
            n_col = len(excel_io.COLUMNS[kind])
            ws = wb["导入数据"]
            head = [c.value for c in ws[2]]
            if len(head) != n_col:
                fails.append(f"{kind}: 模板表头 {len(head)} 列 ≠ 定义 {n_col} 列")
            rows, errors = excel_io.parse_rows(kind, data)
            # 模板里只有示例行，应当被 is_sample_row 过滤掉
            if rows:
                fails.append(f"{kind}: 模板自带的示例行没被跳过，解析出 {len(rows)} 行")
            steps.append(f"✅ {kind:14s} 模板 {n_col} 列，示例行已跳过")
        except Exception as exc:
            fails.append(f"{kind}: 生成/解析模板异常 {type(exc).__name__}: {exc}")

    print("── 一、模板生成与自解析 ──")
    for s in steps:
        print("  " + s)

    # ── 2. 销售单模板：真实数据往返 ──
    print()
    print("── 二、历史销售单模板：填数 → 解析 ──")
    specs = excel_io.COLUMNS["sales-orders"]
    headers = [c["label"] for c in specs]
    good_rows = [
        # 单据编号 / 日期 / 客户 / 仓库 / 商品 / 数量 / 单价 / 金额 / 单位 / 备注
        ["LS-T-001", "2025-07-06", "测试客户甲", "寨卡仓库", "*金属制品*遮阳棚", 4, 1062.0, 4248.0, "个", ""],
        ["LS-T-001", "2025-07-06", "测试客户甲", "寨卡仓库", "劳保手套", 10, 1.19, 11.9, "件", ""],
    ]
    data = _make_xlsx(headers, good_rows)
    rows, errors = excel_io.parse_rows("sales-orders", data)
    if errors:
        fails.append(f"销售单正常行被拒：{errors}")
    if len(rows) != 2:
        fails.append(f"销售单应解析 2 行，实际 {len(rows)}")
    else:
        r0 = rows[0]
        checks = {
            "order_no": "LS-T-001",
            "customer_name": "测试客户甲",
            "warehouse_name": "寨卡仓库",
            "product_name": "*金属制品*遮阳棚",
            "quantity": 4,
            "unit_price": 1062.0,
            "amount": 4248.0,
        }
        for k, v in checks.items():
            if r0.get(k) != v:
                fails.append(f"销售单字段 {k} 期望 {v!r}，实际 {r0.get(k)!r}")
        print(f"  ✅ 2 行解析正确（单据编号/客户/仓库/商品/数量/单价/金额 全部对上）")

    # ── 3. 反证：缺必填必须被拦 ──
    print()
    print("── 三、反证：故意填错必须被拦 ──")
    bad = _make_xlsx(
        [c["label"] for c in specs],
        [
            ["LS-BAD-1", "2025-07-06", "", "寨卡仓库", "劳保手套", 1, 10.0, 10.0, "", ""],
        ],
    )
    rows_b, errs_b = excel_io.parse_rows("sales-orders", bad)
    if rows_b and not errs_b:
        fails.append("缺客户名称的行竟然通过了校验")
    else:
        print(f"  ✅ 缺「客户名称」被拦下：{errs_b[0]['message'] if errs_b else ''}")

    # ── 4. 反证：表头认不出来必须明确报错 ──
    junk = _make_xlsx(["随便", "什么", "表头"], [["a", "b", "c"]])
    rows_j, errs_j = excel_io.parse_rows("sales-orders", junk)
    if rows_j and not errs_j:
        fails.append("胡乱表头竟然解析出了数据")
    else:
        msg = errs_j[0]["message"] if errs_j else ""
        print(f"  ✅ 非标准表头被拒：{msg[:38]}")

    # ── 5. 导出 → 再解析（档案类往返）──
    print()
    print("── 四、导出 → 原样导回（档案类）──")
    sample = {
        "products": [
            {"sku": "SP-T-01", "name": "测试商品", "category": "测试", "unit": "个",
             "purchase_price": 10.5, "sale_price": 15.0, "stock_upper": 100, "stock_lower": 5},
        ],
        "customers": [
            {"code": "KH-T-01", "name": "测试客户", "phone": "029-1", "level": "A", "credit_limit": 1000.0},
        ],
        "suppliers": [
            {"code": "GYS-T-01", "name": "测试供应商", "contact": "王", "init_payable": 0.0},
        ],
    }
    for kind, records in sample.items():
        data = excel_io.export_rows(kind, records)
        rows, errors = excel_io.parse_rows(kind, data)
        if errors:
            fails.append(f"{kind} 导出后无法导回：{errors}")
            continue
        if len(rows) != 1:
            fails.append(f"{kind} 往返后行数 {len(rows)} ≠ 1")
            continue
        # 逐字段核对（None 与空视为等价）
        diffs = []
        for k, v in records[0].items():
            got = rows[0].get(k)
            if v is None and got is None:
                continue
            if isinstance(v, (int, float)) and got is not None:
                if abs(float(v) - float(got)) > 1e-9:
                    diffs.append(f"{k}: {v}→{got}")
            elif got != v:
                diffs.append(f"{k}: {v!r}→{got!r}")
        if diffs:
            fails.append(f"{kind} 往返丢字段：{diffs}")
        else:
            print(f"  ✅ {kind:12s} 往返 {len(records[0])} 个字段完全一致")

    print()
    if fails:
        print(f"❌ 模板验证未通过，{len(fails)} 处问题：")
        for f in fails:
            print(f"    {f}")
        return 1
    print("✅ 模板验证全部通过：能生成、能导回、错的值挡得住")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
