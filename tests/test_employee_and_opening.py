"""员工档案 与 期初建账（基础资料收尾）回归测试。

这一批的风险集中在两处"静默"上，各有一条测试专门钉住：

1. **Excel 导入静默丢字段**：`_import_archive` 拿到列名直接 setattr，
   而「部门」这一列填的是**名字**、库里存的是 **id**。不做翻译的话
   SQLAlchemy 会默默接受这个不存在的属性 —— 导入报成功、部门却没了。
   `test_employee_excel_import_resolves_department_and_status` 导入后**回读**，
   断言 department_id 真的落库了。

2. **期初流水与真实业务流水混在同一张表**：期初就是
   `inventory_transactions(related_type='opening')`。少一个判断就可能
   借期初接口删掉一条真实出库 —— 那等于凭空改库存。
   `test_opening_stock_cannot_touch_business_transactions` 拿一条真实出库的
   id 去敲期初删除接口，必须 404；清空期初后真实流水条数必须一条不少。

其余覆盖：员工档案 CRUD / 校验 / 部门引用阻断删除 / 批量删除；
期初 upsert 幂等、归零即删、负数拦截、现存量联动、应收应付期初读写。

测试数据命名遵守 scripts/clean_test_data.py 的签名：EMP-* / WH-* / SKU-* / CUST-* / SUP-*。
"""

import uuid

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.models.employee import EMPLOYEE_STATUS, GENDER_OPTIONS
from app.services import excel_io

client = TestClient(app)


def _hex() -> str:
    return uuid.uuid4().hex[:8]


def _headers() -> dict[str, str]:
    resp = client.post("/api/v1/auth/login", json={"username": "admin", "password": "Admin123"})
    assert resp.status_code == 200, resp.text
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


def _stock_of(headers: dict[str, str], product_id: int) -> int:
    """某商品的现存量合计（跨仓库）。"""
    data = client.get(f"/api/v1/inventory/stock?product_id={product_id}", headers=headers).json()
    return int(data["summary"]["total_quantity"])


@pytest.fixture()
def sandbox():
    """造一套用完即删的基础资料：仓库 + 商品 + 客户 + 供应商（+ 部门）。"""
    headers = _headers()
    tag = _hex()
    dept = client.post(
        "/api/v1/system/departments",
        json={"code": f"TEST-DEPT-{tag}", "name": f"测试部门-{tag}"},
        headers=headers,
    ).json()
    warehouse = client.post(
        "/api/v1/warehouses", json={"code": f"WH-{tag}", "name": f"期初测试仓-{tag}"}, headers=headers
    ).json()
    product = client.post(
        "/api/v1/products",
        json={"sku": f"SKU-EMP-{tag}", "name": f"期初测试商品-{tag}", "purchase_price": 10.0, "sale_price": 20.0},
        headers=headers,
    ).json()
    customer = client.post(
        "/api/v1/customers", json={"code": f"CUST-EMP-{tag}", "name": f"期初测试客户-{tag}"}, headers=headers
    ).json()
    supplier = client.post(
        "/api/v1/suppliers", json={"code": f"SUP-EMP-{tag}", "name": f"期初测试供应商-{tag}"}, headers=headers
    ).json()
    yield {
        "headers": headers,
        "tag": tag,
        "dept": dept,
        "warehouse": warehouse,
        "product": product,
        "customer": customer,
        "supplier": supplier,
    }
    # 清场：先删单据（会冲销库存流水），再删档案，最后删部门
    for order in client.get("/api/v1/sales-orders", headers=headers).json():
        if order.get("customer_id") == customer["id"]:
            client.delete(f"/api/v1/sales-orders/{order['id']}", headers=headers, params={"force": True})
    client.put(
        "/api/v1/opening-stock",
        json={"items": [{"warehouse_id": warehouse["id"], "product_id": product["id"], "quantity": 0, "unit_price": 0}]},
        headers=headers,
    )
    for kind, item in (
        ("products", product),
        ("warehouses", warehouse),
        ("customers", customer),
        ("suppliers", supplier),
    ):
        client.delete(f"/api/v1/{kind}/{item['id']}", headers=headers, params={"force": True})
    client.delete(f"/api/v1/system/departments/{dept['id']}", headers=headers)


