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

    first_open = source.index("ip_cell.click_input()")
    serial_enable = source.rindex("ensure_serial_column_visible")
    serial_read = source.rindex("discover_serial_from_row")

    assert "except SerialFallbackNeeded" in source
    assert first_open < serial_enable < serial_read
    assert 'DeviceDiscoveryUserControl_ManageButton' not in source


@pytest.fixture
def add_ui(monkeypatch, uploader, request):
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
    native_kind = getattr(request, 'param', 'uia')
    if native_kind in {'win32', 'win32_generic_labels'}:
        for kind, items in controls.items():
            for item in items:
                item.friendly_class_name = lambda kind=kind: (
                    ('Window' if native_kind == 'win32_generic_labels' else 'Static') if kind == 'Text' else kind)
        dialog = types.SimpleNamespace(
            backend=types.SimpleNamespace(name='win32'),
            descendants=lambda: [item for items in controls.values() for item in items])
    else:
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


@pytest.mark.parametrize('add_ui', ['uia', 'win32', 'win32_generic_labels'], indirect=True)
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


def test_structured_credentials_keep_usernames_and_serial_last(uploader):
    credential = {'credential_candidates': [
        {'username': 'operator', 'password': 'same'},
        {'username': 'admin', 'password': 'same'},
        {'username': 'admin', 'password': 'extron'},
    ]}
    assert uploader._credential_attempts(credential, 'SERIAL') == [
        ('operator', 'same', 'configured'), ('admin', 'same', 'configured'),
        ('admin', 'extron', 'configured'), ('admin', 'SERIAL', 'serial')]


@pytest.mark.parametrize('serial', [None, 'SERIAL'])
def test_add_device_uses_individual_shared_default_then_serial(uploader, add_ui, serial):
    win, state, controls = add_ui
    state.reject = True
    original_submit = controls['Button'][0].action

    def submit():
        state.reject = len(state.submitted) < (3 if serial else 2)
        original_submit()

    controls['Button'][0].action = submit
    uploader._DEVICE_CREDENTIALS = {'192.168.0.112': {
        'credential_candidates': [{'username': 'admin', 'password': p} for p in ('individual', 'shared', 'extron')],
        'password_candidates': ['individual', 'shared', 'extron', '__SERIAL__'],
    }}
    uploader.add_device(win, '192.168.0.112', serial=serial)
    passwords = [value for top, value in state.filled if top == 245]
    assert passwords == ['individual', 'shared', 'extron'] + ([serial] if serial else [])
    assert len(state.submitted) == len(passwords)
    assert not state.open


@pytest.mark.parametrize('add_ui', ['uia', 'win32_generic_labels'], indirect=True)
def test_add_authentication_failed_retries_extron_without_timeout(monkeypatch, uploader, add_ui):
    win, state, controls = add_ui
    status = types.SimpleNamespace(
        window_text=lambda: 'Authentication Failed', is_visible=lambda: state.reject,
        friendly_class_name=lambda: 'Window',
        rectangle=lambda: types.SimpleNamespace(left=70, right=420, top=270, bottom=288))
    controls['Text'].append(status)
    original_submit = controls['Button'][0].action

    def submit():
        state.reject = len(state.submitted) == 0
        original_submit()

    controls['Button'][0].action = submit
    monkeypatch.setattr(uploader, '_credentials_rejected_present', lambda dialog: uploader._dialog_status_present(dialog, ('authentication failed',)))
    monkeypatch.setattr(uploader, '_add_dialog_uia', lambda dialog: None)
    uploader._DEVICE_CREDENTIALS = {'192.168.0.112': {'username': 'admin', 'password_candidates': ['wrong-shared', 'extron', '__SERIAL__']}}
    uploader.add_device(win, '192.168.0.112', timeout=20)
    assert state.filled == [(125, '192.168.0.112'), (245, 'wrong-shared'), (245, 'extron')]
    assert len(state.submitted) == 2
    assert not state.open
    assert not state.cancelled


