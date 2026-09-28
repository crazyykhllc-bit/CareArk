"""Double-click launcher for the self-contained Windows edition."""

import asyncio
import logging
import os
import queue
import socket
import sys
import tempfile
import threading
import webbrowser
from pathlib import Path


DEFAULT_MODEL_CONFIG = """# 视觉识别需要自行填写支持图片输入的模型 API Key；修改后重启 CareArk。
# 下面以 DeepSeek 为例；使用其他模型服务时，请同时修改基础地址、模型名称和 API Key。
MODEL_PROVIDER=openai-compatible
MODEL_BASE_URL=https://api.deepseek.com
MODEL_API_KEY=
MODEL_NAME=deepseek-flash
MODEL_STRICT_JSON_SCHEMA=false
"""


def bundle_directory() -> Path:
    return Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))


def default_data_directory() -> Path:
    override = os.environ.get("CAREARK_DATA_DIR")
    if override:
        return Path(override).expanduser().resolve()
    base = os.environ.get("LOCALAPPDATA")
    if not base:
        base = str(Path.home() / "AppData" / "Local")
    return Path(base) / "CareArk"


def prepare_runtime(data_dir: Path) -> Path:
    """Keep databases, originals, and model credentials outside the program files."""
    data_dir = data_dir.resolve()
    data_dir.mkdir(parents=True, exist_ok=True)
    config_file = data_dir / ".env"
    if not config_file.exists():
        config_file.write_text(DEFAULT_MODEL_CONFIG, encoding="utf-8")
    originals = data_dir / "originals"
    originals.mkdir(exist_ok=True)
    os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{(data_dir / 'careark.db').as_posix()}"
    os.environ["STORAGE_BACKEND"] = "file"
    os.environ["FILE_STORAGE_ROOT"] = str(originals)
    os.environ["SESSION_COOKIE_NAME"] = "careark_desktop_session"
    os.environ["SECURE_COOKIES"] = "false"
    os.chdir(data_dir)
    return config_file


def migrate_database() -> None:
    from alembic import command
    from alembic.config import Config

    directory = bundle_directory()
    config = Config(str(directory / "alembic.ini"))
    config.set_main_option("script_location", str(directory / "alembic"))
    command.upgrade(config, "head")


def available_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def configure_logging(data_dir: Path) -> None:
    logging.basicConfig(filename=data_dir / "careark.log", level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(message)s", encoding="utf-8",
                        force=True)


def self_test() -> None:
    import io

    previous_directory = Path.cwd()
    with tempfile.TemporaryDirectory(prefix="careark-self-test-") as temporary:
        try:
            prepare_runtime(Path(temporary))
            migrate_database()
            from app.db import _engine
            from app.main import app
            from app.services.storage import get_storage
            from app.worker import run as run_worker

            import httpx
            import uvicorn

            async def storage_check():
                storage = get_storage()
                await storage.put("self-test/check.txt", io.BytesIO(b"ok"), 2, "text/plain")
                stream = await storage.get("self-test/check.txt")
                try:
                    assert stream.read() == b"ok"
                finally:
                    stream.close()

            async def server_check():
                port = available_port()
                server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port,
                                                       log_config=None, access_log=False))
                worker = asyncio.create_task(run_worker())
                web = asyncio.create_task(server.serve())
                try:
                    for _ in range(100):
                        if server.started or web.done():
                            break
                        await asyncio.sleep(0.1)
                    assert server.started, "本机网站未能启动"
                    async with httpx.AsyncClient() as client:
                        health = await client.get(f"http://127.0.0.1:{port}/health")
                        setup = await client.get(f"http://127.0.0.1:{port}/api/setup/status")
                        home = await client.get(f"http://127.0.0.1:{port}/")
                        assert health.json() == {"status": "ok"}
                        assert setup.status_code == 200
                        assert setup.json()["required"] is True
                        assert home.status_code == 200
                        created = await client.post(f"http://127.0.0.1:{port}/api/setup/admin", json={
                            "email": "self-test@example.test", "password": "Test-123",
                        })
                        assert created.status_code == 201
                        assert (await client.get(f"http://127.0.0.1:{port}/api/auth/me")).status_code == 200
                        uploaded = await client.post(f"http://127.0.0.1:{port}/api/uploads", files={
                            "file": ("sample.csv", b"a,b\n1,2\n", "text/csv"),
                        })
                        assert uploaded.status_code == 202
                        content = await client.get(
                            f"http://127.0.0.1:{port}/api/attachments/{uploaded.json()['attachment_id']}/content"
                        )
                        assert content.content == b"a,b\n1,2\n"
                        assert (await client.post(f"http://127.0.0.1:{port}/api/auth/logout")).status_code == 204
                        assert (await client.get(f"http://127.0.0.1:{port}/api/auth/me")).status_code == 401
                    assert not worker.done(), "识别任务服务未能启动"
                finally:
                    server.should_exit = True
                    await asyncio.wait_for(web, timeout=10)
                    worker.cancel()
                    await asyncio.gather(worker, return_exceptions=True)

            asyncio.run(storage_check())
            asyncio.run(server_check())
            asyncio.run(_engine.dispose())
        finally:
            os.chdir(previous_directory)
    print("SELF_TEST_OK")


