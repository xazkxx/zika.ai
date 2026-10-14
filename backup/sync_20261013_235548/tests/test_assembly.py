"""组合拆卸（库存管理）回归测试。

这一批的风险集中在**库存会不会算错**上，所以最重的两条是：

1. `test_combo_and_split_move_stock_in_opposite_directions` —— 组合：子件出、成品入；
   拆卸：成品出、子件入。逐个商品核对现存量，不是"接口返回 200 就算过"。
2. `test_deleting_order_restores_stock` —— 删单必须把整单的流水一起冲销。
   冲销不干净是最难发现的库存错账：单子没了、库存还少着。

另外覆盖：BOM 一级展开与总用量折算、无配方的明确回报（has_bom=False）、
明细快照（BOM 改了不影响历史单）、各项校验（空清单 / 子件=成品 / 重复子件 / 非法类型）、
打印可达、以及"库存不足只警告不拦单"这条既定口径。

测试数据命名遵守 scripts/clean_test_data.py 的签名：
SKU-KIT-<8hex> / SKU-CMP-<8hex> / WH-<8hex>。
"""

import uuid

import fitz
import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.models.assembly import ASSEMBLY_PREFIX, ASSEMBLY_STATUS, ASSEMBLY_TYPES

client = TestClient(app)


def _hex() -> str:
    return uuid.uuid4().hex[:8]


def _headers() -> dict[str, str]:
    resp = client.post("/api/v1/auth/login", json={"username": "admin", "password": "Admin123"})
    assert resp.status_code == 200, resp.text
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


@pytest.fixture()
def kit():
    """一套用完即删的组合件：仓库 + 成品 + 两个子件 + BOM 配方 + 子件备货。

    配方：1 套 = 2 个甲 + 3 个乙；备货 甲 100 / 乙 100（按仓库）。
    """
    headers = _headers()
    tag = _hex()
    warehouse = client.post(
        "/api/v1/warehouses", json={"code": f"WH-{tag}", "name": f"组合测试仓-{tag}"}, headers=headers
    ).json()
    product = client.post(
        "/api/v1/products",
        json={"sku": f"SKU-KIT-{tag}", "name": "测试套装", "purchase_price": 100.0, "sale_price": 180.0},
        headers=headers,
    ).json()
    comp_a = client.post(
        "/api/v1/products",
        json={"sku": f"SKU-CMP-{tag}", "name": "子件甲", "purchase_price": 30.0, "unit": "个"},
        headers=headers,
    ).json()
    # 第二个子件换一个签名前缀，避免与第一个撞编码规则
    comp_b = client.post(
        "/api/v1/products",
        json={"sku": f"SKU-CMP-{tag[1:] + 'b'}", "name": "子件乙", "purchase_price": 20.0, "unit": "个"},
        headers=headers,
    ).json()

    for comp, per in ((comp_a, 2), (comp_b, 3)):
        created = client.post(
            "/api/v1/production-boms",
            json={
                "product_id": product["id"],
                "component_product_id": comp["id"],
                "quantity": per,
                "bom_type": "assembly",
                "level": 1,
            },
            headers=headers,
        )
        assert created.status_code == 201, created.text

    client.put(
        "/api/v1/opening-stock",
        json={
            "items": [
                {"warehouse_id": warehouse["id"], "product_id": comp_a["id"], "quantity": 100, "unit_price": 30.0},
                {"warehouse_id": warehouse["id"], "product_id": comp_b["id"], "quantity": 100, "unit_price": 20.0},
            ]
        },
        headers=headers,
    )

    yield {
        "headers": headers,
        "tag": tag,
        "warehouse": warehouse,
        "product": product,
        "comp_a": comp_a,
        "comp_b": comp_b,
    }

    # 收尾：删掉本测试开的单（冲销库存）→ 清期初 → 删 BOM → 删档案（订单与 BOM 都删干净）
    for order in client.get("/api/v1/assembly-orders", headers=headers).json():
        if order["product_id"] == product["id"]:
            client.delete(f"/api/v1/assembly-orders/{order['id']}", headers=headers)
    client.put(
        "/api/v1/opening-stock",
        json={
            "items": [
                {"warehouse_id": warehouse["id"], "product_id": comp_a["id"], "quantity": 0, "unit_price": 0},
                {"warehouse_id": warehouse["id"], "product_id": comp_b["id"], "quantity": 0, "unit_price": 0},
            ]
        },
        headers=headers,
    )
    for bom in client.get("/api/v1/production-boms", headers=headers).json():
        if bom.get("product_id") == product["id"]:
            client.delete(f"/api/v1/production-boms/{bom['id']}", headers=headers)
    for kind, item in (("products", comp_a), ("products", comp_b), ("products", product), ("warehouses", warehouse)):
        client.delete(f"/api/v1/{kind}/{item['id']}", headers=headers, params={"force": True})


