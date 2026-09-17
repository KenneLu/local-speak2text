# -*- coding: utf-8 -*-
"""注入左 Ctrl+空格 组合键（持续模式开关测试用）。"""
import ctypes
import sys
import time

user32 = ctypes.windll.user32
VK_LCONTROL = 0xA2
VK_SPACE = 0x20
KEYEVENTF_KEYUP = 0x0002

hold = float(sys.argv[1]) if len(sys.argv) > 1 else 0.15
user32.keybd_event(VK_LCONTROL, 0, 0, 0)
time.sleep(0.08)
user32.keybd_event(VK_SPACE, 0, 0, 0)
time.sleep(hold)
user32.keybd_event(VK_SPACE, 0, KEYEVENTF_KEYUP, 0)
time.sleep(0.08)
user32.keybd_event(VK_LCONTROL, 0, KEYEVENTF_KEYUP, 0)
print("injected ctrl+space")
