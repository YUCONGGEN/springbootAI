"""生成 SpringBootAI README 顶部 banner 图片（v2 优化版）。

输出：doc/images/hero-banner.png
尺寸：1600x500

v2 改进：
- 标题字号 72→100，确保字体加载成功并验证
- 标签改为圆角 pills，背景更亮，文字纯白
- 副标题提亮
- 左侧 logo 放大，平衡左右视觉重量
"""
from __future__ import annotations

import os
import math
import random
from PIL import Image, ImageDraw, ImageFont, ImageFilter

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "doc", "images", "hero-banner.png")

W, H = 1600, 500

# 配色
BG_TOP = (10, 18, 40)
BG_BOTTOM = (5, 8, 22)
ACCENT_CYAN = (0, 200, 255)
ACCENT_GREEN = (80, 220, 130)
ACCENT_BLUE = (60, 130, 255)
ACCENT_PURPLE = (160, 100, 255)
ACCENT_ORANGE = (255, 160, 60)
TEXT_WHITE = (255, 255, 255)       # v2: 纯白，提升对比度
TEXT_BRIGHT = (220, 230, 245)      # v2: 提亮副标题
TEXT_DIM = (170, 185, 210)         # v2: 提亮
LABEL_BG = (30, 42, 68)            # v2: 标签背景更亮
LABEL_BORDER = (60, 80, 120)


def _font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    candidates = []
    if bold:
        candidates += [
            r"C:\Windows\Fonts\arialbd.ttf",
            r"C:\Windows\Fonts\segoeuib.ttf",
            r"C:\Windows\Fonts\msyhbd.ttc",
            r"C:\Windows\Fonts\simhei.ttf",
        ]
    else:
        candidates += [
            r"C:\Windows\Fonts\arial.ttf",
            r"C:\Windows\Fonts\segoeui.ttf",
            r"C:\Windows\Fonts\msyh.ttc",
            r"C:\Windows\Fonts\simsun.ttc",
        ]
    for path in candidates:
        try:
            f = ImageFont.truetype(path, size)
            print(f"  [font] loaded: {path} @ {size}")
            return f
        except Exception:
            continue
    print(f"  [font] WARNING: no truetype found, using default @ {size}")
    return ImageFont.load_default()


def _vertical_gradient(img: Image.Image, top: tuple, bottom: tuple) -> None:
    px = img.load()
    for y in range(H):
        t = y / (H - 1)
        r = int(top[0] + (bottom[0] - top[0]) * t)
        g = int(top[1] + (bottom[1] - top[1]) * t)
        b = int(top[2] + (bottom[2] - top[2]) * t)
        for x in range(W):
            px[x, y] = (r, g, b)


def _draw_grid(draw: ImageDraw.ImageDraw) -> None:
    color = (20, 30, 55)
    step = 50
    for x in range(0, W, step):
        draw.line([(x, 0), (x, H)], fill=color, width=1)
    for y in range(0, H, step):
        draw.line([(0, y), (W, y)], fill=color, width=1)


def _draw_node_network(draw: ImageDraw.ImageDraw) -> None:
    """右侧发光节点网络（IoC 容器 + 微服务）。"""
    random.seed(42)
    cx, cy = 1280, 230
    nodes = []
    for i in range(16):
        angle = (i / 16) * 2 * math.pi
        radius = random.randint(70, 180)
        x = cx + int(math.cos(angle) * radius)
        y = cy + int(math.sin(angle) * radius * 0.65)
        nodes.append((x, y))

    # 连线
    for i, (x1, y1) in enumerate(nodes):
        for j, (x2, y2) in enumerate(nodes):
            if j <= i:
                continue
            dist = math.hypot(x2 - x1, y2 - y1)
            if dist < 140:
                draw.line([(x1, y1), (x2, y2)], fill=(50, 110, 170), width=1)

    # 节点
    for x, y in nodes:
        draw.ellipse([x - 7, y - 7, x + 7, y + 7], fill=ACCENT_CYAN, outline=(180, 240, 255))

    # 中心节点
    draw.ellipse([cx - 22, cy - 22, cx + 22, cy + 22], fill=ACCENT_GREEN, outline=(200, 255, 220))
    draw.ellipse([cx - 34, cy - 34, cx + 34, cy + 34], outline=(60, 180, 100), width=2)
    draw.ellipse([cx - 46, cy - 46, cx + 46, cy + 46], outline=(40, 130, 80), width=1)


def _draw_logo_leaf(draw: ImageDraw.ImageDraw, cx: int, cy: int, size: int) -> None:
    """Spring 风格叶子 logo，放大版。"""
    points_top = []
    points_bot = []
    for i in range(50):
        t = i / 49
        angle = math.pi * t
        r = size * math.sin(angle)
        x = cx - size + int(2 * size * t)
        y_top = cy - int(r * 0.95)
        y_bot = cy + int(r * 0.95)
        points_top.append((x, y_top))
        points_bot.append((x, y_bot))
    leaf = points_top + list(reversed(points_bot))
    draw.polygon(leaf, fill=ACCENT_GREEN, outline=(180, 255, 200))

    # 叶脉
    draw.line([(cx - size, cy), (cx + size, cy)], fill=(20, 80, 40), width=3)
    for i in range(1, 6):
        t = i / 6
        x = cx - size + int(2 * size * t)
        r = size * math.sin(math.pi * t)
        draw.line([(x, cy), (x + int(r * 0.45), cy - int(r * 0.55))], fill=(20, 80, 40), width=2)
        draw.line([(x, cy), (x + int(r * 0.45), cy + int(r * 0.55))], fill=(20, 80, 40), width=2)


