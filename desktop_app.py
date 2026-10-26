"""ERP Web 后端启动器：服务常驻后台，启动成功后自动打开浏览器。

双击 `启动ERP.bat`（源码模式）或 `ERP管理系统.exe`（打包版）都能用：
先起 Web 服务，健康检查通过后自动用默认浏览器打开 http://127.0.0.1:8010。

---------------------------------------------------------------
★ 2026-10-19 排查结论：双击 exe「没反应」不是崩溃，是没开浏览器
---------------------------------------------------------------
历史上本文件是「桌面启动器」，用 pywebview 弹一个独立窗口，关窗即整体退出。
后来为了「纯 Web + 手机 PWA」把窗口彻底剥掉了，却**忘了补上"自动打开浏览器"**。
于是双击 exe 的真实情况是：进程起来了、8010 在监听、接口全通，
但屏幕上没有任何变化 —— 用户只能认为"程序没启动 / 崩溃了"。

现在补齐三件事，让任何失败都**不可能**是静默的：
  1. 端口探测：8010 已在监听 = 已经启动过 → 直接开浏览器，不去抢端口；
  2. 自动开浏览器：后台线程轮询端口，服务就绪后 webbrowser.open()；
  3. 兜底留痕：任何异常（含 **import 阶段** 的崩溃）都写 erp_error.log 并弹窗。

想要"只跑服务、不开浏览器"（开机自启、服务器部署）：
    设置环境变量 ERP_NO_BROWSER=1
换端口：ERP_PORT=8000
"""

import os
import socket
import sys
import threading
import time
import traceback
import webbrowser

# ---------------------------------------------------------------
# 工作目录：打包后必须切到 **exe 所在目录**，不能用 __file__。
# 因为 PyInstaller(onedir) 下 __file__ 指向 `_internal\desktop_app.py`，
# 那是解包目录（.env / frontend/dist 都在里面，路径由 app 自己用 _MEIPASS 解析）。
# 用户可见的数据（data/ 附件、erp_error.log）应该落在 exe 旁边，而不是藏进 _internal。
# ---------------------------------------------------------------
if getattr(sys, "frozen", False):
    BASE_DIR = os.path.dirname(os.path.abspath(sys.executable))
else:
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))
os.chdir(BASE_DIR)

# pythonw / 双击 exe 时没有控制台，stdout/stderr 为 None，重定向避免后端日志报错
_NO_CONSOLE = sys.stdout is None
if sys.stdout is None:
    sys.stdout = open(os.devnull, "w", encoding="utf-8")
if sys.stderr is None:
    sys.stderr = open(os.devnull, "w", encoding="utf-8")

# ---------------------------------------------------------------
# 监听端口：默认 8010。
# 原设计是 8000，但本机 8000 被一条 netsh 端口代理自环规则
# （0.0.0.0:8000 → 127.0.0.1:8000，由 iphlpsvc 持有，系早年为把
# WSL 里的 ERPNext 暴露到局域网所加的残留）占着，导致绑定失败
# （WinError 10013）。改用 8010 绕开，无需管理员权限即可启动。
# 若日后清掉了那条残留规则，可用环境变量 ERP_PORT=8000 覆盖回 8000。
# ---------------------------------------------------------------
PORT = int(os.environ.get("ERP_PORT", "8010"))
HOST = "0.0.0.0"  # 本机 127.0.0.1 和局域网（手机 PWA / 其他设备）都能访问
LOCAL_URL = "http://127.0.0.1:%d" % PORT
LOG_PATH = os.path.join(BASE_DIR, "erp_error.log")
AUTO_BROWSER = os.environ.get("ERP_NO_BROWSER", "").strip() != "1"


def _log_fatal(title: str, detail: str) -> None:
    """把致命错误写进 exe 同目录的 erp_error.log，并在无控制台时弹窗。

    为什么要弹窗：`erp.spec` 里 `console=False`，双击 exe 没有控制台，
    不弹窗的话"缺少模块 / 路径错误"这类崩溃对用户就是一片死寂。
    """
    text = "【%s】\n%s\n\n%s\n" % (time.strftime("%Y-%m-%d %H:%M:%S"), title, detail)
    try:
        with open(LOG_PATH, "w", encoding="utf-8") as f:
            f.write(text)
    except OSError:
        pass
    if _NO_CONSOLE or getattr(sys, "frozen", False):
        try:
            import ctypes

            ctypes.windll.user32.MessageBoxW(None, text[-1800:], "ERP 启动失败", 0x10)
        except Exception:
            pass


def _port_in_use(port: int, timeout: float = 0.4) -> bool:
    """能否连上 127.0.0.1:port —— 能连上就说明已经有服务在监听。"""
    sock = socket.socket()
    sock.settimeout(timeout)
    try:
        return sock.connect_ex(("127.0.0.1", port)) == 0
    finally:
        sock.close()


def _open_browser_when_ready(url: str, port: int, deadline: float = 60.0) -> bool:
    """后台线程：等到端口可连（= uvicorn 已 accept）再打开浏览器。

    不能起服务前就 open：那时 TCP 还没监听，浏览器会立刻显示"无法访问"，
    用户以为服务挂了。轮询间隔 0.3s，正常 1~3 秒内就绪。
    """
    end = time.time() + deadline
    while time.time() < end:
        if _port_in_use(port):
            try:
                webbrowser.open(url, new=2)
            except Exception:
                pass
            return True
        time.sleep(0.3)
    return False


def _load_deepseek_key() -> None:
    """DeepSeek Key 兜底：部分启动方式读不到用户级环境变量，直接从注册表取。

    必须在 `from app.main import app` **之前**执行 —— 配置在 import 期就固化了。
    """
    if os.environ.get("DEEPSEEK_API_KEY"):
        return
    try:
        import winreg

        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment") as key:
            os.environ["DEEPSEEK_API_KEY"] = winreg.QueryValueEx(key, "DEEPSEEK_API_KEY")[0]
    except OSError:
        pass


def main() -> int:
    _load_deepseek_key()

    # 情况一：已经有一个实例在监听（用户重复双击 exe / 忘了 bat 还开着）
    # 旧代码在这里会 uvicorn 绑定失败 → WinError 10048 → 进程秒退，同样"没反应"。
    # 现在直接把已有实例的页面顶到前台，不再抢端口。
    if _port_in_use(PORT):
        if AUTO_BROWSER:
            try:
                webbrowser.open(LOCAL_URL, new=2)
            except Exception:
                pass
        return 0

    # 情况二：正常启动。先把"等就绪再开浏览器"的线程挂上（daemon：随主进程退出）
    if AUTO_BROWSER:
        threading.Thread(
            target=_open_browser_when_ready, args=(LOCAL_URL, PORT), daemon=True
        ).start()

    # ⚠️ import 必须放在 try 内：`from app.main import app` 会立刻执行 create_app()，
    # 对三套账套跑建表/补列。这一步若因缺模块、模板或静态目录失败，
    # 旧代码（try 只包住 uvicorn.run）**连日志都不会留下** —— 那才是真正的"静默崩溃"。
    import uvicorn

    from app.main import app

    uvicorn.run(app, host=HOST, port=PORT, log_level="warning")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except SystemExit:
        raise
    except BaseException:
        # 用 BaseException 而不是 Exception：uvicorn 绑定失败可能抛 SystemExit，
        # 只捕 Exception 会漏掉最典型的"端口被占"场景。
        _log_fatal("ERP 启动失败", traceback.format_exc())
        sys.exit(1)