def _stock(headers: dict[str, str], warehouse_id: int, product_id: int) -> int:
    data = client.get(
        f"/api/v1/inventory/stock?product_id={product_id}&warehouse_id={warehouse_id}", headers=headers
    ).json()
    return int(data["summary"]["total_quantity"])


def _make_order(kit, doc_type: str, quantity: int, items: list[dict] | None = None):
    return client.post(
        "/api/v1/assembly-orders",
        json={
            "doc_type": doc_type,
            "product_id": kit["product"]["id"],
            "quantity": quantity,
            "warehouse_id": kit["warehouse"]["id"],
            "handler": "验收员",
            "items": items
            if items is not None
            else [
                {"product_id": kit["comp_a"]["id"], "quantity": 2 * quantity},
                {"product_id": kit["comp_b"]["id"], "quantity": 3 * quantity},
            ],
        },
        headers=kit["headers"],
    )


# ============================================================
# 元数据与 BOM 展开
# ============================================================
def test_meta_exposes_types_and_prefixes():
    headers = _headers()
    meta = client.get("/api/v1/assembly-orders/meta", headers=headers).json()
    assert [row["value"] for row in meta["doc_types"]] == list(ASSEMBLY_TYPES)
    assert [row["value"] for row in meta["statuses"]] == list(ASSEMBLY_STATUS)
    assert meta["prefixes"] == ASSEMBLY_PREFIX
    assert meta["default_warehouse_id"] is not None


def test_bom_preview_expands_recipe_with_total_quantity(kit):
    """选完成品 → 按 BOM 展开子件 → 用量按成品数量折算成总用量。"""
    headers, warehouse = kit["headers"], kit["warehouse"]
    preview = client.get(
        f"/api/v1/assembly-orders/bom-preview?product_id={kit['product']['id']}"
        f"&quantity=5&doc_type=combo&warehouse_id={warehouse['id']}",
        headers=headers,
    ).json()

    assert preview["has_bom"] is True
    assert preview["quantity"] == 5
    lines = {row["product_name"]: row for row in preview["items"]}
    assert set(lines) == {"子件甲", "子件乙"}
    # 单位用量 2/3 → 5 套要 10/15
    assert (lines["子件甲"]["per_unit"], lines["子件甲"]["quantity"]) == (2, 10)
    assert (lines["子件乙"]["per_unit"], lines["子件乙"]["quantity"]) == (3, 15)
    # 带出现存量与单价，页面据此算缺口
    assert lines["子件甲"]["on_hand"] == 100
    assert lines["子件甲"]["unit_price"] == 30.0
    assert preview["product"]["on_hand"] == 0
    assert preview["warnings"] == []


