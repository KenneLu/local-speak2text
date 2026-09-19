# -*- coding: utf-8 -*-
"""正常启动路径存活（CONFORMANCE SINGLE-04 / D3-01 / R-02）。

为什么需要这个测试：`--smoke` 在 `main()` 之前分派，**不经过单实例守卫**。
1.2.0~1.4.0 的守卫因互斥体名非法而恒返回 False，构建冒烟却全绿——
工具完全打不开而无人发现。本测试用替身换掉重资源（Tk 浮窗 / 托盘 / ASR 模型 /
键盘钩子 / 自启注册表 / 遗留更新），跑**真正的 `main()`**，断言：

  ① `main()` 不因守卫提前返回（= 故障形态不再重现）；
  ② 启动序列真的走到了 `log_kit.log("startup ...")`；
  ③ `process_pending_update` 与 `migrate_autostart` 都被调用（骨架没被跳过）；
  ④ 日志落在隔离数据区（实例隔离 F11/D12），不碰用户真实 AppData。

⚠️ 守卫与重复启动提示**在下方被打桩**：本测试测的是"守卫放行之后的启动序列"，
守卫自身行为由 test_single_instance.py 覆盖。生产互斥体是内核对象、不受数据根
重定向影响（SINGLE-08），不打桩的话——用户托盘实例在跑时真守卫返回 False，
main() 调 warn_duplicate_instance() 弹**模态** MessageBox，测试会永久挂住。
"""
import os
import sys
import tempfile
from pathlib import Path
from _cleanup import rmtree_cleanup, scratch_dir  # noqa: E402  （同目录助手：R2 位置 + 删前放句柄）

# 实例隔离：必须在 import paths/main 之前重定向数据根与配置
_TMP = scratch_dir("l-s2t-startup-")
os.environ["LOCAL_SPEAK2TEXT_DATA_DIR"] = _TMP
os.environ["LOCAL_SPEAK2TEXT_CONFIG"] = str(Path(_TMP) / "config.json")
# 注：模板 tray_kit 的单实例守卫没有"多开豁免"开关（旧内联版那个开关已随守卫
# 一起淘汰，历史记录见 CHANGELOG 1.2.0），这里不再 pop 任何开关——
# 守卫在测试进程里按正常语义放行/拦下。

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import main as M  # noqa: E402
from modules.paths import LOG_PATH  # noqa: E402

FAILS = []


def check(name, ok, detail=""):
    print(("  ok  " if ok else "  FAIL") + " " + name + ("  " + detail if detail else ""),
          flush=True)
    if not ok:
        FAILS.append(name)


# ---------- 替身：一切会碰 UI / 硬件 / 大模型 / 注册表的东西 ----------
class _FakeRoot:
    def after(self, *_a, **_k):
        pass

    def mainloop(self):
        pass


class _FakeOverlay:
    def __init__(self):
        self.root = _FakeRoot()


class _FakeTray:
    update_ready = None

    def __init__(self, ctrl):
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


CALLS = {"pending": 0, "autostart": 0}
M.Overlay = _FakeOverlay
M.Tray = _FakeTray
M.AsrEngine = _FakeEngine
M.KeyboardHook = _FakeHook
M.process_pending_update = lambda **_kw: CALLS.__setitem__("pending", CALLS["pending"] + 1)
M.migrate_autostart = lambda **_kw: CALLS.__setitem__("autostart", CALLS["autostart"] + 1)

# 本测试只验证"守卫放行后启动序列完整走通"，不验证守卫本身（那是
# test_single_instance.py 的职责）。因此这里把守卫打桩为"放行"，并把重复启动
# 提示打成 no-op：
#   * 生产互斥体是**内核对象**，<APP>_DATA_DIR 隔离不了它（SINGLE-08）——
#     用户的托盘实例在跑时，真守卫会返回 False，main() 随即调
#     warn_duplicate_instance() → MessageBoxW 是**模态阻塞**对话框，测试会
#     永久挂住（比失败更糟：CI 挂死而不是变红）。
#   * 打桩后本测试**不依赖生产互斥体是否空闲**，实例在跑也能快速通过。
M.tray_kit.acquire_single_instance = lambda *_a, **_k: True
M.tray_kit.warn_duplicate_instance = lambda *_a, **_k: None

# ---------- 真实退出流程：待应用的更新必须在 finally 里被真正拉起 ----------
# 用真实 launch_pending_cmd（不打断言）：脚本写一个 marker，证明退出收尾确实执行了替换脚本，
# 且是无控制台/脱离父进程地拉起（旗标断言见 tests/test_update_safety.py D1）。
_launch_marker = Path(_TMP) / "launched.txt"
_launch_bat = Path(_TMP) / "fake_apply.bat"
_launch_bat.write_text('@echo off\r\necho ok > "%~dp0launched.txt"\r\n',
                       encoding="ascii", newline="")
_RealController = M.Controller


class _ControllerWithPending(_RealController):
    def __init__(self, overlay, engine):
        super().__init__(overlay, engine)
        self.update_cmd_path = str(_launch_bat)   # 模拟"已下载、退出时应用"
        self.quit_apply_update = True


M.Controller = _ControllerWithPending

rc = M.main()

import time  # noqa: E402
_deadline = time.time() + 15.0
while time.time() < _deadline and not _launch_marker.exists():
    time.sleep(0.2)
check("exit path really launched the pending update script", _launch_marker.exists(),
      str(_launch_marker))

text = LOG_PATH.read_text(encoding="utf-8", errors="replace") if LOG_PATH.exists() else ""
startup = [line for line in text.splitlines() if "startup" in line]

# main() 只有"检测到重复实例"那条路会 return 0；正常走完 mainloop 返回 None。
# 因此 rc is None 恰好等价于"守卫放行了"——正是本测试要钉的信号。
check("main() did not short-circuit (guard passed)", rc is None, "rc=%r" % (rc,))
check("guard passed -> startup logged", bool(startup),
      startup[-1] if startup else "no startup line in %s" % LOG_PATH)
check("update pending handled", CALLS["pending"] == 1, "calls=%s" % CALLS["pending"])
check("autostart self-heal called", CALLS["autostart"] == 1, "calls=%s" % CALLS["autostart"])
check("log stayed inside isolated data dir", _TMP in str(LOG_PATH), str(LOG_PATH))

# ---------- C-29：交给模板件的 log 必须是 print 形态 ----------
# main.log 被 `log=log` 交给 tray_kit / autostart / update_helper，这些模板件按 print
# 形态调用（`log("update staged:", staged, "->", target)`）。单参包装在这里会直接
# TypeError——而且是在**模板件的帧里**抛出，日志里的证据往往被工具侧的 try 吞掉。
# 两参调用 + 断言文案真的落进日志，钉住"能收可变参数"且"确实转发了"。
try:
    M.log("c29-probe", 42)
    _c29_err = ""
except TypeError as exc:
    _c29_err = repr(exc)
check("log accepts print-style varargs (C-29)", not _c29_err, _c29_err)
_text2 = LOG_PATH.read_text(encoding="utf-8", errors="replace") if LOG_PATH.exists() else ""
check("varargs log actually forwarded (space-joined)", "c29-probe 42" in _text2,
      "log=%s" % LOG_PATH)

check("temp dir cleaned up (no %TEMP% leak)", rmtree_cleanup(_TMP), str(_TMP))
print("STARTUP PATH TEST " + ("FAILED: " + ",".join(FAILS) if FAILS else "OK"), flush=True)
sys.exit(1 if FAILS else 0)
