"""把单体 `erp.py`（11,744 行 / 224 路由 / 144 辅助函数）按业务域拆成多个模块。

**一次性重构工具**，保留作审计记录（改完就不再需要它了）。

## 怎么保证不拆坏

1. **机械搬运**：不改任何函数体、不改路由路径、不改同域内的定义顺序
   （FastAPI 按注册顺序匹配，`/invoices/export/files` 必须排在 `/invoices/{id}` 之前，
   顺序一乱就会被 `{id}` 吃掉）。
2. **零横向依赖**：任何「被本域之外的代码引用」的辅助函数一律下沉公共层
   `erp_common.py`，所以各域文件之间互不 import。
3. **跨域调用路由函数**：极少数接口会被别的域当普通函数调（如 dashboard 调
   `list_inventory_alerts`）。这类调用改成**函数内 import**，把「模块加载期的依赖」
   降级成「运行时的依赖」—— 既不成环，也不必把业务接口塞进公共层。
4. **一个名字的多条语句**（典型是 `_PRINT_KINDS["contract"] = (...)` 散布在全文 15 处）
   必须全部按原行号搬走，只搬第一条会静默丢掉 14 种单据的打印。
5. **前置注释跟着走**：函数/变量上方的说明注释属于它，拆的时候一起搬，
   否则「为什么这么算」的注释会整批失踪。

用法：
    python scripts/split_erp_routes.py            # 只打印分配方案
    python scripts/split_erp_routes.py --apply    # 真正写文件（先自动备份）
"""

from __future__ import annotations

import argparse
import ast
import re
import shutil
import symtable
from collections import defaultdict
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ROUTES = ROOT / "app" / "api" / "v1" / "routes"
SRC_PATH = ROUTES / "erp.py"

DOMAIN_BY_PREFIX = {
    "products": "erp_archive",
    "product-categories": "erp_archive",
    "customers": "erp_archive",
    "suppliers": "erp_archive",
    "warehouses": "erp_archive",
    "employees": "erp_archive",
    "opening-stock": "erp_archive",
    "opening-balances": "erp_archive",
    "excel": "erp_dataio",
    "purchase": "erp_purchase",
    "purchase-orders": "erp_purchase",
    "purchase-returns": "erp_purchase",
    "supplier": "erp_purchase",
    "sales-orders": "erp_sales",
    "quotations": "erp_sales",
    "contracts": "erp_sales",
    "sales-returns": "erp_sales",
    "inventory": "erp_inventory",
    "inventory-transfers": "erp_inventory",
    "stocktakings": "erp_inventory",
    "inventory-adjustments": "erp_inventory",
    "assembly-orders": "erp_inventory",
    "production-boms": "erp_production",
    "production-orders": "erp_production",
    "production-plans": "erp_production",
    "mrp": "erp_production",
    "material-issues": "erp_production",
    "material-returns": "erp_production",
    "finished-goods": "erp_production",
    "outsourcings": "erp_production",
    "finance": "erp_finance",
    "bank-accounts": "erp_finance",
    "bank-transfers": "erp_finance",
    "invoices": "erp_invoice",
    "print": "erp_print",
    "projects": "erp_project",
    "dashboard": "erp_misc",
    "summary": "erp_misc",
    "settings": "erp_misc",
    "agent": "erp_misc",
    "mobile": "erp_misc",
    "reports": "erp_misc",
}

DOMAIN_INFO = {
    "erp_common": ("公共辅助层", "跨域共享的工具函数：分页 / 单号 / 会计期间 / 库存联动 / 财务写入 / 金额大写 / 档案引用检查等。"),
    "erp_archive": ("基础资料", "商品 / 商品类别 / 客户 / 供应商 / 仓库 / 员工 / 期初建账。"),
    "erp_dataio": ("导入导出", "Excel 模板下载、批量导入、按 kind 导出。"),
    "erp_purchase": ("采购管理", "采购入库 / 采购订单 / 采购退货 / 供应商绩效与采购建议。"),
    "erp_sales": ("销售管理", "销售开单 / 销售订单 / 报价单 / 购销合同 / 销售退货。"),
    "erp_inventory": ("库存管理", "库存查询与流水 / 调拨 / 盘点 / 报损报溢 / 组合拆卸。"),
    "erp_production": ("生产管理", "BOM / 生产工单 / 生产计划 / MRP / 领料 / 退料 / 成品入库 / 委外加工。"),
    "erp_finance": ("财务管理", "财务流水 / 应收应付 / 账龄 / 收付款 / 资金账户 / 转账 / 日常收支。"),
    "erp_invoice": ("发票管理", "发票 OCR 识别 / 解析 / 进出项判定 / 原件与二维码 / 同步财务。"),
    "erp_print": ("打印中心", "各类单据的打印规格（print spec）与打印类型注册表。"),
    "erp_project": ("项目管理", "项目台账与成本归集。"),
    "erp_misc": ("综合接口", "仪表盘 / 汇总 / 公司设置 / 智能助手 / 移动端 / 日报导出。"),
}

