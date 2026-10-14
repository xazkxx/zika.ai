"""正式库数据保护：给"会动到全库数据的测试"加一层快照与还原。

**为什么需要这个模块**

本项目的测试直连正式 PostgreSQL（见 tests/conftest.py 的说明），这是既定选择 ——
库不大、跑完即清、比维护一套测试库省事。但这个约定有个隐含前提：
**测试只能写"自己造的数据"，不能碰全库范围的数据。**

「期初建账的清空」「操作日志的清空」这两条接口偏偏是全库范围的。写单元测试时
很容易顺手调一下验证行为，而这一下就真的把用户的期初台账 / 操作留痕清掉了
—— 这不是"测试数据残留"（多出来的脏东西），而是**删除真实数据**，性质严重得多。

所以这里提供一个显式的快照工具，用法固定：

    guard = ProdSnapshot("opening-stock")
    guard.save(rows)          # ① 快照先落盘（哪怕进程随后被杀也能捞回来）
    ...调危险的接口...
    guard.restore(restore_fn) # ② 还原
    guard.done()              # ③ 确认还原成功后删掉快照文件

快照文件写在项目根目录，名字带 `_testsnapshot_` 前缀，方便误留时一眼认出来。
`restore_fn(rows)` 由调用方提供 —— 各表怎么还原本来就不一样（期初走接口、
日志走 ORM），这里只负责"存、读、留痕"。
"""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PREFIX = "_testsnapshot_"


class ProdSnapshot:
    def __init__(self, name: str):
        self.name = name
        self.path = ROOT / f"{PREFIX}{name}.json"
        self.rows: list[dict] = []

    def save(self, rows: list[dict]) -> None:
        """快照落盘。落盘失败不阻断测试（内存里那份还能用），但要留下提示。"""
        self.rows = rows
        try:
            self.path.write_text(
                json.dumps(rows, ensure_ascii=False, default=str, indent=1),
                encoding="utf-8",
            )
        except OSError as exc:  # pragma: no cover - 磁盘异常
            print(f"[prod_snapshot] 快照落盘失败（不阻断）：{exc}")

    def restore(self, restore_fn) -> int:
        """调用方提供的还原函数，返回还原条数。

        还原失败必须**抛出去**：静默失败的还原比不还原更危险 ——
        测试会绿，而用户的数据已经没了。
        """
        if not self.rows:
            return 0
        return int(restore_fn(self.rows))

    def done(self) -> None:
        """还原确认成功后才删快照文件。"""
        try:
            self.path.unlink(missing_ok=True)
        except OSError:  # pragma: no cover
            pass

    def __enter__(self) -> "ProdSnapshot":
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        # 测试异常时**保留**快照文件，并把它指给使用者 —— 这是最后的救命稻草
        if exc_type is not None and self.path.exists():
            print(f"\n[prod_snapshot] 测试异常，快照保留在：{self.path}")
        return False
