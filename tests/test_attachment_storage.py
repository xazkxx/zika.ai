"""附件归档与一键备份的接口级回归（2026-10-23）。

## 为什么这组测试必须改写 `_root`

真实实现把根目录算在 `data/`（打包后是 exe 同目录）。测试如果直接打真实目录，
就会往用户的附件里塞垃圾文件、还会把真实附件打进备份包 —— 既是污染也是慢。
这里统一把 `erp_storage._root` 换成 `tmp_path`，所有断言都在临时目录里自洽。

## 守的四件事

1. **口径**：只统计白名单目录，`logs/`、`backups/` 这种不能算进"附件占用"；
2. **嵌套**：备份包里不许出现 `backups/`，否则每备一次体积翻一倍；
3. **可重复**：连着备两次，第二个包不应该包含第一个包；
4. **下载口子**：非 `.zip`、不存在的、路径穿越的一律拒绝，正常包能拿到 zip 字节。
"""

import zipfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.api.v1.routes import erp_storage
from app.main import app

client = TestClient(app)
BASE = "/api/v1/system"


@pytest.fixture()
def root(tmp_path, monkeypatch):
    """把存储根目录指向临时目录。"""
    monkeypatch.setattr(erp_storage, "_root", lambda: tmp_path)
    return tmp_path


def _write(path: Path, size: int = 16) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"x" * size)
    return path


def _seed(root: Path) -> None:
    _write(root / "contracts" / "c1.pdf", 100)
    _write(root / "contracts" / "c2.pdf", 50)
    _write(root / "contract_templates" / "模板.docx", 30)
    _write(root / "invoices" / "i1.pdf", 20)
    # 下面这些**不该**被算进附件
    _write(root / "logs" / "app.log", 999)
    _write(root / "backups" / "old.zip", 777)


def test_overview_counts_only_whitelisted_dirs(root):
    _seed(root)
    response = client.get(f"{BASE}/attachment-storage")
    assert response.status_code == 200, response.text
    body = response.json()

    # 白名单里每个目录都有一行（不存在的也算 0，前端表格不能缺行）
    names = [row["name"] for row in body["dirs"]]
    assert names == [name for name, _ in erp_storage.ATTACHMENT_DIRS]
    assert all(row["label"] for row in body["dirs"])

    stats = {row["name"]: row for row in body["dirs"]}
    assert stats["contracts"]["files"] == 2
    assert stats["contracts"]["bytes"] == 150
    assert stats["contract_templates"]["files"] == 1
    assert stats["invoices"]["bytes"] == 20
    # 空目录
    assert stats["products"]["files"] == 0
    assert stats["products"]["exists"] is False

    # 合计只含白名单：150 + 30 + 20 = 200，不含 logs/backups 的 1776
    assert body["total_files"] == 4
    assert body["total_bytes"] == 200

    assert body["root"] == str(root)
    assert body["backup_dir"] == str(root / "backups")
    assert body["disk"]["total"] > 0
    assert body["disk"]["free"] > 0


def test_overview_backups_sorted_desc(root):
    _seed(root)
    # 同一秒内写出来的文件 mtime 可能完全相同，排序就退化成目录遍历顺序。
    # 这里显式错开时间，验证的才是"按时间倒序"这个真实意图。
    import os

    for name, stamp in (
        ("附件备份_20260101_010101.zip", 1_767_225_661),
        ("附件备份_20260102_010101.zip", 1_767_312_061),
    ):
        path = _write(root / "backups" / name, 10)
        os.utime(path, (stamp, stamp))

    body = client.get(f"{BASE}/attachment-storage").json()
    names = [row["name"] for row in body["backups"] if row["name"].startswith("附件备份_")]
    assert names == ["附件备份_20260102_010101.zip", "附件备份_20260101_010101.zip"]
    assert all(len(row["created_at"]) == 16 for row in body["backups"])


def test_backup_excludes_backups_dir_and_is_downloadable(root):
    _seed(root)
    response = client.post(f"{BASE}/attachment-backup")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["files"] == 4  # 只有白名单里的 4 个文件
    assert body["name"].startswith("附件备份_") and body["name"].endswith(".zip")
    assert body["bytes"] > 0
    assert "已备份 4 个文件" in body["message"]

    target = root / "backups" / body["name"]
    assert target.is_file()
    with zipfile.ZipFile(target) as archive:
        entries = archive.namelist()
    assert sorted(entries) == sorted(
        ["contracts/c1.pdf", "contracts/c2.pdf", "contract_templates/模板.docx", "invoices/i1.pdf"]
    )
    # 关键：备份包里不能有 backups/
    assert not [item for item in entries if item.startswith("backups/")]

    # 备份完成后概览能看到它，且不把 zip 的体积算进附件占用
    overview = client.get(f"{BASE}/attachment-storage").json()
    assert overview["total_bytes"] == 200
    assert body["name"] in [row["name"] for row in overview["backups"]]

    download = client.get(f"{BASE}/attachment-backup/{body['name']}")
    assert download.status_code == 200
    assert download.headers["content-type"] == "application/zip"
    assert download.content[:2] == b"PK"