@pytest.mark.parametrize('visible, text, expected', [
    (True, 'Authentication Failed', True),
    (True, 'AUTHENTICATION   FAILED', True),
    (True, 'Authentication Failure', True),
    (False, 'Authentication Failed', False),
])
def test_authentication_failure_detection_requires_visible_status(uploader, visible, text, expected):
    status = types.SimpleNamespace(window_text=lambda: text, is_visible=lambda: visible)
    dialog = types.SimpleNamespace(descendants=lambda control_type: [status] if control_type == 'Text' else [])
    assert uploader._credentials_rejected_present(dialog) is expected


def test_authentication_status_ignores_password_edit_values(uploader):
    password = types.SimpleNamespace(window_text=lambda: 'authentication failed', is_visible=lambda: True)
    dialog = types.SimpleNamespace(descendants=lambda control_type: [password] if control_type == 'Edit' else [])
    assert not uploader._credentials_rejected_present(dialog)


@pytest.mark.parametrize('add_ui', ['uia', 'win32_generic_labels'], indirect=True)
def test_add_device_unreachable_stops_without_password_or_serial_retry(uploader, add_ui):
    win, state, controls = add_ui
    state.reject = True
    status = types.SimpleNamespace(
        window_text=lambda: 'Device Unreachable', is_visible=lambda: True,
        friendly_class_name=lambda: 'Window',
        rectangle=lambda: types.SimpleNamespace(left=70, right=420, top=270, bottom=288))
    controls['Text'].append(status)
    uploader._DEVICE_CREDENTIALS = {'192.168.0.112': {'password_candidates': ['first', 'second', '__SERIAL__']}}
    with pytest.raises(uploader.DeviceUnreachableError, match='Device unreachable: 192.168.0.112'):
        uploader.add_device(win, '192.168.0.112')
    assert len(state.submitted) == 1
    assert state.filled == [(125, '192.168.0.112'), (245, 'first')]
    assert state.cancelled


@pytest.mark.parametrize('visible, text, expected', [
    (True, 'DEVICE   UNREACHABLE', True),
    (False, 'Device Unreachable', False),
    (True, 'Credentials are incorrect', False),
])
def test_unreachable_detection_requires_visible_status(uploader, visible, text, expected):
    status = types.SimpleNamespace(window_text=lambda: text, is_visible=lambda: visible)
    dialog = types.SimpleNamespace(descendants=lambda control_type: [status] if control_type == 'Text' else [])
    assert uploader._device_unreachable_present(dialog) is expected


def test_native_unreachable_status_does_not_wait_for_uia(monkeypatch, uploader):
    status = types.SimpleNamespace(window_text=lambda: 'Device Unreachable', is_visible=lambda: True,
                                   friendly_class_name=lambda: 'Window')
    native = types.SimpleNamespace(backend=types.SimpleNamespace(name='win32'), descendants=lambda: [status])
    monkeypatch.setattr(uploader, '_add_dialog_uia', lambda dialog: pytest.fail('visible native error must stop immediately'))
    assert uploader._device_unreachable_present(native)


def test_native_unreachable_detection_can_read_uia_status(monkeypatch, uploader):
    status = types.SimpleNamespace(window_text=lambda: 'Device Unreachable', is_visible=lambda: True)
    alternate = types.SimpleNamespace(descendants=lambda control_type: [status] if control_type == 'Text' else [])
    native = types.SimpleNamespace(backend=types.SimpleNamespace(name='win32'), descendants=lambda: [])
    monkeypatch.setattr(uploader, '_add_dialog_uia', lambda dialog: alternate)
    assert uploader._device_unreachable_present(native)


