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
"""
import os
import shutil
import sys
import tempfile
from pathlib import Path

# 实例隔离：必须在 import paths/main 之前重定向数据根与配置
_TMP = tempfile.mkdtemp(prefix="l-s2t-startup-")
os.environ["LOCALSPEAK2TEXT_DATA_DIR"] = _TMP
os.environ["LOCALSPEAK2TEXT_CONFIG"] = str(Path(_TMP) / "config.json")
os.environ.pop("LST_ALLOW_MULTI", None)

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
M.process_pending_update = lambda: CALLS.__setitem__("pending", CALLS["pending"] + 1)
M.migrate_autostart = lambda **_kw: CALLS.__setitem__("autostart", CALLS["autostart"] + 1)

rc = M.main()

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

shutil.rmtree(_TMP, ignore_errors=True)
print("STARTUP PATH TEST " + ("FAILED: " + ",".join(FAILS) if FAILS else "OK"), flush=True)
sys.exit(1 if FAILS else 0)
