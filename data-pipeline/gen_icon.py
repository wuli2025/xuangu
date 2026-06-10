# -*- coding: utf-8 -*-
"""生成 SENTIO 应用源图标 1024x1024（深空 + 情绪温度环 + 上行箭头）。"""
import math
from pathlib import Path
from PIL import Image, ImageDraw

S = 4  # 超采样
W = 1024 * S
img = Image.new("RGBA", (W, W), (0, 0, 0, 0))
d = ImageDraw.Draw(img)


def lerp(a, b, t):
    return tuple(int(a[i] + (b[i] - a[i]) * t) for i in range(3))


# 圆角深空底
r = int(180 * S)
d.rounded_rectangle([0, 0, W, W], radius=r, fill=(7, 10, 18, 255))

# 径向辉光（蓝 / 青）
glow = Image.new("RGBA", (W, W), (0, 0, 0, 0))
gd = ImageDraw.Draw(glow)
for cx, cy, col, rad in [
    (0.2 * W, 0.12 * W, (91, 140, 255), 0.62 * W),
    (0.85 * W, 0.18 * W, (0, 224, 198), 0.58 * W),
    (0.5 * W, 0.92 * W, (0, 230, 154), 0.5 * W),
]:
    for i in range(60, 0, -1):
        a = int(20 * (i / 60) ** 2)
        rr = rad * i / 60
        gd.ellipse([cx - rr, cy - rr, cx + rr, cy + rr], fill=col + (a,))
img = Image.alpha_composite(img, glow)
d = ImageDraw.Draw(img)

# 情绪温度环：270° 渐变弧（蓝→青→翡翠绿），底部留口（仪表盘感）
cx, cy = W / 2, W / 2
ring_r = 0.33 * W
ring_w = int(58 * S)
start, end = 140, 140 + 260  # 顺时针留底部缺口
stops = [(91, 140, 255), (0, 224, 198), (0, 230, 154)]


def grad(t):
    if t < 0.5:
        return lerp(stops[0], stops[1], t / 0.5)
    return lerp(stops[1], stops[2], (t - 0.5) / 0.5)


steps = 720
for i in range(steps):
    t = i / (steps - 1)
    ang = math.radians(start + (end - start) * t)
    x = cx + ring_r * math.cos(ang)
    y = cy + ring_r * math.sin(ang)
    col = grad(t)
    d.ellipse([x - ring_w / 2, y - ring_w / 2, x + ring_w / 2, y + ring_w / 2], fill=col + (255,))

# 仪表「指针」金点（弧末端）
ang = math.radians(end)
px, py = cx + ring_r * math.cos(ang), cy + ring_r * math.sin(ang)
for rr, a in [(int(70 * S), 90), (int(46 * S), 255)]:
    col = (255, 207, 107)
    d.ellipse([px - rr, py - rr, px + rr, py + rr], fill=col + (a,))

# 中心上行箭头（翡翠绿→金渐变，赚钱感）
aw = int(46 * S)  # 线宽
# 主干：左下 → 右上
p0 = (cx - 0.16 * W, cy + 0.17 * W)
p1 = (cx + 0.02 * W, cy - 0.02 * W)
p2 = (cx + 0.17 * W, cy - 0.16 * W)
pts = [p0, p1, p2]
for j in range(len(pts) - 1):
    a, b = pts[j], pts[j + 1]
    seg = 120
    for k in range(seg):
        t = k / (seg - 1)
        x = a[0] + (b[0] - a[0]) * t
        y = a[1] + (b[1] - a[1]) * t
        gt = (j + t) / (len(pts) - 1)
        col = lerp((0, 230, 154), (255, 207, 107), gt)
        d.ellipse([x - aw / 2, y - aw / 2, x + aw / 2, y + aw / 2], fill=col + (255,))
# 箭头头部（金色三角）
hx, hy = p2
hs = 0.12 * W
d.polygon([
    (hx + hs * 0.5, hy - hs * 0.5),
    (hx - hs * 0.62, hy - hs * 0.18),
    (hx + hs * 0.18, hy + hs * 0.62),
], fill=(255, 207, 107, 255))

out = img.resize((1024, 1024), Image.LANCZOS)
dst = Path(__file__).resolve().parent.parent / "polaris-app" / "src-tauri" / "sentio-icon-src.png"
out.save(dst)
print("icon source saved →", dst)