@pytest.mark.parametrize('commit', [False, True])
def test_batch_skips_unreachable_without_reconnecting_and_continues(monkeypatch, uploader, tmp_path, commit):
    devices = tmp_path / 'devices.txt'
    devices.write_text('10.10.186.105,offline.pem\n10.10.187.112,online.pem\n', encoding='utf-8')
    monkeypatch.setattr(__import__('sys'), 'argv', ['toolbelt_uploader', '--list', str(devices)] + (['--commit'] if commit else []))
    calls, events, connections = [], [], []
    monkeypatch.setattr(uploader, 'setup_logging', lambda: None)
    monkeypatch.setattr(uploader, 'emit', lambda event, **fields: events.append((event, fields)))
    monkeypatch.setattr(uploader, 'connect_toolbelt', lambda: connections.append('connect') or (None, None))
    monkeypatch.setattr(uploader, 'ensure_connection', lambda app, win: (app, win))
    monkeypatch.setattr(uploader, '_close_stray_dialogs', lambda win: None)
    monkeypatch.setattr(uploader, '_write_resolved_credentials', lambda: None)
    monkeypatch.setattr(uploader.time, 'sleep', lambda seconds: None)

    def upload(app, win, ip, *args):
        calls.append(ip)
        if ip == '10.10.186.105':
            raise uploader.DeviceUnreachableError('Device unreachable: ' + ip)
        return True, 'verified' if commit else 'dry-run (not applied)'

    monkeypatch.setattr(uploader, 'upload_to_device', upload)
    uploader.main()
    assert calls == ['10.10.186.105', '10.10.187.112']
    assert connections == ['connect']
    failure = 'upload_failed' if commit else 'dry_run_failed'
    success = 'upload_ok' if commit else 'dry_run_ok'
    assert any(event == failure and fields['selector'] == '10.10.186.105' for event, fields in events)
    assert any(event == success and fields['selector'] == '10.10.187.112' for event, fields in events)
    assert events[-1] == ('run_finished', {'ok': 1, 'total': 2, 'status': 'complete'})


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


@pytest.mark.parametrize('has_manage_button', [True, False])
def test_select_device_adds_first_then_requires_exact_address_without_discovery(monkeypatch, uploader, has_manage_button):
    calls = []
    cell = types.SimpleNamespace(rectangle=lambda: types.SimpleNamespace(top=200, bottom=220),
                                 click_input=lambda: calls.append('row'))
    button = types.SimpleNamespace(element_info=types.SimpleNamespace(automation_id='DeviceDiscoveryUserControl_ManageButton'),
                                   rectangle=cell.rectangle, click_input=lambda: pytest.fail('IP link already opens management'))
    tab = types.SimpleNamespace(click_input=lambda: calls.append('utilities'))
    win = types.SimpleNamespace(descendants=lambda control_type: [button] if control_type == 'Button' and has_manage_button else [])
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
    assert calls == [('add', '192.168.0.112'), ('find', '192.168.0.112'), 'row', 'utilities']


def test_exact_row_matching_does_not_accept_ip_prefix(uploader):
    cell = types.SimpleNamespace(window_text=lambda: '192.168.0.112', is_visible=lambda: True)
    win = types.SimpleNamespace(descendants=lambda control_type: [cell])
    assert uploader._visible_device_cell(win, '192.168.0.11') is None
    assert uploader._visible_device_cell(win, '192.168.0.112') is cell


@pytest.mark.parametrize('control_type', ['Button', 'MenuItem', 'Custom', 'Text'])
def test_add_toolbar_accepts_accessibility_name_and_control_types(uploader, control_type):
    clicks = []
    rect = types.SimpleNamespace(left=80, right=140, top=50, bottom=110)
    control = types.SimpleNamespace(
        is_visible=lambda: True, is_enabled=lambda: True, window_text=lambda: '',
        element_info=types.SimpleNamespace(name='Add', automation_id=''),
        rectangle=lambda: rect, click_input=lambda: clicks.append('add'),
    )
    toolbar = types.SimpleNamespace(descendants=lambda control_type: [control] if control_type == kind else [])
    kind = control_type
    win = types.SimpleNamespace(descendants=lambda control_type: [toolbar] if control_type == 'ToolBar' else [])
    uploader._click_add_toolbar(win)
    assert clicks == ['add']


def test_add_toolbar_deduplicates_button_and_label(uploader):
    clicks = []

    def control(left, right, top, bottom):
        return types.SimpleNamespace(
            is_visible=lambda: True, window_text=lambda: 'Add',
            rectangle=lambda: types.SimpleNamespace(left=left, right=right, top=top, bottom=bottom),
            click_input=lambda: clicks.append(left),
        )

    button, text = control(80, 140, 50, 110), control(100, 125, 90, 105)
    win = types.SimpleNamespace(descendants=lambda control_type: {'Button': [button], 'Text': [text]}.get(control_type, []))
    uploader._click_add_toolbar(win)
    assert clicks == [80]


