# -*- coding: utf-8 -*-
"""화면 우측 하단에 뜨는 뉴모피즘 알림 카드.

카드 전체를 Pillow 로 그린 뒤 Windows 레이어드 윈도우(UpdateLayeredWindow)로 띄운다.
픽셀 단위 알파를 쓰기 때문에 모서리가 계단식으로 깨지지 않고, 진짜 흐린 그림자도 낼 수 있다.
창과 이벤트 루프도 Win32 로 직접 다룬다 - tkinter 를 쓰면 배포본에
tcl/tk 6MB 가 따라 들어온다.
"""
import ctypes
import queue
import time
import traceback

import paths
from ctypes import wintypes

# 팔레트: #08202b · #0b2c36 · #4d7572 · #85bdb3 · #cfd6d5
CARD    = "#dde3e2"
SHADOW  = "#98a8a6"
LIGHT   = "#ffffff"
TEXT    = "#08202b"
MUTED   = "#4d7572"
ACCENT  = "#4d7572"
DEEP    = "#08202b"

PAD = 18                      # 그림자가 번질 여백
CW, CH = 380, 162             # 카드 본체 (제목 두 줄이 들어갈 만큼)
W, H = CW + PAD * 2, CH + PAD * 2
R, GAP = 20, 6
BTN = (22, CH - 44, CW - 44, 28)      # 완료 버튼 - 하단 전체 폭, 얇은 알약형
CLOSE = (CW - 42, 12, 28, 28)         # ✕ 영역
BTN_FACE = "#e7ecea"                  # 살짝 밝게 → 올라온 면처럼 보이게

# 글자 자리. 오른쪽은 ✕ 자리를 비워 둔다.
TX, TY = 42, 25
TW = CW - TX - 44
TITLE_PX, SUB_PX = 13, 11             # 예전 15/12 는 글자가 커서 제목이 잘렸다
LINE_H = 18
TITLE_LINES = 2

FONTS = [r"C:\Windows\Fonts\malgun.ttf", r"C:\Windows\Fonts\NotoSansKR-VF.ttf"]
FONTS_BD = [r"C:\Windows\Fonts\malgunbd.ttf", r"C:\Windows\Fonts\malgun.ttf"]

_queue = queue.Queue()
_live = []


LIFE_MS = 11000               # 카드가 화면에 머무는 시간
HOLD_MAX = 25                 # 마우스를 올려두면 이 초까지는 기다린다
HARD_LIFE = 32                # 이 초를 넘긴 카드는 무조건 없앤다
MAX_CARDS = 3

_seen = {}                    # key -> 마지막으로 띄운 시각


def notify(title, sub="", accent=ACCENT, on_done=None, key=None):
    """같은 알림이 겹쳐 쌓이지 않게 key 로 한 번 걸러낸다.

    key 를 주지 않으면 제목+내용을 키로 쓴다. 60초 안에 같은 키가 다시 오면 버린다.
    """
    k = key or (title + "|" + sub)
    now = time.time()
    for old_key, t in list(_seen.items()):
        if now - t > 300:
            _seen.pop(old_key, None)
    if now - _seen.get(k, 0) < 60:
        return
    _seen[k] = now
    _queue.put({"title": title, "sub": sub, "accent": accent, "on_done": on_done, "key": k})


# ---------------- 그리기 ----------------
def _rgb(h):
    h = h.lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def _font(paths, size):
    from PIL import ImageFont
    for p in paths:
        try:
            return ImageFont.truetype(p, size)
        except Exception:
            continue
    return ImageFont.load_default()


def _round(size, radius, scale=4):
    """둥근 사각형 알파 마스크 (4배로 그린 뒤 축소해서 안티에일리어싱)."""
    from PIL import Image, ImageDraw
    w, h = size
    m = Image.new("L", (w * scale, h * scale), 0)
    ImageDraw.Draw(m).rounded_rectangle(
        [0, 0, w * scale - 1, h * scale - 1], radius=radius * scale, fill=255)
    return m.resize((w, h), Image.LANCZOS)


