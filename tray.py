# -*- coding: utf-8 -*-
"""작업표시줄 알림영역(트레이) 아이콘. 창을 닫아도 여기서 바로 다시 열 수 있다."""
import os, threading

import paths

BASE = paths.RES_DIR
_icon = None


def _tray_size():
    """Windows 가 알림영역에 쓰는 크기 (배율 100%%에서 16)."""
    try:
        import ctypes
        return ctypes.windll.user32.GetSystemMetrics(49) or 16   # SM_CXSMICON
    except Exception:
        return 16


def _image():
    """알림영역 아이콘. 필요한 크기로 "그려둔" 그림을 그대로 쓴다.

    큰 그림을 넣으면 Windows 가 16px 로 축소하면서 흐려진다. app.ico 에는
    크기별로 따로 그린 프레임이 들어 있으므로(gen_icon.py) 그중 맞는 것을 꺼낸다.
    """
    from PIL import Image
    n = _tray_size()
    try:
        ico = Image.open(paths.ICON)
        avail = sorted(ico.ico.sizes())
        pick = next((s for s in avail if s[0] >= n), avail[-1])
        ico.size = pick
        im = ico.convert("RGBA")
        return im if im.size == (n, n) else im.resize((n, n), Image.LANCZOS)
    except Exception:
        pass
    for name in (f"icon-{n}.png", "icon-16.png", "icon.png"):
        png = os.path.join(paths.WEB_DIR, name)
        if os.path.exists(png):
            im = Image.open(png).convert("RGBA")
            return im if im.size == (n, n) else im.resize((n, n), Image.LANCZOS)
    return Image.new("RGBA", (n, n), (13, 44, 54, 255))


def _quit(cb):
    """아이콘을 먼저 없애고 종료 (잔상 아이콘 방지)."""
    try:
        if _icon is not None:
            _icon.visible = False
    except Exception:
        pass
    cb()


def start(on_open, on_test, on_quit, subtitle=lambda: "To-Do Manager"):
    """트레이 아이콘을 별도 스레드에서 띄운다. 실패하면 조용히 넘어간다."""
    global _icon
    try:
        import pystray
        from pystray import MenuItem as Item
    except Exception:
        return None

    menu = pystray.Menu(
        Item("열기", lambda: on_open(), default=True),
        pystray.Menu.SEPARATOR,
        Item("알림 미리보기", lambda: on_test()),
        pystray.Menu.SEPARATOR,
        Item("완전히 종료", lambda: _quit(on_quit)),
    )
    try:
        _icon = pystray.Icon("todomanager", _image(), "To-Do Manager", menu)
    except Exception:
        return None
    threading.Thread(target=_icon.run, daemon=True).start()
    return _icon


def set_title(text):
    if _icon is not None:
        try:
            _icon.title = text
        except Exception:
            pass


def stop():
    if _icon is not None:
        try:
            _icon.stop()
        except Exception:
            pass