def test_add_toolbar_does_not_guess_between_independent_add_controls(uploader):
    def control(left):
        return types.SimpleNamespace(
            is_visible=lambda: True, window_text=lambda: 'Add',
            rectangle=lambda: types.SimpleNamespace(left=left, right=left + 60, top=50, bottom=110),
            click_input=lambda: pytest.fail('Ambiguous Add controls must not be clicked'),
        )

    win = types.SimpleNamespace(descendants=lambda control_type: [control(80), control(200)] if control_type == 'Button' else [])
    with pytest.raises(RuntimeError, match='ambiguous'):
        uploader._click_add_toolbar(win)


def test_add_toolbar_uses_native_fallback_when_uia_exposes_no_button(monkeypatch, uploader):
    calls = []
    monkeypatch.setattr(uploader, '_click_native_add_toolbar', lambda win: calls.append('native') or True)
    uploader._click_add_toolbar(types.SimpleNamespace(descendants=lambda control_type: []))
    assert calls == ['native']


def test_native_add_toolbar_targets_same_window_and_exact_button(monkeypatch, uploader):
    calls = []
    button = types.SimpleNamespace(is_enabled=lambda: True, click_input=lambda: calls.append('click'))

    def find_button(name, exact):
        assert name == 'Add' and exact is True
        return button

    toolbar = types.SimpleNamespace(is_visible=lambda: True, button=find_button)
    native = types.SimpleNamespace(descendants=lambda class_name: [toolbar] if class_name == 'ToolbarWindow32' else [])

    class Application:
        def __init__(self, backend):
            assert backend == 'win32'

        def connect(self, handle):
            calls.append(('connect', handle))
            return self

        def window(self, handle):
            calls.append(('window', handle))
            return native

    monkeypatch.setattr(uploader, 'Application', Application)
    assert uploader._click_native_add_toolbar(types.SimpleNamespace(handle=123))
    assert calls == [('connect', 123), ('window', 123), 'click']


def test_closed_4503_port_does_not_skip_toolbelt_add(monkeypatch, uploader):
    calls = []
    monkeypatch.setattr(uploader, 'reachable', lambda ip: False)
    monkeypatch.setattr(uploader.os.path, 'exists', lambda path: True)
    monkeypatch.setattr(uploader, 'bring_to_front', lambda win: None)
    monkeypatch.setattr(uploader, 'select_device', lambda win, ip: calls.append(ip))
    monkeypatch.setattr(uploader, 'find_ssl_controls', lambda win: {'dots_btn': None, 'pass_edit': None})
    monkeypatch.setattr(uploader, 'set_cert_path', lambda *args: None)
    monkeypatch.setattr(uploader, 'set_passphrase', lambda *args: None)
    assert uploader.upload_to_device(None, None, '10.10.186.105', 'test.pem', '', False) == (True, 'dry-run (not applied)')
    assert calls == ['10.10.186.105']


def test_add_dialog_lookup_is_scoped_to_toolbelt_process(monkeypatch, uploader):
    calls = []
    dialog = types.SimpleNamespace(is_visible=lambda: True)

    def windows(**kwargs):
        calls.append(kwargs)
        return [dialog]

    monkeypatch.setattr(uploader, 'Desktop', lambda **kwargs: types.SimpleNamespace(windows=windows))
    assert uploader._find_add_device_dialog(types.SimpleNamespace(process_id=lambda: 123)) is dialog
    assert calls == [{'process': 123, 'title_re': r'(?i)^\s*Add Device\s*$'}]


@pytest.mark.parametrize('native_state', ['missing', 'error'])
def test_add_dialog_lookup_falls_back_to_uia(monkeypatch, uploader, native_state):
    backends = []
    dialog = types.SimpleNamespace(is_visible=lambda: True)

    def desktop(backend):
        backends.append(backend)

        def windows(**kwargs):
            assert kwargs['process'] == 123
            if backend == 'win32':
                if native_state == 'error':
                    raise RuntimeError('native busy')
                return []
            return [dialog]

        return types.SimpleNamespace(windows=windows)

    monkeypatch.setattr(uploader, 'Desktop', desktop)
    assert uploader._find_add_device_dialog(types.SimpleNamespace(process_id=lambda: 123)) is dialog
    assert backends == ['win32', 'uia']


