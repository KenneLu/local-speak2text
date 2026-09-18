# -*- coding: utf-8 -*-
"""验证自启自愈：注册表指向不存在的旧包 -> migrate_autostart 重写。"""
import os
import sys
import winreg

sys.path.insert(0, r"H:\Tools\my_diy_tools\local-speak2text")
os.chdir(r"H:\Tools\my_diy_tools\local-speak2text")
import main as M

RUN = r"Software\Microsoft\Windows\CurrentVersion\Run"
fake = '"\\\\nonexistent\\old-pkg\\local-speak2text-1.0.exe"'

with winreg.CreateKey(winreg.HKEY_CURRENT_USER, RUN) as k:
    winreg.SetValueEx(k, "LocalSpeak2Text", 0, winreg.REG_SZ, fake)
print("planted broken:", fake)

M.migrate_autostart()

with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN, 0, winreg.KEY_READ) as k:
    v, _ = winreg.QueryValueEx(k, "LocalSpeak2Text")
print("after migrate :", v)
assert "pythonw" in v and "main.py" in v, "dev-mode expect pythonw+main.py"
print("MIGRATE SELF-HEAL OK")
