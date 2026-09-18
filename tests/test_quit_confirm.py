# -*- coding: utf-8 -*-
"""退出确认弹窗：点「退出」应弹确认窗；点取消不退出；点确认才发 exit。"""
import sys

sys.path.insert(0, r"H:\Tools\my_diy_tools\local-speak2text\src")
from modules import i18n
import main as M

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
    # 第二步：点「取消」-> 弹窗关闭，仍不退出
    buttons = [b for t in tops for b in t.winfo_children()
               if isinstance(b, __import__("tkinter").Frame)
               for b in b.winfo_children() if isinstance(b, __import__("tkinter").Button)]
    cancel_btn = buttons[1]
    cancel_btn.invoke()
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