def launch() -> None:
    import tkinter as tk
    from tkinter import messagebox

    mutex = None
    if sys.platform == "win32":
        import ctypes

        kernel = ctypes.windll.kernel32
        mutex = kernel.CreateMutexW(None, False, "Local\\CareArkDesktop")
        if kernel.GetLastError() == 183:
            messagebox.showinfo("CareArk", "CareArk 已经在运行。")
            kernel.CloseHandle(mutex)
            return

    data_dir = default_data_directory()
    events: queue.Queue[tuple[str, str]] = queue.Queue()
    state: dict[str, object] = {"server": None, "thread": None, "stopping": False, "url": None}
    window = tk.Tk()
    window.title("CareArk · 个人健康档案")
    window.geometry("460x240")
    window.resizable(False, False)
    window.configure(padx=24, pady=18)
    heading = tk.Label(window, text="CareArk", font=("Microsoft YaHei UI", 20, "bold"), anchor="w")
    heading.pack(fill="x")
    tk.Label(window, text="个人与家庭健康档案 · 本机运行", font=("Microsoft YaHei UI", 10), anchor="w").pack(fill="x", pady=(4, 16))
    status = tk.StringVar(value="正在准备本机数据...")
    tk.Label(window, textvariable=status, font=("Microsoft YaHei UI", 10), anchor="w").pack(fill="x", pady=(0, 16))
    buttons = tk.Frame(window)
    buttons.pack(fill="x")
    open_button = tk.Button(buttons, text="打开工作台", state="disabled", width=14,
                            command=lambda: webbrowser.open(str(state["url"])))
    open_button.pack(side="left", padx=(0, 8))
    tk.Button(buttons, text="模型设置", width=12,
              command=lambda: __import__("subprocess").Popen(["notepad.exe", str(data_dir / ".env")])).pack(side="left", padx=(0, 8))
    tk.Button(buttons, text="数据目录", width=12, command=lambda: os.startfile(data_dir)).pack(side="left")
    tk.Label(window, text="首次使用请在浏览器中创建管理员账号；模型密钥填入“模型设置”后重启。",
             font=("Microsoft YaHei UI", 9), fg="#667085", anchor="w").pack(fill="x", pady=(18, 0))

    def background() -> None:
        try:
            prepare_runtime(data_dir)
            configure_logging(data_dir)
            migrate_database()
            configure_logging(data_dir)

            import uvicorn

            from app.main import app
            from app.worker import run as run_worker

            port = available_port()
            server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port,
                                                   log_config=None, access_log=False))
            state["server"] = server
            if state["stopping"]:
                server.should_exit = True

            async def serve() -> None:
                worker = asyncio.create_task(run_worker())
                web = asyncio.create_task(server.serve())
                try:
                    while not server.started and not web.done():
                        await asyncio.sleep(0.1)
                    if not server.started:
                        raise RuntimeError("本机网站未能启动")
                    events.put(("ready", f"http://127.0.0.1:{port}/"))
                    await web
                finally:
                    worker.cancel()
                    await asyncio.gather(worker, return_exceptions=True)

            asyncio.run(serve())
            events.put(("stopped", ""))
        except Exception as error:
            configure_logging(data_dir)
            logging.exception("CareArk startup failed")
            events.put(("error", str(error)))

    def stop() -> None:
        state["stopping"] = True
        status.set("正在退出...")
        open_button.configure(state="disabled")
        server = state["server"]
        if server is not None:
            server.should_exit = True

    def poll() -> None:
        while not events.empty():
            kind, value = events.get_nowait()
            if kind == "ready":
                state["url"] = value
                status.set(f"正在本机运行：{value}")
                open_button.configure(state="normal")
                if not state["stopping"]:
                    webbrowser.open(value)
            elif kind == "error":
                status.set("启动失败，请查看数据目录中的 careark.log")
                messagebox.showerror("CareArk 启动失败", value)
            elif kind == "stopped":
                window.destroy()
                return
        thread = state["thread"]
        if state["stopping"] and thread is not None and not thread.is_alive():
            window.destroy()
            return
        window.after(100, poll)

    window.protocol("WM_DELETE_WINDOW", stop)
    thread = threading.Thread(target=background, name="careark-server")
    state["thread"] = thread
    thread.start()
    window.after(100, poll)
    try:
        window.mainloop()
    finally:
        if mutex is not None:
            kernel.CloseHandle(mutex)


if __name__ == "__main__":
    if "--self-test" in sys.argv:
        self_test()
    else:
        launch()
