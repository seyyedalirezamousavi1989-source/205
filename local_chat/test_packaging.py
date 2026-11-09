from pathlib import Path
import sys

import pytest

from local_chat import launcher


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_pyinstaller_specs_point_to_existing_launcher():
    entry = 'os.path.join(ROOT, "local_chat", "launcher.py")'
    launcher_file = PROJECT_ROOT / "local_chat" / "launcher.py"

    assert launcher_file.is_file()
    launcher_source = launcher_file.read_text(encoding="utf-8")
    assert "from local_chat import settings as app_settings" in launcher_source
    assert "from local_chat.version import APP_VERSION" in launcher_source
    assert not any(
        line.strip() == "import settings as app_settings"
        for line in launcher_source.splitlines()
    )
    for name in ("localchat.spec", "localchat_onefile.spec"):
        spec = (PROJECT_ROOT / "packaging" / name).read_text(encoding="utf-8")
        assert entry in spec, f"{name} must use the existing launcher entry point"
        assert "localchat_app.py" not in spec


@pytest.mark.parametrize("frozen", [False, True])
def test_launcher_starts_server_with_correct_command(monkeypatch, frozen):
    calls = []
    running = iter((False, True))

    monkeypatch.setattr(launcher, "chat_server_is_running", lambda: next(running))
    monkeypatch.setattr(launcher, "port_is_available", lambda port: True)
    monkeypatch.setattr(launcher.time, "monotonic", iter((0.0, 1.0)).__next__)
    monkeypatch.setattr(launcher.time, "sleep", lambda seconds: None)
    monkeypatch.setattr(launcher.subprocess, "Popen", lambda command, **kwargs: calls.append((command, kwargs)))
    monkeypatch.setattr(launcher.subprocess, "CREATE_NEW_CONSOLE", 0, raising=False)
    monkeypatch.setattr(launcher.sys, "frozen", frozen, raising=False)

    launcher.start_chat_server()

    expected = (
        [sys.executable, "--localchat-server"]
        if frozen
        else [sys.executable, str(launcher.SERVER_FILE)]
    )
    assert calls and calls[0][0] == expected
    assert calls[0][1]["cwd"] == launcher.APP_DIR



def test_onefile_spec_contains_the_full_server_module_set():
    onedir = (PROJECT_ROOT / "packaging" / "localchat.spec").read_text(encoding="utf-8")
    onefile = (PROJECT_ROOT / "packaging" / "localchat_onefile.spec").read_text(encoding="utf-8")
    required = (
        "local_chat.server", "local_chat.search_plan", "local_chat.system_tools",
        "local_chat.coding_agent", "local_chat.context_manager",
        "local_chat.forex_service", "local_chat.forex_desk", "local_chat.forex_analysis",
        "local_chat.forex_decision", "local_chat.forex_backtest", "local_chat.forex_agent",
        "local_chat.forex_watch", "local_chat.mt5_data", "local_chat.mt5_trade",
    )
    for module in required:
        assert module in onedir, f"onedir spec misses {module}"
        assert module in onefile, f"onefile spec misses {module}"


def test_startup_log_reports_child_process_exit(monkeypatch, tmp_path):
    class DeadProcess:
        def poll(self):
            return 17

    log_file = tmp_path / "server_startup.log"
    log_file.write_text("ModuleNotFoundError: missing_runtime_module", encoding="utf-8")
    monkeypatch.setattr(launcher, "chat_server_is_running", lambda: False)
    monkeypatch.setattr(launcher, "port_is_available", lambda port: True)
    monkeypatch.setattr(launcher, "startup_log_path", lambda: log_file)
    monkeypatch.setattr(launcher, "read_startup_log", lambda: log_file.read_text(encoding="utf-8"))
    monkeypatch.setattr(launcher.subprocess, "Popen", lambda *args, **kwargs: DeadProcess())
    monkeypatch.setattr(launcher.subprocess, "CREATE_NO_WINDOW", 0, raising=False)
    monkeypatch.setattr(launcher.sys, "frozen", True, raising=False)

    with pytest.raises(RuntimeError, match="کد خروج: 17") as error:
        launcher.start_chat_server()
    assert "ModuleNotFoundError" in str(error.value)
    assert str(log_file) in str(error.value)
