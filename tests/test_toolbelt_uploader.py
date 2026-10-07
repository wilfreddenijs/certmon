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
    serial_enable = source.rindex("ensure_serial_column_visible")
    serial_read = source.rindex("discover_serial_from_row")

    assert "except SerialFallbackNeeded" in source
    assert first_manage < serial_enable < serial_read


@pytest.fixture
def add_ui(monkeypatch, uploader):
    state = types.SimpleNamespace(open=False, submitted=[], filled=[], cancelled=False, reject=False)

    class Control:
        def __init__(self, text, top, action=None):
            self.text = text
            self.top = top
            self.action = action

        def window_text(self):
            return self.text

        def is_visible(self):
            return True

        def is_enabled(self):
            return True

        def rectangle(self):
            return types.SimpleNamespace(left=70, right=420, top=self.top, bottom=self.top + 18)

        def click_input(self):
            if self.action:
                self.action()

    def submit():
        state.submitted.append(dict(state.filled))
        if not state.reject:
            state.open = False

    def cancel():
        state.cancelled = True
        state.open = False

    controls = {
        'Text': [Control('IP Address/Hostname', 100), Control('Username', 160), Control('Password', 220)],
        'Edit': [Control('admin', 185), Control('', 245)],
        'ComboBox': [Control('', 125)],
        'Button': [Control('Add', 300, submit), Control('Cancel', 300, cancel)],
    }
    dialog = types.SimpleNamespace(descendants=lambda control_type: controls.get(control_type, []))

    def open_dialog():
        state.open = True

    win = types.SimpleNamespace(descendants=lambda control_type: [Control('Add', 10, open_dialog)] if control_type == 'Button' else [])
    monkeypatch.setattr(uploader, '_find_add_device_dialog', lambda win: dialog if state.open else None)
    monkeypatch.setattr(uploader, '_fill_edit', lambda edit, root, value: state.filled.append((edit.top, value)) or True)
    monkeypatch.setattr(uploader, '_credentials_rejected_present', lambda root: state.reject)
    counter = iter(range(0, 10000, 3))
    monkeypatch.setattr(uploader, 'time', types.SimpleNamespace(time=lambda: next(counter), sleep=lambda seconds: None))
    return win, state, controls


def test_add_device_fills_address_and_saved_password_without_editing_admin(uploader, add_ui):
    win, state, _ = add_ui
    uploader._DEVICE_CREDENTIALS = {'192.168.0.112': {'username': 'admin', 'password': 'secret'}}
    uploader.add_device(win, '192.168.0.112')
    assert state.filled == [(125, '192.168.0.112'), (245, 'secret')]
    assert len(state.submitted) == 1
    assert not state.open
    assert not state.cancelled


def test_add_device_retries_password_candidates_and_cancels_on_rejection(uploader, add_ui):
    win, state, _ = add_ui
    state.reject = True
    uploader._DEVICE_CREDENTIALS = {'192.168.0.112': {'password_candidates': ['first', 'second']}}
    with pytest.raises(RuntimeError, match='credentials rejected'):
        uploader.add_device(win, '192.168.0.112')
    assert state.filled == [(125, '192.168.0.112'), (245, 'first'), (245, 'second')]
    assert len(state.submitted) == 2
    assert state.cancelled


def test_add_device_requires_serial_fallback_only_after_candidate_rejected(uploader, add_ui):
    win, state, _ = add_ui
    state.reject = True
    uploader._DEVICE_CREDENTIALS = {'192.168.0.112': {'password_candidates': ['extron', '__SERIAL__']}}
    with pytest.raises(uploader.SerialFallbackNeeded):
        uploader.add_device(win, '192.168.0.112')
    assert len(state.submitted) == 1
    assert state.cancelled


def test_add_device_does_not_submit_when_field_fill_fails(monkeypatch, uploader, add_ui):
    win, state, _ = add_ui
    monkeypatch.setattr(uploader, '_fill_edit', lambda *args: False)
    with pytest.raises(RuntimeError, match='address'):
        uploader.add_device(win, '192.168.0.112')
    assert state.submitted == []
    assert state.cancelled


