"""路由鉴权审计（P0-1「方案 B」的施工地图 + 收口后的门禁，2026-10-26）。

背景
----
第一版这个脚本是"施工地图"：把 `app.main:app` 的路由表走一遍，逐个依赖树找
`get_current_user` / `require_roles`，列出**没有身份校验**的端点。当时的结论是
**320 个 /api/v1 端点里 318 个裸奔** —— 也正因为如此，逐路由补 `Depends(...)` 这条路
根本走不通（漏一个不报错，以后新加的路由照样默认裸奔）。

方案 B 换了个方向：**默认拒绝，白名单放行**（`app/core/auth_gate.py`）。所以本脚本的
职责也跟着变了 —— 它现在守的是**网关本身**：

  · 网关中间件还在不在？
  · `auth_mode` 有没有被人偷偷改成 off？
  · 白名单有没有被加宽（多放一个路径/前缀就等于多开后门）？

判定口径
--------
  · 路由级：依赖树里出现 `get_current_user` 或 `require_roles.<locals>.dependency`
    → 记"路由级已鉴权"（这是**纵深防御**，不再是唯一防线）；
  · 网关级：`/api/v1` 下除白名单外一律由中间件拦（含 401/403 与账号停用校验）。

用法
----
    .venv/Scripts/python.exe scripts/audit_auth_routes.py            # 摘要
    .venv/Scripts/python.exe scripts/audit_auth_routes.py -v         # 逐条列出路由级未加校验的端点
    .venv/Scripts/python.exe scripts/audit_auth_routes.py --strict   # 门禁：网关/白名单异常则 exit 1
"""

from __future__ import annotations

import sys
from collections import defaultdict
from pathlib import Path

# 允许 `python scripts/audit_auth_routes.py` 直接跑：`sys.path[0]` 是 scripts/，不是项目根，
# 直接 import app.* 会 ModuleNotFoundError。与 scripts/clean_test_data.py 同一套写法。
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fastapi.routing import APIRoute

from app.api.v1.routes.auth import get_current_user
from app.core import auth_gate
from app.core.config import settings
from app.main import app

# 允许出现在网关白名单里的路径。**改动这里等于改安全边界**，必须同步改 auth_gate.py
# 并在提交说明里讲清理由。
EXPECTED_PUBLIC_PATHS = {
    "/api/v1/health",  # 探活：桌面壳/负载均衡轮询，必须无凭证
    "/api/v1/auth/login",  # 登录本身（要发 token，自然不能先要 token）
    "/api/v1/auth/register",  # 路由自己回 403 中文说明（默认已关闭）
}
EXPECTED_PUBLIC_PREFIXES = {
    # 商品图：前端 `<img src>` 直接引，浏览器带不了 Authorization，拦了就是整页缩略图全空
    "/api/v1/uploads/products/",
}


def _is_auth_callable(call) -> bool:
    if call is get_current_user:
        return True
    return "require_roles.<locals>" in getattr(call, "__qualname__", "")


def _collect_auth(dependant, depth: int = 0) -> bool:
    """递归依赖树，找身份校验依赖。"""
    for sub in dependant.dependencies:
        if _is_auth_callable(sub.call):
            return True
        if _collect_auth(sub, depth + 1):
            return True
    return False


def _api_routes() -> list[APIRoute]:
    return [
        route
        for route in app.routes
        if isinstance(route, APIRoute) and route.path.startswith("/api/v1")
    ]


def _gate_installed() -> bool:
    """网关有没有真的挂到 middleware 栈上（挂漏了就是全局裸奔）。"""
    for middleware in app.user_middleware:
        dispatch = (getattr(middleware, "kwargs", None) or {}).get("dispatch")
        if dispatch is auth_gate.auth_gate_middleware:
            return True
    return False


def main() -> int:
    verbose = "-v" in sys.argv
    strict = "--strict" in sys.argv

    routes = _api_routes()
    guarded: list[APIRoute] = []
    unguarded: list[tuple[str, str]] = []
    for route in routes:
        if _collect_auth(route.dependant):
            guarded.append(route)
            continue
        for method in sorted(route.methods or []):
            if method in {"HEAD", "OPTIONS"}:
                continue
            unguarded.append((method, route.path))

    buckets: dict[str, list[tuple[str, str]]] = defaultdict(list)
    for method, path in unguarded:
        parts = path.split("/")
        group = parts[3] if len(parts) > 4 else path
        buckets[group].append((method, path))

    installed = _gate_installed()
    mode = str(settings.auth_mode or "").strip().lower()
    enforced = auth_gate.auth_enforced()

    print(f"[AUTH_AUDIT] /api/v1 端点 {len(routes)} 个（方法计 {len(unguarded) + sum(len(r.methods or ()) for r in guarded)} 个）")
    print(f"[AUTH_AUDIT] 路由级已鉴权 {len(guarded)} 个 / 路由级未加校验 {len(unguarded)} 个（方法计）")
    print(f"[AUTH_AUDIT] 网关中间件: {'已安装' if installed else '[NG] 未安装'}；auth_mode={mode}（{'拒绝匿名' if enforced else '放行匿名'}）")

    if verbose:
        print("\n[AUTH_AUDIT] 以下端点没有路由级校验，靠网关兜底（按分组）：")
        for group in sorted(buckets):
            print(f"\n  -- {group} ({len(buckets[group])})")
            for method, path in sorted(buckets[group], key=lambda r: r[1]):
                mark = "  (网关白名单)" if auth_gate.is_public_path(path) else ""
                print(f"     {method:6} {path:60}{mark}")

    problems: list[str] = []
    if not installed:
        problems.append("网关中间件没挂上（/api/v1 将整体裸奔）")
    if not enforced:
        problems.append(f"auth_mode={mode}：当前放行匿名请求")
    extra_paths = set(auth_gate.PUBLIC_PATHS) - EXPECTED_PUBLIC_PATHS
    if extra_paths:
        problems.append(f"白名单被加宽（多出路径）: {sorted(extra_paths)}")
    missing_paths = EXPECTED_PUBLIC_PATHS - set(auth_gate.PUBLIC_PATHS)
    if missing_paths:
        problems.append(f"白名单缺项（登录/探活会被拦）: {sorted(missing_paths)}")
    extra_prefixes = set(auth_gate.PUBLIC_PREFIXES) - EXPECTED_PUBLIC_PREFIXES
    if extra_prefixes:
        problems.append(f"白名单被加宽（多出前缀）: {sorted(extra_prefixes)}")

    if problems:
        print("\n[AUTH_AUDIT] [NG] 鉴权收口被破坏：")
        for item in problems:
            print(f"     - {item}")
        if strict:
            return 1
    else:
        print("[AUTH_AUDIT] [OK] 收口完成：/api/v1 默认拒绝匿名，白名单与约定一致")

    covered = sum(1 for m, p in unguarded if not auth_gate.is_public_path(p))
    print(f"[AUTH_AUDIT] 网关兜底覆盖 {covered} 个未加路由级校验的方法级端点")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

