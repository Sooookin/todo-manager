# -*- coding: utf-8 -*-
"""작업표시줄 알림영역(트레이) 아이콘. 창을 닫아도 여기서 바로 다시 열 수 있다."""
import os, threading

import paths

BASE = paths.RES_DIR
_icon = None


def _image():
    from PIL import Image
    png = os.path.join(paths.WEB_DIR, "icon.png")
    if os.path.exists(png):
        return Image.open(png).convert("RGBA").resize((64, 64), Image.LANCZOS)
    return Image.new("RGBA", (64, 64), (13, 44, 54, 255))


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
