# -*- coding: utf-8 -*-
"""退出路径必须 fail-open：弹窗链路**不可用时仍要退出**（#44-A，与 reme 同形）。

为什么单独钉住：`Controller._confirm_quit` 的降级链是
    富对话框 → 原生 askyesno → 放行
最后那一跳是"把控制权还给用户"的保险。它一旦写反（抛异常 ⇒ 不退出），在
**没有 Tk 运行时的机器**上用户就**退不掉**——而"能退出"是用户最后的控制权。

判据四档，缺任何一档都会让"无条件退出"的实现也通过：
  A 富框抛 + 原生框抛 → **仍退出**（fail-open，本文件主断言），且**只放行一次**
  B 富框返回"取消"     → **不退出**（正对照：证明 A 不是"无条件退出"）
  C 富框返回"确认"     → 退出（正常路径），同样**只放行一次**
  D 富框抛 + 原生框答"否" → **不退出**（证明 A 不是"只要富框抛就退出"）

"只放行一次"不是凑数：退出收尾要落盘并拉起替换脚本，放行两次就等于跑两遍；
而这条链有三个出口（富框 / 原生框 / 末级放行），出口之间若不互斥就会 >1。

**"放行"不等于"执行破坏性动作"**（2026-09-19 lead 裁定，本文件新增两条）：
退出时是否**应用已下载的更新**（= 替换安装目录）由 `quit_apply_update` 决定，而它在
`main()` 的 finally 里被读（`src/main.py:1063`）。因此：
  A' 链路不可用 → `quit_apply_update` 必须为 **False**（用户这次**没被问过**，
     不得沿用他上次在有确认框语境下保存的勾选去触发破坏性动作；dsh/ocx 末级硬编码
     False 即标准形）。隔离配置里故意写 `true`，所以这条在旧实现下必红。
  C' 用户确认   → 仍然**沿用**保存的勾选（正对照：防止上方那条被修成"一律不装更新"）。
两条合起来才说明这个修正是**有指向的**，不是把用户偏好整个作废。

三态在 l-s2t 各由哪一行体现（钉靶，2026-09-19 核）：
  富框抛              → src/main.py:932 `except Exception as exc:`（转原生框）
  富框抛 + 原生框也抛  → src/main.py:939-942（`choice = None`）→ :943 放行
  用户明确取消        → 富框返回 `{"go": False}` → :945 `elif not choice.get("go"):` → :947 return

不启真 Tk：以鸭子类型 self 直接调 `Controller._confirm_quit`（它只用到
`overlay.root` / `ui_q` / `quit_apply_update` 三样）。
"""
import json
import os
import queue
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _cleanup import rmtree_cleanup, scratch_dir  # noqa: E402  （R2 位置 + 删前放句柄）

# F11/D12 实例隔离：必须在 import paths/main 之前重定向数据根与配置，
# 否则 _confirm_quit 里的 load_config_dict/save_config_dict 会读写用户真实配置。
_TMP = scratch_dir("l-s2t-quitfo-")
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


# ---------- 替身：只要三样，不启 Tk、不起托盘 ----------
class _FakeOverlay:
    class root:  # noqa: N801
        pass


class _Self:
    def __init__(self):
        self.overlay = _FakeOverlay()
        self.ui_q = queue.Queue()
        # 初值**故意取 True**：它就是"上次保存的勾选 = 退出时应用已下载的更新"。
        # 这样"链路不可用时必须变 False"才有判别力，而不是碰巧等于初值。
        self.quit_apply_update = True


def _boom(*_a, **_k):
    raise RuntimeError("simulated: dialog link unavailable")


# 隔离配置里也写 True：旧实现是从这里读的，不写就成了"读不到→默认"，测不出那条路径。
_cfg_path = Path(os.environ["LOCAL_SPEAK2TEXT_CONFIG"])
_cfg_path.write_text(json.dumps({"quit_apply_update": True}), encoding="utf-8")

_real_dialog = M.tray_kit.confirm_quit_dialog
_real_askyesno = M.messagebox.askyesno
_confirm = M.Controller._confirm_quit

