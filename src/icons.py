# -*- coding: utf-8 -*-
"""T6 构建工具的仓库根入口（工具自有壳，W6 薄壳化）。

build.bat GATE 调 `python src\\icons.py`：脚本目录（src/）自动进 sys.path，
`import template` 即命中。此前本文件是模板正本的完整副本（W1 平铺残留）——
双正本意味着模板升级它不会跟（W6 实测：icons 2.1.0 的 make_state_icons
它就没有），改为薄壳委派，正本唯一在 src/template/icons/。
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from template.icons.icons import (  # noqa: F401
    STATE_SIZES,
    TASKBAR_SIZES,
    TRAY_SIZES,
    base_image,
    make_icons,
    make_state_icons,
    state_keys,
)

if __name__ == "__main__":
    _src = Path(__file__).resolve().parent
    base = str(_src.parent)
    t, k = make_icons(base)
    states = make_state_icons(base)
    print("OK", t, k, "states:", {s: len(v) for s, v in states.items()},
          "exists:", Path(t).exists(), Path(k).exists())
