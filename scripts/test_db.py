# -*- coding: utf-8 -*-
"""测试专用 PostgreSQL 实例管理（A5，2026-10-27）。

为什么要单独起一个实例
----------------------
2026-10-27 之前的状况：`tests/` 里 601 个测试拿 `.env` 的 `DATABASE_URL` 直连**正式库** `erp`。
它们会真实建商品、客户、供应商、仓库，会走审核/状态机；收尾靠 `scripts/clean_test_data.py`
事后按名字擦。擦不干净就是业务数据被污染（商品数突破接口分页上限 500 那次就是这么来的），
而任何一行写错的 DELETE/UPDATE 都可能直接毁掉生产数据。

为什么不在同一个实例里建个 erp_test 库
--------------------------------------
试过了：连接账号 `erp` 的 `rolcreatedb = false`，建库需要超级用户密码。
本脚本改用 PostgreSQL 自带的 `initdb` **另起一个本地实例**（端口 55432）：

  · 跑 initdb 的当前 Windows 用户就是这个实例的超级用户，**不需要任何密码**；
  · 只监听 127.0.0.1、trust 认证 —— 仅限本机开发，别暴露到网络；
  · 与生产实例（5432）是两个进程、两个数据目录，测试里就算
    `DROP SCHEMA public CASCADE` 也碰不到生产库。

用法
----
    python scripts\\test_db.py init      # 首次：建实例 + 建库 + 灌 dump（会顺手写 .env）
    python scripts\\test_db.py start     # 开机后启动
    python scripts\\test_db.py stop
    python scripts\\test_db.py status
    python scripts\\test_db.py reset     # 清库重灌 dump（测试数据乱了用它）
    python scripts\\test_db.py url       # 只打印 TEST_DATABASE_URL

    python -m pytest                    # conftest 会强制走 TEST_DATABASE_URL

可覆盖的环境变量
----------------
    PG_BIN              PostgreSQL bin 目录（找不到会自动探测）
    ERP_TEST_PG_DATA    实例数据目录，默认 <项目根>/.pgtest
    ERP_TEST_PG_PORT    端口，默认 55432
    ERP_TEST_PG_DB      库名，默认 erp_test
    ERP_TEST_PG_USER    超级用户，默认 erp_test
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = Path(os.environ.get("ERP_TEST_PG_DATA") or (ROOT / ".pgtest"))
LOG_FILE = ROOT / "pg_test.log"
PORT = os.environ.get("ERP_TEST_PG_PORT") or "55432"
DB_NAME = os.environ.get("ERP_TEST_PG_DB") or "erp_test"
DB_USER = os.environ.get("ERP_TEST_PG_USER") or "erp_test"
DEFAULT_DUMP = ROOT / "backup" / "pre_optimize_20261027" / "db_pre_optimize.dump"


# ---------------------------------------------------------------- 基础工具

def pg_bin(name: str) -> str:
    """定位 PostgreSQL 可执行文件：PG_BIN > PATH > 常见安装位置。"""
    exe = name if os.name != "nt" or name.endswith(".exe") else name + ".exe"
    candidates: list[Path] = []
    if os.environ.get("PG_BIN"):
        candidates.append(Path(os.environ["PG_BIN"]) / exe)
    found = shutil.which(exe) or shutil.which(name)
    if found:
        candidates.append(Path(found))
    # 本机已知布局，再兜底扫标准安装目录
    candidates.append(Path(r"E:\AI\Postgres\bin") / exe)
    candidates.extend(sorted(Path(r"C:\Program Files\PostgreSQL").glob("*/bin/" + exe)))
    for candidate in candidates:
        if candidate and candidate.exists():
            return str(candidate)
    raise SystemExit(
        "找不到 %s。请把 PostgreSQL 的 bin 目录写进环境变量 PG_BIN，例如：\n"
        "    set PG_BIN=E:\\AI\\Postgres\\bin" % exe
    )


def run(*args: str, check: bool = True) -> subprocess.CompletedProcess:
    cmd = [pg_bin(args[0]), *args[1:]]
    proc = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if check and proc.returncode != 0:
        raise SystemExit(
            "命令失败（%d）：%s\n%s\n%s"
            % (proc.returncode, " ".join(cmd), (proc.stdout or "").strip(), (proc.stderr or "").strip())
        )
    return proc


def is_running() -> bool:
    if not DATA_DIR.exists():
        return False
    return run("pg_ctl", "-D", str(DATA_DIR), "status", check=False).returncode == 0


def psql(sql: str) -> str:
    """连实例的 postgres 维护库执行一句 SQL，返回 -tA 输出。"""
    proc = run("psql", "-h", "127.0.0.1", "-p", PORT, "-U", DB_USER, "-d", "postgres",
               "-tAc", sql, check=False)
    return (proc.stdout or "").strip()


def database_exists() -> bool:
    return psql("select 1 from pg_database where datname = '%s'" % DB_NAME) == "1"


def test_url() -> str:
    # trust 认证所以 URL 里没有密码；仅本地实例、只监听 127.0.0.1。
    return "postgresql+psycopg://%s@127.0.0.1:%s/%s" % (DB_USER, PORT, DB_NAME)


# ---------------------------------------------------------------- 子命令

def cmd_start() -> None:
    if not DATA_DIR.exists():
        raise SystemExit("实例还没初始化，先跑：python scripts\\test_db.py init")
    if is_running():
        print("已在运行：127.0.0.1:%s（数据目录 %s）" % (PORT, DATA_DIR))
        return
    run("pg_ctl", "-D", str(DATA_DIR), "-l", str(LOG_FILE), "-w",
        "-o", "-p %s -c listen_addresses=127.0.0.1" % PORT, "start")
    print("已启动：127.0.0.1:%s  日志 %s" % (PORT, LOG_FILE))


def cmd_stop() -> None:
    if not is_running():
        print("没在运行。")
        return
    run("pg_ctl", "-D", str(DATA_DIR), "-m", "fast", "-w", "stop")
    print("已停止。")


def cmd_status() -> None:
    if not DATA_DIR.exists():
        print("实例未初始化（数据目录不存在）：%s" % DATA_DIR)
        return
    running = is_running()
    print("数据目录：%s" % DATA_DIR)
    print("状态    ：%s" % ("运行中 127.0.0.1:%s" % PORT if running else "已停止"))
    if running:
        print("测试库  ：%s %s" % (DB_NAME, "(已建)" if database_exists() else "(还没建，跑 init)"))
    print("TEST_DATABASE_URL=%s" % test_url())


def _restore(dump: Path) -> None:
    if not dump.exists():
        raise SystemExit("找不到 dump：%s\n先用 pg_dump -Fc 备份生产库，或用 --dump 指定别的文件。" % dump)
    print("正在灌数据：%s → %s（%d KB）" % (dump.name, DB_NAME, dump.stat().st_size // 1024))
    proc = run("pg_restore", "-h", "127.0.0.1", "-p", PORT, "-U", DB_USER, "-d", DB_NAME,
               "--no-owner", "--no-privileges", "--exit-on-error", str(dump), check=False)
    if proc.returncode != 0:
        raise SystemExit("pg_restore 失败（%d）：\n%s\n%s"
                         % (proc.returncode, (proc.stdout or "").strip(), (proc.stderr or "").strip()))
    tables = psql_count_tables()
    schemas = psql(
        "select string_agg(nspname, ',' order by nspname) from pg_namespace "
        "where nspname not like 'pg\\_%' and nspname <> 'information_schema'"
    )
    print("灌完：public 表 %s 张；schema：%s" % (tables, schemas))


def psql_count_tables() -> int:
    """测试库里 public schema 的表数（用来判断"是不是空的"）。"""
    out = run("psql", "-h", "127.0.0.1", "-p", PORT, "-U", DB_USER, "-d", DB_NAME,
              "-tAc", "select count(*) from information_schema.tables "
                      "where table_schema = 'public'", check=False).stdout
    try:
        return int((out or "0").strip() or 0)
    except ValueError:
        return 0


def _write_env_url() -> None:
    """把 TEST_DATABASE_URL 写进项目根 .env；已有同名键就不动，免得覆盖手工配置。"""
    env_file = ROOT / ".env"
    line = "TEST_DATABASE_URL=%s" % test_url()
    if env_file.exists():
        text = env_file.read_text(encoding="utf-8", errors="replace")
        for raw in text.splitlines():
            if raw.strip().startswith("TEST_DATABASE_URL="):
                print(".env 里已有 TEST_DATABASE_URL，未改动：%s" % raw.strip())
                return
        if not text.endswith("\n"):
            text += "\n"
        text += "# 测试库：scripts/test_db.py 起的独立实例，绝不指向生产库\n" + line + "\n"
        env_file.write_text(text, encoding="utf-8")
    else:
        env_file.write_text(line + "\n", encoding="utf-8")
    print("已写入 .env：%s" % line)


def cmd_init(dump: Path, write_env: bool) -> None:
    if not DATA_DIR.exists():
        print("initdb → %s" % DATA_DIR)
        run("initdb", "-D", str(DATA_DIR), "-U", DB_USER, "-A", "trust", "-E", "UTF8", "--no-locale")
    else:
        print("数据目录已存在，跳过 initdb：%s" % DATA_DIR)

    cmd_start()

    if database_exists():
        print("测试库 %s 已存在。" % DB_NAME)
    else:
        run("psql", "-h", "127.0.0.1", "-p", PORT, "-U", DB_USER, "-d", "postgres",
            "-c", 'CREATE DATABASE "%s"' % DB_NAME)
        print("已建库 %s。" % DB_NAME)

    if psql_count_tables() == 0:
        _restore(dump)
    else:
        print("测试库已有 %d 张 public 表，跳过灌数据（要重灌用 reset）。" % psql_count_tables())

    if write_env:
        _write_env_url()
    print("\n完成。跑测试：python -m pytest\n")
    cmd_status()


def cmd_reset(dump: Path, write_env: bool) -> None:
    if not is_running():
        cmd_start()
    # 先踢掉残留连接，否则 DROP DATABASE 会卡在 "is being accessed by other users"
    psql("select pg_terminate_backend(pid) from pg_stat_activity where datname = '%s'" % DB_NAME)
    psql('DROP DATABASE IF EXISTS "%s"' % DB_NAME)
    run("psql", "-h", "127.0.0.1", "-p", PORT, "-U", DB_USER, "-d", "postgres",
        "-c", 'CREATE DATABASE "%s"' % DB_NAME)
    _restore(dump)
    if write_env:
        _write_env_url()
    print("\n完成。")


def main() -> int:
    parser = argparse.ArgumentParser(description="测试专用 PostgreSQL 实例（A5 测试库隔离）")
    parser.add_argument("command", choices=["init", "start", "stop", "status", "reset", "url"])
    parser.add_argument("--dump", default=str(DEFAULT_DUMP), help="要灌的 pg_dump -Fc 文件")
    parser.add_argument("--no-write-env", action="store_true", help="不要往 .env 写 TEST_DATABASE_URL")
    args = parser.parse_args()

    write_env = not args.no_write_env
    if args.command == "init":
        cmd_init(Path(args.dump), write_env)
    elif args.command == "start":
        cmd_start()
    elif args.command == "stop":
        cmd_stop()
    elif args.command == "status":
        cmd_status()
    elif args.command == "reset":
        cmd_reset(Path(args.dump), write_env)
    elif args.command == "url":
        print(test_url())
    return 0


if __name__ == "__main__":
    sys.exit(main())
