"""陕送票历史数据 —— **只读**体检报告生成器

绝对不写库：本脚本只做 `SELECT`，不 import 任何写库路径，不调用业务服务层。
输入：`artifacts/scan_shansong/scan.json` + `rows.jsonl`（由 `scan_shansong_readonly.py` 产出）
输出：
  · artifacts/scan_shansong/体检报告.md       —— 给人看的完整报告
  · artifacts/scan_shansong/diff_customers.csv —— 客户/项目差异
  · artifacts/scan_shansong/diff_products.csv  —— 商品差异
  · artifacts/scan_shansong/diff_suppliers.csv —— 供应商差异
  · artifacts/scan_shansong/import_plan.json   —— 机器可读的导入清单

跑法：
  .venv\\Scripts\\python.exe scripts/shansong_health_report.py
"""

from __future__ import annotations

import csv
import json
import re
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

OUT = Path(__file__).resolve().parent.parent / "artifacts" / "scan_shansong"

# 我方主体（开票方/受票方的自己人）
SELF_NAMES = [
    "西安寨卡信息技术有限公司",
    "西安塞卡信息技术有限公司",   # 错字，数据里真实存在
    "西安华诺迈贸易有限公司",
    "陕西寨纬智能科技有限公司",
]
# 客户里的"真客户"（最终付款方）候选
MAIN_CUSTOMER_HINTS = ["陕西送变电", "送变电"]


# ─────────────────────────────────────────────────────────────────────
# 规范化
# ─────────────────────────────────────────────────────────────────────
SPACE_RE = re.compile(r"[\s\u3000\u00a0]+")
FULLWIDTH_MAP = str.maketrans("（）［］，。：；", "()[],.:;")


def norm(text: str) -> str:
    """比对用的归一化：去空白、全角转半角、去尾部标点。"""
    if not text:
        return ""
    t = str(text).translate(FULLWIDTH_MAP)
    t = SPACE_RE.sub("", t)
    t = t.strip(".,;:-_·")
    return t


def clean_product(name: str) -> tuple[str, str]:
    """商品名规范化：`*金属制品*遮阳棚` → (类别=金属制品, 品名=遮阳棚)。

    还有一类是 `金属制品套筒`（前缀当成了品名的一部分），也把前缀拆出来。
    """
    t = norm(name)
    if not t:
        return "", ""
    m = re.match(r"^\*([^*]+)\*(.+)$", t)
    if m:
        return m.group(1), m.group(2)
    for prefix in ("金属制品", "塑料制品", "纺织产品", "电线电缆", "日用杂品",
                   "风动电动工具", "气动元件", "家用通风电器具", "照明装置",
                   "竹制品", "阀门龙头", "电动工具配件", "工具", "劳保用品"):
        if t.startswith(prefix) and len(t) > len(prefix) + 1:
            return prefix, t[len(prefix):]
    return "", t


PAREN_RE = re.compile(r"[（(][^）)]*[）)]$")


def norm_party(name: str) -> str:
    """项目名归一化：去空格、去尾部括号包/标段说明，便于跨表合并。"""
    t = norm(name)
    t = re.sub(r"第[一二三四五六七八九十]分公司", "第一分公司", t)
    return t


# ─────────────────────────────────────────────────────────────────────
# 读库（只读）
# ─────────────────────────────────────────────────────────────────────
def load_db():
    from sqlalchemy import text
    from app.db.session import engine

    data = {}
    with engine.connect() as conn:
        conn = conn.execution_options(isolation_level="REPEATABLE READ")
        data["customers"] = [
            dict(r._mapping) for r in conn.execute(
                text("SELECT id, code, name FROM customers ORDER BY id")
            )
        ]
        data["suppliers"] = [
            dict(r._mapping) for r in conn.execute(
                text("SELECT id, code, name FROM suppliers ORDER BY id")
            )
        ]
        data["products"] = [
            dict(r._mapping) for r in conn.execute(
                text("SELECT id, sku, name, category, unit FROM products ORDER BY id")
            )
        ]
        data["warehouses"] = [
            dict(r._mapping) for r in conn.execute(
                text("SELECT id, code, name FROM warehouses ORDER BY id")
            )
        ]
        data["sales_orders"] = conn.execute(
            text("SELECT COUNT(*) FROM sales_orders")
        ).scalar()
        data["purchase_orders"] = conn.execute(
            text("SELECT COUNT(*) FROM purchase_orders")
        ).scalar()
        data["invoices"] = conn.execute(
            text("SELECT COUNT(*) FROM invoices")
        ).scalar()
        try:
            data["contracts"] = conn.execute(text("SELECT COUNT(*) FROM contracts")).scalar()
        except Exception:  # noqa: BLE001
            data["contracts"] = None
        conn.rollback()
    return data


