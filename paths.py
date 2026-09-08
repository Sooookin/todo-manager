# -*- coding: utf-8 -*-
"""파일 위치를 한 곳에서 정한다.

- 프로그램 파일(web/, app.ico)은 실행 파일 옆 또는 PyInstaller 임시 폴더
- 내 일정(data.json)은 %APPDATA%\\오늘  ← 프로그램 폴더와 분리해야
  · 배포본에 남의 일정이 섞이지 않고
  · 읽기 전용 공유 폴더에서 실행해도 저장이 되고
  · 프로그램을 새 버전으로 덮어써도 일정이 유지된다
"""
import os
import sys

FROZEN = getattr(sys, "frozen", False)

# 프로그램 자원(읽기 전용)
if FROZEN:
    RES_DIR = getattr(sys, "_MEIPASS", os.path.dirname(sys.executable))
    APP_DIR = os.path.dirname(sys.executable)
else:
    RES_DIR = APP_DIR = os.path.dirname(os.path.abspath(__file__))

WEB_DIR = os.path.join(RES_DIR, "web")
ICON = os.path.join(RES_DIR, "app.ico")

# 사용자 데이터(쓰기 가능)
_base = os.environ.get("APPDATA") or os.path.expanduser("~")
DATA_DIR = os.path.join(_base, "To-Do Manager")
OLD_DATA_DIRS = [os.path.join(_base, "오늘")]   # 예전 이름
DATA_FILE = os.path.join(DATA_DIR, "data.json")


UNBLOCKED = None        # unblock() 이 떼어낸 파일 수 (점검에서 보여주려고 기억한다)


def unblock():
    """묶여 온 DLL 에서 "인터넷에서 받은 파일" 표시를 뗀다.

    zip 을 받아 그냥 풀면 안쪽 파일마다 Zone.Identifier 라는 꼬리표가 붙는다.
    .NET Framework 는 이 표시가 붙은 어셈블리를 아예 읽지 않아서,
    Python.Runtime.dll 을 못 불러 창이 통째로 뜨지 않았다
    ("Failed to resolve Python.Runtime.Loader.Initialize").
    받는 사람이 zip 속성에서 "차단 해제" 를 누르기를 기대할 수는 없으니
    우리가 시작할 때 직접 뗀다. 꼬리표는 부속 스트림이라 파일 내용은 그대로다.
    """
    global UNBLOCKED
    if not FROZEN:
        UNBLOCKED = 0
        return 0
    import ctypes

    kernel32 = ctypes.windll.kernel32
    n = 0
    for root, _, files in os.walk(APP_DIR):
        for f in files:
            if not f.lower().endswith((".dll", ".pyd", ".exe")):
                continue
            tag = os.path.join(root, f) + ":Zone.Identifier"
            if kernel32.DeleteFileW(tag):
                n += 1
    if n:
        log("다운로드 표시를 %d개 파일에서 떼어냈다" % n)
    if UNBLOCKED is None:
        UNBLOCKED = n
    return n


def ensure_data_dir():
    os.makedirs(DATA_DIR, exist_ok=True)
    return DATA_DIR


def _copy(src, dst):
    try:
        with open(src, "rb") as a, open(dst, "wb") as b:
            b.write(a.read())
        return True
    except OSError:
        return False


def migrate_legacy():
    """예전 위치(프로그램 폴더 / 예전 이름의 APPDATA 폴더)에 있던 일정을 한 번만 옮겨온다."""
    if os.path.exists(DATA_FILE):
        return
    for old_dir in OLD_DATA_DIRS:
        old = os.path.join(old_dir, "data.json")
        if os.path.exists(old):
            ensure_data_dir()
            _copy(old, DATA_FILE)
            return
    legacy = os.path.join(APP_DIR, "data.json")
    if os.path.exists(legacy):
        ensure_data_dir()
        if _copy(legacy, DATA_FILE):
            try:
                os.replace(legacy, legacy + ".migrated")
            except OSError:
                pass


def log(msg, name="app.log"):
    """빌드본은 콘솔이 없다(sys.stderr is None). 무슨 일이 있어도 파일로 남긴다."""
    try:
        ensure_data_dir()
        import datetime as _dt
        path = os.path.join(DATA_DIR, name)
        if os.path.exists(path) and os.path.getsize(path) > 128 * 1024:
            os.replace(path, path + ".1")          # 무한히 커지지 않게 한 번만 보관
        with open(path, "a", encoding="utf-8") as f:
            f.write(_dt.datetime.now().strftime("%m-%d %H:%M:%S") + "  " + str(msg) + chr(10))
    except Exception:
        pass


def exe_path():
    """자동 실행 등록에 쓸 실행 명령."""
    if FROZEN:
        return sys.executable
    pyw = os.path.join(os.path.dirname(sys.executable), "pythonw.exe")
    runner = pyw if os.path.exists(pyw) else sys.executable
    return f'"{runner}" "{os.path.join(APP_DIR, "main.py")}"'
