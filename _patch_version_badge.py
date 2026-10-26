"""一次性补丁：把版本条改成 `v52 · 2026-10-19 17:15 · 寨卡`（CRLF 安全）。

用法： .venv\\Scripts\\python.exe _patch_version_badge.py
跑完即删（含自校验：每处必须唯一命中，否则整体中止不写盘）。
"""
from pathlib import Path

ROOT = Path(r"E:\AI\ERP软件")


def patch(rel, pairs):
    path = ROOT / rel
    text = path.read_bytes().decode("utf-8")
    is_crlf = "\r\n" in text
    original_len = len(text)
    for idx, (old, new) in enumerate(pairs, 1):
        target = old.replace("\n", "\r\n") if is_crlf else old
        count = text.count(target)
        if count != 1:
            raise SystemExit(f"[FAIL] {rel} 第 {idx} 处命中 {count} 次（要求恰好 1 次），已中止，未写盘")
        replacement = new.replace("\n", "\r\n") if is_crlf else new
        text = text.replace(target, replacement, 1)
    path.write_bytes(text.encode("utf-8"))
    after = path.read_bytes().decode("utf-8")
    assert ("\r\n" in after) == is_crlf, f"{rel} 换行符被改坏了"
    print(f"[OK] {rel:32s} {len(pairs)} 处  CRLF={is_crlf}  {original_len} -> {len(after)} 字符")


# ---------------------------------------------------------------- appLib.js
APPLIB_OLD = """// ⚠️ 每次发布仍要 bump public/sw.js 的 CACHE_VERSION，否则老壳缓存里还是旧号。
// ---------------------------------------------------------------------------
export const APP_VERSION =
  typeof __APP_VERSION__ === 'undefined' ? 'dev' : __APP_VERSION__;
export const APP_BUILD =
  typeof __APP_BUILD__ === 'undefined' ? 'dev' : __APP_BUILD__;
export const APP_BUILD_AT =
  typeof __APP_BUILD_AT__ === 'undefined' ? 'dev' : __APP_BUILD_AT__;
export const APP_HASH = typeof __APP_HASH__ === 'undefined' ? 'nogit' : __APP_HASH__;
// 页面上的短标：v1.0.0 · 20261018-2110（不把提交哈希塞进来，标题栏太挤）
export const APP_VERSION_LABEL = `v${APP_VERSION} · ${APP_BUILD}`;"""

APPLIB_NEW = """// ⚠️ 缓存代号 CACHE_VERSION 自 2026-10-19 起由 vite.config.js **构建时自动 +1**，
//    不必再手改 public/sw.js（手改反而会和 dist 里那份对不上，等于没换壳）。
// ---------------------------------------------------------------------------
export const APP_VERSION =
  typeof __APP_VERSION__ === 'undefined' ? 'dev' : __APP_VERSION__;
// 缓存代号：v52 这种。决定浏览器要不要换掉 Service Worker 外壳，每次 build 自动 +1。
export const APP_CACHE =
  typeof __APP_CACHE__ === 'undefined' ? 'v0' : __APP_CACHE__;
// 品牌名：版本条最后一段。构建时注入，换品牌改 vite.config.js 的 BRAND 或设 ERP_BRAND
export const APP_BRAND =
  typeof __APP_BRAND__ === 'undefined' ? '寨卡' : __APP_BRAND__;
export const APP_BUILD =
  typeof __APP_BUILD__ === 'undefined' ? 'dev' : __APP_BUILD__;
export const APP_BUILD_AT =
  typeof __APP_BUILD_AT__ === 'undefined' ? 'dev' : __APP_BUILD_AT__;
export const APP_HASH = typeof __APP_HASH__ === 'undefined' ? 'nogit' : __APP_HASH__;
// 页面上的短标：v52 · 2026-10-19 17:15 · 寨卡
//   缓存代号 · 构建时间 · 品牌 —— 三段都可肉眼核对，不塞提交哈希（标题栏太挤）
export const APP_VERSION_LABEL = `${APP_CACHE} · ${APP_BUILD_AT} · ${APP_BRAND}`;"""

# ---------------------------------------------------------------- App.jsx
APPJSX_IMPORT_OLD = "import { API_BASE, APP_VERSION_LABEL, APP_BUILD_AT, APP_HASH,"
APPJSX_IMPORT_NEW = "import { API_BASE, APP_VERSION_LABEL, APP_VERSION, APP_CACHE, APP_BUILD_AT, APP_HASH,"

APPJSX_BADGE_OLD = """          {/* 版本号（2026-10-18）：构建时由 vite.config.js 注入，每次 build 自动变。
              鼠标悬停能看到完整构建时间与提交哈希，排查"用户看到旧页面"时很有用。 */}
          <span
            className="brand-version"
            data-app-version={APP_VERSION_LABEL}
            title={`构建时间 ${APP_BUILD_AT} ｜ 提交 ${APP_HASH}`}
          >"""

APPJSX_BADGE_NEW = """          {/* 版本条（2026-10-19 全自动）：v52 · 2026-10-19 17:15 · 寨卡
              三段全部由 vite.config.js 在构建时注入 —— 缓存代号自动 +1（顺带换掉
              Service Worker 外壳）、时间就是这次 npm run build 的时间，
              不需要再手改任何文件。悬停补上业务版本与提交哈希供排查。 */}
          <span
            className="brand-version"
            data-app-version={APP_VERSION_LABEL}
            data-app-cache={APP_CACHE}
            title={`业务版本 v${APP_VERSION} ｜ 缓存 ${APP_CACHE} ｜ 构建 ${APP_BUILD_AT} ｜ 提交 ${APP_HASH}`}
          >"""

# ---------------------------------------------------------------- app/main.py
MAIN_OLD = """    app = FastAPI(
        title="ERP 核心系统",
        version="1.0.0",
        description="本地 ERP 基础版本，支持采购、销售、库存、财务和报表基础能力。",
    )"""

MAIN_NEW = """    # 版本标识与前端同源：读 frontend/dist/version.json（由 vite.config.js 在 build 时写，
    # 打包后被 PyInstaller 一起塞进 _internal/frontend/dist，路径走 _MEIPASS）。
    # 读不到就退回业务版本号 —— 版本号是小事，为此让服务起不来才是大事。
    from app.core.build_info import build_info, version_label

    _build = build_info()
    app = FastAPI(
        title="ERP 核心系统",
        version=f"{_build['app_version']} ({_build['cache']})",
        description=(
            "本地 ERP 基础版本，支持采购、销售、库存、财务和报表基础能力。"
            f"<br>构建标识：{version_label()}"
        ),
    )"""


if __name__ == "__main__":
    patch("frontend/src/lib/appLib.js", [(APPLIB_OLD, APPLIB_NEW)])
    patch("frontend/src/App.jsx", [
        (APPJSX_IMPORT_OLD, APPJSX_IMPORT_NEW),
        (APPJSX_BADGE_OLD, APPJSX_BADGE_NEW),
    ])
    patch("app/main.py", [(MAIN_OLD, MAIN_NEW)])
    print("\n全部写入完成")
