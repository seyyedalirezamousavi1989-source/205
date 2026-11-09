import ctypes
import json
import os
import traceback
import shutil
import socket
import subprocess
import sys
import time
import webbrowser
from pathlib import Path
from urllib.error import URLError
from urllib.request import urlopen


# PyInstaller executes the entry script as __main__, so it has no package
# context and relative imports fail. Add the project/bundle root explicitly,
# then always import through the real local_chat package.
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from local_chat import settings as app_settings
from local_chat.version import APP_VERSION

APP_DIR = Path(__file__).resolve().parent
SERVER_FILE = APP_DIR / "server.py"
CHAT_URL = "http://127.0.0.1:8000/"
STATUS_URL = "http://127.0.0.1:8000/api/status"
OLLAMA_URL = "http://127.0.0.1:11434/api/tags"
STARTUP_TIMEOUT = 60
SERVER_STARTUP_TIMEOUT = 30


def startup_log_path():
    """Return a per-user log path that is writable in installed builds."""
    root = Path(os.environ.get("LOCALAPPDATA", str(Path.home() / "AppData" / "Local")))
    log_dir = root / "LocalChat" / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    return log_dir / "server_startup.log"


def read_startup_log(max_chars=6000):
    try:
        content = startup_log_path().read_text(encoding="utf-8", errors="replace")
        return content[-max_chars:].strip()
    except OSError:
        return "(گزارش شروع سرور قابل خواندن نیست.)"


def show_error(message):
    ctypes.windll.user32.MessageBoxW(None, message, "گفت‌وگوی محلی", 0x10)


def chat_server_is_running():
    try:
        with urlopen(STATUS_URL, timeout=2) as response:
            return json.loads(response.read().decode("utf-8")).get("version") == APP_VERSION
    except (OSError, URLError, TimeoutError, ValueError):
        return False


def port_is_available(port):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as connection:
        return connection.connect_ex(("127.0.0.1", port)) != 0


def find_ollama():
    executable = shutil.which("ollama")
    if executable:
        return executable
    candidates = [
        Path.home() / "AppData" / "Local" / "Programs" / "Ollama" / "ollama.exe",
        Path("C:/Program Files/Ollama/ollama.exe"),
    ]
    return next((str(path) for path in candidates if path.is_file()), None)


def ollama_is_running():
    try:
        with urlopen(OLLAMA_URL, timeout=2) as response:
            return response.status == 200
    except (OSError, URLError, TimeoutError):
        return False


def wait_for_ollama():
    if ollama_is_running():
        return

    executable = find_ollama()
    if not executable:
        raise RuntimeError(
            "Ollama پیدا نشد. ابتدا Ollama را نصب کنید یا برنامهٔ Ollama را باز کنید."
        )

    subprocess.Popen(
        [executable, "serve"],
        env=app_settings.ollama_environment(),
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=subprocess.CREATE_NO_WINDOW,
    )
    deadline = time.monotonic() + STARTUP_TIMEOUT
    while time.monotonic() < deadline:
        if ollama_is_running():
            return
        time.sleep(1)
    raise RuntimeError(
        "Ollama در زمان مناسب اجرا نشد. برنامهٔ Ollama را باز کنید و دوباره تلاش کنید."
    )


def start_chat_server():
    if chat_server_is_running():
        return
    if not port_is_available(8000):
        raise RuntimeError(
            "درگاه ۸۰۰۰ توسط برنامهٔ دیگری استفاده شده است. آن برنامه را ببندید و دوباره تلاش کنید."
        )

    # In a frozen build, the executable relaunches itself in server mode.
    command = (
        [sys.executable, "--localchat-server"]
        if getattr(sys, "frozen", False)
        else [sys.executable, str(SERVER_FILE)]
    )
    log_path = startup_log_path()
    try:
        log_handle = log_path.open("a", encoding="utf-8", errors="replace")
        log_handle.write(
            f"\n--- LocalChat server start {time.strftime('%Y-%m-%d %H:%M:%S')} ---\n"
        )
        log_handle.flush()
        try:
            process = subprocess.Popen(
                command,
                cwd=APP_DIR,
                stdin=subprocess.DEVNULL,
                stdout=log_handle,
                stderr=subprocess.STDOUT,
                close_fds=True,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)
                if getattr(sys, "frozen", False)
                else getattr(subprocess, "CREATE_NEW_CONSOLE", 0),
            )
        finally:
            log_handle.close()
    except OSError as error:
        raise RuntimeError(
            f"پردازش سرور ساخته نشد: {error}\nگزارش: {log_path}"
        ) from error

    deadline = time.monotonic() + SERVER_STARTUP_TIMEOUT
    while time.monotonic() < deadline:
        if chat_server_is_running():
            return
        exit_code = process.poll()
        if exit_code is not None:
            details = read_startup_log()
            raise RuntimeError(
                f"سرور بلافاصله متوقف شد (کد خروج: {exit_code}).\n"
                f"گزارش خطا: {log_path}\n\n{details}"
            )
        time.sleep(0.25)

    details = read_startup_log()
    raise RuntimeError(
        f"سرور در {SERVER_STARTUP_TIMEOUT} ثانیه آماده نشد.\n"
        f"گزارش خطا: {log_path}\n\n{details}"
    )


def main():
    try:
        wait_for_ollama()
        start_chat_server()
        webbrowser.open(CHAT_URL)
    except (OSError, RuntimeError) as error:
        show_error(str(error))
        return 1
    return 0


if __name__ == "__main__":
    if "--localchat-server" in sys.argv:
        # Log even import-time failures; the parent redirects stdout/stderr here.
        try:
            from local_chat.server import main as server_main
            server_main()
        except BaseException:
            traceback.print_exc()
            raise
    else:
        raise SystemExit(main())