# ============================================================
# 员工档案
# ============================================================
def test_employee_crud_and_department_link(sandbox):
    headers, dept = sandbox["headers"], sandbox["dept"]
    code = f"EMP-{sandbox['tag']}"

    meta = client.get("/api/v1/employees/meta", headers=headers).json()
    assert [item["value"] for item in meta["statuses"]] == list(EMPLOYEE_STATUS)
    assert meta["genders"] == GENDER_OPTIONS
    assert any(row["id"] == dept["id"] for row in meta["departments"])

    created = client.post(
        "/api/v1/employees",
        json={
            "code": code,
            "name": "验收员工",
            "gender": "男",
            "department_id": dept["id"],
            "position": "车间主任",
            "phone": "13800001111",
            "hire_date": "2026-01-01",
            "status": "active",
            "base_salary": 8000,
        },
        headers=headers,
    )
    assert created.status_code == 201, created.text
    body = created.json()
    assert body["department_name"] == dept["name"], "列表里要直接能显示部门名，不该让前端再查一次组织树"
    employee_id = body["id"]

    # 改：离职 + 离职日期（前端只在离职时显示这个字段）
    patched = client.patch(
        f"/api/v1/employees/{employee_id}",
        json={"code": code, "name": "验收员工改名", "status": "left", "leave_date": "2026-09-30"},
        headers=headers,
    )
    assert patched.status_code == 200, patched.text
    assert patched.json()["name"] == "验收员工改名"
    assert patched.json()["status"] == "left"
    # 整表更新：没传的字段回到默认，部门被清掉（与仓库档案同一约定）
    assert patched.json()["department_id"] is None

    assert len(client.get(f"/api/v1/employees?keyword={code}", headers=headers).json()) == 1
    assert len(client.get("/api/v1/employees?status=left", headers=headers).json()) >= 1
    assert client.get("/api/v1/employees?keyword=一定查不到的工号", headers=headers).json() == []

    assert client.get(f"/api/v1/employees/{employee_id}", headers=headers).status_code == 200
    assert client.delete(f"/api/v1/employees/{employee_id}", headers=headers).status_code == 204
    assert client.get(f"/api/v1/employees/{employee_id}", headers=headers).status_code == 404
    assert client.delete(f"/api/v1/employees/{employee_id}", headers=headers).status_code == 404


def test_employee_validation_rejects_bad_payload(sandbox):
    headers = sandbox["headers"]
    code = f"EMP-{sandbox['tag']}-v"
    ok = {"code": code, "name": "校验员工"}
    assert client.post("/api/v1/employees", json=ok, headers=headers).status_code == 201

    # 工号唯一
    duplicate = client.post("/api/v1/employees", json=ok, headers=headers)
    assert duplicate.status_code == 400 and "已存在" in duplicate.json()["detail"]
    # 状态只能是枚举值
    bad_status = client.post("/api/v1/employees", json={**ok, "code": f"{code}-1", "status": "zombie"}, headers=headers)
    assert bad_status.status_code == 400 and "在职状态" in bad_status.json()["detail"]
    # 性别不做过细枚举，但也不能乱填
    bad_gender = client.post("/api/v1/employees", json={**ok, "code": f"{code}-2", "gender": "外星"}, headers=headers)
    assert bad_gender.status_code == 400 and "性别" in bad_gender.json()["detail"]
    # 部门必须真实存在
    bad_dept = client.post(
        "/api/v1/employees", json={**ok, "code": f"{code}-3", "department_id": 99999999}, headers=headers
    )
    assert bad_dept.status_code == 400 and "部门" in bad_dept.json()["detail"]


def test_department_with_employees_cannot_be_deleted(sandbox):
    """部门下挂着员工时禁删 —— 否则会留下一批指不到部门的员工，界面上还修不回来。"""
    headers, dept = sandbox["headers"], sandbox["dept"]
    employee = client.post(
        "/api/v1/employees",
        json={"code": f"EMP-{sandbox['tag']}-d", "name": "部门占用员工", "department_id": dept["id"]},
        headers=headers,
    ).json()

    blocked = client.delete(f"/api/v1/system/departments/{dept['id']}", headers=headers)
    assert blocked.status_code == 409, blocked.text
    assert "员工" in blocked.json()["detail"]

    # 把员工调走之后才能删
    client.patch(
        f"/api/v1/employees/{employee['id']}",
        json={"code": employee["code"], "name": employee["name"], "department_id": None},
        headers=headers,
    )
    assert client.delete(f"/api/v1/employees/{employee['id']}", headers=headers).status_code == 204
    assert client.delete(f"/api/v1/system/departments/{dept['id']}", headers=headers).status_code == 204
    # 重新造一个，交给 fixture 收尾
    sandbox["dept"] = client.post(
        "/api/v1/system/departments",
        json={"code": f"TEST-DEPT-{_hex()}", "name": "收尾部门"},
        headers=headers,
    ).json()