def _draw_module_pills(draw: ImageDraw.ImageDraw, y: int) -> None:
    """底部功能模块圆角标签（pills 风格，高对比度）。"""
    modules = [
        ("Web MVC", ACCENT_CYAN),
        ("ORM", ACCENT_GREEN),
        ("AI / LangChain", ACCENT_PURPLE),
        ("Cloud", ACCENT_BLUE),
        ("Monitoring", ACCENT_ORANGE),
        ("Security", (255, 90, 110)),
        ("Excel / CSV", (255, 210, 90)),
        ("WebSocket", (100, 240, 200)),
    ]
    font = _font(22, bold=True)

    gaps = 14
    widths = []
    for name, _ in modules:
        bbox = font.getbbox(name)
        w = (bbox[2] - bbox[0]) + 44  # 左色块12 + padding 32
        widths.append(max(w, 110))    # 最小宽度 110

    total = sum(widths) + gaps * (len(modules) - 1)
    x = (W - total) // 2

    for (name, color), bw in zip(modules, widths):
        # 圆角 pill 背景（更亮）
        draw.rounded_rectangle([x, y, x + bw, y + 42], radius=21,
                               fill=LABEL_BG, outline=color, width=2)
        # 左侧色块（圆点）
        dot_x = x + 18
        dot_y = y + 21
        draw.ellipse([dot_x - 7, dot_y - 7, dot_x + 7, dot_y + 7], fill=color)
        # 文字（纯白）
        bbox = font.getbbox(name)
        tw = bbox[2] - bbox[0]
        tx = x + 34 + (bw - 34 - tw) // 2
        ty = y + (42 - (bbox[3] - bbox[1])) // 2 - bbox[1]
        draw.text((tx, ty), name, font=font, fill=TEXT_WHITE)
        x += bw + gaps


def main() -> None:
    os.makedirs(os.path.dirname(OUT), exist_ok=True)

    img = Image.new("RGB", (W, H), BG_BOTTOM)
    _vertical_gradient(img, BG_TOP, BG_BOTTOM)

    # 用 RGBA 叠加层绘制
    draw = ImageDraw.Draw(img, "RGBA")
    _draw_grid(draw)
    _draw_node_network(draw)

    # 左侧 logo（放大，平衡视觉）
    _draw_logo_leaf(draw, 130, 130, 55)
    # Python 蛇简化：两条交叠彩色弧
    draw.arc([55, 70, 205, 220], start=200, end=340, fill=ACCENT_BLUE, width=9)
    draw.arc([55, 85, 205, 235], start=20, end=160, fill=(255, 200, 50), width=9)

    # === 大标题（v2: 字号 100，纯白）===
    print("Loading title font...")
    title_font = _font(96, bold=True)
    sub_font = _font(26, bold=False)
    version_font = _font(22, bold=False)

    title = "SpringBootAI"
    bbox = title_font.getbbox(title)
    title_w = bbox[2] - bbox[0]
    title_h = bbox[3] - bbox[1]
    print(f"  title bbox: {bbox}, size: {title_w}x{title_h}")

    # 标题阴影（轻微发光效果）
    shadow_layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    shadow_draw = ImageDraw.Draw(shadow_layer)
    shadow_draw.text((78, 218), title, font=title_font, fill=(80, 180, 130, 60))
    shadow_layer = shadow_layer.filter(ImageFilter.GaussianBlur(8))
    img.paste(shadow_layer, (0, 0), shadow_layer)

    # 标题正文
    draw.text((80, 215), title, font=title_font, fill=TEXT_WHITE)

    # 副标题
    draw.text((84, 320), "Spring-style Python framework for Web, AI and microservices",
              font=sub_font, fill=TEXT_BRIGHT)

    # 版本信息
    draw.text((84, 360), "v2.2.6  ·  Python 3.10+  ·  MIT License  ·  FastAPI / Uvicorn",
              font=version_font, fill=(120, 190, 230))

    # 底部功能模块 pills
    _draw_module_pills(draw, y=420)

    # 顶底边线
    draw.line([(0, 0), (W, 0)], fill=ACCENT_CYAN, width=2)
    draw.line([(0, H - 1), (W, H - 1)], fill=(30, 50, 90), width=2)

    # 中心节点发光
    glow = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    glow_draw = ImageDraw.Draw(glow)
    glow_draw.ellipse([1240, 195, 1320, 275], fill=(80, 220, 130, 90))
    glow = glow.filter(ImageFilter.GaussianBlur(35))
    img.paste(glow, (0, 0), glow)

    img.save(OUT, "PNG", optimize=True)
    size_kb = os.path.getsize(OUT) // 1024
    print(f"\nBanner saved: {OUT}  ({W}x{H}, {size_kb} KB)")


if __name__ == "__main__":
    main()
