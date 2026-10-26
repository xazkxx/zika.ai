# -*- coding: utf-8 -*-
"""陕送票历史数据导入 —— 预检与预览引擎（**默认只读，一行都不写库**）。

设计原则（为什么这么写）
------------------------
1. **只读优先**：`plan()` 全程只用 `SELECT`，末尾 `rollback()`。任何写库动作都在
   `commit_plan()` 里，且必须显式传 `--commit` 才会被调用。
   历史数据导入最怕的就是"先跑一遍试试，结果写进去了"。

2. **把钱算准比把数据导进去重要**：每一行都做
   「数量 × 单价 = 金额」的勾稽，且必须用 `app/core/money.py` 的 `line_amount`
   （单价是 4 位费率，先收 2 位再乘就是少钱）。

3. **档案先行的三段式**：
   ① 先算「源数据里有哪些客户/商品/供应商」→ ② 跟库里比对 → ③ 缺的先生成
   「待建档案清单」给你确认，**不自动建**。自动建档案是不可逆的（客户编码一生成
   就占号），必须先过你的眼。

4. **口径跟随现状**：库里的客户分类树已经是
   国家电网 → 陕西送变电 → 施工一部 → 谭涛总/周广平总 → 工程，
   所以工程客户直接挂到对应"人"节点下，不另造一套层级。

跑法
----
    # 只读预检（默认）
    ./.venv/Scripts/python.exe scripts/shansong_import_plan.py

    # 指定输出目录
    ./.venv/Scripts/python.exe scripts/shansong_import_plan.py --out artifacts/shansong_import
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from collections import Counter, defaultdict
from datetime import datetime
from decimal import Decimal
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT_DIR))

from app.core.money import dec, line_amount, money  # noqa: E402

SCAN_DIR = ROOT_DIR / "artifacts" / "scan_shansong"

# 我方三个开票主体 = 三个出货仓库。它们在单据上永远是**卖方**，不是买方。
SELF_ENTITIES = {
    "西安寨卡信息技术有限公司": "CK-001",
    "西安华诺迈贸易有限公司": "WH-001",
    "陕西寨纬智能科技有限公司": "WH-FG-04de8033",
}

# 简称/错字 → 标准名。源文件里实测存在「西安塞卡」（错字）。
SELF_ALIASES = {
    "西安寨卡": "西安寨卡信息技术有限公司",
    "西安塞卡": "西安寨卡信息技术有限公司",
    "西安塞卡信息技术有限公司": "西安寨卡信息技术有限公司",
    "西安华诺迈": "西安华诺迈贸易有限公司",
    "陕西寨纬": "陕西寨纬智能科技有限公司",
}

# 源文件「仓库」列的几个写法 → 库里 warehouses.name
# 实测分布：寨卡仓库 86 / 华诺迈仓库 74 / 寨纬仓库 20 / 西安寨卡信息技术有限公司 17
# 最后一类是把**公司全名**填进了仓库列（进项单的习惯写法），指的就是寨卡仓库，
# 不能因为名字对不上就判成"仓库不存在"——那 17 行会白白卡住。
WAREHOUSE_ALIASES = {
    "西安寨卡信息技术有限公司": "寨卡仓库",
    "西安塞卡信息技术有限公司": "寨卡仓库",
    "西安华诺迈贸易有限公司": "华诺迈仓库",
    "陕西寨纬智能科技有限公司": "寨纬仓库",
    "寨卡": "寨卡仓库",
    "华诺迈": "华诺迈仓库",
    "寨纬": "寨纬仓库",
}


def norm(text: object) -> str:
    """名称归一化 —— 用于**比对**，不用于写库。

    踩过的坑：库里写的是全角 `蒲白330千伏输变电工程（线路工程包4）`，
    文件里写的是半角 `蒲白330千伏输变电工程(线路工程包4)`。
    只做 `.replace("（","(")` 的话两边都变成半角，理论上应该能对上，
    但实测仍有 9 个客户对不上 —— 因为**全角括号和半角括号在源字符串里混用**，
    而且有的名字中间带断行空格（`（线 路工程包1）`）。

    所以这里统一做四件事：去所有空白、括号全转半角、全角字符转半角、
    去掉结尾的标点。只要"人能看出是同一个名字"，归一化后就应当相等。
    """
    s = str(text or "")
    # 全角 → 半角（数字、字母、标点）
    s = s.translate(
        str.maketrans(
            "０１２３４５６７８９ＡＢＣＤＥＦＧＨＩＪＫＬＭＮＯＰＱＲＳＴＵＶＷＸＹＺ"
            "ａｂｃｄｅｆｇｈｉｊｋｌｍｎｏｐｑｒｓｔｕｖｗｘｙｚ",
            "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz",
        )
    )
    for ch in (" ", "\u3000", "\n", "\r", "\t"):
        s = s.replace(ch, "")
    s = s.replace("（", "(").replace("）", ")")
    s = s.replace("，", ",").replace("　", "")
    return s.strip().strip(".,;")


# ---------------------------------------------------------------------------
# 数据库（只读）
# ---------------------------------------------------------------------------
def load_db() -> dict:
    """把比对需要的档案一次性读进内存。全程 SELECT，绝不写。"""
    import psycopg

    conn = psycopg.connect(
        "postgresql://erp:erp123456@127.0.0.1:5432/erp",
        options="-c default_transaction_read_only=on",   # 双保险：连接层就禁写
    )
    cur = conn.cursor()

    data: dict = {}

    cur.execute("SELECT id, code, name, category_id FROM customers ORDER BY id")
    data["customers"] = [
        {"id": r[0], "code": r[1], "name": r[2], "category_id": r[3]}
        for r in cur.fetchall()
    ]

    cur.execute("SELECT id, code, name FROM suppliers ORDER BY id")
    data["suppliers"] = [{"id": r[0], "code": r[1], "name": r[2]} for r in cur.fetchall()]

    cur.execute("SELECT id, sku, name, unit, category FROM products ORDER BY id")
    data["products"] = [
        {"id": r[0], "sku": r[1], "name": r[2], "unit": r[3], "category": r[4]}
        for r in cur.fetchall()
    ]

    cur.execute("SELECT id, code, name FROM warehouses ORDER BY id")
    data["warehouses"] = [{"id": r[0], "code": r[1], "name": r[2]} for r in cur.fetchall()]

    cur.execute("SELECT id, parent_id, name FROM customer_categories ORDER BY id")
    data["customer_categories"] = [
        {"id": r[0], "parent_id": r[1], "name": r[2]} for r in cur.fetchall()
    ]

    # 已有历史导入单（按备注前缀识别），用于幂等：重复跑不会建第二遍
    cur.execute(
        "SELECT order_no, note FROM sales_orders WHERE note LIKE '历史导入%' ORDER BY id"
    )
    data["imported_orders"] = [{"order_no": r[0], "note": r[1]} for r in cur.fetchall()]

    conn.rollback()
    conn.close()
    return data


# ---------------------------------------------------------------------------
# 源数据
# ---------------------------------------------------------------------------
def load_sales_rows() -> list[dict]:
    """读取扫描产物里的销售明细（只要销售对账单，物资清单是对账单副本不进）。"""
    path = SCAN_DIR / "rows.jsonl"
    rows: list[dict] = []
    with path.open(encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            rec = json.loads(line)
            if rec.get("table_kind") != "sales_statement":
                continue
            rows.append(rec)
    return rows


def dedup_rows(rows: list[dict]) -> tuple[list[dict], list[dict]]:
    """行级去重 —— **按单据号判，不能按文件判**。

    ## 踩过的坑（这条改了三次才对）

    第一版判据是「同一文件 + 客户 + 商品 + 数量 + 金额」，只剔了 22 行
    —— 完全低估了。第二版把单号加进来，又发现同一文件里**同一个 sheet 内部就重复**。

    真相：这批对账单的存放方式极其重复，同一条明细会同时出现在
      · `XX销售对账单8-14.xls`（单工程对账单，且自身重复 3 次）
      · `XX销售对账单8-14(1).xls`（上面的副本）
      · `西安东750...（包2）.xls / 总表`（全量汇总，包含所有工程）
      · 同一个 xls 里每个工程各一张 sheet（都是总表的子集）

    实测：`XS202507060001` 这**一张单**在 8 个位置共出现 77 行，
    但真实明细只有 **18 条**。`*电线电缆*铜线16 / 4卷 / 4248元` 被抄了 7 遍。

    → 正确的键是 **(单据号, 客户, 商品, 数量, 金额)**：
      同一张单、同一个货、同样的量和价 = 同一条明细。
      只要单据号相同，跨 sheet 跨文件都算重复。

    ⚠️ 为什么必须带上「数量+金额」而不是只按单据号去重整张单：
       同一张单里确实可能有"同一个商品分两行、量不同"的情况（多色多尺码），
       只按单据号合并会把它们并丢。
    """
    seen: dict[tuple, dict] = {}
    kept: list[dict] = []
    dropped: list[dict] = []
    for row in rows:
        key = (
            (row.get("doc_no") or "").strip(),
            norm(row.get("party")),
            norm(row.get("product")),
            row.get("qty"),
            row.get("amount"),
        )
        # 没有单号的行走"文件+行内容"兜底（无法跨文件判断是否同一单）
        if not key[0]:
            key = ("", row.get("source"), *key[1:])
        if key in seen:
            dropped.append(row)
            continue
        seen[key] = row
        kept.append(row)
    return kept, dropped


# ---------------------------------------------------------------------------
# 匹配：源数据名称 → 系统档案
# ---------------------------------------------------------------------------
def build_matchers(db: dict) -> dict:
    by_norm = lambda items: {norm(i["name"]): i for i in items}  # noqa: E731
    return {
        "customer": by_norm(db["customers"]),
        "supplier": by_norm(db["suppliers"]),
        "product": by_norm(db["products"]),
        "warehouse": by_norm(db["warehouses"]),
        "product_by_sku": {p["sku"]: p for p in db["products"]},
    }


def clean_product(raw: str) -> tuple[str, str]:
    """`*金属制品*遮阳棚` → ("金属制品", "遮阳棚")；`金属制品套筒` → ("金属制品", "套筒")。"""
    text = norm(raw)
    m = re.match(r"^\*([^*]+)\*(.+)$", text)
    if m:
        return m.group(1), m.group(2)
    return "", text


def match_product(raw: str, matchers: dict) -> tuple[dict | None, str]:
    """商品匹配三轮：原文精确 → 去星号前缀 → 去空格后包含。"""
    text = norm(raw)
    hit = matchers["product"].get(text)
    if hit:
        return hit, "原文一致"
    _cat, main = clean_product(raw)
    hit = matchers["product"].get(main)
    if hit:
        return hit, "去前缀后一致"
    for key, rec in matchers["product"].items():
        if len(key) >= 3 and (key in text or main in key):
            return rec, "模糊包含"
    return None, "缺失"


# ---------------------------------------------------------------------------
# 主流程
# ---------------------------------------------------------------------------
def fix_date(value: object) -> str:
    """日期归一 —— 兼容 Excel 序列号。

    踩过的坑：`.xls` 里有 4 行日期没被转成文本，`date` 字段是裸序列号 `45883`
    （= 2025-08-14）。扫描器那边没兜住，导入层必须再兜一次：
    带着 `45883` 建单，单据日期就是"公元 4096 年"，账龄报表直接崩。
    """
    text = str(value or "").strip()
    if text.isdigit() and 20000 < int(text) < 80000:
        # Excel 日期序列号：1899-12-30 起算
        from datetime import date, timedelta

        return (date(1899, 12, 30) + timedelta(days=int(text))).isoformat()
    return text


def classify_risks(records: list[dict]) -> dict:
    """识别两类**必须在导入前由人拍板**的结构性问题，不允许脚本替业务猜。

    ## 风险一：同一张单内「同名商品 + 同量 + 同价」多行 → 疑似重复行

    实测 `XS202508060002`（2025-08-06，18 行）是**同一份 9 行清单抄给了两个工程**：
    蒲白750包1 与 陕北通道包12 各 9 行，商品/数量/单价逐字相同。
    `XS202509030001`（7 行）同样：振动棒 2×464 在三个工程各出现一次。

    这两种解释对账上完全不同：
      · **抄重了** → 只该有 1 份，按 2 份导 → 虚增收入 + 虚增出库
      · **真的各发一份** → 该有 2 份，按 1 份导 → 少记收入

    脚本不做判断，只把「同单同品同量同价」的组全部列出来交给人确认。

    ## 风险二：同一张单跨多个工程 → 一张单只能挂一个客户

    系统 `sales_orders` 只有一个 `customer_id`，源数据里 18 张单跨 2~4 个工程。
    推荐做法是**按工程拆成多张单**（单据号加 `-01/-02` 后缀），
    因为应收要按工程对账 —— 拆开后每个工程各挂各的应收，才对得上工程款。
    """
    # ── 风险一 ──
    by_doc: dict[str, list[dict]] = defaultdict(list)
    for rec in records:
        if rec["status"] == "ok":
            by_doc[rec["doc_no"]].append(rec)

    dup_groups = []
    for doc_no, lines in sorted(by_doc.items()):
        seen: dict[tuple, list[dict]] = defaultdict(list)
        for rec in lines:
            seen[(norm(rec["product_raw"]), rec["qty"], rec["price"])].append(rec)
        for (prod, qty, price), hits in seen.items():
            if len(hits) < 2:
                continue
            parties = sorted({h["party"] for h in hits})
            dup_groups.append(
                {
                    "源单号": doc_no,
                    "日期": hits[0]["date"],
                    "商品": prod,
                    "数量": qty,
                    "单价": price,
                    "重复次数": len(hits),
                    "涉及工程数": len(parties),
                    "涉及工程": "、".join(parties),
                    # 「跨工程重复」才是真风险；同一工程内重复更像是同色同尺码多行
                    "类型": "跨工程重复" if len(parties) > 1 else "同工程内重复",
                    "单行金额": str(money(line_amount(price or 0, qty or 0))),
                    "多算金额": str(money(line_amount(price or 0, qty or 0)) * (len(hits) - 1)),
                }
            )

    # ── 风险二 ──
    cross_orders = []
    for doc_no, lines in sorted(by_doc.items()):
        parties = sorted({l["party"] for l in lines})
        if len(parties) < 2:
            continue
        cross_orders.append(
            {
                "源单号": doc_no,
                "日期": lines[0]["date"],
                "明细行": len(lines),
                "金额": str(money(sum((money(l["amount"] or 0) for l in lines), Decimal("0")))),
                "工程数": len(parties),
                "涉及工程": "、".join(parties),
            }
        )

    return {"dup_groups": dup_groups, "cross_orders": cross_orders}


def plan() -> dict:
    db = load_db()
    matchers = build_matchers(db)
    raw_rows = load_sales_rows()
    rows, dropped = dedup_rows(raw_rows)

    issues: list[dict] = []
    records: list[dict] = []

    for row in rows:
        party_raw = str(row.get("party") or "")
        party = norm(party_raw)
        product_raw = str(row.get("product") or "")
        qty = row.get("qty")
        price = row.get("price")
        amount = row.get("amount")

        rec = {
            "source": row.get("source"),
            "sheet": row.get("sheet"),
            "date": fix_date(row.get("date")),
            "doc_no": (row.get("doc_no") or "").strip(),
            "warehouse": norm(row.get("warehouse")),
            "party_raw": party_raw,
            "party": party,
            "product_raw": product_raw,
            "qty": qty,
            "price": price,
            "amount": amount,
            "unit": norm(row.get("unit")),
            "status": "ok",
            "why": "",
            "customer_id": "",
            "customer_code": "",
            "product_id": "",
            "product_sku": "",
            "warehouse_id": "",
            "warehouse_code": "",
            "amount_check": "",
        }

        # ── 客户 ──
        cust = matchers["customer"].get(party)
        if cust:
            rec["customer_id"] = cust["id"]
            rec["customer_code"] = cust["code"]
        else:
            rec["status"] = "待建客户"
            rec["why"] = "客户档案里没有这个名字"

        # ── 商品 ──
        prod, how = match_product(product_raw, matchers)
        if prod:
            rec["product_id"] = prod["id"]
            rec["product_sku"] = prod["sku"]
        else:
            rec["status"] = "待建商品" if rec["status"] == "ok" else rec["status"]
            rec["why"] = (rec["why"] + "；" if rec["why"] else "") + f"商品未匹配（{how}）"

        # ── 仓库（先按别名归一，再查库）──
        wh_name = WAREHOUSE_ALIASES.get(rec["warehouse"], rec["warehouse"])
        wh = matchers["warehouse"].get(wh_name)
        if wh:
            rec["warehouse_id"] = wh["id"]
            rec["warehouse_code"] = wh["code"]
            rec["warehouse"] = wh_name
        else:
            rec["status"] = "待定仓库" if rec["status"] == "ok" else rec["status"]
            rec["why"] = (rec["why"] + "；" if rec["why"] else "") + f"仓库「{rec['warehouse']}」不存在"

        # ── 金额勾稽：数量 × 单价 必须等于金额（2 位以内误差）──
        if qty is not None and price is not None and amount is not None:
            calc = line_amount(price, qty)
            diff = abs(money(calc) - money(amount))
            if diff > Decimal("0.01"):
                rec["amount_check"] = f"不符 差额{diff}"
                issues.append(
                    {
                        "level": "金额勾稽",
                        "row": f"{rec['source']} / {rec['sheet']}",
                        "detail": f"{product_raw}：{qty}×{price}={calc}，但表里写 {amount}，差 {diff}",
                    }
                )
            else:
                rec["amount_check"] = "相符"
        else:
            rec["amount_check"] = "缺数"
            issues.append(
                {
                    "level": "缺数量/单价",
                    "row": f"{rec['source']} / {rec['sheet']}",
                    "detail": f"{product_raw}：qty={qty} price={price} amount={amount}",
                }
            )

        records.append(rec)

    # ── 待建档案清单 ──
    miss_customers = sorted({r["party"] for r in records if not r["customer_id"]})
    miss_products = sorted({r["product_raw"] for r in records if not r["product_id"]})
    miss_warehouses = sorted({r["warehouse"] for r in records if not r["warehouse_id"]})

    # ── 分组：**按原始单据号**，一张源单 = 一张目标单 ──
    # ⚠️ 不能按「客户+日期」聚合：源数据里 39 个单号对应 65 个「单号+客户」组合
    #    （同一单号跨了多个工程），按日期聚合会把不同单号揉成一张，金额就乱了。
    groups: dict[str, list[dict]] = defaultdict(list)
    for rec in records:
        if rec["status"] != "ok":
            continue
        groups[rec["doc_no"] or f"NO-DOC-{rec['date']}"].append(rec)

    group_rows = []
    for doc_no, lines in sorted(groups.items(), key=lambda kv: (kv[1][0]["date"] or "", kv[0])):
        total = sum((money(l["amount"]) for l in lines), Decimal("0"))
        customers = sorted({l["party"] for l in lines})
        warehouses = sorted({l["warehouse"] for l in lines})
        group_rows.append(
            {
                "源单号": doc_no,
                "日期": lines[0]["date"],
                "客户": "、".join(customers),
                "仓库": "、".join(warehouses),
                "明细行": len(lines),
                "金额": str(money(total)),
                "商品": "、".join(sorted({l["product_raw"] for l in lines}))[:100],
            }
        )

    total_amount = sum((money(r["amount"]) for r in records if r["amount"]), Decimal("0"))
    ok_amount = sum((money(r["amount"]) for r in records if r["status"] == "ok"), Decimal("0"))

    return {
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "raw_rows": len(raw_rows),
        "deduped_rows": len(records),
        "dropped_rows": len(dropped),
        "total_amount": str(money(total_amount)),
        "importable_amount": str(money(ok_amount)),
        "status_counter": dict(Counter(r["status"] for r in records)),
        "miss_customers": miss_customers,
        "miss_products": miss_products,
        "miss_warehouses": miss_warehouses,
        "groups": group_rows,
        "issues": issues,
        "already_imported": db["imported_orders"],
        "risks": classify_risks(records),
        "records": records,
    }


def write_outputs(result: dict, out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)

    # 1) 逐行预览（给人看，也给导入脚本吃）
    cols = [
        "date", "warehouse", "party", "product_raw", "qty", "price", "amount",
        "amount_check", "status", "why", "customer_code", "product_sku", "source", "sheet",
    ]
    with (out_dir / "预览_导入明细.csv").open("w", newline="", encoding="utf-8-sig") as fh:
        writer = csv.DictWriter(fh, fieldnames=cols, extrasaction="ignore")
        writer.writeheader()
        for rec in result["records"]:
            writer.writerow(rec)

    # 2) 待建档案
    with (out_dir / "待建_客户.csv").open("w", newline="", encoding="utf-8-sig") as fh:
        w = csv.writer(fh)
        w.writerow(["客户名称", "建议编码", "挂到哪个分类节点", "行数", "金额合计"])
        cnt = Counter()
        amt: dict[str, Decimal] = defaultdict(lambda: Decimal("0"))
        for rec in result["records"]:
            if not rec["customer_id"]:
                cnt[rec["party"]] += 1
                amt[rec["party"]] += money(rec["amount"] or 0)
        for name in result["miss_customers"]:
            w.writerow([name, "（自动生成 甲CUSxxxx）", "（待你指定）", cnt[name], str(money(amt[name]))])

    with (out_dir / "待建_商品.csv").open("w", newline="", encoding="utf-8-sig") as fh:
        w = csv.writer(fh)
        w.writerow(["源商品名", "建议类别", "建议品名", "行数"])
        cnt = Counter()
        for rec in result["records"]:
            if not rec["product_id"]:
                cnt[rec["product_raw"]] += 1
        for raw in result["miss_products"]:
            cat, main = clean_product(raw)
            w.writerow([raw, cat, main, cnt[raw]])

    # 3) 分组预览（将要生成多少张单）
    with (out_dir / "预览_将生成的单据.csv").open("w", newline="", encoding="utf-8-sig") as fh:
        w = csv.DictWriter(fh, fieldnames=["源单号", "日期", "客户", "仓库", "明细行", "金额", "商品"])
        w.writeheader()
        for g in result["groups"]:
            w.writerow(g)

    # 3b) 风险一：同单同品同量同价多行（要人拍板）
    with (out_dir / "风险_重复行.csv").open("w", newline="", encoding="utf-8-sig") as fh:
        cols = ["源单号", "日期", "商品", "数量", "单价", "重复次数", "涉及工程数",
                "涉及工程", "类型", "单行金额", "多算金额"]
        w = csv.DictWriter(fh, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        for g in result["risks"]["dup_groups"]:
            w.writerow(g)

    # 3c) 风险二：同单跨多个工程（一张单只能挂一个客户）
    with (out_dir / "风险_跨工程单.csv").open("w", newline="", encoding="utf-8-sig") as fh:
        cols = ["源单号", "日期", "明细行", "金额", "工程数", "涉及工程"]
        w = csv.DictWriter(fh, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        for g in result["risks"]["cross_orders"]:
            w.writerow(g)

    # 4) 问题清单
    with (out_dir / "问题清单.csv").open("w", newline="", encoding="utf-8-sig") as fh:
        w = csv.DictWriter(fh, fieldnames=["level", "row", "detail"])
        w.writeheader()
        for i in result["issues"]:
            w.writerow(i)

    # 5) 机器可读
    slim = {k: v for k, v in result.items() if k != "records"}
    (out_dir / "plan.json").write_text(
        json.dumps(slim, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def main() -> int:
    ap = argparse.ArgumentParser(description="陕送票历史数据导入预检（只读）")
    ap.add_argument("--out", default=str(ROOT_DIR / "artifacts" / "shansong_import"))
    args = ap.parse_args()

    result = plan()
    write_outputs(result, Path(args.out))

    print("=" * 62)
    print("预检完成（全程只读，未写入任何数据）")
    print("=" * 62)
    print(f"源销售行        {result['raw_rows']}")
    print(f"去重后          {result['deduped_rows']}（剔除同文件重复行 {result['dropped_rows']}）")
    print(f"金额合计        ¥{result['total_amount']}")
    print(f"可直接导入      ¥{result['importable_amount']}")
    print()
    print("逐行状态：")
    for k, v in sorted(result["status_counter"].items(), key=lambda kv: -kv[1]):
        print(f"  {k:10s} {v:5d}")
    print()
    print(f"待建客户 {len(result['miss_customers'])} 个 / 待建商品 {len(result['miss_products'])} 个"
          f" / 待定仓库 {len(result['miss_warehouses'])} 个")
    print(f"将生成单据 {len(result['groups'])} 张")
    print(f"问题记录 {len(result['issues'])} 条")
    print()
    dup = result["risks"]["dup_groups"]
    cross = result["risks"]["cross_orders"]
    print(f"⚠️ 风险一 · 同单同品同量同价多行 {len(dup)} 组"
          f"（若确认是抄重，多算金额 ¥{money(sum((Decimal(x['多算金额']) for x in dup), Decimal('0')))}）")
    print(f"⚠️ 风险二 · 一张单跨多个工程 {len(cross)} 张，需按工程拆单")
    print()
    print(f"产物目录：{args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
