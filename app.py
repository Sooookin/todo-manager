# -*- coding: utf-8 -*-
"""To-Do Manager - 백그라운드 서비스: API 서버 + 알림 스케줄러 + 알림 카드 루프."""
import ctypes, json, os, socket, subprocess, sys, threading, time, traceback, webbrowser
from datetime import date, datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import autostart
import paths
import recur, store, toast, tray

BASE = paths.APP_DIR
WEB = paths.WEB_DIR
HOST, PORT = "127.0.0.1", 8777
UI_PORT = 8779                  # 창 프로세스(ui.py) 가 듣는 포트
LATE_GRACE = 90                 # 마감이 지난 뒤에도 이 분 안에는 알린다
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


class Server(ThreadingHTTPServer):
    """allow_reuse_address 를 반드시 꺼야 한다.

    http.server 는 기본값이 1 이고, Windows 의 SO_REUSEADDR 은 리눅스와 달리
    "이미 듣고 있는 주소에 또 bind 하는 것"을 허용한다. 그래서 bind 성공 여부로
    중복 실행을 판단할 수 없었고, 앱을 다시 켤 때마다 서비스가 하나씩 늘어났다.
    (스케줄러도 같이 늘어나 알림이 겹쳐 떴다)
    """
    allow_reuse_address = False
    daemon_threads = True


_lock_handle = None          # 핸들을 살려둬야 잠금이 유지된다


def acquire_single_instance():
    """이미 다른 인스턴스가 돌고 있으면 False."""
    global _lock_handle
    try:
        k32 = ctypes.windll.kernel32
        k32.CreateMutexW.restype = ctypes.c_void_p
        h = k32.CreateMutexW(None, False, r"Local\TodoManager.Service")
        if h and k32.GetLastError() == 183:            # ERROR_ALREADY_EXISTS
            return False
        _lock_handle = h
        return True
    except Exception:
        log("단일 실행 잠금 실패(무시): " + traceback.format_exc())
        return True


def focus_ui():
    """이미 떠 있는 창을 앞으로 불러온다. 창이 없으면 False.

    창 프로세스를 새로 띄우는 데 몇 초가 걸리므로, 살아 있는 창이 있으면
    프로세스를 만들지 않고 그 창을 쓴다.
    """
    try:
        with socket.create_connection((HOST, UI_PORT), 0.5) as sock:
            sock.sendall(b"GET /focus HTTP/1.0" + CRLF + CRLF)
            # 응답이 오면 창이 살아 있는 것이다. 본문("ok")까지 기다리면 안 된다 -
            # recv 한 번은 헤더만 담고 끝나기도 한다.
            return bool(sock.recv(64))
    except OSError:
        return False


def open_window():
    """앱 창을 새 프로세스로 띄운다. pywebview 를 못 쓰면 Edge 앱 창으로 폴백."""
    if focus_ui():
        log("open_window: 이미 떠 있는 창을 앞으로 불러왔다")
        return
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
        if p == "/api/notify-plan":
            return self._send(200, notify_plan())
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
    fails = 0
    while True:
        try:
            tick()
            fails = 0
        except Exception:
            # 예전에는 여기서 그냥 넘어갔다. 알림이 왜 안 뜨는지 알 방법이 없었다.
            fails += 1
            log("scheduler tick 실패 (%d회째)" % fails + chr(10) + traceback.format_exc())
        time.sleep(20)


