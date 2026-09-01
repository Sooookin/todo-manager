# -*- coding: utf-8 -*-
"""To-Do Manager - 백그라운드 서비스: API 서버 + 알림 스케줄러 + 알림 카드 루프."""
import json, os, socket, subprocess, sys, threading, time, traceback, webbrowser
from datetime import date, datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import autostart
import paths
import recur, store, toast, tray

BASE = paths.APP_DIR
WEB = paths.WEB_DIR
HOST, PORT = "127.0.0.1", 8777
UI_PORT = 8779                  # 창 프로세스(ui.py) 가 듣는 포트
CRLF = bytes([13, 10])
URL = f"http://{HOST}:{PORT}/"
NO_WINDOW = 0x08000000

BROWSERS = [
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
]


def log(msg):
    """빌드본은 콘솔이 없다. 문제를 파일로 남긴다."""
    paths.log(msg)


def open_window():
    """앱 창을 새 프로세스로 띄운다. pywebview 를 못 쓰면 Edge 앱 창으로 폴백."""
    log(f"open_window: frozen={paths.FROZEN} exe={sys.executable!r}")
    try:
        import webview  # noqa: F401
        if paths.FROZEN:
            # --windowed 빌드는 표준 입출력 핸들이 없다. 명시하지 않으면
            # Popen 이 부모 핸들을 복제하려다 실패할 수 있다.
            subprocess.Popen([sys.executable, "--ui"], cwd=BASE,
                             creationflags=NO_WINDOW,
                             stdin=subprocess.DEVNULL,
                             stdout=subprocess.DEVNULL,
                             stderr=subprocess.DEVNULL)
            log("open_window: 창 프로세스 생성 요청 완료")
        else:
            exe = sys.executable or "python.exe"
            pyw = os.path.join(os.path.dirname(exe), "pythonw.exe")
            runner = pyw if os.path.exists(pyw) else exe
            subprocess.Popen([runner, os.path.join(BASE, "main.py"), "--ui"],
                             cwd=BASE, creationflags=NO_WINDOW)
        return
    except Exception:
        log("네이티브 창 실패 -> Edge 폴백: " + traceback.format_exc())
    profile = os.path.join(os.environ.get("LOCALAPPDATA", BASE), "TodoManager", "browser")
    for exe in BROWSERS:
        if os.path.exists(exe):
            subprocess.Popen([exe, f"--app={URL}", f"--user-data-dir={profile}",
                              "--window-size=1020,880", "--no-first-run"],
                             creationflags=NO_WINDOW)
            return
    webbrowser.open(URL)


def close_ui():
    """창 프로세스에 종료를 알린다. 창이 없으면 그냥 넘어간다."""
    try:
        with socket.create_connection((HOST, UI_PORT), 0.6) as s:
            s.sendall(b"GET /quit HTTP/1.0" + CRLF + CRLF)
            s.recv(32)
    except OSError:
        pass


def shutdown():
    """앱 전체 종료: 창 프로세스를 먼저 닫고 서비스를 내린다.
    서비스와 창은 별도 프로세스라, 서비스만 죽이면 창이 남는다."""
    close_ui()
    threading.Timer(0.4, lambda: os._exit(0)).start()


