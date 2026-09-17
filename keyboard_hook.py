# -*- coding: utf-8 -*-
"""Windows 低级键盘钩子（WH_KEYBOARD_LL），支持按键吞掉事件。

pynput 1.8 中回调返回 False 会停止整个监听器，无法用于"吞掉按键"，
所以直接用 ctypes 写一个可精确控制的钩子。

钩子必须装在独立线程上并用自己的消息泵（GetMessageW），不能依赖
Tk 主循环——Tk 的 C 代码会释放 GIL，此时回调触发会触发致命错误。
"""
import ctypes
import threading
from ctypes import wintypes

user32 = ctypes.windll.user32
kernel32 = ctypes.windll.kernel32

WH_KEYBOARD_LL = 13
WM_KEYDOWN = 0x0100
WM_KEYUP = 0x0101
WM_SYSKEYDOWN = 0x0104
WM_SYSKEYUP = 0x0105
WM_QUIT = 0x0012

LLKHF_INJECTED = 0x00000010

HOOKPROC = ctypes.WINFUNCTYPE(
    ctypes.c_long,
    ctypes.c_int,
    wintypes.WPARAM,
    wintypes.LPARAM,
)
user32.CallNextHookEx.argtypes = [
    wintypes.HHOOK,
    ctypes.c_int,
    wintypes.WPARAM,
    wintypes.LPARAM,
]
user32.CallNextHookEx.restype = ctypes.c_long


class KBDLLHOOKSTRUCT(ctypes.Structure):
    _fields_ = [
        ("vkCode", wintypes.DWORD),
        ("scanCode", wintypes.DWORD),
        ("flags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong)),
    ]


class KeyboardHook:
    """on_down(vk, injected) / on_up(vk, injected) 返回 True 表示吞掉该事件。"""

    def __init__(self, on_down=None, on_up=None):
        self.on_down = on_down or (lambda vk, injected: False)
        self.on_up = on_up or (lambda vk, injected: False)
        self._proc = None
        self._hook = None
        self._thread = None
        self._tid = None
        self._installed = threading.Event()

    def _callback(self, n_code, w_param, l_param):
        if n_code >= 0:
            kbd = ctypes.cast(l_param, ctypes.POINTER(KBDLLHOOKSTRUCT)).contents
            vk = kbd.vkCode
            injected = bool(kbd.flags & LLKHF_INJECTED)
            if w_param in (WM_KEYDOWN, WM_SYSKEYDOWN):
                swallow = self.on_down(vk, injected)
            elif w_param in (WM_KEYUP, WM_SYSKEYUP):
                swallow = self.on_up(vk, injected)
            else:
                swallow = False
            if swallow:
                return 1  # 吞掉：不再传给系统
        return user32.CallNextHookEx(None, n_code, w_param, l_param)

    def _run(self):
        """独立线程：装钩子 + 消息泵。"""
        self._proc = HOOKPROC(self._callback)
        user32.SetWindowsHookExW.argtypes = [
            ctypes.c_int,
            HOOKPROC,
            wintypes.HINSTANCE,
            wintypes.DWORD,
        ]
        user32.SetWindowsHookExW.restype = ctypes.c_void_p
        self._tid = kernel32.GetCurrentThreadId()
        self._hook = user32.SetWindowsHookExW(WH_KEYBOARD_LL, self._proc, None, 0)
        self._installed.set()
        msg = wintypes.MSG()
        while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
            user32.TranslateMessage(ctypes.byref(msg))
            user32.DispatchMessageW(ctypes.byref(msg))
        if self._hook:
            user32.UnhookWindowsHookEx(ctypes.c_void_p(self._hook))
            self._hook = None
        self._thread = None

    def start(self):
        if self._thread is not None:
            return True
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        return self._installed.wait(timeout=5) and bool(self._hook)

    def stop(self):
        if self._tid:
            user32.PostThreadMessageW(self._tid, WM_QUIT, 0, 0)
        if self._hook:
            user32.UnhookWindowsHookEx(ctypes.c_void_p(self._hook))
            self._hook = None
