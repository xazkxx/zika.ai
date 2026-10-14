"""ERP 桌面启动器：后台启动后端服务，弹出桌面窗口加载页面。

双击"启动ERP.bat"即可使用；窗口关闭后程序整体退出。
"""
import os
import sys
import threading
import time
import urllib.request

# pythonw 启动时没有控制台，stdout/stderr 为 None，重定向避免后端日志报错
if sys.stdout is None:
    sys.stdout = open(os.devnull, "w")
if sys.stderr is None:
    sys.stderr = open(os.devnull, "w")

# DeepSeek Key 兜底：部分启动方式读不到用户级环境变量，直接从注册表取
if not os.environ.get("DEEPSEEK_API_KEY"):
    try:
        import winreg

        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment") as key:
            os.environ["DEEPSEEK_API_KEY"] = winreg.QueryValueEx(key, "DEEPSEEK_API_KEY")[0]
    except OSError:
        pass

import uvicorn
import webview

# 显式导入 app 包（不用字符串导入）：PyInstaller 静态分析才能把整个后端打进去
from app.main import app  # noqa: F401

# ---------------------------------------------------------------
# 监听端口：默认 8010。
# 原设计是 8000，但本机 8000 被一条 netsh 端口代理自环规则
# （0.0.0.0:8000 → 127.0.0.1:8000，由 iphlpsvc 持有，系早年为把
# WSL 里的 ERPNext 暴露到局域网所加的残留）占着，导致绑定失败
# （WinError 10013）。改用 8010 绕开，无需管理员权限即可启动。
# 若日后清掉了那条残留规则，可用环境变量 ERP_PORT=8000 覆盖回 8000。
# ---------------------------------------------------------------
PORT = int(os.environ.get("ERP_PORT", "8010"))
URL = f"http://127.0.0.1:{PORT}"


def backend_alive() -> bool:
    try:
        with urllib.request.urlopen(URL + "/", timeout=1) as resp:
            return resp.status == 200
    except Exception:
        return False


def run_server() -> None:
    try:
        # 监听 0.0.0.0：本机 127.0.0.1 和局域网（手机 PWA）都能访问
        uvicorn.run(app, host="0.0.0.0", port=PORT, log_level="warning")
    except Exception:
        # 窗口版看不到控制台，出错时把堆栈写到 exe 旁边的日志文件便于排查
        import traceback
        from pathlib import Path

        log_path = Path(sys.executable).parent / "erp_error.log"
        with open(log_path, "w", encoding="utf-8") as f:
            traceback.print_exc(file=f)


def wait_backend() -> None:
    for _ in range(40):
        if backend_alive():
            return
        time.sleep(0.5)


def main() -> None:
    # 若后端已在运行（如开发模式），直接复用，不重复启动
    if not backend_alive():
        threading.Thread(target=run_server, daemon=True).start()
        wait_backend()

    webview.create_window(
        "ERP 管理系统",
        URL,
        width=1280,
        height=800,
        min_size=(1024, 640),
    )
    webview.start()
    os._exit(0)


if __name__ == "__main__":
    main()