def test_add_dialog_lookup_rejects_multiple_native_modals(monkeypatch, uploader):
    dialog = types.SimpleNamespace(is_visible=lambda: True)
    monkeypatch.setattr(uploader, 'Desktop', lambda **kwargs: types.SimpleNamespace(windows=lambda **kwargs: [dialog, dialog]))
    with pytest.raises(RuntimeError, match='Multiple Toolbelt'):
        uploader._find_add_device_dialog(types.SimpleNamespace(process_id=lambda: 123))


def test_native_add_dialog_controls_use_friendly_classes(uploader):
    label = types.SimpleNamespace(friendly_class_name=lambda: 'Static', window_text=lambda: 'failed to connect', is_visible=lambda: True)
    edit = types.SimpleNamespace(friendly_class_name=lambda: 'Edit', window_text=lambda: '')
    dialog = types.SimpleNamespace(backend=types.SimpleNamespace(name='win32'), descendants=lambda: [label, edit])
    assert uploader._add_dialog_controls(dialog, 'Text') == [label]
    assert uploader._add_dialog_controls(dialog, 'Edit') == [edit]
    assert uploader._credentials_rejected_present(dialog)


def test_add_field_falls_back_to_uia_for_same_native_handle(monkeypatch, uploader):
    rect = lambda top: types.SimpleNamespace(left=70, right=420, top=top, bottom=top + 18)
    label = types.SimpleNamespace(window_text=lambda: 'IP Address/Hostname', rectangle=lambda: rect(100))
    address = types.SimpleNamespace(is_visible=lambda: True, rectangle=lambda: rect(125))
    alternate = types.SimpleNamespace(descendants=lambda control_type: {'Text': [label], 'ComboBox': [address]}.get(control_type, []))
    calls = []

    def desktop(backend):
        assert backend == 'uia'

        def window(**kwargs):
            calls.append(kwargs)
            return types.SimpleNamespace(wrapper_object=lambda: alternate)

        return types.SimpleNamespace(window=window)

    monkeypatch.setattr(uploader, 'Desktop', desktop)
    native = types.SimpleNamespace(backend=types.SimpleNamespace(name='win32'), handle=987, descendants=lambda: [])
    assert uploader._add_device_edit(native, 'IP Address/Hostname') is address
    assert calls == [{'handle': 987}]


def test_add_buttons_fall_back_to_uia_for_same_native_handle(monkeypatch, uploader):
    button = object()
    alternate = types.SimpleNamespace(descendants=lambda control_type: [button] if control_type == 'Button' else [])
    calls = []
    monkeypatch.setattr(uploader, 'Desktop', lambda backend: types.SimpleNamespace(
        window=lambda **kwargs: calls.append(kwargs) or types.SimpleNamespace(wrapper_object=lambda: alternate)))
    native = types.SimpleNamespace(backend=types.SimpleNamespace(name='win32'), handle=987, descendants=lambda: [])
    assert uploader._add_dialog_controls(native, 'Button') == [button]
    assert calls == [{'handle': 987}]


def test_add_dialog_diagnostics_never_read_control_values(uploader, caplog):
    control = types.SimpleNamespace(
        class_name=lambda: 'WindowsForms10.EDIT', friendly_class_name=lambda: 'Edit',
        rectangle=lambda: types.SimpleNamespace(left=1, right=20, top=3, bottom=10),
        window_text=lambda: pytest.fail('diagnostics must not read credential values'))
    uploader._log_add_dialog_structure(types.SimpleNamespace(descendants=lambda: [control]))
    assert 'WindowsForms10.EDIT' in caplog.text


@pytest.mark.parametrize('add_ui', ['win32_generic_labels'], indirect=True)
def test_generic_native_labels_ignore_container_bounds(uploader, add_ui):
    win, state, controls = add_ui
    panel = types.SimpleNamespace(
        friendly_class_name=lambda: 'Window', window_text=lambda: '',
        rectangle=lambda: types.SimpleNamespace(left=70, right=420, top=120, bottom=280))
    controls['Text'].append(panel)
    uploader._DEVICE_CREDENTIALS = {'192.168.0.112': {'password': 'secret'}}
    uploader.add_device(win, '192.168.0.112')
    assert state.filled == [(125, '192.168.0.112'), (245, 'secret')]
    assert len(state.submitted) == 1


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
