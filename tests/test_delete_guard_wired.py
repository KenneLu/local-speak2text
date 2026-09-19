# -*- coding: utf-8 -*-
"""C-2 接线：`hold_exe_delete_guard` 必须在**托盘/窗口创建之前**被调用一次。

为什么钉的是「顺序」而不只是「被调用过」
----------------------------------------
模板 `modules/paths/README.md` 采纳步骤第 4 条写的是一个**时序**要求：
    **`main()` 在托盘/窗口创建之前调用 `hold_exe_delete_guard(log=log)`**——
    "顺序不能再往后挪，晚一步就等于那一步的窗口期没有保护"。
⇒ 所以"调用过"这个断言**不足以**表达它：一个把调用放在 `Tray(ctrl)` 之后的实现，
  照样满足"被调用过"，却**正好是 README 明说不许的那种**。本测试因此记录**调用顺序**，
  断言 guard 早于 `Overlay()` 与 `Tray()`。

为什么需要这个测试
------------------
C-27 那条机械判据只能证明"这个符号在工具代码里**被引用**"——**引用不等于在正确的时刻调用**。
这条接线的价值全在时刻上，所以它需要一条**行为**判据，而不是文本判据。

隔离：不建真窗口、不碰注册表、不加载模型；数据根重定向到临时目录（F11/D12）。
"""
import os
import sys
from pathlib import Path

from _cleanup import rmtree_cleanup, scratch_dir  # noqa: E402

_TMP = scratch_dir("l-s2t-guardwire-")
os.environ["LOCAL_SPEAK2TEXT_DATA_DIR"] = _TMP
os.environ["LOCAL_SPEAK2TEXT_CONFIG"] = str(Path(_TMP) / "config.json")

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import main as M  # noqa: E402
from modules.paths import LOG_PATH  # noqa: E402

FAILS = []


def check(name, ok, detail=""):
    print(("  ok  " if ok else "  FAIL") + " " + name + ("  " + detail if detail else ""),
          flush=True)
    if not ok:
        FAILS.append(name)


# ---------- 调用顺序记录本：谁先谁后，一个列表说了算 ----------
ORDER = []


class _FakeRoot:
    def after(self, *_a, **_k):
        pass

    def mainloop(self):
        pass


class _FakeOverlay:
    def __init__(self):
        ORDER.append("overlay")
        self.root = _FakeRoot()


class _FakeTray:
    update_ready = None

    def __init__(self, ctrl):
        ORDER.append("tray")
        self.ctrl = ctrl

    def start(self):
        pass

    def stop(self):
        pass

    def set_title(self, *_a):
        pass

    def notify(self, *_a):
        pass

    def rebuild(self):
        pass

    def set_recording(self, *_a):
        pass


class _FakeEngine:
    model_type = "stub"


class _FakeHook:
    def __init__(self, **_kwargs):
        pass

    def start(self):
        return True

    def stop(self):
        pass


def _record_guard(**_kwargs):
    ORDER.append("guard")
    return True


M.Overlay = _FakeOverlay
M.Tray = _FakeTray
M.AsrEngine = _FakeEngine
M.KeyboardHook = _FakeHook
M.hold_exe_delete_guard = _record_guard          # 替身：只记顺序，不真取句柄
M.process_pending_update = lambda **_kw: None
M.migrate_autostart = lambda **_kw: None

# 守卫与重复启动提示打桩（理由同 test_startup_path.py）：生产互斥体是内核对象，
# <APP>_DATA_DIR 隔离不了它；不打桩时用户托盘实例在跑会让 main() 弹**模态** MessageBox。
M.tray_kit.acquire_single_instance = lambda *_a, **_k: True
M.tray_kit.warn_duplicate_instance = lambda *_a, **_k: None

rc = M.main()

check("main() ran the normal path (no short-circuit)", rc is None, "rc=%r" % (rc,))
check("hold_exe_delete_guard was called exactly once", ORDER.count("guard") == 1,
      "order=%s" % (ORDER,))
check("the window/tray really got created after it (so the order below is meaningful)",
      "overlay" in ORDER and "tray" in ORDER, "order=%s" % (ORDER,))

if "guard" in ORDER and "overlay" in ORDER:
    check("guard is called BEFORE the Tk window (overlay) is created",
          ORDER.index("guard") < ORDER.index("overlay"),
          "order=%s" % (ORDER,))
else:
    check("guard is called BEFORE the Tk window (overlay) is created", False,
          "order=%s" % (ORDER,))

if "guard" in ORDER and "tray" in ORDER:
    check("guard is called BEFORE the tray icon is created",
          ORDER.index("guard") < ORDER.index("tray"),
          "order=%s" % (ORDER,))
else:
    check("guard is called BEFORE the tray icon is created", False,
          "order=%s" % (ORDER,))

check("log stayed inside isolated data dir", _TMP in str(LOG_PATH), str(LOG_PATH))
check("temp dir cleaned up (no %TEMP% leak)", rmtree_cleanup(_TMP), str(_TMP))
print("DELETE GUARD WIRING TEST " + ("FAILED: " + ",".join(FAILS) if FAILS else "OK"),
      flush=True)
sys.exit(1 if FAILS else 0)
