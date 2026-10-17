# -*- coding: utf-8 -*-
"""从 DeepSeek 娘精灵图生成应用图标（不再手绘）。

形象来源（非官方同人作品，见 README「致谢」）：
    https://github.com/xpy12367/codex-pet-DeepSeek-girl
    精灵图 8 列 × 11 行，单元 192×208；本脚本取 row0/col0 的正面待机帧。

产出：
    packaging/app.ico      编译进 exe 的图标（16~256 多尺寸）
    web/icon.png           网页图标 / 任务栏图标（深色圆角框 + DeepSeek 蓝描边）
    web/mascot.png         顶栏头像用的头部特写（透明底）

要点：图标要在大尺寸给全身+鲸尾、小尺寸只给头和肩 —— 16px 下全身就是一团蓝，
所以按尺寸换裁切（真实图标集都是这么做的）。
"""
import os
from PIL import Image, ImageDraw, ImageFilter

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
WEB_DIR = os.path.join(ROOT, "web")
ASSET = os.path.join(HERE, "assets", "deepseek-girl-spritesheet.webp")

CELL_W, CELL_H = 192, 208
FRAME = (0, 0)                      # row0/col0：正面待机
CROP_BIG = (22, 4, 170, 162)        # 头 → 裙摆 + 鲸尾
CROP_SMALL = (34, 1, 158, 125)      # 头 + 肩（小尺寸用）
CROP_FACE = (44, 0, 148, 104)       # 头像用

INK = (20, 19, 19)                  # 图标底：和界面同色
DS_BLUE = (77, 107, 254)            # DeepSeek 品牌蓝（外框描边）

# 精灵图是第三方同人素材，不随仓库分发；缺失时按这个地址自动下载（README 里也记了）
ASSET_URL = ("https://raw.githubusercontent.com/xpy12367/"
             "codex-pet-DeepSeek-girl/main/spritesheet.webp")


def ensure_asset():
    if os.path.exists(ASSET):
        return
    os.makedirs(os.path.dirname(ASSET), exist_ok=True)
    print("  素材缺失，按 README 记录的地址下载：")
    print("  " + ASSET_URL)
    import urllib.request
    urllib.request.urlretrieve(ASSET_URL, ASSET)


def load_frame():
    im = Image.open(ASSET).convert("RGBA")
    if im.size != (CELL_W * 8, CELL_H * 11):
        # 尺寸变了就按声明推导，避免硬编码失效
        raise SystemExit("精灵图尺寸不符：%s（预期 %dx%d）"
                         % (im.size, CELL_W * 8, CELL_H * 11))
    col, row = FRAME
    return im.crop((col * CELL_W, row * CELL_H, (col + 1) * CELL_W, (row + 1) * CELL_H))


def square(img, size, pad=0.03):
    """把任意长宽比的图居中放进正方画布（透明底）。"""
    w, h = img.size
    side = int(max(w, h) * (1 + pad * 2))
    canvas = Image.new("RGBA", (side, side), (0, 0, 0, 0))
    canvas.alpha_composite(img, ((side - w) // 2, (side - h) // 2))
    return canvas.resize((size, size), Image.LANCZOS)


def app_icon(cell, size):
    """带深色圆角框 + 品牌蓝描边的应用图标；小尺寸自动换更近的裁切。"""
    s = size * 4
    base = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    d = ImageDraw.Draw(base)
    d.rounded_rectangle([0, 0, s - 1, s - 1], radius=int(s * 0.22), fill=INK + (255,),
                        outline=DS_BLUE, width=max(2, int(s * 0.028)))
    crop = CROP_BIG if size >= 48 else CROP_SMALL
    fig = square(cell.crop(crop), int(s * 0.95))
    base.alpha_composite(fig, ((s - fig.size[0]) // 2, (s - fig.size[1]) // 2))
    out = base.resize((size, size), Image.LANCZOS)
    # 源精灵图只有 ~150px，放大到 256 会发软 —— 补一道轻锐化（小尺寸是从大图缩下来的，
    # 本来就锐，所以只在 48px 以上做）
    if size >= 48:
        rgb = out.convert("RGB").filter(ImageFilter.UnsharpMask(radius=1.4, percent=55, threshold=3))
        out = Image.merge("RGBA", (*rgb.split(), out.split()[3]))
    return out


def main():
    ensure_asset()
    cell = load_frame()
    sizes = [256, 128, 64, 48, 32, 24, 16]
    app_icon(cell, 256).save(os.path.join(HERE, "app.ico"), format="ICO",
                             sizes=[(x, x) for x in sizes])
    app_icon(cell, 256).save(os.path.join(WEB_DIR, "icon.png"))
    square(cell.crop(CROP_FACE), 256).save(os.path.join(WEB_DIR, "mascot.png"))

    # 预览：大尺寸一排 + 真实像素尺寸一排（判断 16px 还能不能认出来）
    row = 300
    total_w = 20 + sum(x + 20 for x in sizes)
    prev = Image.new("RGB", (total_w, row * 2 + 40), (12, 12, 12))
    prev.paste(Image.new("RGB", (total_w, row), (233, 231, 228)), (0, row + 30))
    x = 20
    for sz in sizes:
        ic = app_icon(cell, sz)
        prev.paste(ic, (x, 20 + (256 - sz) // 2), ic)
        prev.paste(ic, (x, row + 50 + (256 - sz) // 2), ic)
        x += sz + 20
    prev.save(os.path.join(HERE, "_icon_preview.png"))

    for f in ("app.ico", os.path.join("..", "web", "icon.png"), os.path.join("..", "web", "mascot.png")):
        p = os.path.normpath(os.path.join(HERE, f))
        print("  %-22s %6.1f KB" % (os.path.basename(p), os.path.getsize(p) / 1024))


if __name__ == "__main__":
    main()