def test_second_backup_does_not_nest_the_first(root):
    _seed(root)
    first = client.post(f"{BASE}/attachment-backup").json()

    # 第一次备份之后，backups 里已经有一个 zip；第二次的包里仍然只能有 4 个附件
    second = client.post(f"{BASE}/attachment-backup").json()
    assert second["files"] == 4

    with zipfile.ZipFile(root / "backups" / second["name"]) as archive:
        assert not [item for item in archive.namelist() if item.startswith("backups/")]

    # 两个包都在概览里
    names = {row["name"] for row in client.get(f"{BASE}/attachment-storage").json()["backups"]}
    assert {first["name"], second["name"]} <= names


def test_download_rejects_non_zip_and_missing(root):
    _seed(root)
    _write(root / "backups" / "notes.txt", 5)

    assert client.get(f"{BASE}/attachment-backup/notes.txt").status_code == 400
    assert client.get(f"{BASE}/attachment-backup/nope.zip").status_code == 404


def test_download_blocks_path_traversal(root):
    _seed(root)
    secret = _write(root / "logs" / "secret.zip", 12)

    # 不管是 ../ 还是编码过的，只要落在 backups 之外就不能拿到
    for probe in ("../logs/secret.zip", "..%2Flogs%2Fsecret.zip", "a/../../logs/secret.zip"):
        response = client.get(f"{BASE}/attachment-backup/{probe}")
        assert response.status_code in (400, 404, 422), f"{probe} 竟然返回 {response.status_code}"
        assert response.status_code != 200
    assert secret.is_file()  # 只是拒绝访问，不能顺手删掉


def test_backup_creates_dir_when_absent(root):
    assert not (root / "backups").exists()
    response = client.post(f"{BASE}/attachment-backup")
    assert response.status_code == 200, response.text
    assert response.json()["files"] == 0  # 一个附件都没有也要能成功
    assert (root / "backups").is_dir()


def test_base64_download_channel_returns_full_zip(root):
    """`?as=base64` 是前端真正用的通道。

    为什么必须验它：Chrome 对 `.zip` 直链的 `fetch` 会回一个**空的 204**，
    前端拿到的 blob 是 0 字节 —— 用户点「下载」只会得到一个打不开的包。
    所以前端改走 base64，这条测试守的就是"那段 base64 解出来必须是完整的 zip"。
    """
    import base64

    _seed(root)
    created = client.post(f"{BASE}/attachment-backup").json()

    response = client.get(f"{BASE}/attachment-backup/{created['name']}?as=base64")
    assert response.status_code == 200, response.text
    body = response.json()

    assert body["filename"] == created["name"]
    on_disk = (root / "backups" / created["name"]).read_bytes()
    assert body["bytes"] == len(on_disk)
    decoded = base64.b64decode(body["content_base64"])
    assert decoded == on_disk, "base64 解出来的字节与磁盘上的包不一致"
    assert decoded[:2] == b"PK"
    # JSON 通道必须是 application/json —— 前端才不会把它当下载拦掉
    assert response.headers["content-type"].startswith("application/json")


def test_base64_channel_guards_same_as_file_channel(root):
    _seed(root)
    _write(root / "backups" / "notes.txt", 5)
    assert client.get(f"{BASE}/attachment-backup/notes.txt?as=base64").status_code == 400
    assert client.get(f"{BASE}/attachment-backup/nope.zip?as=base64").status_code == 404


def test_base64_channel_refuses_oversize_package(root, monkeypatch):
    """超大包不能硬塞进 JSON：内存会炸。必须 413 并把用户指到磁盘目录。"""
    from app.api.v1.routes import erp_storage as module

    _seed(root)
    created = client.post(f"{BASE}/attachment-backup").json()
    monkeypatch.setattr(module, "BASE64_MAX_BYTES", 10)

    response = client.get(f"{BASE}/attachment-backup/{created['name']}?as=base64")
    assert response.status_code == 413, response.text
    detail = response.json()["detail"]
    assert "备份包" in detail and str(root) in detail