def test_bom_preview_reports_missing_recipe_and_shortage(kit):
    """没有配方要明确回报；要料超过现存量要给出缺口提示（但不拦单）。"""
    headers, warehouse = kit["headers"], kit["warehouse"]

    # 子件甲本身没有配方
    bare = client.get(
        f"/api/v1/assembly-orders/bom-preview?product_id={kit['comp_a']['id']}&quantity=1&warehouse_id={warehouse['id']}",
        headers=headers,
    ).json()
    assert bare["has_bom"] is False and bare["items"] == []

    # 要 100 套 → 需要 200 个甲，现货只有 100
    short = client.get(
        f"/api/v1/assembly-orders/bom-preview?product_id={kit['product']['id']}"
        f"&quantity=100&doc_type=combo&warehouse_id={warehouse['id']}",
        headers=headers,
    ).json()
    assert any("子件甲" in text and "负库存" in text for text in short["warnings"]), short["warnings"]

    # 拆卸看的是成品够不够
    split_short = client.get(
        f"/api/v1/assembly-orders/bom-preview?product_id={kit['product']['id']}"
        f"&quantity=3&doc_type=split&warehouse_id={warehouse['id']}",
        headers=headers,
    ).json()
    assert any("成品" in text and "负库存" in text for text in split_short["warnings"]), split_short["warnings"]

    assert client.get("/api/v1/assembly-orders/bom-preview?product_id=99999999", headers=headers).status_code == 404
    assert (
        client.get(
            f"/api/v1/assembly-orders/bom-preview?product_id={kit['product']['id']}&quantity=0", headers=headers
        ).status_code
        == 400
    )


# ============================================================
# 库存联动（本轮最重要的一条）
# ============================================================
def test_combo_and_split_move_stock_in_opposite_directions(kit):
    """组合：成品入 + 子件出；拆卸：成品出 + 子件入。逐项核对现存量。"""
    headers, warehouse = kit["headers"], kit["warehouse"]
    product, comp_a, comp_b = kit["product"]["id"], kit["comp_a"]["id"], kit["comp_b"]["id"]

    assert (_stock(headers, warehouse["id"], comp_a), _stock(headers, warehouse["id"], comp_b)) == (100, 100)
    assert _stock(headers, warehouse["id"], product) == 0

    # —— 组合 5 套：成品 +5，甲 −10，乙 −15 ——
    combo = _make_order(kit, "combo", 5)
    assert combo.status_code == 201, combo.text
    body = combo.json()
    assert body["doc_type"] == "combo" and body["doc_type_label"] == "组合"
    assert body["order_no"].startswith("ZH")
    assert body["total_quantity"] == 25.0
    assert len(body["items"]) == 2
    assert _stock(headers, warehouse["id"], product) == 5
    assert _stock(headers, warehouse["id"], comp_a) == 90
    assert _stock(headers, warehouse["id"], comp_b) == 85

    # —— 拆卸 2 套：成品 −2，甲 +4，乙 +6 ——
    split = _make_order(kit, "split", 2)
    assert split.status_code == 201, split.text
    assert split.json()["order_no"].startswith("CX")
    assert _stock(headers, warehouse["id"], product) == 3
    assert _stock(headers, warehouse["id"], comp_a) == 94
    assert _stock(headers, warehouse["id"], comp_b) == 91

    # 库存流水要能追到这张单，且方向正确
    rows = [
        row
        for row in client.get("/api/v1/inventory?limit=20", headers=headers).json()
        if row.get("related_type") == "assembly"
    ]
    assert rows, "组合拆卸没有写库存流水"
    by_type = {row["transaction_type"] for row in rows}
    assert by_type == {"inbound", "outbound"}, by_type
    assert {row["doc_no"] for row in rows} >= {body["order_no"], split.json()["order_no"]}


