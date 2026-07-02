import time
import types
import inspect

import pytest


@pytest.fixture
def uploader(monkeypatch):
    pywinauto = types.ModuleType("pywinauto")
    pywinauto.Application = object
    pywinauto.Desktop = object
    timings = types.ModuleType("pywinauto.timings")
    timings.wait_until = lambda *args, **kwargs: None
    monkeypatch.setitem(__import__("sys").modules, "pywinauto", pywinauto)
    monkeypatch.setitem(__import__("sys").modules, "pywinauto.timings", timings)
    import importlib
    import toolbelt_uploader

    return importlib.reload(toolbelt_uploader)


def test_wait_for_ui_returns_controls_without_truthiness_check(uploader):
    class TruthyBrokenControl:
        def __bool__(self):
            raise TypeError("argument of type 'bool' is not iterable")

    control = TruthyBrokenControl()

    assert uploader._wait_for_ui(
        win=None,
        ip="192.168.0.112",
        label="Utilities tab",
        predicate=lambda: control,
        timeout=1,
    ) is control


def test_wait_for_ui_keeps_polling_transient_toolbelt_errors(monkeypatch, uploader):
    attempts = {"count": 0}
    control = object()

    def predicate():
        attempts["count"] += 1
        if attempts["count"] == 1:
            raise TypeError("argument of type 'bool' is not iterable")
        return control

    monkeypatch.setattr(uploader, "POLL", 0)
    start = time.time()

    assert uploader._wait_for_ui(
        win=None,
        ip="192.168.0.112",
        label="Utilities tab",
        predicate=predicate,
        timeout=1,
    ) is control
    assert time.time() - start < 1


def test_credentials_modal_detection_treats_busy_uia_tree_as_not_present(uploader):
    class BusyWindow:
        def window_text(self):
            return ""

        def descendants(self, control_type=None):
            raise TypeError("argument of type 'bool' is not iterable")

    assert uploader._credentials_modal_text(BusyWindow()) == ""
    assert uploader._credentials_modal_present(BusyWindow()) is False


def test_select_device_does_not_open_serial_column_before_manage(uploader):
    source = inspect.getsource(uploader.select_device)

    assert "ensure_serial_column_visible" not in source
    assert "discover_serial_from_row" not in source
