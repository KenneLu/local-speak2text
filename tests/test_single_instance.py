# -*- coding: utf-8 -*-
"""单实例守卫（CONFORMANCE SINGLE-01 / SINGLE-02 / SINGLE-07）。

回归背景：1.2.0~1.4.0 的互斥体名写成 r"Local\\<app>\\SingleInstance"，含第二个
反斜杠 → CreateMutexW 恒失败（err=3），而守卫把"创建失败"当成"已有实例"→
双击 exe 永远弹"已在运行"，工具完全打不开。--smoke 又绕过了守卫，所以
冒烟 / 门禁 / review 三层全绿也没拦住。本文件就是补上的那条断言（D3.2）。

守卫实现已收敛到模板 modules/tray_kit（T7）；断言语义一条不丢：
  ① 互斥体名合法（命名空间前缀之后无第二个反斜杠）且内核真的接受；
  ② 旧非法名必须仍然失败（把根因钉死，防止有人改回去）；
  ③ 守卫正常时：首拍放行、第二拍拦下，且 tray_kit 派生的名字 == main.MUTEX_NAME
     （--smoke 的合法性探针必须与运行期守卫问同一个名字）；
  ④ 守卫自身出错时必须**放行**（失败方向为打开，否则工具会变砖）。
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
os.environ["LOCALSPEAK2TEXT_DATA_DIR"] = _TMP

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import main as M  # noqa: E402
from modules import tray_kit  # noqa: E402

FAILS = []


def check(name, ok, detail=""):
    print(("  ok  " if ok else "  FAIL") + " " + name + ("  " + detail if detail else ""),
          flush=True)
    if not ok:
        FAILS.append(name)


def _quiet(_msg):
    pass


# ① 名字合法（与 tray_kit.acquire_single_instance 的派生约定一致）
check("mutex name has no second backslash",
      M.MUTEX_NAME.count("\\") == 1, M.MUTEX_NAME)
check("mutex name is Local-scoped", M.MUTEX_NAME.startswith("Local\\"))
check("mutex name carries APP_ID", M.APP_ID in M.MUTEX_NAME)

# ② 内核真的接受当前名字；旧非法名仍然失败（根因钉死）
k32 = ctypes.WinDLL("kernel32", use_last_error=True)
k32.CreateMutexW.restype = ctypes.c_void_p
ctypes.set_last_error(0)
h = k32.CreateMutexW(None, False, M.MUTEX_NAME)
check("CreateMutexW accepts current name", bool(h),
      "err=%s" % ctypes.get_last_error())
if h:
    k32.CloseHandle(h)
ctypes.set_last_error(0)
bad = k32.CreateMutexW(None, False, r"Local\%s\SingleInstance" % M.APP_ID)
bad_err = ctypes.get_last_error()
check("old illegal name still fails (root cause pinned)", not bad and bad_err == 3,
      "err=%s" % bad_err)
if bad:
    k32.CloseHandle(bad)

# ③ 守卫正常：首拍放行；tray_kit 用的名字就是 MUTEX_NAME（反向占用探测）；
#    第二拍（同进程重入 = 已有实例）拦下
check("first acquire passes",
      tray_kit.acquire_single_instance(M.APP_ID, log=_quiet) is True)
ctypes.set_last_error(0)
probe = k32.CreateMutexW(None, False, M.MUTEX_NAME)
probe_err = ctypes.get_last_error()
if probe:
    k32.CloseHandle(probe)
check("tray_kit guard holds the pinned name (no naming drift)", probe_err == 183,
      "err=%s" % probe_err)
check("second acquire is refused",
      tray_kit.acquire_single_instance(M.APP_ID, log=_quiet) is False)

# ④ 失败方向：守卫自身出错必须放行
_real_win_dll = ctypes.WinDLL


def _boom(*_args, **_kwargs):
    raise OSError("simulated: kernel32 unavailable")


ctypes.WinDLL = _boom
try:
    check("guard failure fails OPEN",
          tray_kit.acquire_single_instance(M.APP_ID, log=_quiet) is True)
finally:
    ctypes.WinDLL = _real_win_dll

shutil.rmtree(_TMP, ignore_errors=True)
print("SINGLE INSTANCE TEST "
      + ("FAILED: " + ",".join(FAILS) if FAILS else "OK"), flush=True)
sys.exit(1 if FAILS else 0)
