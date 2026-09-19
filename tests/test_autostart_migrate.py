# -*- coding: utf-8 -*-
"""自启自愈（G4.1-03/05）：注册表指向不存在的旧包 -> migrate_autostart 重写。

**只读纪律（CONFORMANCE D3-03 / B4-04 / C-17）**：这个用例必须动 HKCU\\...\\Run
才能验证自愈，所以它是唯一被允许写注册表的测试——但必须**备份原值并在结束时还原**。
旧版没有还原，跑一次测试就把用户真实的自启项改成了 `pythonw ... src\\main.py`，
等于测试静默改坏了用户的开机自启。任何新增的注册表操作用例都必须照此模式写。
"""
import os
import sys
import winreg
from pathlib import Path

_SRC = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(_SRC))
from modules import autostart as A  # noqa: E402
from modules.appconfig import APP_NAME  # noqa: E402

# 模板 autostart 的源码态命令行取自 sys.argv[0]（被启动的脚本）。测试进程的
# argv[0] 是本测试文件；把它指向真实入口 main.py，才能验证「重写成 pythonw +
# 入口脚本」这一形态（测试替身只换 argv，不改被测函数语义）。
sys.argv[0] = str(_SRC / "main.py")

RUN = r"Software\Microsoft\Windows\CurrentVersion\Run"
VALUE_NAME = APP_NAME
fake = '"\\\\nonexistent\\old-pkg\\local-speak2text-1.0.exe"'


def read_run_value():
    """返回 (是否存在, 值)。"""
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


existed, original = read_run_value()
print("backup original autostart:", "present" if existed else "(none)", flush=True)
try:
    write_run_value(fake)
    print("planted broken:", fake, flush=True)

    A.migrate_autostart()

    _ok, after = read_run_value()
    print("after migrate :", after, flush=True)
    assert after and "pythonw" in after and "main.py" in after, \
        "dev-mode expect pythonw + main.py, got %r" % (after,)
    print("MIGRATE SELF-HEAL OK", flush=True)
finally:
    # 还原：测试绝不能把用户真实的自启项留在被改写的状态
    write_run_value(original if existed else None)
    _back, now = read_run_value()
    assert now == original, "autostart not restored: %r != %r" % (now, original)
    print("autostart restored", flush=True)
