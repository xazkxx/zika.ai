"""打印模板 与 操作日志（第 5 批第 3 轮）回归测试。

这一轮的核心风险有两条，各对应一组测试：

1. **打印模板"改了没反应"**：模板表里加了一堆字段、渲染器其实不认，
   用户改完打印出来还是老样子。
   所以 `test_template_choices_reach_the_pdf` 是**真改模板 → 真打一张单据 →
   从 PDF 里抠字比对**，和参数页那条测试同一套路子。
   另外 `test_print_registry_is_covered_by_templates` 保证新增一张单据的打印
   不会漏掉模板记录，也不会漏进 DOC_TYPE_ORDER 导致排序错乱。

2. **操作日志"把业务搞挂"或"记不全"**：中间件写得不好会拖慢甚至打挂正常请求；
   动作名翻译得不好，日志就是一堆 url 天书。
   所以有 `test_operation_log_records_writes_only`（查询不记、写操作记全）、
   `test_login_attempts_are_logged_with_username`（失败登录也要留下是谁在试）、
   以及纯函数级的 `test_describe_operation`（不碰数据库，把翻译规则钉死）。

日志表会自我修剪，这条规则用**内存 sqlite 库 + 很小的上限**单独验证
（`test_operation_log_prunes_oldest`），不去动真库里的历史日志。

测试数据命名遵守 scripts/clean_test_data.py 的签名：CUST-TPL-* / SKU-TPL-*。
"""

import uuid

import fitz
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.main import app
from app.models.operation_log import (
    MAX_OPERATION_LOGS,
    OPERATION_LOG_METHODS,
    OperationLog,
    describe_operation,
    prune_operation_logs,
    record_operation,
)
from app.models.print_template import DOC_TYPE_ORDER, STANDALONE_DOC_TYPES

client = TestClient(app)
ADMIN = {"username": "admin", "password": "Admin123"}


def _hex() -> str:
    return uuid.uuid4().hex[:8]


def _admin_headers() -> dict[str, str]:
    resp = client.post("/api/v1/auth/login", json=ADMIN)
    assert resp.status_code == 200, resp.text
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


def _pdf_text(resp) -> str:
    assert resp.status_code == 200, resp.text
    assert resp.headers["content-type"].startswith("application/pdf")
    return fitz.open(stream=resp.content, filetype="pdf")[0].get_text()


def _templates(headers: dict[str, str]) -> dict[str, dict]:
    data = client.get("/api/v1/system/print-templates", headers=headers).json()
    return {row["doc_type"]: row for row in data["items"]}


def _reset_template(headers: dict[str, str], doc_type: str) -> None:
    row = _templates(headers)[doc_type]
    client.post(f"/api/v1/system/print-templates/{row['id']}/reset", headers=headers)


@pytest.fixture()
def template_guard():
    """模板改动自动还原：模板是部署级配置，测试不能把管理员调好的外观留在改过的状态。"""
    headers = _admin_headers()
    before = _templates(headers)
    snapshot = {
        doc_type: {
            "name": row["name"],
            "title": row["title"],
            "header_text": row["header_text"],
            "footer_text": row["footer_text"],
            "show_company": row["show_company"],
            "show_signatures": row["show_signatures"],
            "note": row["note"],
        }
        for doc_type, row in before.items()
    }
    yield headers
    for doc_type, payload in snapshot.items():
        row = _templates(headers).get(doc_type)
        if row is None:
            continue
        client.patch(f"/api/v1/system/print-templates/{row['id']}", json=payload, headers=headers)


