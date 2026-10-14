import io
import uuid

import pytest
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def _make_invoice_png() -> bytes | None:
    """生成一张含发票要素的中文模拟发票图片；无中文字体时返回 None。"""
    try:
        from PIL import Image, ImageDraw, ImageFont
    except ImportError:
        return None
    try:
        font = ImageFont.truetype(r"C:\Windows\Fonts\simhei.ttf", 30)
    except OSError:
        return None
    lines = [
        "增值税专用发票",
        "发票号码: INV-2026-0001",
        "开票日期: 2026-09-24",
        "购买方",
        "名称: 广州测试采购有限公司",
        "纳税人识别号: 91440101MA5ABCDE1X",
        "销售方",
        "名称: 测试商贸有限公司",
        "纳税人识别号: 91310000MA1FGHIJ2Y",
        "*办公用品*打印纸A4 2 50.00 100.00",
        "*办公用品*墨盒 1 1134.56 1134.56",
        "合计金额: 1234.56",
        "税率: 13%",
        "税额: 160.18",
    ]
    img = Image.new("RGB", (1100, 820), "white")
    draw = ImageDraw.Draw(img)
    for index, text in enumerate(lines):
        draw.text((40, 40 + index * 54), text, font=font, fill="black")
    buffer = io.BytesIO()
    img.save(buffer, format="PNG")
    return buffer.getvalue()


def test_local_invoice_ocr_extracts_real_fields():
    """真实图片端到端：识别引擎 + 双方信息 + 明细 + 字段提取都要正确。"""
    png = _make_invoice_png()
    if png is None:
        pytest.skip("本机无中文字体，跳过真实 OCR 测试")
    response = client.post(
        "/api/v1/invoices/ocr",
        files={"file": ("invoice.png", png, "image/png")},
    )
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["provider"] == "rapidocr"
    assert "INV-2026-0001" in (payload.get("invoice_no") or "")
    assert payload.get("invoice_date") == "2026-09-24"
    assert payload.get("total_amount") == 1234.56
    # 双方信息
    assert payload.get("buyer_name") and "测试采购" in payload["buyer_name"]
    assert payload.get("seller_name") and "测试商贸" in payload["seller_name"]
    assert "91440101" in (payload.get("buyer_tax_no") or "")
    assert "91310000" in (payload.get("seller_tax_no") or "")
    # 发票类型 / 税率 / 税额 / 不含税额
    assert payload.get("invoice_type") == "专票"
    assert payload.get("tax_rate") == 13.0
    assert payload.get("tax_amount") == 160.18
    assert payload.get("excl_tax_amount") == 1074.38
    # 产品明细：两条且品名正确
    items = payload.get("items") or []
    assert len(items) == 2
    assert any("打印纸" in str(item.get("item_name")) for item in items)
    assert any("墨盒" in str(item.get("item_name")) for item in items)
    assert abs(sum(item["amount"] for item in items) - 1234.56) < 0.01


def test_invoice_item_parser_handles_spaced_and_glued_lines():
    """明细解析：空格分隔列 与 OCR 数字粘连 两种格式都要能拆出 数量/单价/金额。"""
    from app.api.v1.routes.erp import _extract_invoice_items

    spaced = _extract_invoice_items(
        ["*办公用品*打印纸A4 2 50.00 100.00", "*办公用品*墨盒 1 1134.56 1134.56"],
        1234.56,
    )
    assert len(spaced) == 2
    assert spaced[0]["item_name"] == "打印纸A4"
    assert spaced[0]["quantity"] == 2 and spaced[0]["unit_price"] == 50.0 and spaced[0]["amount"] == 100.0

    glued = _extract_invoice_items(
        ["*办公用品*打印纸A4250.00100.00", "*办公用品*墨盒11134.561134.56"],
        1234.56,
    )
    assert len(glued) == 2
    assert glued[0]["item_name"] == "打印纸A4"
    assert glued[0]["quantity"] == 2 and glued[0]["unit_price"] == 50.0 and glued[0]["amount"] == 100.0
    assert glued[1]["item_name"] == "墨盒"
    assert glued[1]["quantity"] == 1 and glued[1]["unit_price"] == 1134.56 and glued[1]["amount"] == 1134.56