def _x_mark(size, color, alpha, thick=1.6, scale=4):
    """대칭이 딱 맞는 ✕. 4배로 그린 뒤 축소한다 (PIL 의 width>1 선은 한쪽으로 치우친다)."""
    from PIL import Image, ImageDraw
    n = size * scale
    m = Image.new("L", (n, n), 0)
    d = ImageDraw.Draw(m)
    pad = int(n * 0.10)
    w = max(1, int(thick * scale))
    d.line((pad, pad, n - 1 - pad, n - 1 - pad), fill=255, width=w)
    d.line((pad, n - 1 - pad, n - 1 - pad, pad), fill=255, width=w)
    m = m.resize((size, size), Image.LANCZOS)
    layer = Image.new("RGBA", (size, size), _rgb(color) + (0,))
    layer.putalpha(m.point(lambda v: int(v * alpha / 255)))
    return layer


def _wrap(text, font, width, max_lines=TITLE_LINES):
    """픽셀 폭을 재서 줄을 나눈다.

    글자 수로 자르면(예전 방식) 한글 제목이 어이없이 잘린다. 한국어는 공백이
    드물어서 낱말 단위로만 끊을 수도 없으므로, 기본은 글자 단위로 채우고
    끊을 자리 근처에 공백이 있으면 거기서 끊는다.
    """
    text = " ".join((text or "").split())
    if not text:
        return [""]
    lines, i, n = [], 0, len(text)
    while i < n and len(lines) < max_lines:
        lo, hi = i + 1, n
        while lo < hi:                                  # 이 줄에 들어갈 마지막 글자
            mid = (lo + hi + 1) // 2
            if font.getlength(text[i:mid]) <= width:
                lo = mid
            else:
                hi = mid - 1
        end = lo
        if end < n and len(lines) < max_lines - 1:      # 마지막 줄이 아니면
            sp = text.rfind(" ", i + 1, end + 1)
            if sp > i and end - sp < 8:                 # 공백이 가까우면 거기서
                end = sp
        lines.append(text[i:end].rstrip())
        i = end
        while i < n and text[i] == " ":
            i += 1
    if i < n and lines:                                 # 남은 글자가 있다는 표시
        last = lines[-1]
        while last and font.getlength(last + "\u2026") > width:
            last = last[:-1]
        lines[-1] = last + "\u2026"
    return lines


def _fit(text, font, width):
    """한 줄에 맞게 자른다 (부제목용)."""
    text = " ".join((text or "").split())
    if font.getlength(text) <= width:
        return text
    while text and font.getlength(text + "\u2026") > width:
        text = text[:-1]
    return text + "\u2026"


# 그림자·버튼·✕ 는 그리는 비용이 크고 내용과 무관하므로 여기 담아 둔다.
# 글자는 절대 담지 않는다 - 예전에는 카드 전체를 (accent, hover) 로만 담아서,
# 같은 색의 두 번째 알림이 첫 번째 알림의 글자를 그대로 다시 띄웠다.
_bgcache = {}


