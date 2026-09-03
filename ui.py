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
        """창을 없애지 않고 숨긴다.

        창을 파괴하면 프로세스가 끝나고, 다시 열 때 WebView2 초기화를 처음부터
        해야 해서 몇 초가 걸린다. 숨겨두면 다음 열기가 즉시 끝난다.
        완전히 끄는 것은 트레이의 "완전히 종료" 가 담당한다.
        """
        hide()


# 창을 보이고 숨기는 일은 Win32 로 직접 한다.
# pywebview 의 show/restore 는 UI 스레드에서 부르도록 만들어져 있어서, 포커스
# 요청을 받은 HTTP 스레드에서 부르면 조용히 아무 일도 일어나지 않았다.
# (최소화된 창에 열기를 눌러도 그대로 최소화 상태로 남던 원인)
_U = ctypes.windll.user32
SW_HIDE, SW_SHOW, SW_RESTORE = 0, 5, 9
_hwnd_cache = None


def hwnd():
    """이 프로세스가 가진 'To-Do Manager' 최상위 창 핸들."""
    global _hwnd_cache
    if _hwnd_cache and _U.IsWindow(_hwnd_cache):
        return _hwnd_cache
    from ctypes import wintypes
    me = os.getpid()
    found = []

    @ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)
    def cb(h, _):
        pid = wintypes.DWORD()
        _U.GetWindowThreadProcessId(h, ctypes.byref(pid))
        if pid.value != me:
            return True
        n = _U.GetWindowTextLengthW(h)
        if n:
            b = ctypes.create_unicode_buffer(n + 1)
            _U.GetWindowTextW(h, b, n + 1)
            if b.value == "To-Do Manager":
                r = wintypes.RECT()
                _U.GetWindowRect(h, ctypes.byref(r))
                found.append((r.right - r.left, h))
        return True

    _U.EnumWindows(cb, 0)
    if not found:
        return None
    _hwnd_cache = max(found)[1]          # 트레이 툴팁 같은 작은 창을 피한다
    return _hwnd_cache


def hide():
    h = hwnd()
    if h:
        _U.ShowWindow(h, SW_HIDE)


def focus():
    """숨어 있거나 최소화된 창을 다시 보여준다."""
    h = hwnd()
    if not h:
        paths.log("ui.focus: 창 핸들을 찾지 못했다")
        return
    _U.ShowWindow(h, SW_SHOW)
    _U.ShowWindow(h, SW_RESTORE)
    _U.SetForegroundWindow(h)
    _U.BringWindowToTop(h)
    _nudge(h)


def _nudge(h):
    """숨김·최소화에서 돌아오면 WebView2 가 내용을 다시 그리지 않는 때가 있다.
    창 크기를 1px 흔들어 강제로 다시 그리게 한다."""
    from ctypes import wintypes
    r = wintypes.RECT()
    if not _U.GetWindowRect(h, ctypes.byref(r)):
        return
    w, ht = r.right - r.left, r.bottom - r.top
    SWP_NOZORDER = 0x0004
    _U.SetWindowPos(h, None, r.left, r.top, w - 1, ht - 1, SWP_NOZORDER)
    _U.SetWindowPos(h, None, r.left, r.top, w, ht, SWP_NOZORDER)


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
        hidden="--hidden" in sys.argv,      # 자동 실행 때 미리 만들어만 둔다
    )
    icon = paths.ICON
    try:
        webview.start(icon=icon if os.path.exists(icon) else None)
    except TypeError:
        webview.start()


if __name__ == "__main__":
    main()
