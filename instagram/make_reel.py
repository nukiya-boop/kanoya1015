#!/usr/bin/env python3
"""奈良春日の森 鹿のや — Instagram リール動画 (1080x1920 / 30fps / 30秒) を生成する。

写真は一切トリミングせず、額装した「夜の画廊」のように一枚ずつ見せる。

使い方:
    python3 instagram/make_reel.py                    # instagram/shikanoya_reel.mp4 を出力
    python3 instagram/make_reel.py --preview 1,5,12   # 指定秒のフレームを PNG で確認
"""
import argparse
import math
import os
import subprocess
from multiprocessing import Pool

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
FONTS = os.path.join(HERE, "fonts")
OUT = os.path.join(HERE, "shikanoya_reel.mp4")
MUSIC = os.path.join(HERE, "music", "Paper_Screens_and_Starlight.mp3")

W, H, FPS, DUR = 1080, 1920, 30, 30.0
NF = int(FPS * DUR)
GOLD = (201, 169, 110)
CREAM = (238, 230, 214)
CY = 830                     # 額の中心 (Reels の下部 UI を避けて少し上)
PORTRAIT_BOX = (780, 1170)
LANDSCAPE_BOX = (960, 640)
PAD = 70                     # 影のための余白
LINE_GAP, LINE_GAP2 = 18, 27  # 金の額縁線 (内・外)

# (ファイル, 題, 英題, 切り替え演出)
SLIDES = [
    ("7C1A5459.jpg", "迎えの灯り", "WELCOME LIGHT", "frame"),
    ("7C1A5456.jpg", "額縁の庭", "THE FRAMED GARDEN", "scroll"),
    ("7C1A5463.jpg", "竹垣の小径", "BAMBOO PATH", "wipe"),
    ("7C1A5461.jpg", "静寂の枝", "SILENT BRANCHES", "zoom"),
    ("7C1A5465.jpg", "石と緑の調べ", "STONE & GREEN", "shine"),
    ("7C1A5467.jpg", "苔の静けさ", "QUIET MOSS", "split"),
    ("7C1A5472.jpg", "障子あかり", "SHOJI GLOW", "diag"),
    ("7C1A5475.jpg", "宵の庭", "TWILIGHT GARDEN", "frame"),
]
SLOT0, SLOT, TR = 3.0, 3.0, 1.0   # 曲のフレーズ (6秒ごと) に切り替えを合わせる
OUTRO = SLOT0 + SLOT * len(SLIDES)  # 27.0s


def font(name, size):
    return ImageFont.truetype(os.path.join(FONTS, name), size)


MINCHO = "shippori-mincho-japanese-400-normal.woff"
MINCHO_M = "shippori-mincho-japanese-500-normal.woff"
CORM = "cormorant-garamond-latin-400-normal.woff"
CORM_I = "cormorant-garamond-latin-400-italic.woff"
CORM_M = "cormorant-garamond-latin-500-normal.woff"


# ---------------------------------------------------------------- helpers
def clamp(x, a=0.0, b=1.0):
    return max(a, min(b, x))


def ease(x):
    x = clamp(x)
    return 4 * x ** 3 if x < 0.5 else 1 - (-2 * x + 2) ** 3 / 2


def ease_out(x):
    x = clamp(x)
    return 1 - (1 - x) ** 3


