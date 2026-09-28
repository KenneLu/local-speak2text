# -*- coding: utf-8 -*-
"""自启自愈（G4.1-03/05）+ frozen 守卫（autostart 1.2.1）双用例。

**只读纪律（CONFORMANCE D3-03 / B4-04 / C-17）**：这个用例必须动 HKCU\\...\\Run
才能验证自愈，所以它是唯一被允许写注册表的测试——但必须**备份原值并在结束时还原**。
旧版没有还原，跑一次测试就把用户真实的自启项改成了 `pythonw ... src\\main.py`，
等于测试静默改坏了用户的开机自启。任何新增的注册表操作用例都必须照此模式写。

**1.2.1 语义适配（2026-09-28 W5 后段）**：migrate_autostart 在非 frozen 运行下
**只读只记**（dev/测试态的 get_autostart_cmd 是 pythonw+argv[0]，谁跑谁抢写 Run 键
——reme 事故实测）。旧测试在 dev 态期望"重写"，1.2.1 起该期望反转为"不动"；
重写语义改由 frozen 替身用例验证（monkeypatch A.sys，参考 reme test_autostart 手法）。
"""
import os
import sys
import types
import winreg
from pathlib import Path

from _cleanup import rmtree_cleanup, scratch_dir  # noqa: E402

# F11/D12 实例隔离：必须在 import autostart 之前重定向数据根与配置，否则导入期的
# seed_config() 会写用户真实的 %LOCALAPPDATA%\local-speak2text\。
_TMP = scratch_dir("l-s2t-migrate-")
os.environ["LOCAL_SPEAK2TEXT_DATA_DIR"] = _TMP
os.environ["LOCAL_SPEAK2TEXT_CONFIG"] = str(Path(_TMP) / "config.json")

_SRC = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(_SRC))
from template import autostart as A  # noqa: E402
from template.appconfig import APP_NAME  # noqa: E402

# 模板 autostart 的源码态命令行取自 sys.argv[0]（被启动的脚本）。把它指向真实入口
# main.py，frozen 替身用例才能验证「重写成 pythonw + 入口脚本」这一形态。
sys.argv[0] = str(_SRC / "main.py")

RUN = r"Software\Microsoft\Windows\CurrentVersion\Run"
VALUE_NAME = APP_NAME
fake = '"\\\\nonexistent\\old-pkg\\local-speak2text-1.0.exe"'


def read_run_value():
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN, 0, winreg.KEY_READ) as k:
            v, _ = winreg.QueryValueEx(k, VALUE_NAME)
            return True, v
    except FileNotFoundError:
        return False, None


def write_run_value(value):
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, RUN) as k:
        if value is None:
            try:
                winreg.DeleteValue(k, VALUE_NAME)
            except FileNotFoundError:
                pass
        else:
            winreg.SetValueEx(k, VALUE_NAME, 0, winreg.REG_SZ, value)


def frozen_substitute(enabled):
    """把**子模块**（autostart.autostart）的 sys 换成 frozen 可控替身。

    A 是包门面：函数体读的是子模块命名空间的 sys，替换包属性无效
    （包 __getattr__ 委派读的是真值）——必须写 A.autostart.sys。
    """
    real = A.autostart.sys
    A.autostart.sys = types.SimpleNamespace(executable=real.executable,
                                            argv=list(real.argv), frozen=enabled)
    return real


existed, original = read_run_value()
print("backup original autostart:", "present" if existed else "(none)", flush=True)
real_sys = None
try:
    # ---- 用例①：dev 态（本进程非 frozen）守卫——注册表不动 ----
    write_run_value(fake)
    A.migrate_autostart()
    _ok, after = read_run_value()
    print("dev-run after migrate:", after, flush=True)
    assert after == fake, "dev run must NOT touch registry, got %r" % (after,)

    # ---- 用例②：frozen 替身——死链重写为「当前命令行」 ----
    # frozen 态 get_autostart_cmd 走 stable 分支（INSTALL_EXE 或 sys.executable 绝对路径），
    # 不是 dev 态的 pythonw+argv[0]。期望值由同一函数在替身生效时算出（同源自证：
    # 验证「死链 → 重写为当前命令行」的行为，不锁具体路径形态）。
    real_sys = frozen_substitute(True)
    wanted = A.get_autostart_cmd()
    print("frozen wanted:", wanted, flush=True)
    write_run_value(fake)
    A.migrate_autostart()
    _ok, after = read_run_value()
    print("frozen after migrate:", after, flush=True)
    assert after == wanted, "frozen expect rewrite to current cmd, got %r want %r" % (after, wanted)
    print("MIGRATE SELF-HEAL OK (dev guard + frozen rewrite)", flush=True)
finally:
    if real_sys is not None:
        A.autostart.sys = real_sys
    # 还原：测试绝不能把用户真实的自启项留在被改写的状态
    write_run_value(original if existed else None)
    _back, now = read_run_value()
    assert now == original, "autostart not restored: %r != %r" % (now, original)
    print("autostart restored", flush=True)

assert rmtree_cleanup(_TMP), "temp dir not cleaned (leak): %s" % _TMP