# ---------------- HTTP ----------------
class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send(self, code, body, ctype="application/json; charset=utf-8"):
        data = body if isinstance(body, bytes) else json.dumps(body, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        try:
            self.wfile.write(data)
        except Exception:
            pass

    def _body(self):
        n = int(self.headers.get("Content-Length") or 0)
        return json.loads(self.rfile.read(n) or b"{}")

    def do_GET(self):
        p = self.path.split("?")[0]
        if p == "/api/overview":
            o = store.overview()
            o["settings"] = dict(o.get("settings", {}), autostart=autostart.is_enabled())
            return self._send(200, o)
        if p == "/api/ping":
            return self._send(200, {"ok": True})
        if p == "/api/open":
            open_window()
            return self._send(200, {"ok": True})
        if p == "/api/all":
            return self._send(200, {"items": store.instances(back=60, ahead=120)})

        rel = "index.html" if p == "/" else p.lstrip("/")
        path = os.path.normpath(os.path.join(WEB, rel))
        if not path.startswith(WEB) or not os.path.isfile(path):
            return self._send(404, b"not found", "text/plain")
        ctype = {"html": "text/html; charset=utf-8", "css": "text/css; charset=utf-8",
                 "js": "text/javascript; charset=utf-8", "png": "image/png",
                 "svg": "image/svg+xml"}.get(path.rsplit(".", 1)[-1], "application/octet-stream")
        with open(path, "rb") as f:
            return self._send(200, f.read(), ctype)

    def do_POST(self):
        p = self.path.split("?")[0]
        try:
            if p == "/api/task":
                return self._send(200, store.add(self._body()))
            if p == "/api/preview":
                r = self._body().get("rule") or {}
                today = date.today()
                ds = recur.occurrences(r, today, today + timedelta(days=430))[:5]
                W = "월화수목금토일"
                return self._send(200, {
                    "text": recur.describe(r),
                    "dates": [f"{d.month}/{d.day}({W[d.weekday()]})" for d in ds] or ["해당 날짜 없음"],
                })
            if p.startswith("/api/task/"):
                parts = p.split("/")
                tid = parts[3]
                act = parts[4] if len(parts) > 4 else ""
                if act == "toggle":
                    return self._send(200, store.toggle_done(tid, self._body().get("date")))
                if act == "delete":
                    store.remove(tid)
                    return self._send(200, {"ok": True})
                if act == "skip":
                    return self._send(200, store.skip(tid, self._body().get("date")))
                return self._send(200, store.update(tid, self._body()) or {})
            if p == "/api/settings":
                body = self._body()
                if "autostart" in body:
                    body["autostart"] = autostart.set_enabled(bool(body["autostart"]))
                d = store.load()
                d["settings"].update(body)
                store.save(d)
                return self._send(200, d["settings"])
            if p == "/api/shortcut":
                link = autostart.make_desktop_shortcut()
                return self._send(200, {"ok": bool(link), "path": link or ""})
            if p == "/api/test-toast":
                toast.notify("알림 미리보기", "이런 모양으로 떠올랐다 사라집니다")
                return self._send(200, {"ok": True})
            if p == "/api/quit":
                threading.Thread(target=shutdown, daemon=True).start()
                return self._send(200, {"ok": True})
        except Exception as e:
            return self._send(500, {"error": str(e)})
        return self._send(404, {"error": "no route"})


# ---------------- 알림 스케줄러 ----------------
def _mark(key):
    d = store.load()
    fired = d.get("fired", [])
    if key in fired:
        return False
    fired.append(key)
    d["fired"] = fired[-800:]
    store.save(d)
    return True


def scheduler():
    while True:
        try:
            tick()
        except Exception:
            pass
        time.sleep(20)


def tick():
    now = datetime.now()
    d = store.load()
    st = d.get("settings", {})
    default_lead = timedelta(minutes=int(st.get("notify_min", 30)))

    o = store.overview()
    left = o["stats"]["left"]
    tray.set_title(f"To-Do Manager · {left}건 남음" if left else "To-Do Manager · 급한 일 없음")

    brief = st.get("brief_time", "08:30")
    if brief and now.strftime("%H:%M") >= brief:
        if (left or o["overdue"]) and _mark(f"brief:{now.date()}"):
            first = (o["overdue"] + [i for i in o["todays"] if not i["done"]])[:1]
            tail = f" 외 {left-1}건" if left > 1 else ""
            toast.notify(f"오늘 할 일 {left}건",
                         (first[0]["title"] if first else "") + tail, accent="#85bdb3")

    for i in store.instances(back=1, ahead=1, data=d):
        if i["done"] or not i["due"] or i.get("muted"):
            continue
        due = datetime.fromisoformat(i["due"])
        lead = timedelta(minutes=i["notify_min"]) if i["notify_min"] is not None else default_lead
        if due - lead <= now <= due + timedelta(minutes=90):
            if _mark(f"{i['id']}:{i['date']}:{i['time']}"):
                mins = int((due - now).total_seconds() // 60)
                sub = f"{mins}분 뒤 마감 · {i['time']}" if mins > 0 else f"마감 시간 지남 · {i['time']}"
                tid, day = i["id"], i["date"]
                toast.notify(i["title"], sub, accent="#08202b" if mins <= 0 else "#4d7572",
                             on_done=lambda tid=tid, day=day: store.toggle_done(tid, day))


def main():
    paths.log("main: 시작 (frozen=%s)" % paths.FROZEN)
    try:
        srv = ThreadingHTTPServer((HOST, PORT), Handler)
    except OSError:
        open_window()          # 서비스가 이미 돌고 있음 → 창만 열기
        return
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    threading.Thread(target=scheduler, daemon=True).start()
    paths.log("main: 서버·스케줄러 시작, tray 진입")
    tray.start(on_open=open_window,
               on_test=lambda: toast.notify("알림 미리보기", "이런 모양으로 떠올랐다 사라집니다"),
               on_quit=shutdown)
    paths.log("main: tray 완료, toast.run_forever 진입")
    toast.run_forever(on_ready=None if "--silent" in sys.argv else open_window)


if __name__ == "__main__":
    main()