def test_employee_archive_delete_contract(sandbox):
    """员工走通用档案通路：引用检查口存在、批量删除可用、删不存在的返回 404。"""
    headers = sandbox["headers"]
    employee = client.post(
        "/api/v1/employees", json={"code": f"EMP-{sandbox['tag']}-ref", "name": "引用检查员工"}, headers=headers
    ).json()

    refs = client.get(f"/api/v1/employees/{employee['id']}/references", headers=headers)
    assert refs.status_code == 200
    assert refs.json()["kind"] == "employee"
    # 目前没有业务表用外键引用员工（单据上的人名是字符串快照），所以引用清单为空
    assert refs.json()["references"] == []

    second = client.post(
        "/api/v1/employees", json={"code": f"EMP-{sandbox['tag']}-ref2", "name": "引用检查员工2"}, headers=headers
    ).json()
    batch = client.request(
        "DELETE",
        "/api/v1/employees/batch",
        json={"ids": [employee["id"], second["id"]]},
        headers=headers,
    )
    assert batch.status_code in (200, 204), batch.text
    assert client.get(f"/api/v1/employees/{employee['id']}", headers=headers).status_code == 404
    assert client.get("/api/v1/employees/99999999/references", headers=headers).status_code == 404


# ============================================================
# 员工档案 × Excel
# ============================================================
def test_employees_registered_as_excel_kind():
    headers = _headers()
    kinds = [row["kind"] for row in client.get("/api/v1/excel/kinds", headers=headers).json()]
    assert "employees" in kinds

    template = client.get("/api/v1/excel/templates/employees", headers=headers)
    assert template.status_code == 200
    assert "spreadsheet" in template.headers["content-type"]

    exported = client.get("/api/v1/excel/export/employees", headers=headers)
    assert exported.status_code == 200

    # 列定义里必须有「部门」这一列，且它是**名字**不是 id
    fields = [col["field"] for col in excel_io.COLUMNS["employees"]]
    assert "department_name" in fields
    assert "code" in excel_io.KEY_FIELDS["employees"]