def test_deleting_order_restores_stock(kit):
    """删单必须把整单流水冲销干净 —— 冲销不干净是最难发现的库存错账。"""
    headers, warehouse = kit["headers"], kit["warehouse"]
    product, comp_a, comp_b = kit["product"]["id"], kit["comp_a"]["id"], kit["comp_b"]["id"]

    combo = _make_order(kit, "combo", 4).json()
    assert (_stock(headers, warehouse["id"], product), _stock(headers, warehouse["id"], comp_a)) == (4, 92)

    assert client.delete(f"/api/v1/assembly-orders/{combo['id']}", headers=headers).status_code == 204
    assert _stock(headers, warehouse["id"], product) == 0, "删单后成品没复原"
    assert _stock(headers, warehouse["id"], comp_a) == 100, "删单后子件没复原"
    assert _stock(headers, warehouse["id"], comp_b) == 100

    # 明细跟着一起删干净
    assert client.get(f"/api/v1/assembly-orders/{combo['id']}", headers=headers).status_code == 404
    leftover = [
        row
        for row in client.get("/api/v1/inventory?limit=20", headers=headers).json()
        if row.get("related_type") == "assembly" and row.get("doc_no") == combo["order_no"]
    ]
    assert leftover == [], "删单后还留着库存流水"
    assert client.delete(f"/api/v1/assembly-orders/{combo['id']}", headers=headers).status_code == 404


def test_items_are_snapshots_independent_of_bom(kit):
    """明细是快照：BOM 改了，历史单重印还是当初那批料。"""
    headers = kit["headers"]
    order = _make_order(kit, "combo", 1).json()
    stored = {row["product_name"]: row["quantity"] for row in order["items"]}
    assert stored == {"子件甲": 2.0, "子件乙": 3.0}

    # 把甲的配方从 2 改成 9
    bom_a = next(
        row
        for row in client.get("/api/v1/production-boms", headers=headers).json()
        if row.get("product_id") == kit["product"]["id"] and row.get("component_product_id") == kit["comp_a"]["id"]
    )
    client.delete(f"/api/v1/production-boms/{bom_a['id']}", headers=headers)
    client.post(
        "/api/v1/production-boms",
        json={
            "product_id": kit["product"]["id"],
            "component_product_id": kit["comp_a"]["id"],
            "quantity": 9,
            "bom_type": "assembly",
            "level": 1,
        },
        headers=headers,
    )

    again = client.get(f"/api/v1/assembly-orders/{order['id']}", headers=headers).json()
    assert {row["product_name"]: row["quantity"] for row in again["items"]} == stored, (
        "BOM 改了之后历史单据的明细跟着变了 —— 快照没生效"
    )
    # 而新预览会用新配方
    preview = client.get(
        f"/api/v1/assembly-orders/bom-preview?product_id={kit['product']['id']}&quantity=1", headers=headers
    ).json()
    assert next(row for row in preview["items"] if row["product_name"] == "子件甲")["quantity"] == 9

    # 还原配方，避免影响 fixture 收尾（收尾会按 product_id 删掉全部 BOM）
    for row in client.get("/api/v1/production-boms", headers=headers).json():
        if row.get("product_id") == kit["product"]["id"]:
            client.delete(f"/api/v1/production-boms/{row['id']}", headers=headers)
    for comp, per in ((kit["comp_a"], 2), (kit["comp_b"], 3)):
        client.post(
            "/api/v1/production-boms",
            json={
                "product_id": kit["product"]["id"],
                "component_product_id": comp["id"],
                "quantity": per,
                "bom_type": "assembly",
                "level": 1,
            },
            headers=headers,
        )


def test_shortage_warns_but_does_not_block(kit):
    """库存不足照样能开单（允许负库存），但必须把缺口回报出来。"""
    headers, warehouse = kit["headers"], kit["warehouse"]
    # 要 100 套 → 需要 200 个甲，现货 100
    resp = _make_order(kit, "combo", 100)
    assert resp.status_code == 201, resp.text
    warnings = resp.json()["warnings"]
    assert any("子件甲" in text for text in warnings), warnings
    # 单开了，库存就成了负数 —— 这是既定口径（先开单后补货）
    assert _stock(headers, warehouse["id"], kit["comp_a"]["id"]) == -100


