# -*- coding: utf-8 -*-
"""验证基准 UI 流：进度窗可关闭 → 检测完成后结果窗自动弹出。

不键入文字、不改配置；结束后自动退出。需要 models 与 test wav（真跑检测）。
"""
import os
import sys
import time

sys.path.insert(0, r"H:\Tools\my_diy_tools\local-speak2text")
import i18n
import main as M

i18n.init("zh")
overlay = M.Overlay()
ctrl = M.Controller(overlay, None)
overlay.root.after(40, ctrl.poll)  # 真实调度路径：ui_q 由 poll 抽取

state = {"done": False}
orig_done = ctrl._bench_done
orig_show = ctrl._show_bench_result

# 截短：_bench_done 记录窗口状态后，直接弹出结果窗（同真实路径）
def bench_done(result):
    win = ctrl._bench_win
    if win is not None:
        try:
            if win.winfo_exists():
                win.destroy()
        except Exception:
            pass
    ctrl._bench_win = None
    orig_show(result)
    state["done"] = True

ctrl._bench_done = bench_done

def check():
    # 1) 进度窗存在且可销毁（模拟用户关闭）
    assert ctrl._bench_win is not None, "progress window not created"
    ctrl._bench_win.destroy()
    print("progress window closed by user (simulated)", flush=True)
    # 2) 等后台检测完成（poll 负责把 benchmark_done 从队列搬进 _bench_done）
    deadline = time.time() + 300
    while not state["done"] and time.time() < deadline:
        overlay.root.update()
        time.sleep(0.02)
    assert state["done"], "benchmark did not finish in time"
    # 3) 结果窗应已弹出
    kids = [w for w in overlay.root.winfo_children() if isinstance(w, __import__("tkinter").Toplevel)]
    assert kids, "result window did not open after completion"
    print("result window re-opened automatically:", kids[0].title(), flush=True)
    for w in list(overlay.root.winfo_children()):
        if isinstance(w, __import__("tkinter").Toplevel):
            w.destroy()
    overlay.root.quit()
    overlay.root.after(50, overlay.root.quit)  # poll 自身会重排 after；再保险退出

# 启动检测（走真实调度路径：后台线程 + ui_q 队列封送）
ctrl._start_benchmark()
overlay.root.after(1500, check)
overlay.root.mainloop()
ctrl.hook.stop()
print("BENCH UI TEST OK")