def test_local_invoice_ocr_empty_image_falls_back_gracefully():
    """空白图片：不应报错，应返回 200 并标记 fallback。"""
    sample_png = (
        b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\nIDATx\x9cc``\x00\x00\x00\x02\x00\x01\xe5\x27\xd8\xcf\x00\x00\x00\x00IEND\xaeB`\x82"
    )
    response = client.post(
        "/api/v1/invoices/ocr",
        files={"file": ("blank.png", sample_png, "image/png")},
    )
    assert response.status_code == 200, response.text
    assert response.json()["provider"] == "fallback"


def test_bom_tree_endpoint_creates_nested_structure():
    root_sku = f"BOM-ROOT-{uuid.uuid4().hex[:8]}"
    child_sku = f"BOM-CHILD-{uuid.uuid4().hex[:8]}"
    product_root = client.post(
        "/api/v1/products",
        json={
            "sku": root_sku,
            "name": "主机产品",
            "category": "电子设备",
            "unit": "台",
            "purchase_price": 50,
            "sale_price": 120,
        },
    )
    assert product_root.status_code == 201, product_root.text
    product_child = client.post(
        "/api/v1/products",
        json={
            "sku": child_sku,
            "name": "CPU模块",
            "category": "电子元器件",
            "unit": "颗",
            "purchase_price": 20,
            "sale_price": 40,
        },
    )
    assert product_child.status_code == 201, product_child.text

    root_payload = {
        "product_id": product_root.json()["id"],
        "component_product_id": product_child.json()["id"],
        "name": "主机装配",
        "code": root_sku,
        "quantity": 1,
        "unit_cost": 60,
        "level": 0,
        "bom_type": "assembly",
        "parent_id": None,
        "description": "主机装配层",
    }
    root_response = client.post("/api/v1/production-boms", json=root_payload)
    assert root_response.status_code == 201, root_response.text
    root_data = root_response.json()

    child_payload = {
        "product_id": product_root.json()["id"],
        "component_product_id": product_child.json()["id"],
        "name": "CPU子件",
        "code": child_sku,
        "quantity": 2,
        "unit_cost": 20,
        "level": 1,
        "bom_type": "component",
        "parent_id": root_data["id"],
        "description": "CPU 子件",
    }
    child_response = client.post("/api/v1/production-boms", json=child_payload)
    assert child_response.status_code == 201, child_response.text

    tree_response = client.get("/api/v1/production-boms/tree")
    assert tree_response.status_code == 200, tree_response.text
    payload = tree_response.json()
    assert isinstance(payload, list)
    assert any(node.get("code") == root_sku for node in payload)


def test_invoice_persistence_summary_sync_and_agent_analysis(monkeypatch):
    # 本用例验证「未配置 Key 时走本地规则兜底」，因此显式清掉环境变量，
    # 否则本机若设有 DEEPSEEK_API_KEY 会真调线上接口，结果不稳定。
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    """发票全链路：保存 → 列表 → 汇总 → 财务同步（幂等）→ 智能体分析兜底 → 抵扣标记。"""
    invoice_no = f"TEST-{uuid.uuid4().hex[:10].upper()}"
    create_response = client.post(
        "/api/v1/invoices",
        json={
            "invoice_no": invoice_no,
            "invoice_type": "专票",
            "issue_date": "2026-09-24",
            "counterparty_name": "测试商贸有限公司",
            "invoice_code": "044032600111",
            "total_amount": 1000.0,
            "tax_rate": 13.0,
            "tax_amount": 115.04,
            "excl_tax_amount": 884.96,
            "deducted": False,
            "category": "采购",
            "seller_name": "测试商贸有限公司",
            "items": [{"item_name": "打印纸A4", "quantity": 2, "unit_price": 50.0, "amount": 100.0}],
        },
    )
    assert create_response.status_code == 201, create_response.text
    invoice_id = create_response.json()["id"]

    # 重复上传：旧记录被删除，新解析结果替换入库（库中只保留一条）
    duplicate_response = client.post(
        "/api/v1/invoices",
        json={"invoice_no": invoice_no, "invoice_type": "专票", "total_amount": 1000.0},
    )
    assert duplicate_response.status_code == 201
    assert duplicate_response.json()["id"] != invoice_id
    invoice_id = duplicate_response.json()["id"]  # 后续步骤改用替换后的新记录

    # 列表可查到
    list_response = client.get("/api/v1/invoices")
    assert list_response.status_code == 200
    assert any(item["invoice_no"] == invoice_no for item in list_response.json())

    # 汇总：未抵扣专票计入未抵扣金额
    summary_response = client.get("/api/v1/invoices/summary")
    assert summary_response.status_code == 200
    summary = summary_response.json()
    assert summary["total_count"] >= 1
    assert summary["deduction"]["undeducted_count"] >= 1
    assert summary["deduction"]["undeducted_amount"] >= 1000.0
    assert "2026-09" in summary["monthly"]

    # 财务同步：第一次创建流水，第二次幂等为 0
    sync_response = client.post("/api/v1/invoices/sync-finance")
    assert sync_response.status_code == 200
    assert sync_response.json()["created"] >= 1
    sync_again = client.post("/api/v1/invoices/sync-finance")
    assert sync_again.status_code == 200
    assert sync_again.json()["created"] == 0

    # 智能体分析：未配置 Key 时本地规则兜底，且包含抵扣提醒
    analysis_response = client.post(
        "/api/v1/invoices/agent-analysis",
        json={"summary": summary},
    )
    assert analysis_response.status_code == 200
    analysis = analysis_response.json()
    assert analysis["provider"] == "local"
    assert "发票" in analysis["analysis"]
    assert "尚未抵扣" in analysis["analysis"]

    # 抵扣标记：PATCH 后汇总里的未抵扣金额减少
    patch_response = client.patch(
        f"/api/v1/invoices/{invoice_id}",
        json={"deducted": True},
    )
    assert patch_response.status_code == 200
    assert patch_response.json()["deducted"] is True
    summary_after = client.get("/api/v1/invoices/summary").json()
    assert summary_after["deduction"]["undeducted_amount"] <= summary["deduction"]["undeducted_amount"] - 1000.0

    # 清理测试发票
    delete_response = client.delete(f"/api/v1/invoices/{invoice_id}")
    assert delete_response.status_code == 204