def test_add_device_preserves_credentials_out_of_progress_events(monkeypatch, uploader, add_ui):
    win, state, _ = add_ui
    events = []
    monkeypatch.setattr(uploader, 'emit', lambda event, **fields: events.append((event, fields)))
    uploader._DEVICE_CREDENTIALS = {'192.168.0.112': {'password': 'secret-sentinel'}}
    uploader.add_device(win, '192.168.0.112')
    assert events[0][0] == 'device_adding'
    assert 'secret-sentinel' not in repr(events)


def test_add_serial_candidate_is_not_persisted_before_manage_verification(monkeypatch, uploader, add_ui):
    win, state, _ = add_ui
    uploader._DEVICE_CREDENTIALS = {'192.168.0.112': {'password_candidates': ['__SERIAL__']}}
    monkeypatch.setattr(uploader, '_record_resolved_credential', lambda *args: pytest.fail('Add alone does not confirm authentication'))
    assert uploader.add_device(win, '192.168.0.112', serial='A123456') == ('admin', 'A123456')
    assert len(state.submitted) == 1


def test_main_does_not_start_discovery_for_upload_batches(uploader):
    assert 'ensure_discovery_started' not in inspect.getsource(uploader.main)


def test_select_device_adds_first_then_requires_exact_address_without_discovery(monkeypatch, uploader):
    calls = []
    cell = types.SimpleNamespace(rectangle=lambda: types.SimpleNamespace(top=200, bottom=220),
                                 click_input=lambda: calls.append('row'))
    button = types.SimpleNamespace(element_info=types.SimpleNamespace(automation_id='DeviceDiscoveryUserControl_ManageButton'),
                                   rectangle=cell.rectangle, click_input=lambda: calls.append('manage'))
    tab = types.SimpleNamespace(click_input=lambda: calls.append('utilities'))
    win = types.SimpleNamespace(descendants=lambda control_type: [button] if control_type == 'Button' else [])
    monkeypatch.setattr(uploader, 'add_device', lambda win, ip: calls.append(('add', ip)))

    def find(win, ip, start_discovery):
        assert start_discovery is False
        calls.append(('find', ip))
        return cell

    monkeypatch.setattr(uploader, 'find_device_cell', find)
    monkeypatch.setattr(uploader, 'accept_credentials_prompt', lambda *args, **kwargs: False)
    monkeypatch.setattr(uploader, '_find_text_control', lambda *args: tab)
    monkeypatch.setattr(uploader, '_text_visible', lambda *args: True)
    monkeypatch.setattr(uploader.time, 'sleep', lambda seconds: None)
    uploader.select_device(win, '192.168.0.112')
    assert calls == [('add', '192.168.0.112'), ('find', '192.168.0.112'), 'row', 'manage', 'utilities']


def test_exact_row_matching_does_not_accept_ip_prefix(uploader):
    cell = types.SimpleNamespace(window_text=lambda: '192.168.0.112', is_visible=lambda: True)
    win = types.SimpleNamespace(descendants=lambda control_type: [cell])
    assert uploader._visible_device_cell(win, '192.168.0.11') is None
    assert uploader._visible_device_cell(win, '192.168.0.112') is cell


def test_add_dialog_lookup_is_scoped_to_toolbelt_process(monkeypatch, uploader):
    calls = []
    dialog = types.SimpleNamespace(is_visible=lambda: True)

    def windows(**kwargs):
        calls.append(kwargs)
        return [dialog]

    monkeypatch.setattr(uploader, 'Desktop', lambda **kwargs: types.SimpleNamespace(windows=windows))
    assert uploader._find_add_device_dialog(types.SimpleNamespace(process_id=lambda: 123)) is dialog
    assert calls == [{'process': 123, 'title': 'Add Device'}]


def test_add_device_does_not_put_address_in_another_field(uploader, add_ui):
    win, state, controls = add_ui
    controls['ComboBox'] = []
    with pytest.raises(RuntimeError, match='IP Address/Hostname'):
        uploader.add_device(win, '192.168.0.112')
    assert state.filled == []
    assert state.submitted == []
    assert state.cancelled


