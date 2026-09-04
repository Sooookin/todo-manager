# -*- coding: utf-8 -*-
"""화면 우측 하단에 뜨는 뉴모피즘 알림 카드.

카드 전체를 Pillow 로 그린 뒤 Windows 레이어드 윈도우(UpdateLayeredWindow)로 띄운다.
픽셀 단위 알파를 쓰기 때문에 모서리가 계단식으로 깨지지 않고, 진짜 흐린 그림자도 낼 수 있다.
(GDI 나 Pillow 를 못 쓰는 환경이면 예전 tkinter 캔버스 방식으로 자동 폴백)
"""
import ctypes
import queue
import time
import traceback

import paths
import tkinter as tk
from ctypes import wintypes

# 팔레트: #08202b · #0b2c36 · #4d7572 · #85bdb3 · #cfd6d5
CARD    = "#dde3e2"
SHADOW  = "#98a8a6"
LIGHT   = "#ffffff"
TEXT    = "#08202b"
MUTED   = "#4d7572"
ACCENT  = "#4d7572"
MINT    = "#85bdb3"
DEEP    = "#08202b"
TRANSP  = "#ff00ff"

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
_root = None
_use_layered = True


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


def toplevel_hwnd(widget):
    """Tk 은 최상위 창을 감싸는 래퍼를 따로 만든다. winfo_id() 는 그 안쪽 자식이다."""
    h = widget.winfo_id()
    p = U32.GetParent(h)
    return p if p else h


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


# ---------------- 폴백용 캔버스 도형 ----------------
def _poly(c, x1, y1, x2, y2, r, **kw):
    return c.create_polygon(
        x1 + r, y1, x2 - r, y1, x2, y1, x2, y1 + r, x2, y2 - r, x2, y2, x2 - r, y2,
        x1 + r, y2, x1, y2, x1, y2 - r, x1, y1 + r, x1, y1, smooth=True, **kw)