# ============================================================
# 校验
# ============================================================
def test_validation_rejects_bad_payloads(kit):
    headers = kit["headers"]
    base = {
        "doc_type": "combo",
        "product_id": kit["product"]["id"],
        "quantity": 1,
        "warehouse_id": kit["warehouse"]["id"],
    }
    # 子件清单不能为空（否则就是一张只动成品不动子件的"假组合单"）
    empty = client.post("/api/v1/assembly-orders", json={**base, "items": []}, headers=headers)
    assert empty.status_code == 400 and "子件清单" in empty.json()["detail"]

    # 子件不能是成品自己
    itself = client.post(
        "/api/v1/assembly-orders",
        json={**base, "items": [{"product_id": kit["product"]["id"], "quantity": 1}]},
        headers=headers,
    )
    assert itself.status_code == 400 and "自己" in itself.json()["detail"]

    # 重复子件要挡住（两行同样的键会让库存口径变得难以核对）
    dup = client.post(
        "/api/v1/assembly-orders",
        json={
            **base,
            "items": [
                {"product_id": kit["comp_a"]["id"], "quantity": 1},
                {"product_id": kit["comp_a"]["id"], "quantity": 2},
            ],
        },
        headers=headers,
    )
    assert dup.status_code == 400 and "两次" in dup.json()["detail"]

    # 单据类型 / 数量 / 商品 / 仓库
    assert (
        client.post(
            "/api/v1/assembly-orders",
            json={**base, "doc_type": "unknown", "items": [{"product_id": kit["comp_a"]["id"], "quantity": 1}]},
            headers=headers,
        ).status_code
        == 400
    )
    assert (
        client.post(
            "/api/v1/assembly-orders",
            json={**base, "quantity": 0, "items": [{"product_id": kit["comp_a"]["id"], "quantity": 1}]},
            headers=headers,
        ).status_code
        in (400, 422)
    )
    assert (
        client.post(
            "/api/v1/assembly-orders",
            json={**base, "product_id": 99999999, "items": [{"product_id": kit["comp_a"]["id"], "quantity": 1}]},
            headers=headers,
        ).status_code
        == 400
    )
    assert (
        client.post(
            "/api/v1/assembly-orders",
            json={**base, "warehouse_id": 99999999, "items": [{"product_id": kit["comp_a"]["id"], "quantity": 1}]},
            headers=headers,
        ).status_code
        == 400
    )
    # 用量必须为正
    assert (
        client.post(
            "/api/v1/assembly-orders",
            json={**base, "items": [{"product_id": kit["comp_a"]["id"], "quantity": 0}]},
            headers=headers,
        ).status_code
        in (400, 422)
    )


# ============================================================
# 列表 / 打印 / 模板注册
# ============================================================
def test_list_filters_by_doc_type(kit):
    headers = kit["headers"]
    combo = _make_order(kit, "combo", 1).json()
    split = _make_order(kit, "split", 1).json()

    all_rows = client.get("/api/v1/assembly-orders", headers=headers).json()
    assert {row["id"] for row in all_rows} >= {combo["id"], split["id"]}

    only_combo = client.get("/api/v1/assembly-orders?doc_type=combo", headers=headers).json()
    assert all(row["doc_type"] == "combo" for row in only_combo)
    assert combo["id"] in {row["id"] for row in only_combo}
    assert split["id"] not in {row["id"] for row in only_combo}

    hit = client.get(f"/api/v1/assembly-orders?keyword={combo['order_no']}", headers=headers).json()
    assert [row["id"] for row in hit] == [combo["id"]]
    assert client.get("/api/v1/assembly-orders?keyword=一定没有的单号", headers=headers).json() == []