def _plus(hhmm, minutes):
    """'08:30' + 120분 -> '10:30'. 자정을 넘으면 23:59 로 자른다."""
    try:
        h, m = int(hhmm[:2]), int(hhmm[3:5])
    except (ValueError, IndexError):
        return "23:59"
    total = h * 60 + m + minutes
    return "23:59" if total >= 24 * 60 else "%02d:%02d" % (total // 60, total % 60)


def tick():
    now = datetime.now()
    hm = now.strftime("%H:%M")
    d = store.load()
    st = d.get("settings", {})
    default_lead = timedelta(minutes=int(st.get("notify_min", 30)))

    first_tick = not getattr(tick, "_ran", False)
    tick._ran = True

    o = store.overview()
    left = o["stats"]["left"]
    tray.set_title(f"To-Do Manager · {left}건 남음" if left else "To-Do Manager · 급한 일 없음")

    # 브리핑은 시각이 지난 뒤 2시간 안에만. 그러지 않으면 저녁에 프로그램을 켰을 때
    # 아침 브리핑이 그제서야 떠오른다.
    brief = st.get("brief_time", "08:30")
    if brief and brief <= hm <= _plus(brief, 120):
        if (left or o["overdue"]) and _mark(f"brief:{now.date()}"):
            head = (o["overdue"] + [i for i in o["todays"] if not i["done"]])[:1]
            tail = f" 외 {left-1}건" if left > 1 else ""
            toast.notify(f"오늘 할 일 {left}건",
                         (head[0]["title"] if head else "") + tail, accent="#85bdb3",
                         key=f"brief:{now.date()}")

    missed = []
    for i in store.instances(back=1, ahead=1, data=d):
        # 항목 하나에서 터져도 나머지 알림은 계속 떠야 한다
        try:
            if _maybe_notify(i, now, default_lead, first_tick) == "missed":
                missed.append(i)
        except Exception:
            log("알림 처리 실패 (%s)" % i.get("id") + chr(10) + traceback.format_exc())

    # 프로그램을 늦게 켰을 때: 지나간 알림을 한 장으로 모아 보여준다.
    # 예전에는 조용히 버려서 "오늘 알림이 안 떴다" 가 됐고, 그렇다고 다 띄우면
    # 카드가 무더기로 겹쳐 떴다.
    if missed:
        missed.sort(key=lambda x: (x["date"], x["time"]))
        head = missed[0]
        if len(missed) == 1:
            tid, day = head["id"], head["date"]
            toast.notify(head["title"], "마감 시간 지남 · %s" % head["time"],
                         accent="#08202b",
                         on_done=lambda tid=tid, day=day: store.toggle_done(tid, day),
                         key="missed:%s:%s" % (tid, day))
        else:
            toast.notify("놓친 알림 %d건" % len(missed),
                         "%s · %s 외 %d건" % (head["time"], head["title"],
                                                  len(missed) - 1),
                         accent="#08202b", key="missed:%s" % now.date())
        log("놓친 알림 %d건을 한 장으로 알림" % len(missed))


def _plan(i, now, default_lead):
    """이 항목의 알림 계획. (알림 시각, 마감 시각, 건너뛸 이유) 를 돌려준다.

    점검할 때 이 함수만 보면 "왜 안 떴는지" 를 알 수 있다.
    """
    if not i["due"]:
        return None, None, "마감 시각 없음"
    due = datetime.fromisoformat(i["due"])
    lead = timedelta(minutes=i["notify_min"]) if i["notify_min"] is not None else default_lead
    at = due - lead
    if i["done"]:
        return at, due, "이미 완료"
    if i.get("muted"):
        return at, due, "알림 끔"
    if now < at:
        return at, due, "아직 이르다"
    if now > due + timedelta(minutes=LATE_GRACE):
        return at, due, "시간이 너무 지났다"
    return at, due, None


def _maybe_notify(i, now, default_lead, first_tick):
    at, due, skip = _plan(i, now, default_lead)
    if skip:
        return
    key = "%s:%s:%s" % (i["id"], i["date"], i["time"])
    mins = int((due - now).total_seconds() // 60)
    if first_tick and mins <= 0:
        # 프로그램을 켠 첫 순간에 지나간 것들은 각각 띄우지 않고 모아서 한 장으로
        # 보여준다 (tick 의 missed 처리). 여기서는 표시만 해둔다.
        _mark(key)
        return "missed"
    if not _mark(key):
        return
    sub = ("%d분 뒤 마감 · %s" % (mins, i["time"])) if mins > 0 else           ("마감 시간 지남 · %s" % i["time"])
    tid, day = i["id"], i["date"]
    toast.notify(i["title"], sub, accent="#08202b" if mins <= 0 else "#4d7572",
                 on_done=lambda tid=tid, day=day: store.toggle_done(tid, day),
                 key="%s:%s" % (tid, day))
    log("알림 띄움: %s (%s)" % (key, sub))



def notify_plan():
    """알림 점검용. 어제~내일의 각 회차가 언제 알려질 예정인지, 안 알려지면 왜인지.

    "왜 안 떴지" 를 추측하지 않고 확인할 수 있어야 한다.
    """
    now = datetime.now()
    d = store.load()
    default_lead = timedelta(minutes=int(d.get("settings", {}).get("notify_min", 30)))
    fired = set(d.get("fired", []))
    out = []
    for i in store.instances(back=1, ahead=1, data=d):
        at, due, skip = _plan(i, now, default_lead)
        key = "%s:%s:%s" % (i["id"], i["date"], i["time"])
        out.append({
            "title": i["title"],
            "date": i["date"],
            "time": i["time"],
            "kind": i["kind"],
            "notify_at": at.strftime("%m-%d %H:%M") if at else "",
            "due_at": due.strftime("%m-%d %H:%M") if due else "",
            "already_fired": key in fired,
            "skip": skip or "",
            "will_notify": bool(not skip and key not in fired),
        })
    out.sort(key=lambda r: (r["notify_at"] or "9"))
    return {"now": now.strftime("%m-%d %H:%M"),
            "default_lead_min": int(default_lead.total_seconds() // 60),
            "rows": out}



def main():
    paths.log("main: 시작 (frozen=%s)" % paths.FROZEN)
    silent = "--silent" in sys.argv

    # 이미 백그라운드에 돌고 있으면 서비스를 또 띄우지 않는다.
    # 바탕화면 아이콘을 다시 눌렀을 때 기대하는 동작은 "그 창을 열어라" 이다.
    if not acquire_single_instance():
        paths.log("main: 이미 실행 중 → 기존 창만 열고 종료")
        if not silent:
            open_window()
        return
    try:
        srv = Server((HOST, PORT), Handler)
    except OSError:
        paths.log("main: 포트 사용 중 → 기존 창만 열고 종료")
        open_window()
        return
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    threading.Thread(target=scheduler, daemon=True).start()
    paths.log("main: 서버·스케줄러 시작, tray 진입")
    tray.start(on_open=open_window,
               on_test=lambda: toast.notify("알림 미리보기", "이런 모양으로 떠올랐다 사라집니다"),
               on_quit=shutdown)
    paths.log("main: tray 완료, toast.run_forever 진입")
    toast.run_forever(on_ready=(prewarm_window if silent else open_window))


def prewarm_window():
    """창을 숨긴 채로 미리 만들어 둔다.

    창 프로세스는 WebView2 초기화까지 몇 초가 걸린다. 자동 실행으로 조용히
    떠 있을 때 미리 만들어 두면, 트레이나 바로가기로 열 때 곧바로 나타난다.
    """
    if focus_ui():
        return
    try:
        if paths.FROZEN:
            subprocess.Popen([sys.executable, "--ui", "--hidden"], cwd=BASE,
                             creationflags=NO_WINDOW,
                             stdin=subprocess.DEVNULL,
                             stdout=subprocess.DEVNULL,
                             stderr=subprocess.DEVNULL)
        else:
            exe = sys.executable or "python.exe"
            pyw = os.path.join(os.path.dirname(exe), "pythonw.exe")
            runner = pyw if os.path.exists(pyw) else exe
            subprocess.Popen([runner, os.path.join(BASE, "main.py"), "--ui", "--hidden"],
                             cwd=BASE, creationflags=NO_WINDOW)
        log("prewarm_window: 숨긴 창 미리 생성")
    except Exception:
        log("prewarm_window 실패(무시): " + traceback.format_exc())


if __name__ == "__main__":
    main()
