# -*- coding: utf-8 -*-
"""图标生成：麦克风造型，代码绘制，零美术素材。

生成两个 .ico：
  local-speak2text.ico          托盘态：16/24/32/48/64/256 帧
  local-speak2text-taskbar.ico  任务栏/窗口/exe：按 Windows 外壳真实索取的像素铺帧，
                                覆盖 100%~200% DPI（标题栏/任务栏/Alt-Tab），避免缩小发糊。

颜色语义与运行时托盘一致：蓝 = 空闲，橙 = 录音中；ico 用蓝色（默认态）。
"""
import math
import os

from PIL import Image, ImageDraw

APP_ID = "local-speak2text"
COLOR_IDLE = (30, 120, 230, 255)
COLOR_RECORDING = (240, 140, 20, 255)


def draw_mic(size, fill=COLOR_IDLE):
    """在 size×size 画布上画麦克风（与 main.py 托盘图标同一设计）。"""
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    s = size / 64.0  # 设计稿按 64 坐标
    # 话筒头
    d.rounded_rectangle([22 * s, 8 * s, 42 * s, 38 * s], radius=10 * s, fill=fill)
    # 三条白色栅格线
    for y in (15, 21, 27):
        d.rectangle([26 * s, y * s, 38 * s, (y + 2) * s], fill=(255, 255, 255, 255))
    # 支架弧
    d.arc([18 * s, 28 * s, 46 * s, 56 * s], start=0, end=180, fill=fill, width=max(2, round(4 * s)))
    # 立杆
    d.rectangle([30 * s, 46 * s, 34 * s, 55 * s], fill=fill)
    return img


TRAY_SIZES = (16, 24, 32, 48, 64, 256)
# 100%~200% DPI 下外壳真实索取的像素档（参见 reme-helper 同款清单）
TASKBAR_SIZES = (16, 20, 24, 28, 30, 32, 36, 40, 42, 48, 56, 64, 96, 128, 256)


def make_icons(base_dir):
    """在 base_dir 下生成托盘态与任务栏态两个 ico，返回 (托盘, 任务栏) 路径。"""
    tray_path = os.path.join(base_dir, f"{APP_ID}.ico")
    taskbar_path = os.path.join(base_dir, f"{APP_ID}-taskbar.ico")
    img = draw_mic(256, COLOR_IDLE)
    img.save(tray_path, sizes=[(s, s) for s in TRAY_SIZES])
    img.save(taskbar_path, sizes=[(s, s) for s in TASKBAR_SIZES])
    return tray_path, taskbar_path


if __name__ == "__main__":
    base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # 仓库根（ico 落根，构建按根取）
    t, k = make_icons(base)
    print("OK", t, k, "exists:", os.path.exists(t), os.path.exists(k))
