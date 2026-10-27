# -*- coding: utf-8 -*-
"""从运行期 `app.main` 的 `*_ADDITIONS` 生成 `app/db/migration_columns.py`（C1-3，一次性）。

为什么用脚本而不是手抄：逐列手抄错一个字母 = 错列名 / 错类型，且在测试里很难发现。
这里直接 import 运行期 dict，格式化后写回静态常量，并做「写回后再读出来必须完全相等」
的自校验 —— 有任何一边不对就当场失败。

⚠️ 会连测试库（读 .env 的 TEST_DATABASE_URL），绝不碰生产。
运行：
    .venv\\Scripts\\python.exe scripts\\gen_migration_columns.py
"""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
OUT = ROOT / "app" / "db" / "migration_columns.py"


def _env_value(key: str) -> str | None:
    path = ROOT / ".env"
    if not path.exists():
        return None
    for raw in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        name, value = line.split("=", 1)
        if name.strip() == key:
            return value.strip().strip('"').strip("'") or None
    return None


def main() -> int:
    test_url = _env_value("TEST_DATABASE_URL")
    if not test_url:
        print("没有 TEST_DATABASE_URL，先起测试库：python scripts\\test_db.py start")
        return 2

    os.environ["DATABASE_URL"] = test_url
    os.environ.setdefault(
        "ERP_SECRET_FILE", str(Path(tempfile.gettempdir()) / "erp_core_test_secret_key")
    )

    import app.main as m  # noqa: E402 —— 必须在换库之后 import

    missing = [
        name
        for name in ("PRODUCT_ADDITIONS", "CUSTOMER_ADDITIONS", "SUPPLIER_ADDITIONS", "INVOICE_ADDITIONS")
        if not hasattr(m, name)
    ]
    if missing:
        print(f"app.main 已不再定义 {', '.join(missing)}（C1-3 已迁移完成），无需再生成。")
        return 0

    groups: dict[str, dict[str, str]] = {
        "PRODUCT_COLUMNS": dict(m.PRODUCT_ADDITIONS),
        "CUSTOMER_COLUMNS": dict(m.CUSTOMER_ADDITIONS),
        "SUPPLIER_COLUMNS": dict(m.SUPPLIER_ADDITIONS),
        "INVOICE_COLUMNS": dict(m.INVOICE_ADDITIONS),
    }

    lines: list[str] = [
        '"""C1-3：迁移列定义（由 scripts/gen_migration_columns.py 生成，勿手改）。',
        "",
        "来源：原 app/main.py 的 PRODUCT / CUSTOMER / SUPPLIER / INVOICE_ADDITIONS。",
        "生成器保证与运行期 dict 逐字相等；要改列定义，改生成源或迁移脚本后重跑生成器。",
        '"""',
        "",
        "from __future__ import annotations",
    ]
    for name, mapping in groups.items():
        lines.append("")
        lines.append(f"{name}: dict[str, str] = {{")
        for key, value in mapping.items():
            lines.append(f"    {key!r}: {value!r},")
        lines.append("}")

    OUT.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"已生成 {OUT}（{OUT.stat().st_size} 字节，{sum(len(g) for g in groups.values())} 列）")

    # 自校验：读回生成文件，必须与原 dict 完全相等
    import importlib.util

    spec = importlib.util.spec_from_file_location("_gen_cols_check", OUT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    for name, mapping in groups.items():
        assert getattr(module, name) == mapping, f"{name} 生成后不相等"
    print("自校验通过：4 组常量与运行期 dict 完全相等")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