def test_print_renders_both_directions(kit):
    headers, warehouse = kit["headers"], kit["warehouse"]
    combo = _make_order(kit, "combo", 5).json()
    split = _make_order(kit, "split", 1).json()

    combo_pdf = client.get(f"/api/v1/print/assembly/{combo['id']}")
    assert combo_pdf.status_code == 200
    assert combo_pdf.headers["content-type"].startswith("application/pdf")
    text = fitz.open(stream=combo_pdf.content, filetype="pdf")[0].get_text()
    assert "组合单" in text
    assert combo["order_no"] in text
    assert "子件甲" in text and "子件乙" in text
    assert "成品入库" in text, "组合单要写清成品是入库方向"
    assert warehouse["name"] in text

    split_text = fitz.open(
        stream=client.get(f"/api/v1/print/assembly/{split['id']}").content, filetype="pdf"
    )[0].get_text()
    assert "拆卸单" in split_text
    assert "成品出库" in split_text

    assert client.get("/api/v1/print/assembly/99999999").status_code == 404


def test_print_template_registered_for_assembly():
    """新增打印类型必须同时进 DOC_TYPE_ORDER，否则模板表排序会漏掉它。"""
    from app.api.v1.routes.erp import printable_doc_types
    from app.models.print_template import DOC_TYPE_ORDER

    assert "assembly" in dict(printable_doc_types())
    assert "assembly" in DOC_TYPE_ORDER

    rows = client.get("/api/v1/system/print-templates", headers=_headers()).json()
    hit = next(row for row in rows["items"] if row["doc_type"] == "assembly")
    assert hit["doc_label"] == "组合拆卸单"
    assert hit["registered"] is True


def test_frontend_page_and_menu_are_wired():
    from pathlib import Path

    root = Path(__file__).resolve().parent.parent
    source = (root / "frontend" / "src" / "App.jsx").read_text(encoding="utf-8")

    assert "selectedTab === 'assembly'" in source, "组合拆卸页没有渲染分支"
    line = next(l for l in source.splitlines() if "{ key: 'assembly', label:" in l)
    assert "todo: true" not in line, "组合拆卸菜单还标着「待建」"
    for endpoint in ("/assembly-orders", "/assembly-orders/bom-preview", "/assembly-orders/meta"):
        assert endpoint in source, f"前端没有调用 {endpoint}"
    for handler in ("refreshAssemblyOrders", "submitAssemblyOrder", "loadAssemblyBomPreview"):
        assert handler in source, f"前端缺少处理函数 {handler}"


def test_statement_menus_alias_the_existing_ledger_page():
    """采购 / 销售对账单不另建页面 —— 它们就是「往来对账」的预设视图。

    这条测试锁住的是**不做重复建设**这个决定：如果以后有人给这两个菜单
    新写一套页面，就得同时维护两份对账逻辑，迟早对不上。
    """
    from pathlib import Path

    root = Path(__file__).resolve().parent.parent
    source = (root / "frontend" / "src" / "App.jsx").read_text(encoding="utf-8")

    # 别名映射必须是这两条（采购=供应商、销售=客户）
    assert "const LEDGER_ALIASES = { 'purchase-statement': 'supplier', 'sales-statement': 'customer' };" in source

    for key in ("purchase-statement", "sales-statement"):
        line = next(l for l in source.splitlines() if f"{{ key: '{key}', label:" in l)
        assert "todo: true" not in line, f"{key} 菜单还标着「待建」"
        # 不能有单独渲染分支（那意味着又造了一个页面）
        assert f"selectedTab === '{key}'" not in source, f"{key} 不应该有自己的页面"

    # 点进去要落到既有对账页，并把往来类型固定成对应的一方。
    # 第 10 批把侧边栏改成递归渲染后，这段逻辑收进了统一的 gotoMenu ——
    # 断言跟着绑**行为**（查别名表 + 落到 ledger + 菜单项走 gotoMenu），
    # 不再绑当时的变量名与实参个数（重构时先后误报过两次）。
    assert "const alias = LEDGER_ALIASES[pageKey];" in source
    assert "setSelectedTab('ledger');" in source
    # 对账单菜单必须继续走 gotoMenu（否则别名就失效了）
    assert "onClick={() => gotoMenu(node.page_key" in source
