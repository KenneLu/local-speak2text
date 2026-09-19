# -*- coding: utf-8 -*-
"""退出确认弹窗：点「退出」应弹确认窗；点取消不退出；点确认才发 exit。"""
import os
import sys
from pathlib import Path

from _cleanup import rmtree_cleanup, scratch_dir  # noqa: E402

# F11/D12 实例隔离：必须在 import main 之前重定向数据根与配置，否则导入期的
# seed_config() 与退出确认的 load/save_config_dict 会读写用户真实的配置。
_TMP = scratch_dir("l-s2t-quit-")
os.environ["LOCAL_SPEAK2TEXT_DATA_DIR"] = _TMP
os.environ["LOCAL_SPEAK2TEXT_CONFIG"] = str(Path(_TMP) / "config.json")

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from modules import i18n  # noqa: E402
import main as M  # noqa: E402

i18n.init("zh")
overlay = M.Overlay()
ctrl = M.Controller(overlay, None)
overlay.root.after(40, ctrl.poll)

state = {"exited": False, "phase": 1}
orig_quit = overlay.root.quit


def guarded_quit():
    # exit 事件里会调 root.quit；拦截它以观察行为
    state["exited"] = True


overlay.root.quit = guarded_quit

# 第一步：托盘点退出 -> 应弹确认窗，且尚未退出（_quit 在 Tray 上，走队列封送）
class FakeTray:
    controller = ctrl


M.Tray._quit(FakeTray, None, None)


def phase2():
    tops = [w for w in overlay.root.winfo_children()
            if isinstance(w, __import__("tkinter").Toplevel)]
    assert tops, "confirm dialog missing"
    assert not state["exited"], "should NOT exit before confirmation"
    print("phase1: dialog shown, not exited", flush=True)
    # 第二步：按 Esc -> 弹窗关闭，仍不退出。
    # 这是回归点：旧内联 _confirm_quit 没有 <Escape> 绑定，GUI 实测按 Esc 关不掉；
    # 模板 tray_kit.confirm_quit_dialog 有该绑定。
    tops[0].event_generate("<Escape>")
    overlay.root.after(100, phase3)


def phase3():
    tops = [w for w in overlay.root.winfo_children()
            if isinstance(w, __import__("tkinter").Toplevel)]
    assert not tops, "dialog should be closed after cancel"
    assert not state["exited"], "cancel must not exit"
    print("phase2: cancel keeps app running", flush=True)
    # 第三步：再次点退出 -> 点「退出」确认 -> exit 事件入队 -> poll 处理 -> exited
    M.Tray._quit(FakeTray, None, None)
    overlay.root.after(100, phase4)


def phase4():
    tops = [w for w in overlay.root.winfo_children()
            if isinstance(w, __import__("tkinter").Toplevel)]
    assert tops, "confirm dialog missing on second quit"
    buttons = [b for t in tops for b in t.winfo_children()
               if isinstance(b, __import__("tkinter").Frame)
               for b in b.winfo_children() if isinstance(b, __import__("tkinter").Button)]
    yes_btn = buttons[0]
    yes_btn.invoke()
    overlay.root.after(200, phase5)


def phase5():
    assert state["exited"], "confirmed quit should exit"
    print("phase3: confirmed quit exits", flush=True)
    print("QUIT CONFIRM TEST OK", flush=True)
    overlay.root.after(10, overlay.root.destroy)


overlay.root.after(300, phase2)
overlay.root.mainloop()

assert rmtree_cleanup(_TMP), "temp dir not cleaned (leak): %s" % _TMP
