# -*- coding: utf-8 -*-
"""弹窗「所属分类」下拉的数据形状（2026-10-21 回归）。

事故：`loadPartnerCategoryOptions` 把 `/customer-categories` 的树摊平成
`[{value, label}]`（v75 的旧形状），而弹窗 v76 已换成 `<ErpTreeSelect nodes={…}>`，
组件按 `node.id` / `node.name` 取值。结果：

  · 回显找不到 id → 兜底显示原始数字（用户看到「330」而不是「其他客户 / 储能」）；
  · 树渲染读不到 name → 一个节点都画不出来，只剩组件自带的「未分类」。

这两个症状都是"数据形状"造成的，不是组件坏了 —— 所以这里钉住的是**形状**：
后端返回的树必须原样传给 `ErpTreeSelect`，不许再摊平、不许再拼路径前缀。
"""

from __future__ import annotations

from pathlib import Path

import pytest

APP = Path(__file__).resolve().parent.parent / "frontend" / "src" / "App.jsx"


def _loader_body() -> str:
    """截出 loadPartnerCategoryOptions 的函数体（从定义到下一个顶层 const/function）。"""
    source = APP.read_text(encoding="utf-8")
    start = source.index("const loadPartnerCategoryOptions = async")
    rest = source[start:]
    end = rest.index("useEffect(", 0) if "useEffect(" in rest[:4000] else len(rest)
    return rest[:end]


def test_分类选项把后端树原样传下去():
    body = _loader_body()
    assert "Array.isArray(data) ? data : []" in body, (
        "分类选项必须原样使用后端返回的树（{id,name,children}）；"
        "一旦摊平成 {value,label}，ErpTreeSelect 既回显不出名称、也渲染不出节点"
    )


def test_不许再把树摊平成_value_label():
    body = _loader_body()
    # 这两样是 v75 扁平形状的指纹：push({ value... }) 与手动拼 " / " 路径
    assert "value: String(node.id)" not in body, "又在摊平成 {value,label} 了"
    assert "`${prefix} / ${node.name}`" not in body, "路径前缀交给 ErpTreeSelect 自己拼，别在这里拼"


@pytest.mark.parametrize("kind", ["customer", "supplier"])
def test_弹窗把选项当成_nodes_传(kind: str):
    """PartnerModal 里必须是 `nodes={categoryOptions}`，不是 options/items。"""
    modal = (
        Path(__file__).resolve().parent.parent
        / "frontend"
        / "src"
        / "components"
        / "partners"
        / "PartnerModal.jsx"
    ).read_text(encoding="utf-8")
    assert "nodes={categoryOptions}" in modal


def test_组件默认按_id_与_name_取值():
    """ErpTreeSelect 的默认取值口径 —— 与后端树字段一一对应，改这里要同步后端。"""
    comp = (
        Path(__file__).resolve().parent.parent
        / "frontend"
        / "src"
        / "components"
        / "ui"
        / "ErpTreeSelect.jsx"
    ).read_text(encoding="utf-8")
    assert "const defaultGetValue = (node) => (node ? node.id : '');" in comp
    assert "const defaultGetLabel = (node) => (node ? node.name : '');" in comp
    assert "Array.isArray(node.children)" in comp