class Card(tk.Toplevel):
    def __init__(self, master, item):
        super().__init__(master)
        self.item = item
        self.overrideredirect(True)
        self.attributes("-topmost", True)
        self.layered = False
        self.img = None
        self.pos = (0, 0)
        self.alpha = 0
        self.hover = None

        if _use_layered:
            try:
                self.img = _card_rgba(item)
                self.layered = True
            except Exception:
                self.layered = False

        if self.layered:
            self.geometry(f"{W}x{H}+0+0")
            self.update_idletasks()
        else:
            self._build_canvas(item)
        for w in (self, getattr(self, "canvas", None)):
            if w is None:
                continue
            w.bind("<Button-1>", self._click)
            w.bind("<Motion>", self._motion)
            w.bind("<Leave>", self._leave)

        self.born = time.time()
        self._closing = False
        self._over = False
        self.after(LIFE_MS, self._expire)

    # --- 폴백: 캔버스로 직접 그리기 ---
    def _build_canvas(self, item):
        self.attributes("-alpha", 0.0)
        self.configure(bg=TRANSP)
        keyed = True
        try:
            self.attributes("-transparentcolor", TRANSP)
        except tk.TclError:
            keyed = False
            self.configure(bg=CARD)
        c = tk.Canvas(self, width=CW, height=CH, bg=TRANSP if keyed else CARD,
                      highlightthickness=0, bd=0)
        c.pack()
        self.canvas = c
        _poly(c, 4, 4, CW - 2, CH - 2, R, fill=SHADOW, outline="")
        _poly(c, 2, 2, CW - 4, CH - 4, R, fill=CARD, outline=LIGHT)
        c.create_rectangle(24, 28, 28, 76, fill=item["accent"], outline="")
        c.create_text(44, 37, anchor="w", text=item["title"][:24], fill=TEXT,
                      font=("Malgun Gothic", 11, "bold"))
        c.create_text(44, 62, anchor="w", text=item["sub"][:32], fill=MUTED,
                      font=("Malgun Gothic", 9))
        bx, by, bw, bh = BTN
        face = _poly(c, bx, by, bx + bw, by + bh, bh // 2, fill=BTN_FACE, outline=SHADOW)
        lab = c.create_text(bx + bw / 2, by + bh / 2, text="완료", fill=ACCENT,
                            font=("Malgun Gothic", 10, "bold"))
        self._btn_ids = (face, lab)
        cx, cy, cw, ch = CLOSE
        c.create_line(cx + 4, cy + 4, cx + cw - 4, cy + ch - 4, fill=MUTED, width=2)
        c.create_line(cx + 4, cy + ch - 4, cx + cw - 4, cy + 4, fill=MUTED, width=2)

    def _hit(self, ex, ey):
        off = PAD if self.layered else 0
        x, y = ex - off, ey - off
        bx, by, bw, bh = BTN
        cx, cy, cw, ch = CLOSE
        if bx <= x <= bx + bw and by <= y <= by + bh:
            return "btn"
        if cx - 3 <= x <= cx + cw + 3 and cy - 3 <= y <= cy + ch + 3:
            return "x"
        return None

    def _click(self, e):
        t = self._hit(e.x, e.y)
        if t == "btn":
            self.done()
        elif t == "x":
            self.close()

    def _motion(self, e):
        self._over = True
        t = self._hit(e.x, e.y)
        if t == self.hover:
            return
        self.hover = t
        try:
            self.configure(cursor="hand2" if t else "arrow")
        except tk.TclError:
            pass
        if self.layered:
            try:
                self.img = _card_rgba(self.item, t)
            except Exception:
                return
            self._repaint()
        else:
            self._paint_canvas_hover(t)

    def _leave(self, e):
        self._over = False
        if self.hover is not None:
            self.hover = None
            try:
                self.configure(cursor="arrow")
            except tk.TclError:
                pass
            if self.layered:
                try:
                    self.img = _card_rgba(self.item, None)
                    self._repaint()
                except Exception:
                    pass
            else:
                self._paint_canvas_hover(None)

    def _paint_canvas_hover(self, t):
        """폴백(캔버스) 모드에서의 간단한 hover 표시."""
        if not hasattr(self, "_btn_ids"):
            return
        face, label = ((ACCENT, DEEP) if t == "btn" else (BTN_FACE, ACCENT))
        try:
            self.canvas.itemconfigure(self._btn_ids[0], fill=face)
            self.canvas.itemconfigure(self._btn_ids[1], fill=label)
        except tk.TclError:
            pass

    def place(self, x, y):
        self.pos = (x, y)
        if self.layered:
            self.geometry(f"{W}x{H}+{x}+{y}")
            self.update_idletasks()
            self._repaint()
        else:
            self.geometry(f"{CW}x{CH}+{x}+{y}")

    def _repaint(self):
        """레이어드 페인트. 실패하면 이 카드부터 캔버스 방식으로 되돌린다."""
        global _use_layered
        if not self.layered:
            return
        try:
            _paint_layered(toplevel_hwnd(self), self.img, self.alpha)
        except Exception:
            _use_layered = False
            self.layered = False
            try:
                self._build_canvas(self.item)
                x, y = self.pos
                self.geometry(f"{CW}x{CH}+{x + PAD}+{y + PAD}")
                self.attributes("-alpha", self.alpha / 255)
            except Exception:
                pass

    def set_alpha(self, a):
        self.alpha = max(0, min(255, int(a)))
        if self.layered:
            self._repaint()
        else:
            try:
                self.attributes("-alpha", self.alpha / 255)
            except Exception:
                pass

    def done(self):
        cb = self.item.get("on_done")
        if cb:
            try:
                cb()
            except Exception:
                pass
        self.close()

    def fade(self, target, step):
        a = self.alpha + step
        done = (step > 0 and a >= target) or (step < 0 and a <= 0)
        self.set_alpha(target if step > 0 and done else max(0, a))
        if done:
            if step < 0:
                self._destroy()
            return
        self.after(16, lambda: self.fade(target, step))

    def _expire(self):
        """수명이 끝났다. 읽고 있는 중이면(마우스가 위에 있으면) 조금 기다린다."""
        if self._over and time.time() - self.born < HOLD_MAX:
            self.after(1000, self._expire)
            return
        self.close()

    def close(self):
        if self._closing or self not in _live:
            return
        self._closing = True
        self.fade(0, -30)

    def _destroy(self):
        if self in _live:
            _live.remove(self)
        try:
            self.destroy()
        except Exception:
            pass
        _layout()


class _RECT(ctypes.Structure):
    _fields_ = [("left", ctypes.c_long), ("top", ctypes.c_long),
                ("right", ctypes.c_long), ("bottom", ctypes.c_long)]


def _work_area():
    """작업표시줄을 뺀 화면 영역. 화면 크기로 계산하면 카드가 작업표시줄에 가린다."""
    try:
        r = _RECT()
        if U32.SystemParametersInfoW(0x0030, 0, ctypes.byref(r), 0):   # SPI_GETWORKAREA
            return r.left, r.top, r.right, r.bottom
    except Exception:
        pass
    return 0, 0, _root.winfo_screenwidth(), _root.winfo_screenheight()


def _layout():
    _, _, sw, sh = _work_area()
    for n, card in enumerate(reversed(_live)):
        pad = PAD if card.layered else 0
        w = W if card.layered else CW
        try:
            card.place(sw - w - 20 + pad, sh - 12 - (n + 1) * (CH + GAP) - pad)
        except Exception:
            paths.log("toast: " + traceback.format_exc())


def _pump():
    if not getattr(_pump, "_logged", False):
        _pump._logged = True
        paths.log("toast._pump: 첫 실행")
    try:
        while True:
            try:
                item = _queue.get_nowait()
            except queue.Empty:
                break
            try:
                while len(_live) >= MAX_CARDS:
                    # 가장 오래된 것부터 즉시 없앤다. fade 를 기다리면 그 사이
                    # 새 카드가 위로 쌓여 화면을 넘어간다.
                    _live[0]._destroy()
                card = Card(_root, item)
                _live.append(card)
                _layout()
                card.fade(247, 30)
            except Exception:
                paths.log("toast: " + traceback.format_exc())
    except Exception:
        paths.log("toast: " + traceback.format_exc())
    try:
        _sweep()
    except Exception:
        paths.log("toast: " + traceback.format_exc())
    finally:
        # 무슨 일이 있어도 다음 회차를 예약한다
        _root.after(300, _pump)


def _sweep():
    """수명을 넘긴 카드를 강제로 없앤다.

    fade 는 Tk 의 after 로 이어지는데, 중간에 한 번 예외가 나면 그 사슬이
    끊겨 카드가 화면에 그대로 남는다. 그러면 다음 알림이 그 위에 겹쳐 떠서
    "지난 알림이 계속 보이는" 것처럼 된다. 마지막 안전망.
    """
    now = time.time()
    for card in list(_live):
        if now - getattr(card, "born", now) > HARD_LIFE:
            card._destroy()


def _safe(fn, tag):
    try:
        fn()
    except Exception:
        paths.log(tag + ": " + traceback.format_exc())


def run_forever(on_ready=None):
    """메인 스레드에서 호출. tkinter 이벤트 루프를 돈다."""
    global _root
    paths.log("toast.run_forever: Tk 생성 전")
    _root = tk.Tk()
    _root.withdraw()

    # 빌드본은 sys.stderr 가 None 이다. tkinter 기본 예외 처리기가 stderr 에
    # 쓰려다 실패하면 이벤트 루프째로 망가진다. 파일로 남기도록 교체한다.
    _root.report_callback_exception = lambda exc, val, tb: paths.log(
        "tk callback: " + "".join(traceback.format_exception(exc, val, tb)))

    _root.after(200, _pump)
    if on_ready:
        _root.after(300, lambda: _safe(on_ready, "on_ready"))
    paths.log("toast.run_forever: mainloop 진입")
    _root.mainloop()
    paths.log("toast.run_forever: mainloop 종료")


def stop():
    if _root:
        _root.quit()
