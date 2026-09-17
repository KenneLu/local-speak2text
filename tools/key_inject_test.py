# -*- coding: utf-8 -*-
"""向系统注入右 Ctrl 按下/松开事件（真实热键链路测试用）。"""
import ctypes
import sys
import time

user32 = ctypes.windll.user32
VK_RCONTROL = 0xA3
KEYEVENTF_KEYUP = 0x0002

user32.keybd_event(VK_RCONTROL, 0, 0, 0)
time.sleep(float(sys.argv[1]) if len(sys.argv) > 1 else 2.0)
user32.keybd_event(VK_RCONTROL, 0, KEYEVENTF_KEYUP, 0)
print("injected rctrl down/up")
