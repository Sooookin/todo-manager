# -*- coding: utf-8 -*-
"""앱 아이콘을 각 크기마다 새로 그린다 (python gen_icon.py).

큰 그림 하나를 축소하면 16px 에서 뭉개진다. 그래서 크기별로 8배 확대해
그린 뒤 LANCZOS 로 줄이고, 작은 크기에서는 여백·선 굵기 비율을 따로 준다.

결과: app.ico (16~256 다중 해상도) · web/icon.png (256, 트레이/웹용)
"""
import os

from PIL import Image, ImageDraw, ImageFilter

HERE = os.path.dirname(os.path.abspath(__file__))
SIZES = [16, 20, 24, 32, 40, 48, 64, 96, 128, 256]

TILE_HI = (240, 243, 242, 255)      # 타일 윗면 (빛)
TILE_LO = (214, 221, 220, 255)      # 타일 아랫면 (그늘)
EDGE    = (150, 166, 164, 90)       # 아주 얇은 경계선
CHECK   = (11, 44, 54, 255)         # 체크 - 팔레트 진한 청록. 16px 에서도 읽힌다


def _round_rect(size, radius, fill):
    im = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    ImageDraw.Draw(im).rounded_rectangle([0, 0, size - 1, size - 1], radius, fill=fill)
    return im


def draw(px):
    S = 8                                    # 수퍼샘플링 배수
    n = px * S
    im = Image.new("RGBA", (n, n), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)

    # 작은 크기는 여백을 줄여야 실제로 커 보인다
    pad = round(n * (0.045 if px <= 24 else 0.075))
    box = [pad, pad, n - pad - 1, n - pad - 1]
    side = box[2] - box[0]
    radius = round(side * 0.28)

    # 타일: 위(밝음) → 아래(어두움) 세로 그라데이션을 라운드 사각형으로 마스킹
    grad = Image.new("RGBA", (1, n))
    for y in range(n):
        t = y / max(1, n - 1)
        grad.putpixel((0, y), tuple(round(a + (b - a) * t) for a, b in zip(TILE_HI, TILE_LO)))
    grad = grad.resize((n, n))
    mask = Image.new("L", (n, n), 0)
    ImageDraw.Draw(mask).rounded_rectangle(box, radius, fill=255)
    im.paste(grad, (0, 0), mask)

    # 아래쪽 안쪽 그늘 (뉴모피즘) - 큰 크기에서만. 작은 크기에선 탁해진다
    if px >= 48:
        sh = Image.new("RGBA", (n, n), (0, 0, 0, 0))
        off = round(side * 0.035)
        ImageDraw.Draw(sh).rounded_rectangle(
            [box[0], box[1] + off, box[2], box[3] + off], radius, outline=(120, 140, 138, 70),
            width=max(1, round(side * 0.02)))
        sh = sh.filter(ImageFilter.GaussianBlur(side * 0.02))
        im.alpha_composite(Image.composite(sh, Image.new("RGBA", (n, n), (0, 0, 0, 0)),
                                           mask))
    d.rounded_rectangle(box, radius, outline=EDGE, width=max(S // 2, round(side * 0.008)))

    # 체크 표시 - 세 점을 지나는 둥근 선
    cx, cy = n / 2, n / 2
    u = side / 2                              # 반지름 단위
    pts = [(cx - u * 0.52, cy + u * 0.02),
           (cx - u * 0.14, cy + u * 0.42),
           (cx + u * 0.55, cy - u * 0.42)]
    w = round(side * (0.20 if px <= 24 else 0.165))
    d.line(pts, fill=CHECK, width=w, joint="curve")
    for p in (pts[0], pts[2]):                # 끝을 둥글게
        d.ellipse([p[0] - w / 2, p[1] - w / 2, p[0] + w / 2, p[1] + w / 2], fill=CHECK)

    return im.resize((px, px), Image.LANCZOS)


def main():
    frames = [draw(s) for s in SIZES]
    big = draw(256)
    big.save(os.path.join(HERE, "web", "icon.png"))
    # Pillow 의 ICO 저장은 sizes 로 넘긴 크기를 스스로 축소하므로,
    # 크기별로 따로 그린 프레임을 append_images 로 직접 넣는다.
    frames[-1].save(os.path.join(HERE, "app.ico"), format="ICO",
                    sizes=[(s, s) for s in SIZES],
                    append_images=frames[:-1])
    print("app.ico:", ", ".join(str(s) for s in SIZES))


if __name__ == "__main__":
    main()
