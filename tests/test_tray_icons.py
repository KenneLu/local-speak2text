# -*- coding: utf-8 -*-
"""tray_icons 静态贴图断言（W6）：状态定义 == 资产目录（防"定义了没生成/生成了没定义"漂移，
test_i18n_keys 同款手法）+ 按档加载 + 缺图回退 default 永不崩。
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from template.tray_icons import tray_icons  # noqa: E402
from template.appconfig import ICON_STATE_ARTISTS  # noqa: E402

FAILS = []


def check(name, ok, detail=""):
    print(("  ok  " if ok else "  FAIL") + " " + name + ("  " + str(detail) if not ok else ""), flush=True)
    if not ok:
        FAILS.append(name)


ROOT = Path(__file__).resolve().parents[1]
ASSET_DIR = ROOT / "resources" / "icons"

# ① 状态定义 == 资产目录（default 恒在资产侧，不进 ARTISTS）
want = set(ICON_STATE_ARTISTS or {}) | {"default"}
have = {p.name for p in ASSET_DIR.iterdir() if p.is_dir()} if ASSET_DIR.is_dir() else set()
check("状态键集 == 资产目录状态集", want == have,
      "定义=%s 资产=%s 差=%s" % (sorted(want), sorted(have), sorted(want ^ have)))

# ② 每状态每档帧在位
from template.icons.icons import STATE_SIZES  # noqa: E402
missing = [f"{s}/{z}.png" for s in have for z in STATE_SIZES
           if not (ASSET_DIR / s / f"{z}.png").is_file()]
check("全套帧在位（%d 状态 × %d 档）" % (len(have), len(STATE_SIZES)), not missing, missing[:4])

# ③ 运行时加载 + 回退
dirs = tray_icons.init()
check("init 解析到资产目录", any(d == ASSET_DIR for d in dirs), [str(d) for d in dirs])
img = tray_icons.get("recording", 32)
check("按档加载 recording/32", img.size == (32, 32), img.size)
fb = tray_icons.get("__nonexistent__", 24)
check("缺图回退 default 永不崩", fb.size == (24, 24), fb.size)
check("set_state 去重", tray_icons.set_state("idle") in (True, False) and not tray_icons.set_state("idle"))

print("TRAY ICONS TEST " + ("FAILED: " + ",".join(FAILS) if FAILS else "OK"), flush=True)
sys.exit(1 if FAILS else 0)
