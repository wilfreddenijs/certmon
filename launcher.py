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


def wait_for_server(port, timeout=20):
    for _ in range(timeout * 10):
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.1):
                return True
        except OSError:
            time.sleep(0.1)
    return False


def start_flask(port):
    try:
        log(f"Starting Flask on port {port}")
        log(f"sys.path: {sys.path}")
        log(f"frozen: {getattr(sys, 'frozen', False)}")
        if getattr(sys, 'frozen', False):
            log(f"_MEIPASS: {sys._MEIPASS}")
            log(f"_MEIPASS contents: {os.listdir(sys._MEIPASS)}")

        import logging
        log_wz = logging.getLogger("werkzeug")
        log_wz.setLevel(logging.ERROR)

        from app import app, data_dir
        log(f"app imported OK, data_dir={data_dir()}")
        os.makedirs(data_dir(), exist_ok=True)
        app.run(host="127.0.0.1", port=port, debug=False, use_reloader=False, threaded=True)
    except Exception as e:
        log(f"FLASK ERROR: {e}")
        log(traceback.format_exc())


def make_tray_icon(port):
    try:
        import pystray
        from PIL import Image, ImageDraw

        img = Image.new("RGB", (64, 64), color=(13, 18, 32))
        draw = ImageDraw.Draw(img)
        draw.ellipse([4, 4, 60, 60], outline=(0, 229, 255), width=3)
        draw.text((20, 16), "CM", fill=(0, 229, 255))

        def open_browser(icon, item):
            webbrowser.open(f"http://127.0.0.1:{port}")

        def quit_app(icon, item):
            icon.stop()
            os._exit(0)

        menu = pystray.Menu(
            pystray.MenuItem(f"Open CertMon (:{port})", open_browser, default=True),
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
    log("CertMon starting")
    port = find_free_port(5000)
    log(f"Using port {port}")

    flask_thread = threading.Thread(target=start_flask, args=(port,), daemon=True)
    flask_thread.start()

    if wait_for_server(port):
        log("Server ready, opening browser")
        webbrowser.open(f"http://127.0.0.1:{port}")
    else:
        log("Server did not respond after 20s, opening browser anyway")
        webbrowser.open(f"http://127.0.0.1:{port}")

    make_tray_icon(port)


if __name__ == "__main__":
    main()
