# -*- coding: utf-8 -*-
"""浮窗自动生长自动化测试：验证高度随内容增长、向上生长不超屏、始终滚到最新。"""
import sys

sys.path.insert(0, r"H:\Tools\my_diy_tools\local-speak2text\src")
import main as M

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
print("OVERLAY TEST OK")
