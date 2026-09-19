# -*- coding: utf-8 -*-
"""浮窗自动生长自动化测试：验证高度随内容增长、向上生长不超屏、始终滚到最新。"""
import os
import sys
from pathlib import Path

from _cleanup import rmtree_cleanup, scratch_dir  # noqa: E402

# F11/D12 实例隔离：必须在 import main 之前重定向数据根与配置，否则导入期的
# seed_config() 会写用户真实的 %LOCALAPPDATA%\local-speak2text\。
_TMP = scratch_dir("l-s2t-grow-")
os.environ["LOCAL_SPEAK2TEXT_DATA_DIR"] = _TMP
os.environ["LOCAL_SPEAK2TEXT_CONFIG"] = str(Path(_TMP) / "config.json")

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import main as M  # noqa: E402

ov = M.Overlay()
ov.show("hold")
ov.root.update()
sh = ov.root.winfo_screenheight()
checks = []
text = ""
for i in range(1, 9):
    text += f"第{i}句，这是自动生长测试的文本内容，说着说着就变长了。"
    ov.set_text(text, "")
    ov.root.update()
    h = ov.root.winfo_height()
    y = ov.root.winfo_rooty()
    lines = ov.text.cget("height")
    checks.append((int(lines), h, y, y + h))
    max_h = 12 * ov._line_h + M.WINDOW_HEIGHT - 3 * ov._line_h
    assert h <= max_h + 4, f"超过最大高度: {h} > {max_h}"
    assert y >= 0 and (y + h) <= sh - 4, f"超出屏幕: y={y} h={h} sh={sh}"
    assert ov.text.yview()[1] > 0.99, "没有滚动到最新内容"

for c in checks:
    print("lines=%d h=%d y=%d bottom=%d" % c)
mid = checks[len(checks) // 2][3]
anchored = all(abs(c[3] - mid) <= 3 for c in checks[3:])
print("bottom anchored:", anchored, "screen_h:", sh)
ov.hide()
ov.quit()
assert rmtree_cleanup(_TMP), "temp dir not cleaned (leak): %s" % _TMP
print("OVERLAY TEST OK")
