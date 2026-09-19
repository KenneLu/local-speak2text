# -*- coding: utf-8 -*-
"""单实例守卫（CONFORMANCE SINGLE-01 / SINGLE-02 / SINGLE-07 / SINGLE-08，R-09）。

回归背景：1.2.0~1.4.0 的互斥体名写成 r"Local\\<app>\\SingleInstance"，含第二个
反斜杠 → CreateMutexW 恒失败（err=3），而守卫把"创建失败"当成"已有实例"→
双击 exe 永远弹"已在运行"，工具完全打不开。--smoke 又绕过了守卫，所以
冒烟 / 门禁 / review 三层全绿也没拦住。本文件就是补上的那条断言（D3.2）。

守卫实现已收敛到模板 modules/tray_kit（T7）。断言语义一条不丢，且按 SINGLE-08
拆成"命名正确性（不占锁）"与"抢锁/拒绝（测试专属名）"两类，**用户实例在跑时
也全绿**（R-09）——因为 <APP>_DATA_DIR 只隔离磁盘，隔离不了内核对象：
  ① 命名正确性：纯字符串断言 MUTEX_NAME == 家族派生式，再用 CreateMutexW
     建+关（不持有）验内核接受——实例在跑时拿到 handle + err=183 同样算接受；
  ② 运行期真名：捕获式替身（记录 CreateMutexW 的 name 实参）证明 tray_kit
     真正传给内核的就是 MUTEX_NAME——不碰内核对象、不占生产锁，断言反而更直接；
  ③ 旧非法名必须仍然失败（把根因钉死，防止有人改回去）；
  ④ 抢锁/拒绝：用测试专属名（Local\\<app>-test-<pid>，显式传 mutex_name=），
     绝不占用生产名；
  ⑤ 守卫自身出错时必须**放行**（失败方向为打开，否则工具会变砖）。
"""
import ctypes
import os
import shutil
import sys
import tempfile
from pathlib import Path

# 实例隔离（F11/D12）：必须在 import paths/main **之前**重定向数据根，
# 否则守卫的日志会写进用户真实的 %LOCALAPPDATA%。
_TMP = tempfile.mkdtemp(prefix="l-s2t-test-")
os.environ["LOCAL_SPEAK2TEXT_DATA_DIR"] = _TMP

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import main as M  # noqa: E402
from modules import tray_kit  # noqa: E402

FAILS = []
EXPECTED_NAME = r"Local\%s-single-instance" % M.APP_ID
TEST_NAME = r"Local\%s-test-%d" % (M.APP_ID, os.getpid())


def check(name, ok, detail=""):
    print(("  ok  " if ok else "  FAIL") + " " + name + ("  " + detail if detail else ""),
          flush=True)
    if not ok:
        FAILS.append(name)


def _quiet(_msg):
    pass


# ---------- ① 命名正确性（纯字符串 + 建/关不持有，实例在跑也可过） ----------
check("mutex name matches the family derivation", M.MUTEX_NAME == EXPECTED_NAME,
      M.MUTEX_NAME)
check("mutex name has no second backslash", M.MUTEX_NAME.count("\\") == 1, M.MUTEX_NAME)
check("mutex name is Local-scoped", M.MUTEX_NAME.startswith("Local\\"))
check("mutex name carries APP_ID", M.APP_ID in M.MUTEX_NAME)

k32 = ctypes.WinDLL("kernel32", use_last_error=True)
k32.CreateMutexW.restype = ctypes.c_void_p
ctypes.set_last_error(0)
h = k32.CreateMutexW(None, False, M.MUTEX_NAME)
accept_err = ctypes.get_last_error()
check("CreateMutexW accepts current name (0 or already-exists)",
      bool(h) and accept_err in (0, 183), "err=%s" % accept_err)
if h:
    k32.CloseHandle(h)   # 只探测，不持有

ctypes.set_last_error(0)
bad = k32.CreateMutexW(None, False, r"Local\%s\SingleInstance" % M.APP_ID)
bad_err = ctypes.get_last_error()
check("old illegal name still fails (root cause pinned)", not bad and bad_err == 3,
      "err=%s" % bad_err)
if bad:
    k32.CloseHandle(bad)

# ---------- ② 运行期真名：捕获式替身，完全不碰内核对象 ----------
captured = []


class _Fn:
    def __init__(self, impl):
        self.impl = impl
        self.argtypes = None
        self.restype = None

    def __call__(self, *a, **k):
        return self.impl(*a, **k)


class _FakeK32:
    def __init__(self, err):
        self._err = err
        self.CreateMutexW = _Fn(self._create)
        self.CloseHandle = _Fn(lambda _h: None)

    def _create(self, _attrs, _initial, name):
        captured.append(name)
        ctypes.set_last_error(self._err)
        return 1   # 非空 handle


_real_win_dll = ctypes.WinDLL
ctypes.WinDLL = lambda *_a, **_k: _FakeK32(0)
try:
    captured_ok = tray_kit.acquire_single_instance(M.APP_ID, log=_quiet)
finally:
    ctypes.WinDLL = _real_win_dll
check("runtime actually passes the pinned mutex name",
      captured_ok is True and captured == [EXPECTED_NAME], repr(captured))

# ---------- ③ 抢锁 / 拒绝：测试专属名，绝不占生产名 ----------
check("first acquire passes",
      tray_kit.acquire_single_instance(M.APP_ID, mutex_name=TEST_NAME, log=_quiet) is True)
check("second acquire is refused",
      tray_kit.acquire_single_instance(M.APP_ID, mutex_name=TEST_NAME, log=_quiet) is False)

# ---------- ④ 失败方向：守卫自身出错必须放行 ----------


def _boom(*_args, **_kwargs):
    raise OSError("simulated: kernel32 unavailable")


ctypes.WinDLL = _boom
try:
    check("guard failure fails OPEN",
          tray_kit.acquire_single_instance(M.APP_ID, mutex_name=TEST_NAME, log=_quiet) is True)
finally:
    ctypes.WinDLL = _real_win_dll

shutil.rmtree(_TMP, ignore_errors=True)
print("SINGLE INSTANCE TEST "
      + ("FAILED: " + ",".join(FAILS) if FAILS else "OK"), flush=True)
sys.exit(1 if FAILS else 0)