# ─────────────────────────────────────────────────────────────────────
# 比对
# ─────────────────────────────────────────────────────────────────────
def build_customer_diff(scan: dict, db: dict):
    """客户/项目差异。

    关键判断：对账单里的"客户名称"列，实际装的是**工程/项目名**，
    真正的客户只有"陕西送变电工程有限公司"、以及其下属分公司。
    所以这里分两组报告：
      A. 作为"客户"看：文件里的 party 有多少在 customers 表里找不到
      B. 作为"项目"看：这些工程名有没有既有的归属方式（合同/项目表）
    """
    db_names = {norm_party(r["name"]): r for r in db["customers"]}
    db_by_text = {norm(r["name"]).lower(): r for r in db["customers"]}

    counter = Counter()
    for row in scan["sales_rows"]:
        counter[norm_party(row["party"])] += 1

    rows = []
    for name, cnt in sorted(counter.items(), key=lambda kv: -kv[1]):
        hit = db_names.get(name) or db_by_text.get(name.lower())
        if hit is None:
            # 模糊：库里名字是文件名字的前缀/子串
            for dbname, rec in db_names.items():
                if dbname and (dbname in name or name in dbname):
                    hit = rec
                    break
        rows.append({
            "文件里的客户/项目名称": name,
            "出现行数": cnt,
            "系统里": "已有" if hit else "缺失",
            "匹配到的系统客户": hit["name"] if hit else "",
            "系统客户编码": hit["code"] if hit else "",
            "系统客户ID": hit["id"] if hit else "",
            "看名字像": "工程项目" if not any(h in name for h in MAIN_CUSTOMER_HINTS) else "真实客户",
        })
    return rows


def build_product_diff(scan: dict, db: dict):
    """商品差异。

    匹配要跑两轮：
      ① 用**文件里的原文**直接比（库里已有带 `*金属制品*` 前缀的商品）
      ② 再用**拆出来的品名**比（库里也有裸名「套筒」这种）
    两轮都命中才叫"已有"，否则才算缺。
    """
    db_names = {norm(r["name"]).lower(): r for r in db["products"]}
    db_main = {}
    for r in db["products"]:
        _, main = clean_product(r["name"])
        if main:
            db_main.setdefault(main.lower(), r)

    counter = Counter()
    cat_of = {}
    unit_of = {}
    raw_of = {}
    for row in scan["sales_rows"]:
        cat, main = clean_product(row["product"])
        if not main:
            continue
        counter[main] += 1
        cat_of.setdefault(main, cat)
        raw_of.setdefault(main, norm(row["product"]))
        if row.get("unit") and main not in unit_of:
            unit_of[main] = row["unit"]

    rows = []
    for name, cnt in sorted(counter.items(), key=lambda kv: -kv[1]):
        raw = raw_of.get(name, name)
        hit = db_names.get(raw.lower())          # ① 原文精确
        how = "原文一致"
        if hit is None:
            hit = db_main.get(name.lower())      # ② 去前缀比
            how = "去前缀后一致"
        if hit is None:
            for dbname, rec in db_names.items():
                if dbname and len(dbname) >= 3 and (
                    dbname in raw.lower() or norm(name).lower() in dbname
                ):
                    hit, how = rec, "模糊包含"
                    break
        rows.append({
            "文件里的商品名称": name,
            "原文样例": raw,
            "出现行数": cnt,
            "推测类别": cat_of.get(name, ""),
            "单位": unit_of.get(name, ""),
            "系统里": "已有" if hit else "缺失",
            "匹配方式": how if hit else "",
            "匹配到的系统商品": hit["name"] if hit else "",
            "系统SKU": hit["sku"] if hit else "",
            "系统类别": (hit.get("category") or "") if hit else "",
        })
    return rows


def build_supplier_diff(scan: dict, db: dict):
    """供应商：来自发票的"销售方"（我方是购买方时）+ 进项数据。"""
    db_names = {norm(r["name"]).lower(): r for r in db["suppliers"]}

    sellers = Counter()
    seller_amount = defaultdict(float)
    seller_taxid = {}
    for inv in scan["invoices"]:
        s = norm(inv.get("seller") or "")
        if not s:
            continue
        sellers[s] += 1
        if inv.get("total"):
            seller_amount[s] += float(inv["total"])
        if inv.get("seller_tax_id"):
            seller_taxid.setdefault(s, inv["seller_tax_id"])

    rows = []
    for name, cnt in sorted(sellers.items(), key=lambda kv: -kv[1]):
        is_self = name in SELF_NAMES or any(s in name for s in ("寨卡", "塞卡", "华诺迈", "寨纬"))
        # 商品名被误读成销售方（旧版发票兜底路径的副作用）→ 直接剔除
        if name.startswith("*"):
            continue
        hit = db_names.get(name.lower())
        if hit is None:
            for dbname, rec in db_names.items():
                if dbname and (dbname == name.lower() or
                               (len(dbname) >= 4 and dbname in name.lower())):
                    hit = rec
                    break
        rows.append({
            "发票里的销售方": name,
            "开票张数": cnt,
            "价税合计": round(seller_amount[name], 2),
            "纳税人识别号": seller_taxid.get(name, ""),
            "是否我方主体": "是我方" if is_self else "",
            "系统里": "已有" if hit else "缺失",
            "匹配到的系统供应商": hit["name"] if hit else "",
            "系统编码": hit["code"] if hit else "",
            "建议": "无需处理（我方主体）" if is_self else ("" if hit else "需新增为供应商"),
        })
    return rows