FORCE_DOMAIN = {
    "printable_doc_types": "erp_print",
    "is_printable_doc_type": "erp_print",
    "print_contract": "erp_print",
    "_PRODUCTION_PLAN_PRINT": "erp_print",
}

SKIP_NAMES = {"router"}  # 每个域文件自己定义，不参与分配


# ══════════════════════════════════════════════════════════════════════════
def build_index(src, tree):
    """返回 stmts_by_name / domain / base_of / imports / unhandled。"""
    stmts_by_name: dict[str, list[ast.stmt]] = defaultdict(list)
    domain: dict[str, str] = {}
    base_of: dict[int, str] = {}
    imports: list[ast.stmt] = []
    unhandled: list[ast.stmt] = []

    for node in tree.body:
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            imports.append(node)
            continue
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            stmts_by_name[node.name].append(node)
            for d in node.decorator_list:
                if (
                    isinstance(d, ast.Call)
                    and isinstance(d.func, ast.Attribute)
                    and isinstance(d.func.value, ast.Name)
                    and d.func.value.id == "router"
                ):
                    p = d.args[0].value if d.args and isinstance(d.args[0], ast.Constant) else ""
                    domain[node.name] = DOMAIN_BY_PREFIX.get(
                        p.strip("/").split("/")[0], "erp_misc"
                    )
            continue
        if isinstance(node, ast.ClassDef):
            # 模块级类（如生产计划用的 `class _PlanLine`）也要跟着引用者走，
            # 漏了它 = 那个域运行到才会 NameError。
            stmts_by_name[node.name].append(node)
            continue
        # ⚠️ AnnAssign 必须一起收：`_ARCHIVE_KINDS: dict[...] = {...}` 这种
        # 带类型注解的模块级变量，只认 ast.Assign 会**整条静默丢掉**，
        # 表现为运行到用它的时候才 `NameError: name '_ARCHIVE_KINDS' is not defined`。
        if isinstance(node, (ast.Assign, ast.AnnAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            hit = False
            for t in targets:
                nm = None
                if isinstance(t, ast.Name):
                    nm = t.id
                elif isinstance(t, ast.Subscript) and isinstance(t.value, ast.Name):
                    nm = t.value.id
                if nm and nm not in SKIP_NAMES:
                    stmts_by_name[nm].append(node)
                    base_of[t.lineno] = nm
                    hit = True
                    break
            if not hit and not isinstance(node, ast.Assign):
                unhandled.append(node)
            continue
        if isinstance(node, (ast.ClassDef, ast.Expr)):
            unhandled.append(node)
            continue
        unhandled.append(node)
    return stmts_by_name, domain, base_of, imports, unhandled


def build_refs(src, tree, all_names, base_of):
    st = symtable.symtable(src, "erp.py", "exec")

    def collect(table, out):
        for s in table.get_symbols():
            # ⚠️ 必须带 is_global()：局部变量与全局函数同名时（满地的
            # `summary = {...}` 局部字典 vs 全局 `def summary`），
            # 只看 is_referenced() 会把局部变量误判成「引用了全局函数」。
            if s.is_referenced() and s.is_global() and s.get_name() in all_names:
                out.add(s.get_name())
        for child in table.get_children():
            collect(child, out)

    refs: dict[str, set[str]] = {}
    for child in st.get_children():
        out: set[str] = set()
        collect(child, out)
        out.discard(child.get_name())
        refs[child.get_name()] = out

    mod_refs: dict[str, set[str]] = defaultdict(set)
    for node in tree.body:
        if isinstance(node, ast.Assign) and node.lineno in base_of:
            base = base_of[node.lineno]
            for n in ast.walk(node.value):
                if isinstance(n, ast.Name) and n.id in all_names and n.id != base:
                    mod_refs[n.id].add(base)

    users: dict[str, set[str]] = defaultdict(set)
    for f, rs in refs.items():
        for r in rs:
            users[r].add(f)
    for r, bases in mod_refs.items():
        for b in bases:
            users[r].add(b)
    return refs, users


def route_func_names(stmts_by_name):
    names = set()
    for name, stmts in stmts_by_name.items():
        for node in stmts:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.decorator_list:
                names.add(name)
    return names


def assign_domains(names, domain, users, refs, route_names):
    for _ in range(30):
        changed = False
        for name in names:
            if name in domain:
                continue
            ds = {domain[c] for c in users.get(name, ()) if c in domain}
            if len(ds) == 1:
                domain[name] = ds.pop()
                changed = True
            elif len(ds) > 1:
                domain[name] = "PUBLIC"
                changed = True
        if not changed:
            break
    for n in names:
        domain.setdefault(n, "PUBLIC")

    # 路由函数不下沉（留在原域，跨域调用靠函数内 import 破）
    for n in route_names:
        if n in FORCE_DOMAIN:
            domain[n] = FORCE_DOMAIN[n]
        elif domain[n] == "PUBLIC":
            domain[n] = "erp_misc"  # 兜底（不应发生）
    for n, d in FORCE_DOMAIN.items():
        if n in names:
            domain[n] = d

    # 交替迭代：① 被跨域引用的辅助函数下沉 PUBLIC；② 公共层引用的域内名字也拉进 PUBLIC
    dangling = []
    for _ in range(30):
        moved = False
        for name in names:
            d = domain[name]
            if d == "PUBLIC" or name in route_names:
                continue
            if any(domain[c] not in (d, "PUBLIC") for c in users.get(name, ()) if c in domain):
                domain[name] = "PUBLIC"
                moved = True
        for name in names:
            if domain[name] != "PUBLIC":
                continue
            for dep in refs.get(name, ()):
                if dep not in domain or domain[dep] == "PUBLIC":
                    continue
                if dep in route_names:
                    dangling.append(f"{name}(公共层) -> {dep}(路由/{domain[dep]})")
                    continue
                domain[dep] = "PUBLIC"
                moved = True
        if not moved:
            break
    if dangling:
        print("⚠️ 公共层依赖了路由函数（需人工确认）：")
        for d in sorted(set(dangling)):
            print("   ", d)
    return domain


# ══════════════════════════════════════════════════════════════════════════
def import_manifest(imports):
    manifest = {}
    for node in imports:
        if isinstance(node, ast.Import):
            for a in node.names:
                manifest[(a.asname or a.name).split(".")[0]] = ("import", a.name, a.asname)
        else:
            for a in node.names:
                manifest[a.asname or a.name] = ("from", node.module or "", a.name)
    return manifest


def render_imports(needed, manifest):
    froms: dict[str, list[str]] = defaultdict(list)
    plain: list[str] = []
    for name in sorted(needed):
        info = manifest.get(name)
        if not info:
            continue
        kind, module, orig = info
        if kind == "import":
            if module not in plain:
                plain.append(module)
        else:
            entry = name if orig == name else f"{orig} as {name}"
            if entry not in froms[module]:
                froms[module].append(entry)
    out = ["from __future__ import annotations", ""]
    for stmt in sorted(plain):
        out.append(f"import {stmt}")
    if plain:
        out.append("")
    for module in sorted(froms):
        entries = sorted(froms[module])
        joined = ", ".join(entries)
        if len(joined) > 88:
            out.append(f"from {module} import (")
            out += [f"    {e}," for e in entries]
            out.append(")")
        else:
            out.append(f"from {module} import {joined}")
    return "\n".join(out)


IDENT = re.compile(r"\b[A-Za-z_]\w*\b")


def stmt_span(node):
    start = node.lineno
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.decorator_list:
        start = min(start, min(d.lineno for d in node.decorator_list))
    return start, node.end_lineno


def text_with_leading(lines, start, end):
    """带上方的连续注释/空行（说明注释跟着它的目标走）。

    返回 `(文本, 实际起始行号)` —— 起始行号必须一并返回：文本起点可能比
    节点起点更早（吃了上面的注释），调用方算「函数内 import 插在第几行」时
    若仍按原起点算，就会插到别处（实测把 import 插进了多行签名的参数表里）。
    """
    i = start - 2
    while i >= 0:
        s = lines[i].strip()
        if s == "" or s.startswith("#"):
            i -= 1
        else:
            break
    return "".join(lines[i + 1:end]), i + 2


def body_insert_line(node):
    first = node.body[0]
    if (
        isinstance(first, ast.Expr)
        and isinstance(first.value, ast.Constant)
        and isinstance(first.value.value, str)
    ):
        return node.body[1].lineno if len(node.body) > 1 else first.end_lineno + 1
    return first.lineno


def with_inner_imports(text, insert_rel_line, deps_by_domain):
    if not deps_by_domain:
        return text
    parts = text.splitlines(keepends=True)
    block = []
    for dom in sorted(deps_by_domain):
        block.append(
            f"    from app.api.v1.routes.{dom} import {', '.join(sorted(deps_by_domain[dom]))}\n"
        )
    idx = insert_rel_line - 1
    return "".join(parts[:idx]) + "".join(block) + "".join(parts[idx:])


def external_reexports(domain_of):
    """扫描全项目 `from app.api.v1.routes.erp import xxx`，返回需要 re-export 的名字。

    拆分后这些名字散到了各域模块，但**外部（system.py / main.py / 测试）仍然按老路径导入**。
    聚合器把它们转发出来，外部代码一行都不用改（也避免了"改测试去适配重构"这种本末倒置）。
    """
    pat = re.compile(r"from app\.api\.v1\.routes\.erp import\s*\(([^)]*)\)|"
                     r"from app\.api\.v1\.routes\.erp import\s+([^\n]+)")
    found: set[str] = set()
    for base in ("app", "tests", "scripts"):
        for py in (ROOT / base).rglob("*.py"):
            if ".venv" in str(py) or py.name.startswith("erp") and "routes" in str(py):
                continue
            try:
                text = py.read_text(encoding="utf-8")
            except Exception:
                continue
            for m in pat.finditer(text):
                chunk = m.group(1) or m.group(2) or ""
                for n in re.split(r"[,\s]+", chunk):
                    n = n.strip()
                    if n and n != "router" and n in domain_of:
                        found.add(n)
    return found


# ══════════════════════════════════════════════════════════════════════════
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()

    src = SRC_PATH.read_text(encoding="utf-8")
    lines = src.splitlines(keepends=True)
    tree = ast.parse(src)

    stmts_by_name, domain, base_of, imports, unhandled = build_index(src, tree)
    if unhandled:
        print("⚠️ 有未识别的顶层语句（会被丢弃，必须先处理）：")
        for n in unhandled:
            print(f"   L{n.lineno}  {type(n).__name__}")
        raise SystemExit("拒绝执行：存在无法搬运的顶层语句")
    names = list(stmts_by_name)
    refs, users = build_refs(src, tree, set(names), base_of)
    route_names = route_func_names(stmts_by_name)
    domain = assign_domains(names, domain, users, refs, route_names)

    groups: dict[str, list[str]] = defaultdict(list)
    for n in names:
        groups["erp_common" if domain[n] == "PUBLIC" else domain[n]].append(n)

    cross_calls: dict[str, dict[str, str]] = defaultdict(dict)
    for caller, deps in refs.items():
        cd = domain.get(caller)
        if cd is None or cd == "PUBLIC":
            continue
        for dep in deps:
            dd = domain.get(dep)
            if dd and dd not in ("PUBLIC", cd):
                cross_calls[caller][dep] = dd

    manifest = import_manifest(imports)

    print("=== 分配方案 ===")
    for d in sorted(groups, key=lambda x: -sum(
            stmts_by_name[n][0].end_lineno - stmts_by_name[n][0].lineno for n in groups[x])):
        print(f"  {d:<16} {len(groups[d]):>3} 个名字")
    print(f"\n=== 跨域调用（将改为函数内 import）共 {sum(len(v) for v in cross_calls.values())} 处 ===")
    for caller, deps in sorted(cross_calls.items()):
        print(f"  {caller:<28} -> {deps}")

    if not args.apply:
        print("\n（未写文件。加 --apply 执行）")
        return

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup = ROOT / "backup" / f"pre_split_{stamp}"
    backup.mkdir(parents=True, exist_ok=True)
    shutil.copy2(SRC_PATH, backup / "erp.py")

    all_names_set = set(names)
    for d in list(groups) + ([] if "erp_common" in groups else ["erp_common"]):
        members = groups.get(d, [])
        if not members and d != "erp_common":
            continue
        # 收集该域的全部语句（一个名字可能对应多条语句，如 _PRINT_KINDS["x"]=...）
        stmts: list[tuple[str, ast.stmt]] = []
        for n in members:
            for node in stmts_by_name[n]:
                stmts.append((n, node))
        stmts.sort(key=lambda x: stmt_span(x[1])[0])

        body_parts, tokens = [], set()
        for n, node in stmts:
            start, end = stmt_span(node)
            text, text_start = text_with_leading(lines, start, end)
            if n in cross_calls and isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                by_dom: dict[str, list[str]] = defaultdict(list)
                for dep, dd in cross_calls[n].items():
                    by_dom[dd].append(dep)
                rel = body_insert_line(node) - text_start + 1
                text = with_inner_imports(text, rel, by_dom)
            body_parts.append(text)
            tokens |= set(IDENT.findall(text))

        own = set(members)
        pub_names = set(groups.get("erp_common", []))
        common_needed = sorted((tokens & pub_names) - own) if d != "erp_common" else []
        needed = set(tokens & set(manifest))
        if d != "erp_common":
            # `router = APIRouter(...)` 是脚本自己加的样板行，不在节点文本里，
            # 词法扫描扫不到 → 必须显式补上，否则 NameError: APIRouter
            needed.add("APIRouter")
        imp_text = render_imports(needed, manifest)

        title, blurb = DOMAIN_INFO[d]
        head = [
            f'"""{title} —— 由原 `erp.py` 按业务域拆分而来',
            "（拆分脚本：scripts/split_erp_routes.py；只做搬家，函数体与路由路径未改动）。",
            "",
            blurb,
            '"""',
            "",
            imp_text,
            "",
        ]
        if common_needed:
            head.append("from app.api.v1.routes.erp_common import (")
            head += [f"    {n}," for n in common_needed]
            head.append(")")
            head.append("")
        if d != "erp_common":
            head += ['router = APIRouter(prefix="", tags=["erp"])', "", "", ""]
        content = "\n".join(head) + "\n".join(body_parts)
        if content and not content.endswith("\n"):
            content += "\n"
        (ROUTES / f"{d}.py").write_text(content, encoding="utf-8")
        print(f"  写出 {d}.py  ({len(stmts)} 条语句)")

    # 聚合器
    order = sorted((d for d in groups if d != "erp_common"),
                   key=lambda d: min(stmt_span(stmts_by_name[n][0])[0] for n in groups[d]))
    agg = [
        '"""ERP 业务路由聚合入口。',
        "",
        "原先这里是一个 1.1 万行的单体 `erp.py`（224 个路由 + 144 个辅助函数），",
        "已按业务域拆分到同目录下的 `erp_*.py`（见 scripts/split_erp_routes.py）。",
        "本文件只保留两件事：",
        "",
        "1. 把各域 router 按**原定义顺序**聚合起来 —— FastAPI 按注册顺序匹配，",
        "   顺序一变 `/invoices/export/files` 就会被 `/invoices/{id}` 吃掉；",
        "2. re-export 外部仍按老路径 `routes.erp` 导入的名字（system.py、main.py",
        "   与若干测试依赖），外部代码一行都不用改。",
        '"""',
        "",
        "from fastapi import APIRouter",
        "",
    ]
    agg += [f"from app.api.v1.routes.{d} import router as {d}_router" for d in order]
    agg += ["", 'router = APIRouter(prefix="", tags=["erp"])', ""]
    agg += [f"router.include_router({d}_router)" for d in order]
    agg += ["", "# 向后兼容：以下名字历史上是从 routes.erp 导入的（外部模块与测试依赖），"]
    agg += ["# 拆分后它们住在各域模块里，这里统一转发，外部代码无需改动。"]
    reexports = external_reexports(domain)
    by_dom: dict[str, list[str]] = defaultdict(list)
    for n in sorted(reexports):
        by_dom["erp_common" if domain[n] == "PUBLIC" else domain[n]].append(n)
    for dom in sorted(by_dom):
        agg.append(
            f"from app.api.v1.routes.{dom} import (  # noqa: E402,F401"
        )
        agg += [f"    {n}," for n in by_dom[dom]]
        agg.append(")")
    if not by_dom:
        agg.append("# （当前没有外部引用，无需转发）")
    agg.append("")
    SRC_PATH.write_text("\n".join(agg), encoding="utf-8")
    print(f"\nerp.py 已改为聚合器（include {len(order)} 个域，re-export {len(reexports)} 个名字）；备份在 {backup}")


if __name__ == "__main__":
    main()
