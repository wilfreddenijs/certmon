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

# Suppress Flask console window on Windows
os.environ["WERKZEUG_RUN_MAIN"] = "true"


def find_free_port(start=5000):
    for port in range(start, start + 20):
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.bind(("127.0.0.1", port))
                return port
        except OSError:
            continue
    return start


def wait_for_server(port, timeout=15):
    for _ in range(timeout * 10):
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.1):
                return True
        except OSError:
            time.sleep(0.1)
    return False


def start_flask(port):
    import logging
    log = logging.getLogger("werkzeug")
    log.setLevel(logging.ERROR)

    from app import app, data_dir
    os.makedirs(data_dir(), exist_ok=True)
    app.run(host="127.0.0.1", port=port, debug=False, use_reloader=False)


def make_tray_icon(port):
    """Create a simple system tray icon using pystray."""
    try:
        import pystray
        from PIL import Image, ImageDraw

        # Draw a simple icon: dark background, cyan "C"
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

    except ImportError:
        # pystray not available — just keep process alive
        while True:
            time.sleep(1)


def main():
    port = find_free_port(5000)

    # Start Flask in background thread
    flask_thread = threading.Thread(target=start_flask, args=(port,), daemon=True)
    flask_thread.start()

    # Wait for server to be ready, then open browser
    if wait_for_server(port):
        webbrowser.open(f"http://127.0.0.1:{port}")
    else:
        print(f"Server did not start in time on port {port}")

    # Run tray icon (blocks until quit)
    make_tray_icon(port)


if __name__ == "__main__":
    main()