# ============================================================
# 打印模板：注册表覆盖与排序
# ============================================================
def test_print_registry_is_covered_by_templates():
    """每类打印单据都必须有模板记录，且都在 DOC_TYPE_ORDER 里归过类。"""
    from app.api.v1.routes.erp import printable_doc_types

    registry = printable_doc_types()
    keys = [key for key, _ in registry]
    assert len(keys) == len(set(keys)), f"打印注册表里有重复的 doc_type：{keys}"

    missing_order = [key for key in keys if key not in DOC_TYPE_ORDER]
    assert not missing_order, (
        f"这些打印类型没在 DOC_TYPE_ORDER 里归类：{missing_order} —— "
        "新增打印时请顺手把它排进模板清单的顺序里"
    )

    rows = _templates(_admin_headers())
    for key, label in registry:
        assert key in rows, f"打印类型 {key} 没有模板记录（启动播种漏了）"
        assert rows[key]["doc_label"] == label, (
            f"{key} 的中文名与注册表不一致：库 {rows[key]['doc_label']!r} / 代码 {label!r}"
        )
        assert rows[key]["registered"] is True
    assert len(rows) == len(keys), "模板表里有注册表之外的孤儿记录"

    # 独立路由的两张单据（对账单 / 余额确认单）也要有模板
    for key, _ in STANDALONE_DOC_TYPES:
        assert key in rows


def test_template_to_spec_returns_original_spec_when_absent():
    """没有模板时不能改动 spec —— 老调用方与未登记类型的打印行为必须不变。"""
    from app.models.print_template import template_to_spec

    class _Stub:
        title = ""
        header_text = ""
        footer_text = ""
        show_company = True
        show_signatures = True

    spec = {"title": "销售开单", "company": "某某公司", "signatures": ["制单"]}
    assert template_to_spec(_Stub(), spec) == spec


