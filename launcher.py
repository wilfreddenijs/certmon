"""
CertMon Launcher
- Starts Flask server on port 5000
- Opens browser automatically
- System tray icon to quit
"""

import sys
import os
import threading
import time
import webbrowser
import socket
import traceback
from pathlib import Path

# When frozen by PyInstaller, add the bundle dir to sys.path
if getattr(sys, 'frozen', False):
    bundle_dir = sys._MEIPASS
    if bundle_dir not in sys.path:
        sys.path.insert(0, bundle_dir)
    # Write errors to a log file next to the exe
    log_path = os.path.join(os.path.dirname(sys.executable), "certmon_error.log")
else:
    log_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "certmon_error.log")

def log(msg):
    try:
        with open(log_path, "a") as f:
            f.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} {msg}\n")
    except Exception:
        pass

# Suppress Werkzeug reloader


def find_free_port(start=5000):
    for port in range(start, start + 20):
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.bind(("127.0.0.1", port))
                return port
        except OSError:
            continue
    return start


def browser_host_for_bind(bind_host):
    normalized = (bind_host or "").strip().lower()
    if normalized in {"0.0.0.0", "::", ""}:
        return "127.0.0.1"
    return bind_host


def wait_for_server(host, port, timeout=20):
    host = browser_host_for_bind(host)
    for _ in range(timeout * 10):
        try:
            with socket.create_connection((host, port), timeout=0.1):
                return True
        except OSError:
            time.sleep(0.1)
    return False


def start_flask(runtime):
    try:
        log(f"Starting Flask on {runtime.bind_host}:{runtime.port}")
        log(f"sys.path: {sys.path}")
        log(f"frozen: {getattr(sys, 'frozen', False)}")
        if getattr(sys, 'frozen', False):
            log(f"_MEIPASS: {sys._MEIPASS}")
            log(f"_MEIPASS contents: {os.listdir(sys._MEIPASS)}")

        import logging
        log_wz = logging.getLogger("werkzeug")
        log_wz.setLevel(logging.ERROR)

        app_module = initialize_application()
        log(f"app initialized OK, data_dir={app_module.data_dir()}")
        app_module.app.run(
            host=runtime.bind_host,
            port=runtime.port,
            debug=False,
            use_reloader=False,
            threaded=True,
        )
    except Exception as e:
        log(f"FLASK ERROR: {e}")
        log(traceback.format_exc())


def resolve_launcher_runtime():
    from certmon.config import resolve_runtime_config

    runtime = resolve_runtime_config(
        frozen=getattr(sys, "frozen", False),
        executable=Path(sys.executable),
        source_dir=Path(__file__).resolve().parent,
    )
    if runtime.server_mode:
        return runtime
    return runtime.__class__(
        data_dir=runtime.data_dir,
        bind_host=runtime.bind_host,
        port=find_free_port(runtime.port),
        server_mode=runtime.server_mode,
        auth_required=runtime.auth_required,
    )


def initialize_application():
    """Initialize persistent services and recover jobs before serving requests."""
    import app as app_module

    os.makedirs(app_module.data_dir(), exist_ok=True)
    app_module.database.initialize()
    if app_module.vault is not None:
        app_module.vault.initialize()
    if app_module.acme_order_service is not None:
        app_module.renewal_service.recover_interrupted_jobs(
            app_module.acme_order_service
        )
    return app_module


def make_tray_icon(runtime):
    try:
        import pystray
        from PIL import Image, ImageDraw

        img = Image.new("RGB", (64, 64), color=(13, 18, 32))
        draw = ImageDraw.Draw(img)
        draw.ellipse([4, 4, 60, 60], outline=(0, 229, 255), width=3)
        draw.text((20, 16), "CM", fill=(0, 229, 255))

        def open_browser(icon, item):
            webbrowser.open(f"http://{browser_host_for_bind(runtime.bind_host)}:{runtime.port}")

        def quit_app(icon, item):
            icon.stop()
            os._exit(0)

        menu = pystray.Menu(
            pystray.MenuItem(f"Open CertMon (:{runtime.port})", open_browser, default=True),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Quit", quit_app),
        )

        icon = pystray.Icon("CertMon", img, "CertMon", menu)
        icon.run()

    except Exception as e:
        log(f"TRAY ERROR: {e}")
        while True:
            time.sleep(1)


def main():
    if len(sys.argv) > 1 and sys.argv[1] == "--toolbelt-uploader":
        # PyInstaller builds have sys.executable == CertMon.exe. The Toolbelt
        # batch service therefore re-enters this EXE with a dedicated child mode
        # instead of launching another tray/server instance.
        try:
            sys.argv = [sys.argv[0], *sys.argv[2:]]
            import toolbelt_uploader

            toolbelt_uploader.main()
        except Exception as e:
            print(str(e), flush=True)
            log(f"TOOLBELT UPLOADER ERROR: {e}")
            log(traceback.format_exc())
            sys.exit(2)
        return

    log("CertMon starting")
    try:
        from certmon.config import ConfigError

        runtime = resolve_launcher_runtime()
    except ConfigError as exc:
        message = str(exc)
        log(f"CONFIG ERROR: {message}")
        print(message, file=sys.stderr)
        try:
            import tkinter.messagebox

            tkinter.messagebox.showerror("CertMon configuration error", message)
        except Exception:
            pass
        sys.exit(2)

    log(f"Using {runtime.bind_host}:{runtime.port}")

    flask_thread = threading.Thread(target=start_flask, args=(runtime,), daemon=True)
    flask_thread.start()

    browser_host = browser_host_for_bind(runtime.bind_host)
    browser_url = f"http://{browser_host}:{runtime.port}"
    if wait_for_server(runtime.bind_host, runtime.port):
        log("Server ready, opening browser")
        webbrowser.open(browser_url)
    else:
        log("Server did not respond after 20s, opening browser anyway")
        webbrowser.open(browser_url)

    make_tray_icon(runtime)


if __name__ == "__main__":
    main()
