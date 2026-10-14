"""正则健壮性测试：换行/空格拆词、全角冒号、全半角混用、（小写）金额优先。"""

from app.api.v1.routes.erp import _extract_invoice_summary


def test_regex_tolerates_interference():
    """字段名被换行/空格拆开（金\\n额）、全角冒号、全角数字混用都能提取。"""
    result = _extract_invoice_summary(
        [
            "增值税普通发票",
            "发票号\n码：１２３４５６７８",  # 字段名被换行拆开 + 全角冒号 + 全角数字
            "开票日 期：２０２６-０９-２５",  # 字段名被空格拆开 + 全角日期
            "合计金\n额: ８８８.００",  # 金额关键词被换行拆开 + 全角数字
        ]
    )
    assert result["invoice_no"] == "12345678"
    assert result["invoice_date"] == "2026-09-25"
    assert result["total_amount"] == 888.0


def test_regex_prefers_small_amount():
    """发票常见"价税合计(大写)…(小写)…"格式：优先取小写数字，不取大写汉字。"""
    result = _extract_invoice_summary(
        [
            "价税合计（大写）壹佰贰拾叁元（小写）￥１２３.４５",
            "发票号码：20000009",
        ]
    )
    assert result["total_amount"] == 123.45
    assert result["invoice_no"] == "20000009"
