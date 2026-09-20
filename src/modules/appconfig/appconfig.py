# -*- coding: utf-8 -*-
# TEMPLATE-FROM: my-diy-tool-template/modules/appconfig/appconfig.py | TEMPLATE-VER: 1.0.1
"""local-speak2text 参数区（T1：拷贝模板后**唯一允许（也需要）修改的文件**）。

工具差异只允许存在于一处（house 标准 D6 / D15）。本文件按设计豁免 sync_check 比对
（参数文件），但头部仍申报来源，C-19 据此判定。
说明：模板 appconfig 的 ICON_DRAW 示例签名是 (ctx, size)，但模板 icons.py 2.0.0 以
`ICON_DRAW(256)` 单参调用；本工具取兼容形态 `ICON_DRAW(size, fill=...)`（T6 需要）。
VERSION 已按 A1-03/D15 集中到本文件，是全仓唯一事实源（build.bat / release.bat /
release.yml 均从这里解析）。
"""
APP_ID = "local-speak2text"
APP_NAME = "LocalSpeak2Text"   # 历史注册表自启键名，改名 = 断链（NAME-05），不得擅动
# 版本号只在"发版"动作里改（STANDARDS G3 第 7 条）；开发期改动挂在 CHANGELOG 的 ## Unreleased。
# 铁律：下面这行除空白外不得有任何行尾内容——build.bat / CI 用 for/f 解析它，
# 行尾追加注释会被 tokens=2,* 当成版本号一起吞掉，制造垃圾 release 路径。
VERSION = "1.4.4"

REPO_OWNER = "KenneLu"
REPO_NAME = "local-speak2text"
EXE_NAME = "local-speak2text.exe"

# 托盘/图标配色：蓝 = 空闲，橙 = 录音中
COLOR_IDLE = (30, 120, 230, 255)
COLOR_RECORDING = (240, 140, 20, 255)

# G5：本工具无手工资产，图形全部代码绘制（icons.base_image 走 ICON_DRAW 分支）
ICON_ASSET = None


def ICON_DRAW(size, fill=COLOR_IDLE):
    """在 size×size 画布上画麦克风（与运行时托盘图标同一设计语言）。

    这是本工具唯一真正的"个性"，同时被 T6（构建期 ico）与 main.py（运行时托盘）
    消费——图形只有这一处定义，改图 = 改这一个函数。
    """
    from PIL import Image, ImageDraw

    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    s = size / 64.0  # 设计稿按 64 坐标
    # 话筒头
    d.rounded_rectangle([22 * s, 8 * s, 42 * s, 38 * s], radius=10 * s, fill=fill)
    # 三条白色栅格线
    for y in (15, 21, 27):
        d.rectangle([26 * s, y * s, 38 * s, (y + 2) * s], fill=(255, 255, 255, 255))
    # 支架弧
    d.arc([18 * s, 28 * s, 46 * s, 56 * s], start=0, end=180, fill=fill,
          width=max(2, round(4 * s)))
    # 立杆
    d.rectangle([30 * s, 46 * s, 34 * s, 55 * s], fill=fill)
    return img
