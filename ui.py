# -*- coding: utf-8 -*-
"""'To-Do Manager' 앱 창 (네이티브 WebView2 창). 서비스와 별도 프로세스로 뜬다."""
import ctypes, os, socket, sys, threading, time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import webview

import paths

BASE = paths.APP_DIR
HOST, SERVICE_PORT = "127.0.0.1", 8777
SERVICE_URL = f"http://{HOST}:{SERVICE_PORT}/"
UI_PORT = 8779          # 창 단일 실행 + 포커스 요청용


class Api:
    """자체 타이틀바 버튼."""

    def minimize(self):
        w = webview.windows[0]
        w.minimize()

    def toggle_max(self):
        w = webview.windows[0]
        if getattr(w, "_maxed", False):
            w.restore()
            w._maxed = False
        else:
            w.maximize()
            w._maxed = True

    def close(self):
        webview.windows[0].destroy()


def focus():
    try:
        w = webview.windows[0]
        w.restore()
        w.on_top = True
        w.on_top = False
    except Exception:
        pass


def _destroy_all():
    """서비스가 종료를 알려왔을 때 창을 닫는다 → webview.start() 가 반환되며 프로세스 종료."""
    try:
        for w in list(webview.windows):
            w.destroy()
    except Exception:
        pass
    threading.Timer(1.5, lambda: os._exit(0)).start()   # 혹시 안 닫히면 강제


class FocusHandler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_GET(self):
        quitting = self.path.split("?")[0] == "/quit"
        if not quitting:
            focus()
        self.send_response(200)
        self.send_header("Content-Length", "2")
        self.end_headers()
        try:
            self.wfile.write(b"ok")
        except Exception:
            pass
        if quitting:
            threading.Timer(0.1, _destroy_all).start()

    do_POST = do_GET


def watch_service():
    """서비스가 죽었으면 창도 닫는다. 서버 없는 빈 창이 남지 않게."""
    misses = 0
    while True:
        time.sleep(15)
        try:
            with socket.create_connection((HOST, SERVICE_PORT), 1.0):
                misses = 0
        except OSError:
            misses += 1
            if misses >= 3:            # 45초 연속 응답 없음
                _destroy_all()
                return


def already_open():
    """창이 이미 떠 있으면 그 창을 앞으로 불러오고 True."""
    try:
        with socket.create_connection(("127.0.0.1", UI_PORT), 0.4) as s:
            s.sendall(b"GET /focus HTTP/1.0\r\n\r\n")
            s.recv(16)
        return True
    except OSError:
        return False


def main():
    if already_open():
        return
    try:
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("TodoManager.App")
    except Exception:
        pass

    try:
        guard = ThreadingHTTPServer(("127.0.0.1", UI_PORT), FocusHandler)
        threading.Thread(target=guard.serve_forever, daemon=True).start()
        threading.Thread(target=watch_service, daemon=True).start()
    except OSError:
        return

    webview.create_window(
        "To-Do Manager", SERVICE_URL, js_api=Api(),
        width=1020, height=880, min_size=(760, 620),
        frameless=True, easy_drag=False, background_color="#DDE3E2",
    )
    icon = paths.ICON
    try:
        webview.start(icon=icon if os.path.exists(icon) else None)
    except TypeError:
        webview.start()


if __name__ == "__main__":
    main()