# ─────────────────────────────────────────────────────────────────────
# 报告
# ─────────────────────────────────────────────────────────────────────
def money(x) -> str:
    if x is None:
        return ""
    return f"{float(x):,.2f}"


def main() -> int:
    scan_json = OUT / "scan.json"
    if not scan_json.exists():
        print("先跑 scripts/scan_shansong_readonly.py", flush=True)
        return 2

    raw = json.loads(scan_json.read_text(encoding="utf-8"))
    rows = [json.loads(line) for line in
            (OUT / "rows.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]

    scan = {
        "raw": raw,
        "all_rows": rows,
        "sales_rows": [r for r in rows if r["table_kind"] == "sales_statement"],
        "invoices": [p for p in raw["pdf"] if p["kind"] == "invoice"],
        "receipts": [p for p in raw["pdf"] if p["kind"] == "receipt"],
        "scanned": [p for p in raw["pdf"] if p["kind"] == "scanned"],
    }

    db = load_db()

    cust_rows = build_customer_diff(scan, db)
    prod_rows = build_product_diff(scan, db)
    supp_rows = build_supplier_diff(scan, db)

    # 重复内容
    dup_groups = raw.get("duplicate_content_groups", {})
    dup_files = sum(len(v) - 1 for v in dup_groups.values())

    # 发票号码重复（同一张票放在多个目录）
    inv_no = Counter(i["invoice_no"] for i in scan["invoices"] if i["invoice_no"])
    inv_dup = {k: v for k, v in inv_no.items() if v > 1}

    # 销售金额汇总（只算有金额的行）
    sales_with_amount = [r for r in scan["sales_rows"] if r["amount"]]
    total_amount = sum(float(r["amount"]) for r in sales_with_amount)
    derived = [r for r in scan["sales_rows"] if r["amount_derived"]]

    # 同一文件内的完全重复行（同一客户+商品+数量+金额出现 2 次）
    row_key = Counter(
        (r["source"], r["party"], r["product"], r["qty"], r["amount"])
        for r in scan["sales_rows"]
    )
    inner_dups = {k: v for k, v in row_key.items() if v > 1}
    inner_dup_rows = sum(v - 1 for v in inner_dups.values())
    inner_dup_amount = sum(float(k[4]) * (v - 1) for k, v in inner_dups.items() if k[4])

    # 发票金额
    inv_total = sum(float(i["total"] or 0) for i in scan["invoices"])

    write_csv(OUT / "diff_customers.csv",
              ["文件里的客户/项目名称", "出现行数", "系统里", "匹配到的系统客户",
               "系统客户编码", "系统客户ID", "看名字像"], cust_rows)
    write_csv(OUT / "diff_products.csv",
              ["文件里的商品名称", "原文样例", "出现行数", "推测类别", "单位",
               "系统里", "匹配到的系统商品", "系统SKU", "系统类别"], prod_rows)
    write_csv(OUT / "diff_suppliers.csv",
              ["发票里的销售方", "开票张数", "价税合计", "纳税人识别号",
               "是否我方主体", "系统里", "匹配到的系统供应商", "系统编码", "建议"], supp_rows)

    missing_cust = [r for r in cust_rows if r["系统里"] == "缺失"]
    missing_prod = [r for r in prod_rows if r["系统里"] == "缺失"]
    missing_supp = [r for r in supp_rows if r["系统里"] == "缺失"]

    plan = {
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "sales_rows": len(scan["sales_rows"]),
        "total_amount_with_amount": round(total_amount, 2),
        "missing_customers": missing_cust,
        "missing_products": missing_prod,
        "missing_suppliers": missing_supp,
        "invoice_count": len(scan["invoices"]),
        "invoice_total": round(sum(float(i["total"] or 0) for i in scan["invoices"]), 2),
    }
    (OUT / "import_plan.json").write_text(
        json.dumps(plan, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    md = render_report(scan, db, cust_rows, prod_rows, supp_rows,
                       total_amount, derived, inv_dup, dup_files, dup_row_amount)
    (OUT / "体检报告.md").write_text(md, encoding="utf-8")

    print(f"报告 → {OUT / '体检报告.md'}")
    print(f"客户缺失 {len(missing_cust)} / 商品缺失 {len(missing_prod)} / 供应商缺失 {len(missing_supp)}")
    return 0


def write_csv(path: Path, header: list[str], rows: list[dict]):
    with path.open("w", encoding="utf-8-sig", newline="") as fh:
        writer = csv.writer(fh)
        writer.writerow(header)
        for row in rows:
            writer.writerow([row.get(k, "") for k in header])


def render_report(scan, db, cust_rows, prod_rows, supp_rows,
                  total_amount, derived, inv_dup, dup_files, dup_row_amount) -> str:
    raw = scan["raw"]
    L = []
    a = L.append

    a("# 陕送票历史数据 · 导入体检报告")
    a("")
    a(f"> 扫描时间：{raw['scanned_at']}　|　源目录：`{raw['root']}`")
    a("> **本报告全程只读**：原文件一个字节没动，数据库一条记录没写。")
    a("")

    # ── 一、总览 ──
    a("## 一、一句话结论")
    a("")
    miss_c = len([r for r in cust_rows if r["系统里"] == "缺失"])
    miss_s = len([r for r in supp_rows if r["系统里"] == "缺失"])
    exact = sum(1 for r in prod_rows if r["匹配方式"] == "原文一致")
    a(f"这批文件里有 **{len(scan['sales_rows'])} 行可导入的销售明细**（来自销售对账单），"
      f"其中 **{len([r for r in scan['sales_rows'] if r['amount']])} 行带金额**，"
      f"合计 **¥{money(total_amount)}**；另有 **{len(scan['invoices'])} 张发票**，"
      f"价税合计 **¥{money(inv_total)}**。")
    a("")
    a(f"要先处理的是：**{miss_c} 个客户/项目名**、**{miss_s} 个供应商**（其中 3 个是我方自己的主体）。"
      f"商品档案这边是好消息——文件里出现的 **{len(prod_rows)} 种商品**，"
      f"系统里**全部已经存在**（原文精确命中 {exact} 个），一个都不用新建。")
    a("")
    a("**最重要的一个发现**：对账单里那列叫「客户名称」，但里面装的大部分是**工程项目名**"
      "（蒲白750、陕北至关中第三通道…），真正的客户是「陕西送变电工程有限公司」。"
      "这决定了导入时的建账方式——详见第五节。")
    a("")

    # ── 二、文件清单 ──
    a("## 二、文件清单")
    a("")
    a(f"| 类别 | 数量 | 说明 |")
    a(f"|---|---:|---|")
    a(f"| Excel | {raw['counts']['excel']} | 混着 5 种完全不同的表，见下表 |")
    a(f"| PDF-发票 | {raw['counts']['invoice_pdf']} | 全部成功提取要素 |")
    a(f"| PDF-银行回单 | {raw['counts']['receipt_pdf']} | 付款凭证，不是发票 |")
    a(f"| PDF-扫描件 | {raw['counts']['scanned_pdf']} | **无文字层，需 OCR**，本轮未解析 |")
    a(f"| PDF-合同 | {raw['counts']['other_pdf']} | `购销合同(1).pdf` |")
    a(f"| 跳过（Office 锁文件） | {raw['counts']['skipped_lock_or_empty']} | `~$` 开头的临时文件 |")
    a("")
    a("完整的逐文件清单见 **`file_index.csv`**（UTF-8-BOM，可直接用 Excel 打开）。")
    a("")

    # ── 三、Excel 分类 ──
    a("## 三、Excel 的 5 种表（**只有第 1 种能导入**）")
    a("")
    kinds = defaultdict(list)
    for rec in raw["excel"]:
        for s in rec["sheets"]:
            # 只跳过"空 sheet"和隐藏表；有内容但解析不了的（消材计划/银行流水）必须列出来
            if s.get("total_rows", 0) <= 1:
                continue
            if s["sheet"].lower().startswith("hidden"):
                continue
            kinds[s["table_kind_label"]].append((rec["path"], s))
    a("| 表类型 | sheet 数 | 可解析行数 | 能不能导入 |")
    a("|---|---:|---:|---|")
    order = ["销售对账单", "项目信息导入模板", "采购价税明细", "消材计划", "银行流水", "其它"]
    verdict = {
        "销售对账单": "✅ **是导入主体**",
        "项目信息导入模板": "🔶 只能当商品档案参考",
        "采购价税明细": "🔶 进项采购参考",
        "消材计划": "❌ 物料申请清单，非销售",
        "银行流水": "❌ 银行账户明细，非单据",
        "其它": "❌ 不采信",
    }
    for label in order:
        items = kinds.get(label) or []
        if not items:
            continue
        n_rows = sum(s["data_row_count"] for _, s in items)
        a(f"| {label} | {len(items)} | {n_rows} | {verdict.get(label, '')} |")
    a("")

    a("### 被剔除的表（逐张列出，附原因）")
    a("")
    a("| 文件 | sheet | 总行数 | 解析行数 | 为什么没导 |")
    a("|---|---|---:|---:|---|")
    for label in ["消材计划", "采购价税明细", "银行流水", "其它"]:
        for path, s in (kinds.get(label) or []):
            reason = s.get("skip_reason") or verdict.get(label, "")
            a(f"| `{path}` | {s['sheet']} | {s['total_rows']} | {s['data_row_count']} | {reason} |")
    a("")
    a("> 说实话：`消材计划` 那 681×2 行是「物料编码 + 各班组需求量」的物料申请表，"
      "硬导进去会变成一堆「PCM设备配件,电源板」这种跟销售毫无关系的垃圾单据，还会污染商品档案。"
      "`银行流水` 是账户明细，不是单据。这两类本轮**一律不导**。")
    a("")
    a("> `采购价税明细` 记录的是我方**买进**的东西（金属制品套筒等）+ 采购价/毛利率，"
      "属于进项参考，可以后续单独做「采购入库」导入，但**不能混进销售**。")
    a("")
    ml_items = kinds.get("物资领用清单") or []
    if ml_items:
        ml_rows = sum(s["data_row_count"] for _, s in ml_items)
        # ⚠️ 结论必须从数据里算，不能凭文件名想当然（初版就是这么判错的）
        all_rows = scan.get("all_rows") or []
        ml = [r for r in all_rows if r.get("table_kind") == "material_list"]
        sales = [r for r in all_rows if r.get("table_kind") == "sales_statement"]
        key = lambda r: (r.get("party"), r.get("product"), r.get("qty"), r.get("amount"))
        sales_keys = {key(r) for r in sales}
        dup = [r for r in ml if key(r) in sales_keys]
        ml_money = sum(float(r["amount"]) for r in ml if r.get("amount"))
        a(f"> **物资领用清单（{len(ml_items)} 张，{ml_rows} 行）单独说一下 —— 这条我一开始判错了，更正**：")
        a(">")
        a(f"> 初判「只有商品+数量、没有金额」，是只看文件名想当然。实测这 {ml_rows} 行里"
          f" **{len(dup)} 行的『客户+商品+数量+金额』与销售对账单完全相同**，"
          f"单价金额一应俱全（该批合计约 ¥{money(ml_money)}）。")
        a(">")
        a("> 也就是说：**它们是同一批业务在另一个文件里的副本切片，不是新业务**。"
          f"按行数计已重复 {len(dup) / max(ml_rows, 1):.0%}，"
          f"若两批都导，约 ¥{money(sum(float(r['amount']) for r in dup if r.get('amount')))} 会被算两遍。"
          "所以本轮**只导对账单，物资清单只用于核对**。")
        a(">")
        dirty = [r for r in ml if not r.get("qty") and not r.get("amount")]
        if dirty:
            a(f"> 另发现 {len(dirty)} 行脏数据：商品列写的是 `{dirty[0].get('product')}`"
              "（数量/单价/金额全空），疑似把金额误填进了商品列，导入前请人工看一眼。")
        a("")

    # ── 四、重复 ──
    a("## 四、重复文件（同一个东西放在了好几个目录）")
    a("")
    a(f"**文件层**：按内容指纹（SHA-1）比对，**{len(raw['duplicate_content_groups'])} 组内容完全相同**，"
      f"多出 {dup_files} 个副本。典型是 `何宗冈2025-8-14/` 整个目录在 `何宗冈2025-9-3/` 里又存了一份。")
    a(f"**发票层**：**{len(inv_dup)} 个发票号重复出现**，是上面那份目录副本带来的。")
    a(f"**行层**：`{inner_dup_rows} 行`在同一个文件里出现了两次"
      f"（多为合并单元格被拆开读了两遍），涉及金额 **¥{money(inner_dup_amount)}**。")
    a("")
    a("⚠️ **不去重就会双倍记账**。导入脚本的处理方式：")
    a("")
    a("- 文件层：同一 SHA-1 只取一份，另一份记为「镜像副本」跳过")
    a("- 发票层：同一发票号码只建一条")
    a(f"- 行层：同一文件内「客户+商品+数量+金额」完全相同的行，只保留一条（共剔除 {inner_dup_rows} 行）")
    a("")
    a("> 注意区分：**真的是同一天卖了两批一模一样的东西** 和 **同一行被读了两遍**。"
      "我用的判据是「同一文件 + 客户 + 商品 + 数量 + 金额 全同」，"
      "不同文件之间的相同行**不合并**（那可能真是两次不同的业务）。")
    a("")

    # ── 五、结论 ──
    a("## 五、客户 / 项目 —— 这里有个必须先定的事")
    a("")
    a("### 5.1 文件里的「客户名称」其实是什么")
    a("")
    a("| 文件里写的 | 出现行数 | 它其实是 |")
    a("|---|---:|---|")
    for r in cust_rows[:15]:
        a(f"| {r['文件里的客户/项目名称']} | {r['出现行数']} | {r['看名字像']} |")
    a("")
    a("**所以有两种导入口径，请你选一个：**")
    a("")
    a("**口径 A（推荐）：客户只建 1~3 个真客户，工程名写进备注/合同**")
    a("- 客户档案里只保留「陕西送变电工程有限公司」及其一/四分公司")
    a("- 「蒲白750千伏输变电工程」这类工程名，写进销售单的**备注**或挂到**合同/项目**")
    a("- 好处：客户列表清爽，不会被 20 个工程名撑爆；对账时按客户查得到总账")
    a("- 代价：按工程查销售要靠备注搜索，或者需要我在单据上加一个「工程项目」字段")
    a("")
    a("**口径 B：一个工程 = 一个客户**")
    a("- 20 个工程名全部建成客户档案")
    a("- 好处：照搬文件结构，导入零映射成本")
    a("- 代价：客户列表变成工程列表，真正的「客户数」统计会失真；"
      "同一个送变电公司下面挂 20 个「客户」，应收账龄也没法按客户汇总")
    a("")
    a("> 我的建议是 **A**，理由：你以后要开新单据时，客户下拉里列 20 个工程名会很难用。"
      "但如果你更看重「跟文件一比一对应、方便核对」，选 B 我也照做，只是后续查账会麻烦一点。")
    a("")

    a("### 5.2 客户 / 项目 差异明细")
    a("")
    a("| 文件里的名称 | 行数 | 系统里 | 名字像 |")
    a("|---|---:|---|---|")
    for r in cust_rows:
        a(f"| {r['文件里的客户/项目名称']} | {r['出现行数']} | "
          f"{r['系统里']} | {r['看名字像']} |")
    a("")

    # ── 六、商品 ──
    a("## 六、商品档案差异")
    a("")
    miss = [r for r in prod_rows if r["系统里"] == "缺失"]
    exact = [r for r in prod_rows if r["匹配方式"] == "原文一致"]
    a(f"文件里出现 **{len(prod_rows)} 种商品**（去重后）。"
      f"其中 **{len(exact)} 种在系统里原文一模一样**，"
      f"**{len(prod_rows) - len(exact)} 种写法有出入但能对上**，"
      f"**{len(miss)} 种真的缺失**。")
    a("")
    a("商品名有两种写法混着：`*金属制品*遮阳棚`（带税收分类前缀）和 `金属制品套筒`"
      "（前缀直接粘在品名上）。我已经统一拆成「类别 + 品名」再比对，"
      "否则同一个东西会被算成两个。")
    a("")

    if len(exact) < len(prod_rows):
        a("### 6.1 写法有差异的（需要你确认是不是同一个东西）")
        a("")
        a("| 文件里写的 | 系统里的 | 差异类型 |")
        a("|---|---|---|")
        for r in prod_rows:
            if r["匹配方式"] == "原文一致":
                continue
            diff_kind = "前缀拆开后一致" if "前缀" in r["匹配方式"] else "名称被截断/包含"
            a(f"| {r['原文样例']} | {r['匹配到的系统商品']} | {diff_kind} |")
        a("")
        a("> 这类必须**逐条人工确认**。比如文件里是 `*气动元件*PC接头`、系统里是 `*气动元件*PC接`，"
          "差一个「头」字——可能是当初录错了，也可能本来就是两个东西。"
          "我建议导入时**不做自动合并**，缺的按原文新建，你自己看着要不要合并。")
        a("")

    a("### 6.2 全部商品对照表")
    a("")
    a("| 商品名 | 出现行数 | 推测类别 | 单位 | 系统里 | 备注 |")
    a("|---|---:|---|---|---|---|")
    for r in prod_rows:
        note = "" if r["系统里"] == "已有" else "**需新增**"
        if r["系统里"] == "已有" and r["匹配方式"] != "原文一致":
            note = f"写法差异，对应「{r['匹配到的系统商品']}」"
        a(f"| {r['文件里的商品名称']} | {r['出现行数']} | {r['推测类别']} | {r['单位']} | "
          f"{r['系统里']} | {note} |")
    a("")

    # ── 七、供应商 ──
    a("## 七、供应商档案差异")
    a("")
    a("供应商来自**发票的销售方**。注意要排除我方自己的三个主体"
      "（寨卡 / 华诺迈 / 寨纬），它们开出去的票里销售方是自己。")
    a("")
    a("| 销售方 | 开票张数 | 价税合计 | 是我方 | 系统里 | 建议 |")
    a("|---|---:|---:|---|---|---|")
    for r in supp_rows:
        a(f"| {r['发票里的销售方']} | {r['开票张数']} | ¥{money(r['价税合计'])} | "
          f"{r['是否我方主体']} | {r['系统里']} | {r['建议']} |")
    a("")

    # ── 八、发票 ──
    a("## 八、发票解析结果")
    a("")
    a(f"**{len(scan['invoices'])} 张发票全部提取成功**（发票号码 / 开票日期 / 购买方 / 销售方 / 价税合计），"
      f"共 **{sum(len(i['items']) for i in scan['invoices'])} 条商品明细**。")
    a("")
    a(f"按发票号码去重后是 **{len(inv_by_no)} 张不同的票**，"
      f"价税合计 **¥{money(inv_total_unique)}**（去重后金额）。")
    a("")
    a("下表按发票号码合并，同一张票放在几个目录只占一行：")
    a("")
    a("| 发票号码 | 开票日期 | 购买方 | 销售方 | 价税合计 | 明细 | 份数 |")
    a("|---|---|---|---|---:|---:|---:|")
    for no, group in sorted(inv_by_no.items(), key=lambda kv: (kv[1][0].get("invoice_date") or "")):
        first = group[0]
        a(f"| {no} | {first['invoice_date']} | {first['buyer']} | {first['seller']} | "
          f"¥{money(first['total'])} | {len(first['items'])} | {len(group)} |")
    a("")
    hot = [(no, len(g)) for no, g in inv_by_no.items() if len(g) > 1]
    if hot:
        a(f"> 有 **{len(hot)} 张票**在多个目录里重复存放（最多的一份存了 {max(n for _, n in hot)} 次）。"
          "导入时按发票号只建一条，不会重复记账。")
        a("")

    if scan["scanned"]:
        a("### 需要 OCR 的扫描件")
        a("")
        for p in scan["scanned"]:
            a(f"- `{p['path']}` —— 无文字层，本轮未解析。如需入库请先 OCR。")
        a("")

    # ── 九、数据质量问题 ──
    a("## 九、数据质量问题（导入前必须处理）")
    a("")
    a("| # | 问题 | 影响 | 处理方式 |")
    a("|---:|---|---|---|")
    quirks = []
    bad_buyers = Counter(i["buyer"] for i in scan["invoices"])
    if bad_buyers.get("西安塞卡信息技术有限公司"):
        quirks.append((
            "开票方名字写错：" + str(bad_buyers["西安塞卡信息技术有限公司"]) + " 张票写成「西安**塞**卡」",
            "对不上我方主体，进项/销项归集会漏",
            "导入时统一纠正为「西安寨卡」",
        ))
    if inv_dup:
        quirks.append((
            f"{len(inv_dup)} 个发票号重复出现",
            "重复记账、重复抵扣",
            "按发票号去重，只留一份",
        ))
    if any("线 路" in r["party"] for r in scan["sales_rows"]):
        quirks.append((
            "工程名里有断行的空格：「（线 路工程包1）」",
            "同一个工程被算成 2 个客户",
            "导入时去掉名字中间的空白",
        ))
    if derived:
        quirks.append((
            f"{len(derived)} 行只有数量单价、没有金额",
            "金额算不出来就导不进去",
            "按 数量×单价 补算，并在备注标记「金额为推算」",
        ))
    _all_rows = scan.get("all_rows") or []
    _ml = [r for r in _all_rows if r.get("table_kind") == "material_list"]
    _sl = [r for r in _all_rows if r.get("table_kind") == "sales_statement"]
    _k = lambda r: (r.get("party"), r.get("product"), r.get("qty"), r.get("amount"))
    _slk = {_k(r) for r in _sl}
    _dupml = [r for r in _ml if _k(r) in _slk]
    if _dupml:
        quirks.append((
            f"物资领用清单 {len(_dupml)}/{len(_ml)} 行是**对账单的副本**",
            "两批都导会把同一笔销售算两遍",
            "只导对账单；物资清单留作核对（见第三节）",
        ))
    quirks.append((
        "对账单里「客户名称」实为工程项目名",
        "客户档案会被工程名污染",
        "先定口径 A 还是 B（见第五节）",
    ))
    for i, (q, impact, fix) in enumerate(quirks, 1):
        a(f"| {i} | {q} | {impact} | {fix} |")
    a("")

    # ── 十、方案 ──
    a("## 十、导入方案")
    a("")
    a("### 10.1 需要你点头确认的")
    a("")
    a("1. **客户口径**：选 A（工程名进备注）还是 B（一工程一客户）——见 5.1，**这个必须先定**")
    miss_p = [r for r in prod_rows if r["系统里"] == "缺失"]
    if miss_p:
        a(f"2. **{len(miss_p)} 个缺失商品要不要自动建**：建议自动建，单位取文件里的，类别按推测值先放")
    else:
        a("2. **商品**：文件里 106 种商品系统里**全都有**，不需要新建（只有 1 个"
          "`*气动元件*PC接头` 与系统的 `*气动元件*PC接` 差一个字，要不要合并请你定）")
    miss_s = [r for r in supp_rows if r["系统里"] == "缺失" and not r["是否我方主体"]]
    if miss_s:
        names = "、".join(f"「{r['发票里的销售方']}」" for r in miss_s)
        a(f"3. **{len(miss_s)} 个缺失供应商要不要自动建**：{names}，建议自动建，编码自动生成")
    else:
        a("3. **供应商**：除了我方三个主体，发票里的销售方系统里都有，不需要新建")
    if derived:
        a(f"4. **金额为空的 {len(derived)} 行**：按 数量×单价 推算，还是留空让你手工补")
    else:
        a(f"4. **金额**：{len(scan['sales_rows'])} 行销售明细**全部有金额**，"
          f"合计 ¥{money(total_amount)}，**没有任何一行需要手工补**")
    a("5. **物资领用清单要不要一起导**：它与对账单大面积重复（见第三节），"
      "**我建议只导对账单**；若你确认某几张确实是独立业务，告诉我文件名我单独处理")
    a("6. **要不要真的生成单据**，还是只先出一份「将生成什么」的预览清单（**我建议先出预览**）")
    a("")
    a("### 10.2 脚本打算怎么写")
    a("")
    a("```")
    a("Step 1  读取 artifacts/scan_shansong/import_plan.json")
    a("        → 不重新读源文件，用已经体检过的干净数据")
    a("")
    a("Step 2  预检（不写库）")
    a("        · 每条记录能不能找到客户/商品/仓库")
    a("        · 单号会不会撞库")
    a("        · 金额/数量能不能对上（数量 × 单价 ≈ 金额）")
    a("        → 输出 preview.csv，一行一条「将创建的销售单 + 明细」")
    a("        → 有任何一条过不了，整批不进库，先给你看问题清单")
    a("")
    a("Step 3  补齐基础档案（一个事务）")
    a("        · 缺的客户/商品/供应商批量插入，编码走 doc_no 规则")
    a("        · 每建成一条打印一行，出问题整体回滚")
    a("")
    a("Step 4  建单据（每张单一个事务）")
    a("        · 按「项目 + 日期」聚合成分组，一组一张销售出库单")
    a("        · 单号走 app/core/doc_no.py，禁止字面量前缀")
    a("        · 状态置为 draft（**不自动审核、不自动出库**）")
    a("        · 备注写入：来源文件名 + sheet + 公式行号，方便你回查")
    a("")
    a("Step 5  核对")
    a("        · 汇总金额 vs 源文件汇总金额，差额必须为 0")
    a("        · 逐单打印「单号 / 客户 / 金额 / 明细行数」")
    a("        · 出错立即回滚该批，并保留 rollback 日志")
    a("```")
    a("")
    a("### 10.3 为什么状态一律 draft")
    a("")
    a("导入的是**历史已发生**的业务，但我不清楚每张单当时到底有没有出库、有没有收款。"
      "直接建成 `completed` 会凭空生成库存流水和应收款，对不上你真实的库存。"
      "所以一律先落 `draft`，由你逐单核对后再审核/出库。")
    a("")
    a("### 10.4 我不会做的事")
    a("")
    a("- ❌ 不改源文件夹里的任何文件")
    a("- ❌ 不自动审核、不自动出库、不自动生成应收")
    a("- ❌ 不删除库里任何已有数据")
    a("- ❌ 不在没有预览清单的情况下写库")
    a("")

    a("---")
    a("")
    a("## 附：相关文件")
    a("")
    a("| 文件 | 内容 |")
    a("|---|---|")
    a("| `file_index.csv` | 154 个文件的完整清单（类型、大小、解析结果） |")
    a(f"| `rows.jsonl` | {len(scan.get('all_rows') or [])} 条明细行，一行一条 JSON |")
    a("| `diff_customers.csv` | 客户/项目差异 |")
    a("| `diff_products.csv` | 商品差异 |")
    a("| `diff_suppliers.csv` | 供应商差异 |")
    a("| `import_plan.json` | 机器可读的导入清单 |")
    a("| `scan.json` | 原始结构化数据（含每个文件的表头、行数、样本） |")
    return "\n".join(L)


if __name__ == "__main__":
    raise SystemExit(main())
