# -*- coding: utf-8 -*-
"""历史销售单导入引擎 —— 行为锁死测试。

这些测试全部走**真库 + 真回滚**（fixture 里 `db.rollback()`），不写死数据：
  · 每个 case 结束后库里的行数和进来时一模一样
  · 断言看的是**产物具体数值**（金额、条数、凭证借贷），不是"没报异常"
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from sqlalchemy import text

from app.services.sales_history_import import (
    build_note,
    fix_date,
    group_lines,
    import_sales_history,
    norm,
    parse_statement,
)


# ---------------------------------------------------------------------------
# 夹具
# ---------------------------------------------------------------------------
@pytest.fixture()
def db():
    """真库会话，但套在一个**外层事务**里，让被测代码自己的 commit 也回滚得掉。

    2026-10-21 修：导入引擎在 `dry_run=False` 时末尾会 `db.commit()`（这是对的，
    导入本来就是独立事务）。但原来这个夹具直接给 `SessionLocal()`，
    它的 commit 是**真提交** —— 于是「回滚后必须一行不剩」这几条用例
    每跑一次就往正式库塞一张单（实测漏出 XS20250706003/004 两张）。

    现在改成：外层连接开事务 → 会话用 `join_transaction_mode="create_savepoint"`，
    再把会话的 `commit` **降级成 flush** —— 导入引擎以为提交了，实际只落到
    外层事务的 SAVEPOINT 里；夹具收尾时外层 rollback 一把抹干净，
    测试中间那句 `db.rollback()` 也真的能「一行不剩」。
    """
    from app.db.session import SessionLocal, engine

    conn = engine.connect()
    trans = conn.begin()
    session = SessionLocal(bind=conn, join_transaction_mode="create_savepoint")
    # commit → flush：不让任何一行真的落到正式库
    session.commit = session.flush  # type: ignore[method-assign]
    try:
        yield session
    finally:
        session.close()
        trans.rollback()
        # 兜底体检：真漏了就当场炸，别让测试数据混进正式库
        leaked = conn.execute(
            text("SELECT count(*) FROM sales_orders WHERE note LIKE '%源单号=XSTOR%'")
        ).scalar()
        conn.close()
        assert leaked == 0, f"测试单泄漏进正式库 {leaked} 张（源单号=XSTOR*），清理后再跑"


@pytest.fixture()
def seed(db):
    """造一套最小档案：1 客户 1 商品 1 仓库。名称故意带全角括号。"""
    from app.models.customer import Customer
    from app.models.product import Product
    from app.models.warehouse import Warehouse

    # 幂等：上一轮如果因为 --commit 路径把档案提交了，这里先把同名残留清掉，
    # 否则 `ix_customers_code` 唯一约束会让整个文件 11 条用例全变成 ERROR。
    for model, field, value in (
        (Customer, "code", "TESTSHC001"),
        (Customer, "code", "TESTSHC002"),
        (Warehouse, "code", "TESTSWH001"),
        (Product, "sku", "TESTSP001"),
    ):
        db.query(model).filter(getattr(model, field) == value).delete(synchronize_session=False)
    db.flush()

    cust = Customer(code="TESTSHC001", name="测试工程（线路工程包9）")
    wh = Warehouse(code="TESTSWH001", name="测试仓库甲")
    prod = Product(sku="TESTSP001", name="劳保手套", unit="双", purchase_price=Decimal("1.0"))
    db.add_all([cust, wh, prod])
    db.flush()
    yield {"customer": cust.name, "warehouse": wh.name, "product": prod.name,
           "customer_id": cust.id, "warehouse_id": wh.id, "product_id": prod.id}
    db.rollback()


def _snapshot(db) -> dict[str, int]:
    tables = (
        "sales_orders", "sales_order_items", "inventory_transactions",
        "financial_transactions", "journal_entries", "journal_entry_lines",
    )
    return {t: db.execute(text(f"SELECT count(*) FROM {t}")).scalar() for t in tables}


def _line(seed, **kw):
    base = {
        "__row__": 2,
        "order_date": "2025-07-06",
        "warehouse": seed["warehouse"],
        "external_no": "XSTEST0001",
        "customer": seed["customer"],
        "product": seed["product"],
        "spec": "",
        "model": "",
        "unit": "双",
        "quantity": Decimal("10"),
        "unit_price": Decimal("1.2"),
        "amount": Decimal("12.00"),
        "doc_note": "",
        "line_note": "",
    }
    base.update(kw)
    return base


# ---------------------------------------------------------------------------
# 纯函数
# ---------------------------------------------------------------------------
def test_norm_把全角括号和断行空格归一():
    # 源表里真实出现过的两种写法，必须归成同一个
    assert norm("蒲白750千伏输变电工程（线 路工程包1）") == norm("蒲白750千伏输变电工程(线路工程包1)")
    assert norm("西安渼陂110千伏输变电工程（线路工程)") == norm("西安渼陂110千伏输变电工程(线路工程)")
    # 尾部标点也要吃掉，否则「XX工程。」会建出第二个客户
    assert norm("某某工程。") == norm("某某工程")


def test_fix_date_兜住_Excel_日期序列号():
    # 45883 = 2025-08-14。不兜住的话单据日期会变成"公元 4096 年"
    assert fix_date("45883") == "2025-08-14"
    assert fix_date("45883.0") == "2025-08-14"
    assert fix_date("2025/8/14") == "2025-08-14"
    assert fix_date("2025年8月14日") == "2025-08-14"
    assert fix_date("2025-8-4") == "2025-08-04"


def test_parse_statement_表头不在第一行也能认():
    """真实对账单第 1 行是标题「XX销售对账单」，第 2 行才是表头。"""
    rows = [
        ["陕西送变电第一分公司销售对账单", "", "", "", ""],
        ["日期", "仓库", "单号", "客户名称", "商品名称", "单位", "商品数量", "单价", "金额"],
        ["2025-09-12", "寨卡仓库", "XS202509120004", "某客户", "2.2kw污水泵", "台", 1, 1446.5, 1446.5],
        ["", "", "", "", "", "", "", "", ""],          # 空行要被跳过
        ["合计", "", "", "", "", "", "", "", 1446.5],   # 合计行没有客户和商品，也要跳过
    ]
    out = parse_statement(rows)
    assert len(out) == 1, "空行和合计行不该被当成明细"
    rec = out[0]
    assert rec["external_no"] == "XS202509120004"
    assert rec["order_date"] == "2025-09-12"
    assert rec["quantity"] == Decimal("1")
    assert rec["unit_price"] == Decimal("1446.5")
    assert rec["__row__"] == 3, "行号要指向表格里的真实行，出错时人才能找到"


def test_parse_statement_认不出表头直接报错():
    with pytest.raises(ValueError, match="表头无法识别"):
        parse_statement([["随便", "写点", "什么"], ["1", "2", "3"]])


def test_group_lines_按客户拆单且子单号带后缀():
    lines = [
        {"external_no": "XS1", "customer": "工程甲", "order_date": "2025-07-06", "warehouse": "仓库"},
        {"external_no": "XS1", "customer": "工程甲", "order_date": "2025-07-06", "warehouse": "仓库"},
        {"external_no": "XS1", "customer": "工程乙", "order_date": "2025-07-06", "warehouse": "仓库"},
        {"external_no": "XS2", "customer": "工程甲", "order_date": "2025-07-07", "warehouse": "仓库"},
    ]
    groups = group_lines(lines, split_by_customer=True)
    nos = sorted(g["import_no"] for g in groups)
    # XS1 跨两个工程 → 拆成 -01/-02；XS2 只有一个工程 → 保持原号不拆
    assert nos == ["XS1-01", "XS1-02", "XS2"]
    # 不拆的话 XS1 的两行客户会被硬揉成一张单，另一个工程的货就挂错人了
    nos_nosplit = sorted(g["import_no"] for g in group_lines(lines, split_by_customer=False))
    assert nos_nosplit == ["XS1", "XS2"]


def test_build_note_带上源单号供幂等判断():
    note = build_note("XS202507060001", "对账单.xls")
    assert note.startswith("历史导入|")
    assert "源单号=XS202507060001" in note


# ---------------------------------------------------------------------------
# 校验：坏数据必须挡住，且**不许静默丢行**
# ---------------------------------------------------------------------------
def test_有坏行就整张单不导(db, seed):
    """这是本引擎最关键的一条。

    对照 `_import_archive` 的做法（单行失败就跳过、其余照建）：
    单据导入这么干会造成「18 行的单只进了 15 行、金额少了、状态还是成功」，
    比明确失败危险得多。所以整张单必须挡住。
    """
    lines = [
        _line(seed, __row__=2, external_no="XSTOR001"),
        _line(seed, __row__=3, external_no="XSTOR001",
              product="这个商品档案里绝对没有", quantity=Decimal("1"), amount=Decimal("1")),
    ]
    res = import_sales_history(db, lines, dry_run=True)
    assert res["inspected"]["error_lines"] == 1
    assert res["created"] == 0
    assert len(res["inspected"]["miss_products"]) == 1
    # 整张单进 blocked，一行都不许进 new_groups
    assert res["inspected"]["blocked_groups"] == 1
    assert res["inspected"]["new_groups"] == 0


def test_待建客户会挡住整张单而不是丢行(db, seed):
    lines = [
        _line(seed, external_no="XSTOR002"),
        _line(seed, external_no="XSTOR002", customer="档案里没有的工程名"),
    ]
    res = import_sales_history(db, lines, dry_run=True)
    assert "档案里没有的工程名" in res["inspected"]["miss_customers"]
    assert res["inspected"]["blocked_groups"] == 1


def test_金额勾稽只报告不改数(db, seed):
    """源表金额是会计签过字的，差几分钱也不能替人改。"""
    # 单价入库只到 4 位（numeric(14,4)）；误差 1 分以内算相符。
    # 6 × 3.3333 = 19.9998 → 收 2 位 20.00，表里写 19.99，差正好 0.01，不该报。
    lines = [_line(seed, quantity=Decimal("6"), unit_price=Decimal("3.3333"),
                   amount=Decimal("19.99"))]
    res = import_sales_history(db, lines, dry_run=True)
    issues = [i for i in res["inspected"]["issues"] if i["level"] == "金额勾稽"]
    assert not issues, f"1 分以内的差不该报成问题，实际报了：{issues}"

    lines2 = [_line(seed, quantity=Decimal("10"), unit_price=Decimal("2.00"),
                    amount=Decimal("99.00"))]
    res2 = import_sales_history(db, lines2, dry_run=True)
    issues2 = [i for i in res2["inspected"]["issues"] if i["level"] == "金额勾稽"]
    assert issues2, "10×2=20 但表里写 99，必须报出来"
    assert "差 79.00" in issues2[0]["detail"]


def test_数量为0或负数直接挡(db, seed):
    res = import_sales_history(db, [_line(seed, quantity=Decimal("0"))], dry_run=True)
    assert res["inspected"]["error_lines"] == 1
    assert res["lines"][0]["status"] == "数量错误"


def test_没有外部单号挡下_否则没法判重复(db, seed):
    res = import_sales_history(db, [_line(seed, external_no="")], dry_run=True)
    assert res["inspected"]["error_lines"] == 1
    assert res["lines"][0]["status"] == "缺单号"


# ---------------------------------------------------------------------------
# 写库：三类流水齐全 + 幂等 + 完全可回滚
# ---------------------------------------------------------------------------
def test_建单写出库存_应收_凭证三类流水且能回滚干净(db, seed):
    before = _snapshot(db)
    lines = [
        _line(seed, __row__=2, external_no="XSTOR003", quantity=Decimal("10"),
              unit_price=Decimal("1.2"), amount=Decimal("12.00")),
        _line(seed, __row__=3, external_no="XSTOR003", quantity=Decimal("5"),
              unit_price=Decimal("2.4"), amount=Decimal("12.00")),
    ]
    res = import_sales_history(db, lines, dry_run=False, source_file="测试对账单.xls")
    assert res["created"] == 1, f"应该建成 1 张单，失败原因：{res['failed']}"

    order_no = res["created_orders"][0]["order_no"]
    assert len(order_no) == 13, f"单号应是 XS+8位日期+3位流水=13 位，实际 {order_no!r}"

    # 单头金额 = 明细合计（12 + 12 = 24）
    head = db.execute(
        text("SELECT total_amount, status, doc_type, note FROM sales_orders WHERE order_no=:n"),
        {"n": order_no},
    ).fetchone()
    assert head[0] == Decimal("24.00")
    assert head[1] == "submitted", "不能停在 draft —— unsubmit 的硬闸不许挂流水停草稿"
    assert head[2] == "outbound"
    assert "源单号=XSTOR003" in head[3]

    # 库存：**每行一条**（2 条），数量合计 15
    inv = db.execute(
        text("SELECT count(*), sum(quantity) FROM inventory_transactions WHERE doc_no=:n"),
        {"n": order_no},
    ).fetchone()
    assert inv[0] == 2, f"每个明细行一条库存流水，应是 2 条，实际 {inv[0]}"
    assert inv[1] == 15

    # 应收：**整单一条**（不是每行一条），金额 24
    fin = db.execute(
        text("SELECT count(*), sum(amount) FROM financial_transactions WHERE doc_no=:n"),
        {"n": order_no},
    ).fetchone()
    assert fin[0] == 1, f"应收必须整单一条，否则出纳核销时不知道冲哪条。实际 {fin[0]} 条"
    assert fin[1] == Decimal("24.00")

    # 凭证：借贷必须平
    vou = db.execute(
        text("SELECT count(*), sum(total_debit), sum(total_credit) FROM journal_entries WHERE doc_no=:n"),
        {"n": order_no},
    ).fetchone()
    assert vou[0] == 1
    assert vou[1] == vou[2], f"凭证借贷不平：借 {vou[1]} / 贷 {vou[2]}"

    db.rollback()
    assert _snapshot(db) == before, "回滚后必须一行不剩"


def test_同一份表导两次不会建第二张(db, seed):
    before = _snapshot(db)
    lines = [_line(seed, external_no="XSTOR004")]
    r1 = import_sales_history(db, lines, dry_run=False)
    assert r1["created"] == 1
    r2 = import_sales_history(db, lines, dry_run=False)
    assert r2["created"] == 0
    assert r2["skipped"] == 1, "第二次必须走「已导过」分支，不能建第二张"
    db.rollback()
    assert _snapshot(db) == before


def test_拆单后两个工程各挂各的客户(db, seed):
    """源数据里 14 张单跨多个工程。

    硬塞成一张单（单头只有一个 customer_id）→ 其他工程的货挂到第一个工程名下，
    应收永远对不上工程款。所以必须拆。
    """
    from app.models.customer import Customer

    cust2 = Customer(code="TESTSHC002", name="测试工程（线路工程包8）")
    db.add(cust2)
    db.flush()

    before = _snapshot(db)
    lines = [
        _line(seed, external_no="XSTOR005"),
        _line(seed, external_no="XSTOR005", customer=cust2.name),
    ]
    res = import_sales_history(db, lines, dry_run=False, split_by_customer=True)
    assert res["created"] == 2, f"跨 2 个工程的 1 张源单应拆成 2 张，失败：{res['failed']}"
    nos = sorted(o["order_no"] for o in res["created_orders"])
    assert nos[0] != nos[1]

    custs = db.execute(
        text("SELECT DISTINCT customer_id FROM sales_orders WHERE note LIKE '%源单号=XSTOR005%'")
    ).fetchall()
    assert len(custs) == 2, "拆开后两张单必须挂两个不同客户"
    db.rollback()
    assert _snapshot(db) == before


def test_dry_run_绝不写库(db, seed):
    before = _snapshot(db)
    res = import_sales_history(db, [_line(seed, external_no="XSTOR006")], dry_run=True)
    assert res["created"] == 1, "预检也要报「将会建几张」，否则人看不见预期"
    assert _snapshot(db) == before, "dry_run 一滴都不许落库"


def test_doc_type_order_不写库存也不写应收(db, seed):
    before = _snapshot(db)
    res = import_sales_history(db, [_line(seed, external_no="XSTOR007")],
                               dry_run=False, doc_type="order")
    assert res["created"] == 1
    order_no = res["created_orders"][0]["order_no"]
    assert db.execute(
        text("SELECT count(*) FROM inventory_transactions WHERE doc_no=:n"), {"n": order_no}
    ).scalar() == 0
    assert db.execute(
        text("SELECT count(*) FROM financial_transactions WHERE doc_no=:n"), {"n": order_no}
    ).scalar() == 0
    db.rollback()
    assert _snapshot(db) == before


def test_非法_doc_type_报错(db, seed):
    with pytest.raises(ValueError, match="outbound"):
        import_sales_history(db, [_line(seed)], dry_run=True, doc_type="draft")