def test_add_device_rejects_unsupported_username_before_submit(uploader, add_ui):
    win, state, controls = add_ui
    controls['Edit'][0].is_enabled = lambda: False
    uploader._DEVICE_CREDENTIALS = {'192.168.0.112': {'username': 'other', 'password': 'secret'}}
    with pytest.raises(RuntimeError, match='configured username'):
        uploader.add_device(win, '192.168.0.112')
    assert state.submitted == []
    assert state.cancelled


def test_existing_offscreen_device_is_found_without_discovery(monkeypatch, uploader):
    cell = types.SimpleNamespace(window_text=lambda: '192.168.0.112', is_visible=lambda: True)
    state = {'page': 9}
    scroller = types.SimpleNamespace(wheel_mouse_input=lambda wheel_dist: state.update(page=state['page'] + 1))
    grid = types.SimpleNamespace(is_visible=lambda: True, type_keys=lambda *args, **kwargs: state.update(page=0))

    def descendants(control_type):
        if control_type == 'DataGrid':
            return [grid]
        if control_type == 'ScrollBar':
            return [scroller]
        if control_type in {'Text', 'Hyperlink'}:
            return [cell] if state['page'] == 1 else []
        return []

    monkeypatch.setattr(uploader.time, 'sleep', lambda seconds: None)
    monkeypatch.setattr(uploader, 'ensure_discovery_started', lambda *args, **kwargs: pytest.fail('Discovery must not start'))
    assert uploader.find_device_cell(types.SimpleNamespace(descendants=descendants), '192.168.0.112', start_discovery=False) is cell
    assert state['page'] == 1


def test_serial_column_detection_accepts_ipv4_address_header(uploader):
    source = inspect.getsource(uploader._serial_column_center)
    header_source = inspect.getsource(uploader._grid_header_cells)

    assert '"ipv4 address"' in header_source
    assert '{"ip address", "ipv4 address"} & labels' in source
    assert '"model name" not in labels' not in source


def test_serial_column_detection_handles_rows_far_below_header(uploader):
    class Rect:
        def __init__(self, left, top, right, bottom):
            self.left = left
            self.top = top
            self.right = right
            self.bottom = bottom

    class ElementInfo:
        name = ""
        automation_id = ""
        runtime_id = None

    class Control:
        handle = 1

        def __init__(self, label, rect):
            self.label = label
            self._rect = rect
            self.element_info = ElementInfo()

        def window_text(self):
            return self.label

        def rectangle(self):
            return self._rect

        def is_visible(self):
            return True

    class Window:
        def descendants(self, control_type=None):
            if control_type not in {"Text", "Header", "HeaderItem", "DataItem"}:
                return []
            return [
                Control("IPv4 Address", Rect(100, 112, 190, 148)),
                Control("Hostname", Rect(360, 112, 535, 148)),
                Control("Firmware Version", Rect(995, 112, 1090, 148)),
                Control("Serial Number", Rect(1120, 112, 1180, 148)),
            ]

    assert uploader._serial_column_center(Window(), row_y=350) == 1150
    assert uploader._serial_column_center(Window(), row_y=720) == 1150


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
    assert uploader._LAST_FIELDS_BUTTON_POINT == clicks[0]


def test_serial_column_enable_is_attempted_once_per_run(monkeypatch, uploader):
    calls = {"open": 0}

    def open_fields(_win):
        calls["open"] += 1
        return True

    monkeypatch.setattr(uploader, "_SERIAL_COLUMN_ATTEMPTED", False)
    monkeypatch.setattr(uploader, "_SERIAL_COLUMN_READY", False)
    monkeypatch.setattr(uploader, "_serial_column_visible", lambda win, row_y=None: False)
    monkeypatch.setattr(uploader, "_open_fields_menu", open_fields)
    monkeypatch.setattr(uploader, "_enable_serial_number_field", lambda win: False)
    monkeypatch.setattr(uploader, "_enable_serial_number_field_by_geometry", lambda win: False)

    assert uploader.ensure_serial_column_visible(object(), row_y=100) is False
    assert uploader.ensure_serial_column_visible(object(), row_y=100) is False
    assert calls["open"] == 1


