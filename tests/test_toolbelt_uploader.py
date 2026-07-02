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


def test_select_device_opens_serial_column_only_after_rejected_credentials(uploader):
    source = inspect.getsource(uploader.select_device)

    first_manage = source.index("manage.click_input()")
    serial_enable = source.index("ensure_serial_column_visible")
    serial_read = source.index("discover_serial_from_row")

    assert "except SerialFallbackNeeded" in source
    assert first_manage < serial_enable < serial_read


def test_serial_column_detection_accepts_ipv4_address_header(uploader):
    source = inspect.getsource(uploader._serial_column_center)
    header_source = inspect.getsource(uploader._grid_header_cells)

    assert '"ipv4 address"' in header_source
    assert '{"ip address", "ipv4 address"} & labels' in source
    assert '"model name" not in labels' not in source


def test_open_fields_menu_prefers_visible_fields_button_geometry(monkeypatch, uploader):
    clicks = []
    mouse = types.ModuleType("pywinauto.mouse")
    mouse.click = lambda coords: clicks.append(coords)
    monkeypatch.setitem(__import__("sys").modules, "pywinauto.mouse", mouse)
    monkeypatch.setattr(uploader, "POLL", 0)

    class Rect:
        def __init__(self, left, top, right, bottom):
            self.left = left
            self.top = top
            self.right = right
            self.bottom = bottom

        def width(self):
            return self.right - self.left

        def height(self):
            return self.bottom - self.top

    class Control:
        handle = 1

        def __init__(self, label, rect):
            self.label = label
            self._rect = rect
            self.element_info = types.SimpleNamespace(runtime_id=(label, rect.left))

        def window_text(self):
            return self.label

        def rectangle(self):
            return self._rect

        def is_visible(self):
            return True

    class Window:
        def descendants(self, control_type=None):
            if control_type == "Text":
                return [
                    Control("Filter", Rect(360, 46, 426, 102)),
                    Control("Fields", Rect(505, 70, 550, 100)),
                ]
            if control_type in {"Button", "SplitButton", "MenuItem"}:
                return []
            return []

    assert uploader._open_fields_menu(Window()) is True
    assert clicks
    assert clicks[0][0] >= 500