def text_img(text, f, fill, ls=0):
    widths = [f.getlength(c) for c in text]
    total = sum(widths) + ls * (len(text) - 1)
    asc, desc = f.getmetrics()
    im = Image.new("RGBA", (math.ceil(total) + 8, asc + desc + 8), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    x = 4
    for c, w in zip(text, widths):
        d.text((x, 4), c, font=f, fill=fill)
        x += w + ls
    return im


def fade(im, a):
    if a >= 0.999:
        return im
    r, g, b, al = im.split()
    al = al.point(lambda v: int(v * a))
    return Image.merge("RGBA", (r, g, b, al))


def paste(canvas, im, x, y, a=1.0):
    """im を (x, y) に半透明合成 (はみ出しは切り捨て)。"""
    if a <= 0.003:
        return
    x, y = int(round(x)), int(round(y))
    l, t = max(0, -x), max(0, -y)
    r, b = min(im.width, W - x), min(im.height, H - y)
    if r <= l or b <= t:
        return
    if (l, t, r, b) != (0, 0, im.width, im.height):
        im = im.crop((l, t, r, b))
    canvas.alpha_composite(fade(im, a), (x + l, y + t))


def paste_c(canvas, im, cx, y, a=1.0):
    paste(canvas, im, cx - im.width / 2, y, a)


# ---------------------------------------------------------------- assets
def load_photo(path, box):
    im = Image.open(path)
    im.draft("RGB", (box[0] * 2, box[1] * 2))
    im = im.convert("RGB")
    s = min(box[0] / im.width, box[1] / im.height)
    return im, im.resize((round(im.width * s), round(im.height * s)), Image.LANCZOS)


def make_bg(src):
    s = max(W / src.width, H / src.height)
    bg = src.resize((math.ceil(src.width * s), math.ceil(src.height * s)), Image.BILINEAR)
    bg = bg.crop(((bg.width - W) // 2, (bg.height - H) // 2, (bg.width - W) // 2 + W, (bg.height - H) // 2 + H))
    bg = bg.resize((W // 4, H // 4), Image.BILINEAR).filter(ImageFilter.GaussianBlur(14)).resize((W, H), Image.BICUBIC)
    a = np.asarray(bg).astype(np.float32)
    lum = a.mean(axis=2, keepdims=True)
    a = (a * 0.6 + lum * 0.4) * 0.30  # 少し彩度と明るさを落とす
    return Image.fromarray(np.clip(a, 0, 255).astype(np.uint8)).convert("RGBA")


def make_layer(photo):
    pw, ph = photo.size
    lay = Image.new("RGBA", (pw + 2 * PAD, ph + 2 * PAD), (0, 0, 0, 0))
    sh = Image.new("L", lay.size, 0)
    ImageDraw.Draw(sh).rectangle((PAD - 6, PAD + 10, PAD + pw + 6, PAD + ph + 22), fill=200)
    sh = sh.filter(ImageFilter.GaussianBlur(26))
    lay.putalpha(sh)
    lay.paste(photo, (PAD, PAD))
    return lay


def make_label(i, title, en):
    no = text_img(f"No. {i + 1:02d}", font(CORM_I, 34), GOLD + (255,), 2)
    tt = text_img(title, font(MINCHO_M, 46), CREAM + (255,), 10)
    ee = text_img(en, font(CORM, 24), GOLD + (220,), 7)
    w = max(no.width, tt.width, ee.width)
    im = Image.new("RGBA", (w, no.height + tt.height + ee.height + 30), (0, 0, 0, 0))
    y = 0
    im.alpha_composite(no, ((w - no.width) // 2, y)); y += no.height + 6
    ImageDraw.Draw(im).line((w // 2 - 28, y, w // 2 + 28, y), fill=GOLD + (200,), width=1); y += 12
    im.alpha_composite(tt, ((w - tt.width) // 2, y)); y += tt.height + 4
    im.alpha_composite(ee, ((w - ee.width) // 2, y))
    return im


def build_assets():
    A = {"slides": []}
    for i, (fn, title, en, tr) in enumerate(SLIDES):
        src = Image.open(os.path.join(REPO, fn))
        box = PORTRAIT_BOX if src.height > src.width else LANDSCAPE_BOX
        full, photo = load_photo(os.path.join(REPO, fn), box)
        A["slides"].append({
            "layer": make_layer(photo), "size": photo.size, "bg": make_bg(full),
            "label": make_label(i, title, en), "tr": tr,
        })
    # 周辺減光
    yy, xx = np.mgrid[0:H, 0:W].astype(np.float32)
    d = np.sqrt(((xx - W / 2) / (W * 0.62)) ** 2 + ((yy - H * 0.45) / (H * 0.6)) ** 2)
    vig = np.zeros((H, W, 4), np.uint8)
    vig[..., 3] = (np.clip(d - 0.35, 0, 1) ** 1.6 * 235).astype(np.uint8)
    A["vignette"] = Image.fromarray(vig)
    # 漂う金の光の粒
    rng = np.random.default_rng(7)
    A["dust"] = []
    for _ in range(28):
        r = rng.uniform(2.0, 5.5)
        n = int(r * 6)
        spr = Image.new("L", (n, n), 0)
        ImageDraw.Draw(spr).ellipse((n / 2 - r, n / 2 - r, n / 2 + r, n / 2 + r), fill=255)
        spr = spr.filter(ImageFilter.GaussianBlur(r * 0.8))
        im = Image.new("RGBA", (n, n), (255, 220, 160, 0)); im.putalpha(spr)
        A["dust"].append((im, rng.uniform(0, W), rng.uniform(0, H), rng.uniform(12, 38),
                          rng.uniform(0.15, 0.45), rng.uniform(0, 6.28), rng.uniform(0.4, 1.2)))
    # イントロ: 縦書き
    f = font(MINCHO, 70)
    A["intro_cols"] = [[text_img(c, f, CREAM + (255,)) for c in col] for col in ("まるで絵画のような", "夜の庭をめぐる")]
    A["intro_sub1"] = text_img("奈良春日の森　鹿のや", font(MINCHO, 34), CREAM + (255,), 8)
    A["intro_sub2"] = text_img("NARA KASUGA NO MORI  SHIKANOYA", font(CORM, 24), GOLD + (255,), 7)
    A["brand"] = text_img("SHIKANOYA", font(CORM_M, 30), GOLD + (255,), 14)
    # アウトロ
    A["out"] = [
        (text_img("奈良春日の森", font(MINCHO, 40), CREAM + (255,), 16), 690, 27.2),
        (text_img("鹿のや", font(MINCHO_M, 124), CREAM + (255,), 34), 760, 27.45),
        (text_img("SHIKANOYA", font(CORM_M, 34), GOLD + (255,), 18), 965, 27.7),
        (text_img("庭を望むラウンジで、静かな夜を。", font(MINCHO, 36), CREAM + (255,), 6), 1090, 28.1),
    ]
    A["grain"] = [rng.integers(-3, 4, (H, W, 3), dtype=np.int16) for _ in range(6)]
    return A


ASSETS = None


# ---------------------------------------------------------------- timeline
def slot_start(i):
    return SLOT0 + SLOT * i


def slide_state(i, t):
    """各スライドの表示状態。None なら非表示。"""
    S = slot_start(i)
    tr = SLIDES[i][3]
    t_in = S - TR / 2
    if t < t_in:
        return None
    end = slot_start(i + 1) - TR / 2 if i < len(SLIDES) - 1 else OUTRO - 0.5
    if t > end + TR:
        return None
    ts = t - t_in
    out_a = 1 - ease((t - end) / TR)
    st = {"alpha": out_a, "mask": None, "line_p": 1.0, "line_a": out_a, "shine": None,
          "scale": 0.965 + 0.045 * clamp((t - t_in) / (SLOT + TR + 0.5))}
    pe = ease(ts / TR)
    if tr == "frame":
        st["line_p"] = ease(ts / 0.9)
        st["alpha"] *= ease((ts - 0.45) / 0.9)
        st["shine"] = (ts - 1.2) / 1.4
    elif tr in ("scroll", "wipe", "split", "diag"):
        st["mask"] = (tr, ease(ts / (TR * 1.3)))
        st["line_a"] *= pe
    elif tr == "zoom":
        st["alpha"] *= pe
        st["scale"] += 0.07 * (1 - ease_out(ts / (TR * 1.4)))
    elif tr == "shine":
        st["alpha"] *= pe
        st["line_a"] *= pe
        st["shine"] = (ts - 0.6) / 1.4
    lab_in = ease_out((t - S - 0.1) / 0.8)
    lab_out = 1 - ease((t - (end - 0.2)) / 0.6)
    st["label_a"] = lab_in * lab_out
    st["label_dy"] = 18 * (1 - lab_in)
    return st


def apply_mask(arr, st, s, pw, ph):
    h, w = arr.shape[:2]
    u = (np.arange(w, dtype=np.float32) - PAD * s) / (pw * s)
    v = (np.arange(h, dtype=np.float32) - PAD * s) / (ph * s)
    U, V = u[None, :], v[:, None]
    a = np.ones((h, w), np.float32)
    if st["mask"]:
        kind, p = st["mask"]
        e = 0.22
        q = {"scroll": V + 0 * U, "wipe": U + 0 * V, "split": np.abs(V - 0.5) * 2 + 0 * U,
             "diag": (U + V) / 2}[kind]
        a *= np.clip((p * (1 + e) - q) / e, 0, 1)
    if st["shine"] is not None and 0 < st["shine"] < 1:
        c = -0.3 + 1.6 * st["shine"]
        band = np.exp(-((((U + V) / 2) - c) / 0.06) ** 2) * 0.22
        inside = ((U >= 0) & (U <= 1) & (V >= 0) & (V <= 1)).astype(np.float32)
        band = (band * inside)[..., None]
        rgb = arr[..., :3].astype(np.float32)
        arr[..., :3] = np.clip(rgb + (255 - rgb) * band, 0, 255).astype(np.uint8)
    arr[..., 3] = (arr[..., 3] * a * st["alpha"]).astype(np.uint8)
    return arr


def draw_frame_lines(draw, rect, p, a):
    if a <= 0.003 or p <= 0:
        return
    x0, y0, x1, y1 = rect
    cx = (x0 + x1) / 2
    half = [(cx, y0), (x1, y0), (x1, y1), (cx, y1)]
    total = sum(math.dist(half[k], half[k + 1]) for k in range(3))
    remain = total * p
    pts = [half[0]]
    for k in range(3):
        seg = math.dist(half[k], half[k + 1])
        if remain >= seg:
            pts.append(half[k + 1]); remain -= seg
        else:
            f = remain / seg
            pts.append((half[k][0] + (half[k + 1][0] - half[k][0]) * f, half[k][1] + (half[k + 1][1] - half[k][1]) * f))
            break
    col = GOLD + (int(255 * a),)
    draw.line(pts, fill=col, width=2)
    draw.line([(2 * cx - x, y) for x, y in pts], fill=col, width=2)


def render(fi):
    A = ASSETS
    t = fi / FPS
    canvas = Image.new("RGBA", (W, H), (10, 8, 6, 255))
    states = [slide_state(i, t) for i in range(len(SLIDES))]

    # 背景 (ぼかした写真)
    k = max([i for i in range(len(SLIDES)) if t >= slot_start(i) - TR / 2] or [0])
    if k == 0:
        canvas.alpha_composite(fade(A["slides"][0]["bg"], 0.55 * ease(t / 1.6) + 0.45 * ease((t - 2.5) / TR)))
    else:
        canvas.alpha_composite(A["slides"][k - 1]["bg"])
        canvas.alpha_composite(fade(A["slides"][k]["bg"], ease((t - slot_start(k) + TR / 2) / TR)))
    canvas.alpha_composite(A["vignette"])
    if t > OUTRO - 0.4:
        canvas.alpha_composite(Image.new("RGBA", (W, H), (6, 5, 4, int(120 * ease((t - OUTRO + 0.4) / 1.2)))))

    # 光の粒
    for spr, x, y, sp, al, ph, tw in A["dust"]:
        yy = (y - sp * t) % (H + 40) - 20
        xx = x + 14 * math.sin(t * 0.5 + ph)
        paste(canvas, spr, xx, yy, al * (0.6 + 0.4 * math.sin(t * tw + ph)))

    ov = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    od = ImageDraw.Draw(ov)

    # 額装した写真
    for i, st in enumerate(states):
        if not st:
            continue
        sl = A["slides"][i]
        pw, ph = sl["size"]
        s = st["scale"]
        lay = sl["layer"]
        lay = lay.resize((round(lay.width * s), round(lay.height * s)), Image.BICUBIC)
        arr = apply_mask(np.array(lay), st, s, pw, ph)
        paste(canvas, Image.fromarray(arr), W / 2 - arr.shape[1] / 2, CY - arr.shape[0] / 2)
        hw, hh = pw * s / 2, ph * s / 2
        g, g2 = LINE_GAP * s, LINE_GAP2 * s
        draw_frame_lines(od, (W / 2 - hw - g, CY - hh - g, W / 2 + hw + g, CY + hh + g), st["line_p"], st["line_a"])
        draw_frame_lines(od, (W / 2 - hw - g2, CY - hh - g2, W / 2 + hw + g2, CY + hh + g2), st["line_p"], st["line_a"] * 0.35)
        paste_c(canvas, sl["label"], W / 2, CY + ph / 2 + 64 + st["label_dy"], st["label_a"])
    canvas.alpha_composite(ov)

    # 上部ブランド表記
    ba = ease((t - 2.8) / 0.8) * (1 - ease((t - OUTRO + 0.5) / 0.6))
    if ba > 0:
        b = A["brand"]
        paste_c(canvas, b, W / 2, 128, ba * 0.9)
        d = ImageDraw.Draw(canvas)
        col = GOLD + (int(150 * ba),)
        y = 128 + b.height / 2
        d.line((W / 2 - b.width / 2 - 70, y, W / 2 - b.width / 2 - 14, y), fill=col, width=1)
        d.line((W / 2 + b.width / 2 + 14, y, W / 2 + b.width / 2 + 70, y), fill=col, width=1)

    # イントロ (縦書き)
    if t < 3.2:
        io = 1 - ease((t - 2.35) / 0.55)
        for c, (col, x, y0, t0) in enumerate(zip(A["intro_cols"], (600, 470), (350, 446), (0.25, 0.95))):
            for k, ch in enumerate(col):
                p = ease_out((t - t0 - k * 0.07) / 0.7)
                paste_c(canvas, ch, x, y0 + k * 96 + 14 * (1 - p), p * io)
        p = ease_out((t - 1.55) / 0.7) * io
        if p > 0:
            ImageDraw.Draw(canvas).line((W / 2 - 40 * p, 1290, W / 2 + 40 * p, 1290), fill=GOLD + (int(220 * p),), width=1)
            paste_c(canvas, A["intro_sub1"], W / 2, 1316, p)
            paste_c(canvas, A["intro_sub2"], W / 2, 1376, p)

    # アウトロ
    if t > OUTRO:
        d = ImageDraw.Draw(canvas)
        for im, y, t0 in A["out"]:
            p = ease_out((t - t0) / 0.9)
            paste_c(canvas, im, W / 2, y + 14 * (1 - p), p)
        p = ease((t - 27.8) / 0.9)
        if p > 0:
            for yl in (655, 1050):
                d.line((W / 2 - 90 * p, yl, W / 2 + 90 * p, yl), fill=GOLD + (int(200 * p),), width=1)
            dm = 5
            d.polygon([(W / 2, 655 - dm), (W / 2 + dm, 655), (W / 2, 655 + dm), (W / 2 - dm, 655)], fill=GOLD + (int(230 * p),))

    out = np.asarray(canvas.convert("RGB")).astype(np.int16) + A["grain"][fi % len(A["grain"])]
    return np.clip(out, 0, 255).astype(np.uint8).tobytes()


def main():
    global ASSETS
    ap = argparse.ArgumentParser()
    ap.add_argument("--preview", help="カンマ区切りの秒数。PNG を書き出して終了")
    ap.add_argument("--out", default=OUT)
    ap.add_argument("--music", default=MUSIC, help="BGM。空文字なら無音")
    args = ap.parse_args()
    ASSETS = build_assets()

    if args.preview:
        for sec in args.preview.split(","):
            fi = min(NF - 1, int(float(sec) * FPS))
            Image.frombytes("RGB", (W, H), render(fi)).save(f"{args.out}.preview_{float(sec):05.2f}.png")
        return

    cmd = ["ffmpeg", "-y", "-loglevel", "error",
           "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}", "-r", str(FPS), "-i", "-",
           *(["-i", args.music] if args.music else ["-f", "lavfi", "-i", "anullsrc=r=44100:cl=stereo"]),
           "-af", f"loudnorm=I=-15:TP=-1.5:LRA=11,afade=t=in:d=0.3,afade=t=out:st={DUR - 2.8}:d=2.8,atrim=0:{DUR}",
           "-t", str(DUR),
           "-c:v", "libx264", "-preset", "slow", "-crf", "17", "-pix_fmt", "yuv420p",
           "-profile:v", "high", "-c:a", "aac", "-b:a", "192k", "-ar", "44100", "-movflags", "+faststart", args.out]
    ff = subprocess.Popen(cmd, stdin=subprocess.PIPE)
    with Pool(os.cpu_count()) as pool:
        for k, buf in enumerate(pool.imap(render, range(NF), chunksize=6)):
            ff.stdin.write(buf)
            if k % 150 == 0:
                print(f"  {k}/{NF}", flush=True)
    ff.stdin.close()
    ff.wait()
    print("done:", args.out)


if __name__ == "__main__":
    main()