def test_serial_column_control_click_does_not_follow_with_geometry_click(monkeypatch, uploader):
    calls = {"geometry": 0}

    monkeypatch.setattr(uploader, "_SERIAL_COLUMN_ATTEMPTED", False)
    monkeypatch.setattr(uploader, "_SERIAL_COLUMN_READY", False)
    monkeypatch.setattr(uploader, "_serial_column_visible", lambda win, row_y=None: False)
    monkeypatch.setattr(uploader, "_wait_for_serial_column_visible", lambda win, row_y=None: False)
    monkeypatch.setattr(uploader, "_open_fields_menu", lambda win: True)
    monkeypatch.setattr(uploader, "_enable_serial_number_field", lambda win: True)

    def geometry_click(_win):
        calls["geometry"] += 1
        return True

    monkeypatch.setattr(uploader, "_enable_serial_number_field_by_geometry", geometry_click)

    assert uploader.ensure_serial_column_visible(object(), row_y=100) is False
    assert calls["geometry"] == 0


def test_find_device_cell_scrolls_discovery_list_for_offscreen_rows(monkeypatch, uploader):
    monkeypatch.setattr(uploader, "POLL", 0)
    monkeypatch.setattr(uploader, "ensure_discovery_started", lambda *args, **kwargs: True)

    class Rect:
        def __init__(self, top):
            self.left = 100
            self.top = top
            self.right = 220
            self.bottom = top + 24

    class Cell:
        def __init__(self, text, top):
            self.text = text
            self._rect = Rect(top)

        def window_text(self):
            return self.text

        def rectangle(self):
            return self._rect

        def is_visible(self):
            return True

    class ScrollBar:
        def __init__(self, window):
            self.window = window

        def wheel_mouse_input(self, wheel_dist):
            if wheel_dist < 0:
                self.window.page += 1

    class Window:
        def __init__(self):
            self.page = 0

        def descendants(self, control_type=None):
            if control_type in {"Text", "Hyperlink"}:
                if self.page == 0:
                    return [Cell("192.168.0.10", 120), Cell("192.168.0.11", 150)]
                return [Cell("192.168.0.99", 120)]
            if control_type == "ScrollBar":
                return [ScrollBar(self)]
            return []

    win = Window()

    found = uploader.find_device_cell(win, "192.168.0.99")

    assert found is not None
    assert found.window_text() == "192.168.0.99"
    assert win.page == 1


def test_discovery_refresh_does_not_click_first_device_manage_button(uploader):
    class ElementInfo:
        def __init__(self, name="", automation_id=""):
            self.name = name
            self.automation_id = automation_id

    class Control:
        def __init__(self, label, automation_id):
            self.label = label
            self.element_info = ElementInfo(label, automation_id)
            self.clicks = 0

        def window_text(self):
            return self.label

        def is_visible(self):
            return True

        def click_input(self):
            self.clicks += 1

    manage = Control("", "DeviceDiscoveryUserControl_ManageButton")
    discovery = Control("Discovery", "DeviceDiscoveryUserControl_Discover")

    class Window:
        def descendants(self, control_type=None):
            return [manage, discovery] if control_type == "Button" else []

    assert uploader._click_discovery_control(Window()) is True
    assert manage.clicks == 0
    assert discovery.clicks == 1


def test_discovery_refresh_rejects_manage_button_as_only_candidate(uploader):
    class ElementInfo:
        name = ""
        automation_id = "DeviceDiscoveryUserControl_ManageButton"

    class ManageButton:
        element_info = ElementInfo()

        def __init__(self):
            self.clicks = 0

        def window_text(self):
            return ""

        def is_visible(self):
            return True

        def click_input(self):
            self.clicks += 1

    manage = ManageButton()

    class Window:
        def descendants(self, control_type=None):
            return [manage] if control_type == "Button" else []

    assert uploader._click_discovery_control(Window()) is False
    assert manage.clicks == 0
