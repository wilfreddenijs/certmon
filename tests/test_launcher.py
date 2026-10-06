import sys
import logging
from types import SimpleNamespace

import pytest

import launcher


def test_windowed_request_errors_are_logged_once(monkeypatch, tmp_path):
    path = tmp_path / "certmon_error.log"
    monkeypatch.setattr(launcher, "log_path", str(path))
    root = logging.getLogger()
    original_handlers = list(root.handlers)
    try:
        launcher.configure_error_logging()
        launcher.configure_error_logging()
        added = [handler for handler in root.handlers if handler not in original_handlers]
        assert len(added) == 1
        monkeypatch.setattr(sys, "stderr", None)
        logger = logging.getLogger("certmon.request.test")
        logger.info("ordinary request")
        try:
            raise ConnectionRefusedError("test endpoint unavailable")
        except ConnectionRefusedError:
            logger.exception("Direct Extron host-key probe failed")
        text = path.read_text(encoding="utf-8")
        assert text.count("Direct Extron host-key probe failed") == 1
        assert "ConnectionRefusedError: test endpoint unavailable" in text
        assert "ordinary request" not in text
    finally:
        for handler in list(root.handlers):
            if handler not in original_handlers:
                root.removeHandler(handler)
                handler.close()


def test_initialize_application_recovers_jobs_before_returning(monkeypatch, tmp_path):
    calls = []
    fake = SimpleNamespace(
        data_dir=lambda: str(tmp_path / "data"),
        database=SimpleNamespace(initialize=lambda: calls.append("database")),
        vault=SimpleNamespace(initialize=lambda: calls.append("vault")),
        acme_order_service=object(),
        renewal_service=SimpleNamespace(
            recover_interrupted_jobs=lambda service: calls.append(
                ("recovery", service)
            )
        ),
    )
    monkeypatch.setitem(sys.modules, "app", fake)

    result = launcher.initialize_application()

    assert result is fake
    assert calls == ["database", "vault", ("recovery", fake.acme_order_service)]
    assert (tmp_path / "data").is_dir()


def test_main_toolbelt_uploader_mode_does_not_start_server(monkeypatch):
    calls = []
    fake_uploader = SimpleNamespace(main=lambda: calls.append("uploader"))
    monkeypatch.setattr(sys, "argv", ["CertMon.exe", "--toolbelt-uploader", "--jsonl"])
    monkeypatch.setitem(sys.modules, "toolbelt_uploader", fake_uploader)
    monkeypatch.setattr(launcher, "start_flask", lambda port: calls.append("server"))
    monkeypatch.setattr(launcher, "make_tray_icon", lambda port: calls.append("tray"))

    launcher.main()

    assert calls == ["uploader"]


def test_main_toolbelt_uploader_mode_exits_cleanly_on_error(monkeypatch, capsys):
    def boom():
        raise RuntimeError("Toolbelt missing")

    fake_uploader = SimpleNamespace(main=boom)
    logs = []
    monkeypatch.setattr(sys, "argv", ["CertMon.exe", "--toolbelt-uploader", "--jsonl"])
    monkeypatch.setitem(sys.modules, "toolbelt_uploader", fake_uploader)
    monkeypatch.setattr(launcher, "log", lambda msg: logs.append(msg))
    monkeypatch.setattr(launcher, "start_flask", lambda port: logs.append("server"))
    monkeypatch.setattr(launcher, "make_tray_icon", lambda port: logs.append("tray"))

    with pytest.raises(SystemExit) as exc:
        launcher.main()

    assert exc.value.code == 2
    assert "Toolbelt missing" in capsys.readouterr().out
    assert any("TOOLBELT UPLOADER ERROR" in msg for msg in logs)
    assert "server" not in logs
    assert "tray" not in logs