try:
    # ---------- A：两条链路都抛 → 仍须退出（fail-open），且**只放行一次** ----------
    M.tray_kit.confirm_quit_dialog = _boom
    M.messagebox.askyesno = _boom
    a = _Self()
    _confirm(a)
    drained = []
    while not a.ui_q.empty():
        drained.append(a.ui_q.get_nowait())
    check("A both dialog links raise -> still exits (fail-open)",
          ("exit",) in drained, "queued=%r" % (drained,))
    # "只放行一次"：放行两次 = 退出收尾（落盘 / 拉起替换脚本）跑两遍。
    # 降级链有三个出口（富框 / 原生框 / 末级放行），若它们不互斥，这里就会 >1。
    check("A exactly ONE exit event is queued (no double release)",
          drained.count(("exit",)) == 1, "queued=%r" % (drained,))
    # 证据行也要落盘：断言"确实走了降级"，而不是"碰巧没卡住"
    text = LOG_PATH.read_text(encoding="utf-8", errors="replace") if LOG_PATH.exists() else ""
    check("A fallback was logged (not silent)",
          "native confirm failed" in text, "log=%s" % LOG_PATH)
    # **链路不可用 ⇒ 不得执行破坏性动作**：用户这次根本没被问过，不能沿用他上次
    # 在有确认框的语境下保存的勾选去把更新装上（那是"辅助机制坏掉 ⇒ 触发破坏性动作"，
    # 本轮整轮在打的形态；dsh/ocx 的末级硬编码 False 就是标准形）。隔离配置里写的是
    # True，所以这条断言在旧实现下必红。
    check("A link unavailable -> does NOT apply the pending update",
          a.quit_apply_update is False, "quit_apply_update=%r" % (a.quit_apply_update,))
    # 为什么"不装"必须可**读出来**，而不是只看那个布尔：false 也可能是"碰巧"。
    # 断言日志里的理由行，等于把这次裁决的**依据**也钉住——这正是 lead 要的那"一行日志"。
    _t = LOG_PATH.read_text(encoding="utf-8", errors="replace") if LOG_PATH.exists() else ""
    check("A the reason is logged (unavailable, NOT asking)",
          "WITHOUT applying the pending update" in _t, "log=%s" % LOG_PATH)
    # 再强一层：规则说的是"**不读**已存勾选"，不是"读出来恰好是 False"。
    # ⚠️ 但"完全不读配置"是**比设计更强**的断言：`_confirm_quit` 开头就 `load_config_dict()`
    # 一次，那是给对话框**播种勾选初值**用的（`checked`），合法且必要。所以正确的性质是
    # **"不可用分支的裁决不依赖它"** —— 可观测形式是**读的次数**：播种 1 次；若末级又去读，
    # 就会是 2 次。（我第一版直接写"毒掉读配置"，测试当场红了——红得对，是我把断言写强了。）
    _real_load = M.load_config_dict
    _calls = []

    def _counting():
        _calls.append(1)
        return _real_load()

    M.load_config_dict = _counting
    try:
        a2 = _Self()
        _confirm(a2)
    finally:
        M.load_config_dict = _real_load
    check("A unavailable branch reads the config ONCE (dialog seeding only), not again",
          len(_calls) == 1, "load_config_dict calls=%d" % len(_calls))
    check("A ...and that single read does not decide the outcome",
          a2.quit_apply_update is False, "quit_apply_update=%r" % (a2.quit_apply_update,))

    # ---------- B：正对照——富框明确"取消" → 不许退出 ----------
    M.tray_kit.confirm_quit_dialog = lambda *_a, **_k: {"go": False}
    M.messagebox.askyesno = _boom
    b = _Self()
    _confirm(b)
    check("B user cancelled -> does NOT exit (positive control)",
          b.ui_q.empty(), "queued=%r" % (b.ui_q.qsize(),))

    # ---------- C：正常路径——富框"确认" → 退出（同样只一次） ----------
    M.tray_kit.confirm_quit_dialog = lambda *_a, **_k: {"go": True}
    M.messagebox.askyesno = _boom
    c = _Self()
    _confirm(c)
    c_drained = []
    while not c.ui_q.empty():
        c_drained.append(c.ui_q.get_nowait())
    check("C confirmed -> exits", ("exit",) in c_drained, "queued=%r" % (c_drained,))
    check("C exactly ONE exit event (confirmed path does not fall through)",
          c_drained.count(("exit",)) == 1, "queued=%r" % (c_drained,))
    # 正对照：**用户被问过**时仍然沿用他保存的勾选。防止把上面那条修成"一律不装更新"
    # （那样就等于把用户的偏好整个作废，是从一个极端滑到另一个极端）。
    check("C confirmed -> still honours the persisted checkbox (fix is scoped)",
          c.quit_apply_update is True, "quit_apply_update=%r" % (c.quit_apply_update,))

    # ---------- D：富框抛、原生框答"否" → 也不许退出 ----------
    # 补这一档：否则"只要富框抛就退出"也能同时通过 A 与 C。
    M.tray_kit.confirm_quit_dialog = _boom
    M.messagebox.askyesno = lambda *_a, **_k: False
    d = _Self()
    _confirm(d)
    check("D rich raises but native says no -> does NOT exit",
          d.ui_q.empty(), "qsize=%d" % d.ui_q.qsize())
finally:
    M.tray_kit.confirm_quit_dialog = _real_dialog
    M.messagebox.askyesno = _real_askyesno

check("temp dir cleaned up (no %TEMP% leak)", rmtree_cleanup(_TMP), str(_TMP))
print("QUIT FAIL-OPEN TEST " + ("FAILED: " + ",".join(FAILS) if FAILS else "OK"), flush=True)
sys.exit(1 if FAILS else 0)