def test_employee_excel_import_resolves_department_and_status(sandbox):
    """导入的员工必须真的带上部门与状态 —— 这条专抓"setattr 到不存在的属性、静默丢字段"。"""
    headers, dept = sandbox["headers"], sandbox["dept"]
    code = f"EMP-{sandbox['tag']}-x"

    # 直接按列定义造一份 xlsx（走真实的模板 → 填数 → 上传通路）
    from io import BytesIO

    from openpyxl import Workbook

    wb = Workbook()
    ws = wb.active
    ws.title = "导入数据"
    ws.append(["工号", "姓名", "性别", "部门", "岗位", "在职状态"])
    ws.append([code, "导入员工", "女", dept["name"], "质检员", "在职"])
    ws.append([f"{code}-bad", "部门不存在", "男", f"没有这个部门-{_hex()}", "临时", "在职"])
    ws.append([f"{code}-bad2", "状态乱填", "男", dept["name"], "临时", "退休"])
    buffer = BytesIO()
    wb.save(buffer)
    buffer.seek(0)

    resp = client.post(
        "/api/v1/excel/import/employees",
        files={"file": ("employees.xlsx", buffer.read(), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    result = resp.json()
    assert result["created"] == 1, result
    assert len(result["errors"]) == 2, result
    messages = " ".join(str(item["message"]) for item in result["errors"])
    assert "部门" in messages and "在职状态" in messages

    rows = client.get(f"/api/v1/employees?keyword={code}", headers=headers).json()
    hit = next(row for row in rows if row["code"] == code)
    assert hit["department_id"] == dept["id"], "部门静默丢了：Excel 里的名字没被翻成 id"
    assert hit["department_name"] == dept["name"]
    assert hit["status"] == "active", "中文「在职」没被翻成 active"
    assert hit["gender"] == "女"

    for row in rows:
        client.delete(f"/api/v1/employees/{row['id']}", headers=headers)


# ============================================================
# 期初建账：库存
# ============================================================
def test_opening_stock_upsert_is_idempotent(sandbox):
    headers, warehouse, product = sandbox["headers"], sandbox["warehouse"], sandbox["product"]
    item = {"warehouse_id": warehouse["id"], "product_id": product["id"], "quantity": 100, "unit_price": 10.0}

    before = client.get("/api/v1/opening-stock", headers=headers).json()["summary"]["lines"]
    first = client.put("/api/v1/opening-stock", json={"items": [item]}, headers=headers).json()
    assert first["created"] == 1 and first["updated"] == 0
    assert first["summary"]["lines"] == before + 1

    # 再存一次同样的键：必须是"更新"，不能变成第二行（否则现存量会被翻倍）
    second = client.put(
        "/api/v1/opening-stock", json={"items": [{**item, "quantity": 150, "unit_price": 9.0}]}, headers=headers
    ).json()
    assert second["created"] == 0 and second["updated"] == 1
    assert second["summary"]["lines"] == before + 1

    rows = [
        row
        for row in client.get("/api/v1/opening-stock", headers=headers).json()["items"]
        if row["warehouse_id"] == warehouse["id"] and row["product_id"] == product["id"]
    ]
    assert len(rows) == 1
    assert (rows[0]["quantity"], rows[0]["unit_price"]) == (150, 9.0)
    assert rows[0]["amount"] == 1350.0
    assert rows[0]["has_business"] is False


def test_opening_stock_payload_carries_note(sandbox):
    """列表必须带出备注。

    这条是踩坑补的：第一版 `_opening_stock_rows` 漏了 `note` 字段，
    后果有两个 —— 页面上「备注」列永远是空的；「改这一项」载入时拿不到备注，
    保存后会被刷成默认的"期初建账"，**把用户写的建账说明悄悄改掉**。
    所以这里既查列表返回，也查一次"载入→再保存"的往返。
    """
    headers, warehouse, product = sandbox["headers"], sandbox["warehouse"], sandbox["product"]
    note = f"验收备注-{sandbox['tag']}"
    client.put(
        "/api/v1/opening-stock",
        json={
            "items": [
                {
                    "warehouse_id": warehouse["id"],
                    "product_id": product["id"],
                    "quantity": 20,
                    "unit_price": 3.0,
                    "note": note,
                }
            ]
        },
        headers=headers,
    )
    row = next(
        item
        for item in client.get("/api/v1/opening-stock", headers=headers).json()["items"]
        if item["warehouse_id"] == warehouse["id"] and item["product_id"] == product["id"]
    )
    assert row["note"] == note, "列表没带出备注"

    # 往返：拿列表返回的字段原样回去保存，备注不能被改写
    client.put(
        "/api/v1/opening-stock",
        json={
            "items": [
                {
                    "warehouse_id": row["warehouse_id"],
                    "product_id": row["product_id"],
                    "quantity": row["quantity"],
                    "unit_price": row["unit_price"],
                    "note": row["note"],
                }
            ]
        },
        headers=headers,
    )
    again = next(
        item
        for item in client.get("/api/v1/opening-stock", headers=headers).json()["items"]
        if item["warehouse_id"] == warehouse["id"]
    )
    assert again["note"] == note, "往返保存把备注刷掉了"


def test_opening_stock_zero_means_delete(sandbox):
    """填 0 就是"没有期初"：删掉该行，不留在库里当一行 0。"""
    headers, warehouse, product = sandbox["headers"], sandbox["warehouse"], sandbox["product"]
    item = {"warehouse_id": warehouse["id"], "product_id": product["id"], "quantity": 50, "unit_price": 10.0}
    client.put("/api/v1/opening-stock", json={"items": [item]}, headers=headers)

    cleared = client.put(
        "/api/v1/opening-stock",
        json={"items": [{**item, "quantity": 0, "unit_price": 0}]},
        headers=headers,
    ).json()
    assert cleared["removed"] == 1 and cleared["created"] == 0 and cleared["updated"] == 0
    remaining = [
        row
        for row in client.get("/api/v1/opening-stock", headers=headers).json()["items"]
        if row["warehouse_id"] == warehouse["id"] and row["product_id"] == product["id"]
    ]
    assert remaining == []


def test_opening_stock_feeds_current_stock(sandbox):
    """期初就是库存流水，现存量必须跟着它走 —— 这是"期初建账"能用的前提。"""
    headers, warehouse, product, customer = (
        sandbox["headers"],
        sandbox["warehouse"],
        sandbox["product"],
        sandbox["customer"],
    )
    assert _stock_of(headers, product["id"]) == 0

    client.put(
        "/api/v1/opening-stock",
        json={"items": [{"warehouse_id": warehouse["id"], "product_id": product["id"], "quantity": 100, "unit_price": 10.0}]},
        headers=headers,
    )
    assert _stock_of(headers, product["id"]) == 100

    order = client.post(
        "/api/v1/sales-orders",
        json={
            "customer_id": customer["id"],
            "warehouse_id": warehouse["id"],
            "doc_type": "outbound",
            "items": [{"product_id": product["id"], "quantity": 30, "unit_price": 20.0}],
        },
        headers=headers,
    )
    assert order.status_code == 201, order.text
    assert _stock_of(headers, product["id"]) == 70

    # 开过单之后，该行会被标记出来（页面据此警示"改期初会挪动历史起点"）
    row = [
        item
        for item in client.get("/api/v1/opening-stock", headers=headers).json()["items"]
        if item["warehouse_id"] == warehouse["id"] and item["product_id"] == product["id"]
    ][0]
    assert row["has_business"] is True
    assert row["current_stock"] == 70

    # 把期初改成 200：现存量变成 170（= 200 − 30）
    client.put(
        "/api/v1/opening-stock",
        json={"items": [{"warehouse_id": warehouse["id"], "product_id": product["id"], "quantity": 200, "unit_price": 10.0}]},
        headers=headers,
    )
    assert _stock_of(headers, product["id"]) == 170


def test_opening_stock_cannot_touch_business_transactions(sandbox):
    """期初接口绝不能碰到真实业务流水 —— 少一个 related_type 判断就是凭空改库存。

    ⚠️ 这条测试会调用**全库范围**的 `POST /opening-stock/clear`，而测试连的是正式库，
    库里躺着用户真实的期初台账。所以：

    1. 调之前先把现有期初整份快照**落盘**（进程被杀也能捞回来）；
    2. 断言完在 `finally` 里立刻用快照还原 —— 还原失败会抛出去，不允许"测试绿了数据没了"；
    3. 还原确认无误后才删快照文件。

    没有这层保护的第一版把用户的 42 行期初（40609 数量 / 316565.32 金额）真的删掉了
    —— 这就是本文件里唯一一次真实的教训，别把它改回去。
    """
    from prod_snapshot import ProdSnapshot

    headers, warehouse, product, customer = (
        sandbox["headers"],
        sandbox["warehouse"],
        sandbox["product"],
        sandbox["customer"],
    )
    order = client.post(
        "/api/v1/sales-orders",
        json={
            "customer_id": customer["id"],
            "warehouse_id": warehouse["id"],
            "doc_type": "outbound",
            "items": [{"product_id": product["id"], "quantity": 5, "unit_price": 20.0}],
        },
        headers=headers,
    ).json()

    business_rows = [
        row
        for row in client.get("/api/v1/inventory/stock", headers=headers).json()["rows"]
        if row["warehouse_id"] == warehouse["id"]
    ]
    assert business_rows, "出库单应该已经写了库存流水"

    # 拿真实出库流水的 id 去敲期初删除接口 → 必须 404
    tx = next(
        row
        for row in client.get("/api/v1/inventory?limit=10", headers=headers).json()
        if row.get("related_type") == "sales_out"
    )
    assert client.delete(f"/api/v1/opening-stock/{tx['id']}", headers=headers).status_code == 404
    assert client.delete("/api/v1/opening-stock/99999999", headers=headers).status_code == 404

    guard = ProdSnapshot("opening-stock")
    live = client.get("/api/v1/opening-stock", headers=headers).json()
    guard.save(live["items"])
    before_summary = live["summary"]
    try:
        # 再加一条本次测试自己的期初，确保 clear 确实有东西可删
        client.put(
            "/api/v1/opening-stock",
            json={"items": [{"warehouse_id": warehouse["id"], "product_id": product["id"], "quantity": 88, "unit_price": 1.0}]},
            headers=headers,
        )
        before_tx = len(client.get("/api/v1/inventory?limit=1000", headers=headers).json())
        cleared = client.post("/api/v1/opening-stock/clear", headers=headers).json()
        assert cleared["deleted"] >= 1
        after_tx = client.get("/api/v1/inventory?limit=1000", headers=headers).json()
        assert len(after_tx) == before_tx - cleared["deleted"], "清空期初把业务流水也删了"
        assert any(row["id"] == tx["id"] for row in after_tx), "真实出库流水被清掉了"
        assert client.get("/api/v1/opening-stock", headers=headers).json()["summary"]["lines"] == 0
    finally:
        # 用快照还原（走批量保存口，键是仓库×商品，数量与备注一并带回）
        restored = guard.restore(
            lambda rows: client.put(
                "/api/v1/opening-stock",
                json={
                    "items": [
                        {
                            "warehouse_id": row["warehouse_id"],
                            "product_id": row["product_id"],
                            "quantity": row["quantity"],
                            "unit_price": row["unit_price"],
                            "note": row.get("note"),
                        }
                        for row in rows
                    ]
                },
                headers=headers,
            ).json()["created"]
            + 0
        )
        after = client.get("/api/v1/opening-stock", headers=headers).json()["summary"]
        # 三项都要对上：行数、数量、金额。只比行数会漏掉"数量被改小"这种还原不全
        assert after["lines"] == before_summary["lines"], (
            f"期初还原失败：快照 {before_summary['lines']} 行，实际只剩 {after['lines']} 行"
            f"（快照文件保留在 {guard.path}）"
        )
        assert after["total_quantity"] == before_summary["total_quantity"], (
            f"期初数量没还原：{before_summary['total_quantity']} -> {after['total_quantity']}"
        )
        assert abs(after["total_amount"] - before_summary["total_amount"]) < 0.01, (
            f"期初金额没还原：{before_summary['total_amount']} -> {after['total_amount']}"
        )
        assert restored == len(guard.rows), f"批量还原只写了 {restored} 行，快照是 {len(guard.rows)} 行"
        guard.done()

    assert client.delete(f"/api/v1/sales-orders/{order['id']}", headers=headers).status_code in (200, 204)
    # 顺带确认删单确实冲销了那条出库（这次测试自己的 88 不在快照里，已被 clear 清掉）
    assert client.get(f"/api/v1/inventory/stock?product_id={product['id']}", headers=headers).json()[
        "summary"
    ]["total_quantity"] == 0


def test_opening_stock_validation(sandbox):
    headers, warehouse, product = sandbox["headers"], sandbox["warehouse"], sandbox["product"]
    base = {"warehouse_id": warehouse["id"], "product_id": product["id"], "quantity": 1, "unit_price": 1.0}

    assert client.put("/api/v1/opening-stock", json={"items": "oops"}, headers=headers).status_code == 400
    assert client.put("/api/v1/opening-stock", json={}, headers=headers).status_code == 400
    negative = client.put(
        "/api/v1/opening-stock", json={"items": [{**base, "quantity": -5}]}, headers=headers
    )
    assert negative.status_code == 400 and "不能为负数" in negative.json()["detail"]
    negative_price = client.put(
        "/api/v1/opening-stock", json={"items": [{**base, "unit_price": -1}]}, headers=headers
    )
    assert negative_price.status_code == 400 and "单价" in negative_price.json()["detail"]
    assert client.put(
        "/api/v1/opening-stock", json={"items": [{**base, "warehouse_id": 99999999}]}, headers=headers
    ).status_code == 400
    assert client.put(
        "/api/v1/opening-stock", json={"items": [{**base, "product_id": 99999999}]}, headers=headers
    ).status_code == 400
    assert client.put(
        "/api/v1/opening-stock", json={"items": [{**base, "quantity": "abc"}]}, headers=headers
    ).status_code == 400


# ============================================================
# 期初建账：应收 / 应付
# ============================================================
def test_opening_balances_read_and_write(sandbox):
    headers, customer, supplier = sandbox["headers"], sandbox["customer"], sandbox["supplier"]

    data = client.get("/api/v1/opening-balances", headers=headers).json()
    assert "receivables" in data and "payables" in data
    assert data["summary"]["customer_count"] == len(data["receivables"])
    assert data["summary"]["supplier_count"] == len(data["payables"])

    written = client.put(
        "/api/v1/opening-balances",
        json={
            "receivable": [{"id": customer["id"], "init_amount": 5000, "init_invoice_debt": 300}],
            # 负数合法：给供应商的预付款，期初就是负的
            "payable": [{"id": supplier["id"], "init_amount": -800}],
        },
        headers=headers,
    )
    assert written.status_code == 200, written.text
    result = written.json()

    row = next(item for item in result["receivables"] if item["id"] == customer["id"])
    assert row["init_amount"] == 5000.0
    assert row["init_invoice_debt"] == 300.0
    # 当前余额 = 期初 + 期间发生额（与「往来对账」同一口径）
    assert row["current_balance"] == round(row["init_amount"] + row["occurred_amount"], 2)

    payable = next(item for item in result["payables"] if item["id"] == supplier["id"])
    assert payable["init_amount"] == -800.0

    # 只改期初字段，不碰档案其它字段
    detail = client.get("/api/v1/suppliers", headers=headers).json()
    kept = next(item for item in detail if item["id"] == supplier["id"])
    assert kept["name"] == supplier["name"]

    # 落库了才算数
    again = client.get("/api/v1/opening-balances", headers=headers).json()
    assert next(item for item in again["receivables"] if item["id"] == customer["id"])["init_amount"] == 5000.0

    assert client.put("/api/v1/opening-balances", json={}, headers=headers).status_code == 400
    assert client.put(
        "/api/v1/opening-balances", json={"receivable": [{"id": 99999999, "init_amount": 1}]}, headers=headers
    ).status_code == 400
    assert client.put(
        "/api/v1/opening-balances", json={"receivable": [{"id": customer["id"], "init_amount": "不是数字"}]}, headers=headers
    ).status_code == 400

    # 收尾：把两个期初金额清零
    client.put(
        "/api/v1/opening-balances",
        json={"receivable": [{"id": customer["id"], "init_amount": 0}], "payable": [{"id": supplier["id"], "init_amount": 0}]},
        headers=headers,
    )


def test_department_options_open_to_any_logged_in_user(sandbox):
    """员工档案页要部门下拉，但不该因此要求管理员权限；同时不泄漏管理信息。"""
    # 显式清空 Authorization：conftest 默认注入管理员 token，否则这里验的就不是"匿名"了
    assert (
        client.get("/api/v1/system/departments/options", headers={"Authorization": ""}).status_code == 401
    )

    role = client.post(
        "/api/v1/system/roles",
        json={
            "code": f"TEST-ROLE-{_hex()}",
            "name": "测试角色-部门选项",
            "permissions": {"all": False, "menus": ["staff"]},
        },
        headers=_headers(),
    ).json()
    username = f"TEST-USR-{_hex()}"
    user = client.post(
        "/api/v1/system/users",
        json={"username": username, "password": "Pass1234", "role_id": role["id"]},
        headers=_headers(),
    ).json()
    try:
        login = client.post("/api/v1/auth/login", json={"username": username, "password": "Pass1234"})
        headers = {"Authorization": f"Bearer {login.json()['access_token']}"}

        options = client.get("/api/v1/system/departments/options", headers=headers)
        assert options.status_code == 200, options.text
        assert len(options.json()) >= 1
        first = options.json()[0]
        # 只给选项，不给用户数 / 负责人这类管理信息
        assert set(first) == {"id", "code", "name", "parent_id", "level", "label", "is_active"}

        # 管理接口依然只对管理员开放
        assert client.get("/api/v1/system/departments", headers=headers).status_code == 403
    finally:
        admin = _headers()
        client.delete(f"/api/v1/system/users/{user['id']}", headers=admin)
        client.delete(f"/api/v1/system/roles/{role['id']}", headers=admin)


# ============================================================
# 前端挂载点
# ============================================================
def test_frontend_pages_and_menu_are_wired():
    from pathlib import Path

    root = Path(__file__).resolve().parent.parent
    source = (root / "frontend" / "src" / "App.jsx").read_text(encoding="utf-8")
    styles = (root / "frontend" / "src" / "styles.css").read_text(encoding="utf-8")

    for key in ("staff", "opening-stock"):
        assert f"selectedTab === '{key}'" in source, f"{key} 页面没有渲染分支"
        line = next(l for l in source.splitlines() if f"{{ key: '{key}', label:" in l)
        assert "todo: true" not in line, f"{key} 菜单还标着「待建」"

    for endpoint in ("/employees", "/opening-stock", "/opening-balances", "/employees/meta"):
        assert endpoint in source, f"前端没有调用 {endpoint}"
    for handler in ("refreshEmployees", "submitEmployee", "saveOpeningStock", "saveOpeningBalances", "clearOpeningStock"):
        assert handler in source, f"前端缺少处理函数 {handler}"

    assert ".opening-entry" in styles and ".stat-row" in styles and ".cell-input" in styles