# ============================================================
# 打印模板：改动真的进 PDF
# ============================================================
def test_template_choices_reach_the_pdf(template_guard):
    """改模板 → 打一张真单据 → 从 PDF 里抠字验证。"""
    customer = client.post(
        "/api/v1/customers", json={"code": f"CUST-TPL-{_hex()}", "name": "模板验证客户"}
    ).json()
    product = client.post(
        "/api/v1/products",
        json={"sku": f"SKU-TPL-{_hex()}", "name": "模板验证商品", "sale_price": 33.0},
    ).json()
    order = client.post(
        "/api/v1/sales-orders",
        json={
            "customer_id": customer["id"],
            "items": [{"product_id": product["id"], "quantity": 2, "unit_price": 33.0}],
        },
    )
    assert order.status_code == 201, order.text
    order_id = order.json()["id"]

    row = _templates(template_guard)["sales-order"]
    marker = _hex()
    updated = client.patch(
        f"/api/v1/system/print-templates/{row['id']}",
        json={
            "title": f"自定义标题{marker}",
            "header_text": f"抬头第一行{marker}\n抬头第二行{marker}",
            "footer_text": f"模板页脚{marker}",
            "show_signatures": False,
        },
        headers=template_guard,
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["title"] == f"自定义标题{marker}"

    printed = _pdf_text(client.get(f"/api/v1/print/sales-order/{order_id}"))
    assert f"自定义标题{marker}" in printed, "模板标题没进 PDF"
    assert f"抬头第一行{marker}" in printed and f"抬头第二行{marker}" in printed, (
        "抬头附加文字（含多行）没进 PDF"
    )
    assert f"模板页脚{marker}" in printed, "模板页脚没进 PDF"
    # 关掉签章栏之后，"制单"这类字样不该再出现在纸面上
    assert "制单" not in printed, "show_signatures=False 时签章栏仍被打印"
    # 单据自带的明细数据仍然在（改外观不能把内容改没）
    assert "模板验证商品" in printed and "销售开单" not in printed

    # 恢复默认 → 回到单据自带标题、签章栏回来、页脚回到系统参数（此处为空）
    _reset_template(template_guard, "sales-order")
    restored = _pdf_text(client.get(f"/api/v1/print/sales-order/{order_id}"))
    assert "销售开单" in restored
    assert f"自定义标题{marker}" not in restored
    assert "制单" in restored, "恢复默认后签章栏应该回来"
    assert f"模板页脚{marker}" not in restored

    # 收尾：删掉造出来的单据与档案
    assert client.delete(f"/api/v1/sales-orders/{order_id}").status_code in (200, 204)
    assert client.delete(f"/api/v1/products/{product['id']}").status_code in (200, 204)
    assert client.delete(f"/api/v1/customers/{customer['id']}").status_code in (200, 204)


def test_template_footer_beats_system_param(template_guard):
    """页脚三层优先级：模板 > 系统参数 > 默认页码。"""
    param_headers = template_guard
    original = client.get("/api/v1/system/params", headers=param_headers).json()
    original_footer = next(
        item["param_value"]
        for group in original["groups"]
        for item in group["items"]
        if item["param_key"] == "print.footer_text"
    )
    param_marker, template_marker = f"参数页脚{_hex()}", f"模板页脚{_hex()}"
    try:
        client.put(
            "/api/v1/system/params",
            json={"items": [{"param_key": "print.footer_text", "param_value": param_marker}]},
            headers=param_headers,
        )
        row = _templates(param_headers)["purchase-order"]

        # 模板页脚留空 → 用系统参数
        client.patch(
            f"/api/v1/system/print-templates/{row['id']}", json={"footer_text": ""}, headers=param_headers
        )
        preview = _pdf_text(
            client.get(f"/api/v1/system/print-templates/{row['id']}/preview", headers=param_headers)
        )
        assert param_marker in preview, "模板页脚为空时应回落到系统参数"
        assert template_marker not in preview

        # 模板页脚有值 → 压倒系统参数
        client.patch(
            f"/api/v1/system/print-templates/{row['id']}",
            json={"footer_text": template_marker},
            headers=param_headers,
        )
        preview = _pdf_text(
            client.get(f"/api/v1/system/print-templates/{row['id']}/preview", headers=param_headers)
        )
        assert template_marker in preview, "模板页脚没有压过系统参数"
        assert param_marker not in preview
    finally:
        client.put(
            "/api/v1/system/params",
            json={"items": [{"param_key": "print.footer_text", "param_value": original_footer}]},
            headers=param_headers,
        )


def test_template_preview_is_marked_as_sample(template_guard):
    """预览必须一眼看出是样例数据，不能被当成真单据发出去。"""
    row = _templates(template_guard)["sales-order"]
    marker = _hex()
    client.patch(
        f"/api/v1/system/print-templates/{row['id']}",
        json={"header_text": f"预览抬头{marker}"},
        headers=template_guard,
    )
    preview = _pdf_text(
        client.get(f"/api/v1/system/print-templates/{row['id']}/preview", headers=template_guard)
    )
    assert f"预览抬头{marker}" in preview
    assert "样例数据" in preview, "预览里没有标注「样例数据」，容易被误当成真单据"
    assert "示例单号" in preview
    assert "第 1 页 / 共 1 页" in preview


def test_template_update_ignores_non_editable_fields(template_guard):
    """doc_type / doc_label 不在可改字段里：传了也不能改，否则模板会错位到别的单据上。"""
    rows = _templates(template_guard)
    row = rows["sales-order"]
    other = rows["purchase-order"]
    resp = client.patch(
        f"/api/v1/system/print-templates/{row['id']}",
        json={"doc_type": other["doc_type"], "doc_label": "乱改的名字", "title": "合法改动"},
        headers=template_guard,
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["doc_type"] == "sales-order"
    assert body["doc_label"] == "销售开单"
    assert body["title"] == "合法改动"

    assert client.get("/api/v1/system/print-templates/999999/preview", headers=template_guard).status_code == 404
    assert client.patch(
        "/api/v1/system/print-templates/999999", json={"title": "x"}, headers=template_guard
    ).status_code == 404


def test_print_templates_require_admin():
    assert client.get("/api/v1/system/print-templates").status_code == 401

    role = client.post(
        "/api/v1/system/roles",
        json={"code": f"TEST-ROLE-{_hex()}", "name": "测试角色-模板", "permissions": {"all": False, "menus": ["sales"]}},
        headers=_admin_headers(),
    ).json()
    username = f"TEST-USR-{_hex()}"
    user = client.post(
        "/api/v1/system/users",
        json={"username": username, "password": "Pass1234", "role_id": role["id"]},
        headers=_admin_headers(),
    ).json()
    try:
        login = client.post("/api/v1/auth/login", json={"username": username, "password": "Pass1234"})
        headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
        assert client.get("/api/v1/system/print-templates", headers=headers).status_code == 403
        assert client.get("/api/v1/system/logs", headers=headers).status_code == 403
        assert client.delete("/api/v1/system/logs", headers=headers).status_code == 403
    finally:
        admin = _admin_headers()
        client.delete(f"/api/v1/system/users/{user['id']}", headers=admin)
        client.delete(f"/api/v1/system/roles/{role['id']}", headers=admin)


# ============================================================
# 操作日志：动作名翻译（纯函数，不碰库）
# ============================================================
def test_describe_operation():
    assert describe_operation("POST", "/api/v1/customers") == ("新增客户", "customers", None)
    assert describe_operation("PATCH", "/api/v1/system/users/7") == ("修改用户", "users", 7)
    assert describe_operation("DELETE", "/api/v1/sales-orders/12") == ("删除销售单", "sales-orders", 12)
    # 末段语义覆盖：这些 POST 不是"新增"
    assert describe_operation("POST", "/api/v1/system/users/7/password")[0] == "重置密码"
    assert describe_operation("POST", "/api/v1/system/users/7/toggle")[0] == "启用或停用"
    assert describe_operation("POST", "/api/v1/auth/login")[0] == "登录"
    assert describe_operation("POST", "/api/v1/system/print-templates/4/reset")[0] == "恢复默认"
    # 子资源要补注，避免"新增客户"掩盖了改的是明细
    action, target_type, _ = describe_operation("POST", "/api/v1/sales-orders/3/items")
    assert action == "新增销售单（items）" and target_type == "sales-orders"
    # 没登记过的片段原样出现，不隐瞒
    assert "自定义资源" in describe_operation("POST", "/api/v1/自定义资源")[0]
    # 带查询串也能解析
    assert describe_operation("DELETE", "/api/v1/system/logs?before_days=30")[0] == "删除操作日志"
    assert OPERATION_LOG_METHODS == frozenset({"POST", "PUT", "PATCH", "DELETE"})


# ============================================================
# 操作日志：接口行为
# ============================================================
def test_operation_log_records_writes_only():
    """写操作留痕、查询不留痕 —— 日志不能被查询请求淹没。"""
    headers = _admin_headers()
    before = client.get("/api/v1/system/logs?page_size=1", headers=headers).json()["total"]

    # 一批查询请求：一条都不该记
    client.get("/api/v1/customers", headers=headers)
    client.get("/api/v1/system/params", headers=headers)
    client.get("/api/v1/system/me/permissions", headers=headers)
    assert client.get("/api/v1/system/logs?page_size=1", headers=headers).json()["total"] == before, (
        "GET 请求被写进了操作日志"
    )

    code = f"CUST-TPL-{_hex()}"
    created = client.post("/api/v1/customers", json={"code": code, "name": "日志验证客户"}, headers=headers)
    assert created.status_code == 201, created.text
    customer_id = created.json()["id"]

    page = client.get(f"/api/v1/system/logs?keyword={code[:12]}", headers=headers).json()
    # keyword 匹配的是动作名 / 路径 / 用户名，路径里没有编码，所以这里按 target 找
    page = client.get("/api/v1/system/logs?page_size=5", headers=headers).json()
    top = page["items"][0]
    assert top["action"] == "新增客户", top
    assert top["method"] == "POST" and top["status_code"] == 201
    assert top["username"] == "admin" and top["role"] == "admin"
    assert top["target_type"] == "customers"
    # 新增操作的对象 id 在响应体里，中间件读不到 —— target_id 为 None 是刻意的取舍
    assert top["target_id"] is None
    assert top["path"] == "/api/v1/customers"
    assert top["duration_ms"] >= 0 and top["ip"]

    client.delete(f"/api/v1/customers/{customer_id}", headers=headers)
    page = client.get("/api/v1/system/logs?page_size=5", headers=headers).json()
    assert page["items"][0]["action"] == "删除客户"
    assert page["items"][0]["method"] == "DELETE"
    # 改 / 删这类 url 里带 id 的操作，target_id 是准的
    assert page["items"][0]["target_id"] == customer_id


def test_login_attempts_are_logged_with_username():
    """失败的登录尝试也要记下是谁在试 —— 否则日志里猜不出账号爆破的痕迹。"""
    headers = _admin_headers()
    client.post("/api/v1/auth/login", json={"username": "admin", "password": "definitely-wrong"})

    page = client.get("/api/v1/system/logs?keyword=登录", headers=headers).json()
    fails = [row for row in page["items"] if row["status_code"] == 401]
    assert fails, "登录失败没有被记录"
    assert fails[0]["username"] == "admin", "登录日志没记下尝试的用户名"
    assert fails[0]["path"] == "/api/v1/auth/login"


def test_operation_log_filters_and_pagination():
    headers = _admin_headers()
    # 制造几条可辨识的记录
    for index in range(3):
        client.post(
            "/api/v1/customers",
            json={"code": f"CUST-TPL-{_hex()}", "name": f"过滤验证客户{index}"},
            headers=headers,
        )

    page = client.get("/api/v1/system/logs?page_size=2&page=1", headers=headers).json()
    assert page["page"] == 1 and len(page["items"]) == 2
    assert page["pages"] >= 1 and page["total"] >= 3
    assert "POST" in page["methods"] and "admin" in page["users"]

    # 翻页不重复
    second = client.get("/api/v1/system/logs?page_size=2&page=2", headers=headers).json()
    assert {row["id"] for row in second["items"]}.isdisjoint({row["id"] for row in page["items"]})

    # 方法筛选
    only_delete = client.get("/api/v1/system/logs?method=delete&page_size=50", headers=headers).json()
    assert all(row["method"] == "DELETE" for row in only_delete["items"])

    # 关键词筛不到就为空
    none = client.get("/api/v1/system/logs?keyword=一定不存在的关键词XYZ", headers=headers).json()
    assert none["total"] == 0 and none["items"] == []

    # 日期筛选：解析不了的日期不报错，只是条件作废
    bad = client.get("/api/v1/system/logs?start=not-a-date&end=2026-13-45", headers=headers)
    assert bad.status_code == 200 and bad.json()["total"] > 0

    # 清理测试造的客户档案
    cleanup = client.get("/api/v1/system/logs?page_size=200", headers=headers).json()
    for row in cleanup["items"]:
        if row["action"] == "新增客户" and row["target_id"]:
            client.delete(f"/api/v1/customers/{row['target_id']}", headers=headers)


def test_clearing_logs_keeps_its_own_record():
    """清理动作本身必须留痕 —— 否则日志可以被无声抹掉。

    ⚠️ 这条测试会调用**全库范围**的 `DELETE /system/logs`，而测试连的是正式库。
    日志是"真发生过的操作"的留痕，删掉就是伪造历史 —— 所以先快照落盘、
    断言完在 `finally` 里还原，确认无误才删快照文件（工具见 tests/prod_snapshot.py）。
    """
    from prod_snapshot import ProdSnapshot

    from app.db.session import SessionLocal
    from app.models.operation_log import OperationLog

    headers = _admin_headers()

    def snapshot_rows() -> list[dict]:
        db = SessionLocal()
        try:
            return [
                {
                    "user_id": row.user_id,
                    "username": row.username,
                    "role": row.role,
                    "method": row.method,
                    "path": row.path,
                    "action": row.action,
                    "target_type": row.target_type,
                    "target_id": row.target_id,
                    "status_code": row.status_code,
                    "duration_ms": row.duration_ms,
                    "ip": row.ip,
                    "user_agent": row.user_agent,
                    "detail": row.detail,
                    "created_at": row.created_at,
                }
                for row in db.query(OperationLog).order_by(OperationLog.id).all()
            ]
        finally:
            db.close()

    guard = ProdSnapshot("operation-logs")
    guard.save(snapshot_rows())
    baseline = len(guard.rows)
    try:
        resp = client.delete("/api/v1/system/logs", headers=headers)
        assert resp.status_code == 200, resp.text
        assert resp.json()["deleted"] >= 1

        page = client.get("/api/v1/system/logs", headers=headers).json()
        assert page["total"] == 1, f"清空后应该只剩这次清理动作自己，实际 {page['total']} 条"
        assert page["items"][0]["action"] == "删除操作日志"
        assert page["items"][0]["path"] == "/api/v1/system/logs"

        # 按天数清理：刚写的记录不该被 N 天前这个条件删掉
        keep = client.delete("/api/v1/system/logs?before_days=7", headers=headers)
        assert keep.status_code == 200 and keep.json()["deleted"] == 0
        assert client.get("/api/v1/system/logs", headers=headers).json()["total"] == 2
    finally:
        def restore(rows: list[dict]) -> int:
            db = SessionLocal()
            try:
                # 清掉本轮测试残留 + 清空动作自己那条，再把快照整份写回
                db.query(OperationLog).delete(synchronize_session=False)
                for row in rows:
                    db.add(OperationLog(**row))
                db.commit()
                return len(rows)
            finally:
                db.close()

        written = guard.restore(restore)
        back = client.get("/api/v1/system/logs?page_size=1", headers=headers).json()["total"]
        assert back == baseline, (
            f"日志还原失败：快照 {baseline} 条，实际只剩 {back} 条（快照文件保留在 {guard.path}）"
        )
        assert written == baseline
        guard.done()


def test_operation_log_prunes_oldest():
    """表的自我修剪：在内存库上跑，不动真库里的历史日志。"""
    engine = create_engine("sqlite://")
    OperationLog.__table__.create(engine)
    db = sessionmaker(bind=engine)()
    try:
        for index in range(8):
            record_operation(
                db,
                method="POST",
                path=f"/api/v1/customers/{index}",
                status_code=201,
                duration_ms=1.0,
                username="tester",
            )
        assert db.query(OperationLog).count() == 8
        assert prune_operation_logs(db, limit=5) == 3
        db.commit()
        remaining = db.query(OperationLog).order_by(OperationLog.id).all()
        assert len(remaining) == 5
        # 留下的必须是最新的 5 条
        assert remaining[-1].path == "/api/v1/customers/7"
        assert remaining[0].path == "/api/v1/customers/3"
        # 没超上限时什么都不删
        assert prune_operation_logs(db, limit=5) == 0
    finally:
        db.close()
        engine.dispose()

    assert MAX_OPERATION_LOGS >= 1000, "保留上限太小会让日志失去追溯价值"


def test_log_endpoints_require_admin_but_writes_are_still_recorded():
    """未认证 / 非管理员被拒也一样留痕（403 也要记），否则越权尝试看不见。"""
    headers = _admin_headers()
    # 刻意**不**清空日志表：那会抹掉用户真实的操作留痕（见上一条测试的说明）。
    # 只需要看"刚写进去的最新一条"，按 id 倒序取第一行即可。
    assert client.post("/api/v1/system/roles", json={"code": "X-1", "name": "越权"}).status_code == 401

    page = client.get("/api/v1/system/logs?page_size=1", headers=headers).json()
    assert page["total"] >= 1
    assert page["items"][0]["status_code"] == 401
    assert page["items"][0]["path"] == "/api/v1/system/roles"
    assert page["items"][0]["username"] == "", "未认证请求不该凭空记上用户名"


# ============================================================
# 前端挂载点
# ============================================================
def test_frontend_pages_and_menu_are_wired():
    """模板页 / 日志页必须真的挂上，菜单也不能还挂着"待建"。"""
    from pathlib import Path

    root = Path(__file__).resolve().parent.parent
    source = (root / "frontend" / "src" / "App.jsx").read_text(encoding="utf-8")
    styles = (root / "frontend" / "src" / "styles.css").read_text(encoding="utf-8")

    for key in ("print-templates", "logs"):
        assert f"{{ key: '{key}', label:" in source, f"菜单项 {key} 不见了"
        assert f"selectedTab === '{key}'" in source, f"{key} 页面没有渲染分支"
        assert f"{{ key: '{key}', label: " in source.split("// 扁平视图")[0], f"{key} 不在 menuGroups 里"
        # 菜单项后面不该再跟 todo: true
        line = next(l for l in source.splitlines() if f"{{ key: '{key}', label:" in l)
        assert "todo: true" not in line, f"{key} 菜单还标着「待建」"

    assert "system/print-templates" in source and "system/logs" in source
    assert "previewPrintTemplate" in source and "refreshOperationLogs" in source
    assert ".pdf-preview" in styles and ".log-filters" in styles