def _card_bg(accent, hover, label="완료"):
    """글자를 뺀 카드 바탕. hover 는 None / 'btn' / 'x'."""
    key = (accent, hover, label)
    if key in _bgcache:
        return _bgcache[key]

    from PIL import Image, ImageDraw, ImageFilter

    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    shape = _round((CW, CH), R)

    # 부드러운 이중 그림자 (뉴모피즘)
    for off, col, alpha, blur in (((7, 8), SHADOW, 150, 9), ((-6, -7), LIGHT, 190, 9)):
        layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        tint = Image.new("RGBA", (CW, CH), _rgb(col) + (alpha,))
        layer.paste(tint, (PAD + off[0], PAD + off[1]), shape)
        img.alpha_composite(layer.filter(ImageFilter.GaussianBlur(blur)))

    img.paste(Image.new("RGBA", (CW, CH), _rgb(CARD) + (255,)), (PAD, PAD), shape)

    card = Image.new("RGBA", (CW, CH), (0, 0, 0, 0))
    d = ImageDraw.Draw(card)

    # 왼쪽 강조 바 (글자 블록 옆)
    card.paste(Image.new("RGBA", (4, 52), _rgb(accent) + (255,)),
               (24, TY + 1), _round((4, 52), 2))

    f_btn = _font(FONTS_BD, 12)

    # ── 완료 버튼: 하단 전체 폭, 확실히 올라온 면 ──
    bx, by, bw, bh = BTN
    br = bh // 2          # 얇은 알약형
    btn = Image.new("RGBA", (CW, CH), (0, 0, 0, 0))
    if hover == "btn":
        face, face_label = accent, DEEP
        # 눌러 내려간 느낌 (안쪽 음영)
        sh = Image.new("RGBA", (bw, bh), _rgb(DEEP) + (70,))
        btn.paste(sh, (bx, by + 2), _round((bw, bh), br))
    else:
        face, face_label = BTN_FACE, ACCENT
        for off, col, a, blur in (((0, 3), SHADOW, 150, 3), ((0, -2), LIGHT, 205, 2)):
            l = Image.new("RGBA", (CW, CH), (0, 0, 0, 0))
            l.paste(Image.new("RGBA", (bw, bh), _rgb(col) + (a,)),
                    (bx + off[0], by + off[1]), _round((bw, bh), br))
            btn.alpha_composite(l.filter(ImageFilter.GaussianBlur(blur)))
    btn.paste(Image.new("RGBA", (bw, bh), _rgb(face) + (255,)), (bx, by), _round((bw, bh), br))
    card.alpha_composite(btn)
    d.text((bx + bw / 2, by + bh / 2 - 1), label, font=f_btn, anchor="mm",
           fill=_rgb(face_label) + (255,))

    # ── 닫기 ✕ ──
    cx, cy, cw, ch = CLOSE
    if hover == "x":
        card.paste(Image.new("RGBA", (cw, ch), _rgb(SHADOW) + (110,)),
                   (cx, cy), _round((cw, ch), 9))
    xm = _x_mark(14, TEXT if hover == "x" else MUTED, 255 if hover == "x" else 200)
    card.alpha_composite(xm, (cx + (cw - 14) // 2, cy + (ch - 14) // 2))

    img.alpha_composite(card, (PAD, PAD))
    _bgcache[key] = img
    return img


def _card_rgba(item, hover=None):
    """카드 한 장. 바탕은 캐시에서 가져오고 글자는 이 알림의 것으로 새로 그린다."""
    from PIL import ImageDraw

    # 완료 처리할 대상이 없는 알림(브리핑·요약)은 버튼이 "확인" 이다.
    # "완료" 라고 적어두면 무엇이 완료되는지 알 수 없다.
    btn_label = "완료" if item.get("on_done") else "확인"
    img = _card_bg(item["accent"], hover, btn_label).copy()
    d = ImageDraw.Draw(img)
    f_title = _font(FONTS_BD, TITLE_PX)
    f_sub = _font(FONTS, SUB_PX)

    lines = _wrap(item["title"], f_title, TW)
    y = PAD + TY
    for ln in lines:
        d.text((PAD + TX, y), ln, font=f_title, fill=_rgb(TEXT) + (255,))
        y += LINE_H
    if item.get("sub"):
        d.text((PAD + TX, y + 4), _fit(item["sub"], f_sub, TW), font=f_sub,
               fill=_rgb(MUTED) + (255,))
    return img


# ---------------- 레이어드 윈도우 (GDI) ----------------
GWL_EXSTYLE = -20
WS_EX_LAYERED = 0x00080000
WS_EX_TOOLWINDOW = 0x00000080     # Alt+Tab · 작업표시줄에 안 잡히게
ULW_ALPHA = 0x00000002
AC_SRC_OVER, AC_SRC_ALPHA = 0x00, 0x01
BI_RGB, DIB_RGB_COLORS = 0, 0
PVOID = ctypes.c_void_p


class BLENDFUNCTION(ctypes.Structure):
    _fields_ = [("BlendOp", ctypes.c_byte), ("BlendFlags", ctypes.c_byte),
                ("SourceConstantAlpha", ctypes.c_byte), ("AlphaFormat", ctypes.c_byte)]


class BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [("biSize", wintypes.DWORD), ("biWidth", wintypes.LONG),
                ("biHeight", wintypes.LONG), ("biPlanes", wintypes.WORD),
                ("biBitCount", wintypes.WORD), ("biCompression", wintypes.DWORD),
                ("biSizeImage", wintypes.DWORD), ("biXPelsPerMeter", wintypes.LONG),
                ("biYPelsPerMeter", wintypes.LONG), ("biClrUsed", wintypes.DWORD),
                ("biClrImportant", wintypes.DWORD)]


U32 = ctypes.windll.user32
G32 = ctypes.windll.gdi32

# 핸들은 64비트다. restype 을 지정하지 않으면 c_long(32비트)으로 잘려서 실패한다.
U32.GetDC.restype = PVOID
U32.GetDC.argtypes = [PVOID]
U32.ReleaseDC.argtypes = [PVOID, PVOID]
U32.GetParent.restype = PVOID
U32.GetParent.argtypes = [PVOID]
U32.GetWindowLongW.restype = ctypes.c_long
U32.GetWindowLongW.argtypes = [PVOID, ctypes.c_int]
U32.SetWindowLongW.restype = ctypes.c_long
U32.SetWindowLongW.argtypes = [PVOID, ctypes.c_int, ctypes.c_long]
U32.UpdateLayeredWindow.restype = wintypes.BOOL
U32.UpdateLayeredWindow.argtypes = [
    PVOID, PVOID, ctypes.POINTER(wintypes.POINT), ctypes.POINTER(wintypes.SIZE),
    PVOID, ctypes.POINTER(wintypes.POINT), wintypes.DWORD,
    ctypes.POINTER(BLENDFUNCTION), wintypes.DWORD]
G32.CreateCompatibleDC.restype = PVOID
G32.CreateCompatibleDC.argtypes = [PVOID]
G32.CreateDIBSection.restype = PVOID
G32.CreateDIBSection.argtypes = [PVOID, PVOID, wintypes.UINT,
                                 ctypes.POINTER(PVOID), PVOID, wintypes.DWORD]
G32.SelectObject.restype = PVOID
G32.SelectObject.argtypes = [PVOID, PVOID]
G32.DeleteObject.argtypes = [PVOID]
G32.DeleteDC.argtypes = [PVOID]


def _premultiplied_bgra(img):
    """PIL RGBA → 알파 미리곱한 BGRA 바이트."""
    from PIL import Image, ImageChops
    r, g, b, a = img.split()
    r = ImageChops.multiply(r, a)
    g = ImageChops.multiply(g, a)
    b = ImageChops.multiply(b, a)
    return Image.merge("RGBA", (b, g, r, a)).tobytes()


def _paint_layered(hwnd, img, alpha=255):
    """창 위치는 Tk 가 정한 그대로 두고(pptDst=NULL) 픽셀만 갈아끼운다."""
    ex = U32.GetWindowLongW(hwnd, GWL_EXSTYLE)
    want = ex | WS_EX_LAYERED | WS_EX_TOOLWINDOW
    if ex != want:
        U32.SetWindowLongW(hwnd, GWL_EXSTYLE, want)

    data = _premultiplied_bgra(img)
    screen_dc = U32.GetDC(None)
    mem_dc = G32.CreateCompatibleDC(screen_dc)
    hbmp = old = None
    try:
        bi = BITMAPINFOHEADER()
        bi.biSize = ctypes.sizeof(BITMAPINFOHEADER)
        bi.biWidth, bi.biHeight = W, -H          # 음수 = 위에서 아래로
        bi.biPlanes, bi.biBitCount = 1, 32
        bi.biCompression = BI_RGB
        bits = PVOID()
        hbmp = G32.CreateDIBSection(mem_dc, ctypes.byref(bi), DIB_RGB_COLORS,
                                    ctypes.byref(bits), None, 0)
        if not hbmp:
            raise OSError("CreateDIBSection failed")
        ctypes.memmove(bits, data, len(data))
        old = G32.SelectObject(mem_dc, hbmp)

        size = wintypes.SIZE(W, H)
        src = wintypes.POINT(0, 0)
        blend = BLENDFUNCTION(AC_SRC_OVER, 0, int(alpha), AC_SRC_ALPHA)
        if not U32.UpdateLayeredWindow(hwnd, screen_dc, None, ctypes.byref(size),
                                       mem_dc, ctypes.byref(src), 0,
                                       ctypes.byref(blend), ULW_ALPHA):
            raise OSError("UpdateLayeredWindow failed (%d)" % ctypes.get_last_error())
    finally:
        if old:
            G32.SelectObject(mem_dc, old)
        if hbmp:
            G32.DeleteObject(hbmp)
        G32.DeleteDC(mem_dc)
        U32.ReleaseDC(None, screen_dc)

# ---------------- 창 (순수 Win32) ----------------
# 예전에는 tkinter 를 창 껍데기와 타이머로만 썼는데, 그 하나 때문에 배포본에
# tcl/tk 가 6MB 들어갔다. 카드는 어차피 UpdateLayeredWindow 로 직접 그리므로
# 창과 이벤트 루프도 Win32 로 직접 다룬다.
WM_DESTROY, WM_TIMER = 0x0002, 0x0113
WM_MOUSEMOVE, WM_LBUTTONDOWN, WM_MOUSELEAVE = 0x0200, 0x0201, 0x02A3
WM_SETCURSOR = 0x0020
WS_POPUP = 0x80000000
WS_EX_TOPMOST, WS_EX_NOACTIVATE = 0x00000008, 0x08000000
SW_SHOWNOACTIVATE, SW_HIDE = 4, 0
SWP_NOACTIVATE, SWP_NOSIZE, SWP_NOZORDER = 0x0010, 0x0001, 0x0004
HWND_TOPMOST = -1
IDC_ARROW, IDC_HAND = 32512, 32649
TME_LEAVE = 0x00000002
IDLE_MS, ANIM_MS = 400, 30      # 놀 때는 느리게, 움직일 때만 빠르게

LRESULT = ctypes.c_ssize_t
WPARAM = ctypes.c_size_t
LPARAM = ctypes.c_ssize_t
WNDPROC = ctypes.WINFUNCTYPE(LRESULT, PVOID, ctypes.c_uint, WPARAM, LPARAM)


class WNDCLASS(ctypes.Structure):
    _fields_ = [("style", wintypes.UINT), ("lpfnWndProc", WNDPROC),
                ("cbClsExtra", ctypes.c_int), ("cbWndExtra", ctypes.c_int),
                ("hInstance", PVOID), ("hIcon", PVOID), ("hCursor", PVOID),
                ("hbrBackground", PVOID), ("lpszMenuName", ctypes.c_wchar_p),
                ("lpszClassName", ctypes.c_wchar_p)]


class TRACKMOUSEEVENT(ctypes.Structure):
    _fields_ = [("cbSize", wintypes.DWORD), ("dwFlags", wintypes.DWORD),
                ("hwndTrack", PVOID), ("dwHoverTime", wintypes.DWORD)]


class MSG(ctypes.Structure):
    _fields_ = [("hwnd", PVOID), ("message", wintypes.UINT), ("wParam", WPARAM),
                ("lParam", LPARAM), ("time", wintypes.DWORD),
                ("pt_x", ctypes.c_long), ("pt_y", ctypes.c_long)]


U32.DefWindowProcW.restype = LRESULT
U32.DefWindowProcW.argtypes = [PVOID, ctypes.c_uint, WPARAM, LPARAM]
U32.CreateWindowExW.restype = PVOID
U32.CreateWindowExW.argtypes = [wintypes.DWORD, ctypes.c_wchar_p, ctypes.c_wchar_p,
                                wintypes.DWORD, ctypes.c_int, ctypes.c_int,
                                ctypes.c_int, ctypes.c_int, PVOID, PVOID, PVOID, PVOID]
U32.RegisterClassW.argtypes = [ctypes.POINTER(WNDCLASS)]
U32.SetWindowPos.argtypes = [PVOID, PVOID, ctypes.c_int, ctypes.c_int,
                             ctypes.c_int, ctypes.c_int, wintypes.UINT]
U32.SetTimer.restype = PVOID
U32.SetTimer.argtypes = [PVOID, PVOID, wintypes.UINT, PVOID]
U32.KillTimer.argtypes = [PVOID, PVOID]
U32.DestroyWindow.argtypes = [PVOID]
U32.ShowWindow.argtypes = [PVOID, ctypes.c_int]
U32.LoadCursorW.restype = PVOID
U32.LoadCursorW.argtypes = [PVOID, ctypes.c_wchar_p]
U32.SetCursor.restype = PVOID
U32.SetCursor.argtypes = [PVOID]
U32.GetMessageW.argtypes = [ctypes.POINTER(MSG), PVOID, wintypes.UINT, wintypes.UINT]
U32.TranslateMessage.argtypes = [ctypes.POINTER(MSG)]
U32.DispatchMessageW.argtypes = [ctypes.POINTER(MSG)]
U32.TrackMouseEvent.argtypes = [ctypes.POINTER(TRACKMOUSEEVENT)]

_cards = {}                     # hwnd -> Card
_ctrl = None                    # 타이머만 받는 숨은 창
_rate = 0                       # 지금 타이머 간격
_cursors = {}


def _cursor(which):
    if which not in _cursors:
        _cursors[which] = U32.LoadCursorW(None, ctypes.c_wchar_p(which))
    return _cursors[which]


def _lo(v):
    v &= 0xFFFF
    return v - 0x10000 if v > 0x7FFF else v


class Card:
    """알림 카드 하나 = 레이어드 창 하나."""

    def __init__(self, item):
        self.item = item
        self.alpha = 0
        self.step = 30                      # 나타나는 중
        self.hover = None
        self.over = False
        self.born = time.time()
        self.closing = False
        self.pos = (0, 0)
        self.img = _card_rgba(item)
        self.hwnd = U32.CreateWindowExW(
            WS_EX_LAYERED | WS_EX_TOOLWINDOW | WS_EX_TOPMOST | WS_EX_NOACTIVATE,
            _CLASS_NAME, "To-Do Manager 알림", WS_POPUP,
            0, 0, W, H, None, None, None, None)
        if not self.hwnd:
            raise OSError("CreateWindowEx 실패 (%d)" % ctypes.get_last_error())
        _cards[self.hwnd] = self
        U32.ShowWindow(self.hwnd, SW_SHOWNOACTIVATE)

    # --- 배치 ---
    def place(self, x, y):
        self.pos = (x, y)
        U32.SetWindowPos(self.hwnd, PVOID(HWND_TOPMOST & 0xFFFFFFFFFFFFFFFF),
                         x, y, W, H, SWP_NOACTIVATE)
        self.paint()

    def paint(self):
        try:
            _paint_layered(self.hwnd, self.img, self.alpha)
        except Exception:
            paths.log("toast.paint 실패: " + traceback.format_exc())

    # --- 마우스 ---
    def _hit(self, x, y):
        cx, cy = x - PAD, y - PAD
        bx, by, bw, bh = BTN
        if bx <= cx <= bx + bw and by <= cy <= by + bh:
            return "btn"
        ox, oy, ow, oh = CLOSE
        if ox <= cx <= ox + ow and oy <= cy <= oy + oh:
            return "x"
        return None

    def on_move(self, x, y):
        if not self.over:
            self.over = True
            tme = TRACKMOUSEEVENT(ctypes.sizeof(TRACKMOUSEEVENT), TME_LEAVE,
                                  self.hwnd, 0)
            U32.TrackMouseEvent(ctypes.byref(tme))
        t = self._hit(x, y)
        if t == self.hover:
            return
        self.hover = t
        try:
            self.img = _card_rgba(self.item, t)
        except Exception:
            return
        self.paint()

    def on_leave(self):
        self.over = False
        if self.hover is not None:
            self.hover = None
            try:
                self.img = _card_rgba(self.item, None)
                self.paint()
            except Exception:
                pass

    def on_click(self, x, y):
        t = self._hit(x, y)
        if t == "btn":
            cb = self.item.get("on_done")
            if cb:
                try:
                    cb()
                except Exception:
                    paths.log("toast on_done 실패: " + traceback.format_exc())
            self.close()
        elif t == "x":
            self.close()

    # --- 수명 ---
    def close(self):
        if self.closing:
            return
        self.closing = True
        self.step = -30

    def destroy(self):
        _cards.pop(self.hwnd, None)
        if self in _live:
            _live.remove(self)
        try:
            U32.DestroyWindow(self.hwnd)
        except Exception:
            pass


def _wndproc(hwnd, msg, wp, lp):
    if msg == WM_TIMER:
        if hwnd == _ctrl:
            _pump()
        return 0
    card = _cards.get(hwnd)
    if card is not None:
        if msg == WM_MOUSEMOVE:
            card.on_move(_lo(lp), _lo(lp >> 16))
            return 0
        if msg == WM_LBUTTONDOWN:
            card.on_click(_lo(lp), _lo(lp >> 16))
            return 0
        if msg == WM_MOUSELEAVE:
            card.on_leave()
            return 0
        if msg == WM_SETCURSOR:
            U32.SetCursor(_cursor(IDC_HAND if card.hover else IDC_ARROW))
            return 1
        if msg == WM_DESTROY:
            _cards.pop(hwnd, None)
            return 0
    return U32.DefWindowProcW(hwnd, msg, wp, lp)


_WNDPROC_REF = WNDPROC(_wndproc)      # 살려 둬야 한다. 가비지가 되면 즉시 죽는다
_CLASS_NAME = "TodoManagerToast"


def _register():
    wc = WNDCLASS()
    wc.style = 0x0020                  # CS_OWNDC 아님: CS_HREDRAW/VREDRAW 불필요
    wc.lpfnWndProc = _WNDPROC_REF
    wc.hInstance = None
    wc.hCursor = _cursor(IDC_ARROW)
    wc.lpszClassName = _CLASS_NAME
    if not U32.RegisterClassW(ctypes.byref(wc)):
        err = ctypes.get_last_error()
        if err != 1410:                # ERROR_CLASS_ALREADY_EXISTS
            raise OSError("RegisterClass 실패 (%d)" % err)


def _work_area():
    """작업표시줄을 뺀 화면 영역. 화면 크기로 계산하면 카드가 작업표시줄에 가린다."""
    try:
        r = wintypes.RECT()
        if U32.SystemParametersInfoW(0x0030, 0, ctypes.byref(r), 0):   # SPI_GETWORKAREA
            return r.left, r.top, r.right, r.bottom
    except Exception:
        pass
    return 0, 0, U32.GetSystemMetrics(0), U32.GetSystemMetrics(1)


def _layout():
    _, _, sw, sh = _work_area()
    for n, card in enumerate(reversed(_live)):
        card.place(sw - W - 20 + PAD, sh - 12 - (n + 1) * (CH + GAP) - PAD)


def _set_rate(ms):
    """타이머 간격. 놀 때 30ms 로 돌 이유가 없다."""
    global _rate
    if ms == _rate:
        return
    if _rate:
        U32.KillTimer(_ctrl, PVOID(1))
    U32.SetTimer(_ctrl, PVOID(1), ms, None)
    _rate = ms


def _pump():
    """큐 처리 + 페이드 진행 + 수명 정리. 무슨 일이 있어도 죽지 않는다."""
    if not getattr(_pump, "_logged", False):
        _pump._logged = True
        paths.log("toast._pump: 첫 실행")
    try:
        moved = False
        while True:                                     # 새 알림
            try:
                item = _queue.get_nowait()
            except queue.Empty:
                break
            try:
                while len(_live) >= MAX_CARDS:
                    _live[0].destroy()
                _live.append(Card(item))
                moved = True
            except Exception:
                paths.log("toast: " + traceback.format_exc())

        now = time.time()
        for card in list(_live):                        # 수명
            if card.closing:
                continue
            age = now - card.born
            if age > HARD_LIFE:
                card.destroy()
                moved = True
            elif age > LIFE_MS / 1000 and not (card.over and age < HOLD_MAX):
                card.close()

        if moved:
            _layout()

        anim = False                                    # 페이드
        for card in list(_live):
            if not card.step:
                continue
            anim = True
            card.alpha = max(0, min(247, card.alpha + card.step))
            if card.step > 0 and card.alpha >= 247:
                card.step = 0
            elif card.step < 0 and card.alpha <= 0:
                card.destroy()
                _layout()
                continue
            card.paint()
        _set_rate(ANIM_MS if anim else IDLE_MS)
    except Exception:
        paths.log("toast: " + traceback.format_exc())


def _safe(fn, tag):
    try:
        fn()
    except Exception:
        paths.log("toast %s 실패: %s" % (tag, traceback.format_exc()))


def run_forever(on_ready=None):
    """메인 스레드에서 호출. Win32 메시지 루프를 돈다."""
    global _ctrl
    paths.log("toast.run_forever: 창 클래스 등록")
    _register()
    _ctrl = U32.CreateWindowExW(0, _CLASS_NAME, "To-Do Manager", WS_POPUP,
                                0, 0, 0, 0, None, None, None, None)
    if not _ctrl:
        raise OSError("타이머용 창 생성 실패 (%d)" % ctypes.get_last_error())
    _set_rate(IDLE_MS)
    if on_ready:
        _safe(on_ready, "on_ready")
    paths.log("toast.run_forever: 메시지 루프 진입")
    msg = MSG()
    while U32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
        U32.TranslateMessage(ctypes.byref(msg))
        U32.DispatchMessageW(ctypes.byref(msg))
