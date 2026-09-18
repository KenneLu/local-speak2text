# -*- coding: utf-8 -*-
"""local-speak2text 主程序（本地离线语音转文字）：托盘版。

用法:
  python main.py             源码运行（保留控制台输出）
  local-speak2text-1.0.exe              打包运行（右下角托盘常驻）
  local-speak2text-1.0.exe --smoke      冒烟测试，结果写入 exe 同目录 smoke.log

热键:
  按住右 Ctrl      按住说话，实时出字，松手后文字键入当前窗口
  左 Ctrl+空格     切换持续模式：一直说话一直出字，再次 Ctrl+空格结束并键入
  Esc             持续模式下取消（不键入）
"""
import ctypes
import json
import os
import queue
import sys
import threading
import time
import tkinter as tk
from tkinter import filedialog, font as tkfont, messagebox
import winreg

import pystray
from PIL import Image, ImageDraw

from modules import i18n
import log_kit
from paths import APP_ID, APP_NAME, RUN_DIR, VERSION, process_pending_update
from updater import check_update, download_update, prepare_update_cmd
from keyboard_hook import KeyboardHook
from pipeline import (
    AsrEngine,
    CONFIG_PATH,
    MODEL_DIR,
    MODEL_NAME,
    Pipeline,
    load_config,
    set_auto_gain,
    run_benchmark,
)

WINDOW_WIDTH = 680
WINDOW_HEIGHT = 104          # 初始浮窗高度（约 3 行），会随内容自动生长
MIN_TEXT_LINES = 3           # 浮窗最小行数
MAX_TEXT_LINES = 12          # 浮窗最大行数；超过后内部滚动，总高不超过屏幕

user32 = ctypes.windll.user32
VK_CONTROL = 0x11
VK_RCONTROL = 0xA3
VK_LCONTROL = 0xA2
VK_SPACE = 0x20
VK_ESCAPE = 0x1B
VK_V = 0x56
KEYEVENTF_KEYUP = 0x0002
DEBUG = os.environ.get("LST_DEBUG", "") == "1"

RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
COLOR_IDLE = (30, 120, 230, 255)      # 空闲：蓝色
COLOR_RECORDING = (240, 140, 20, 255) # 录制中：橙色


def dprint(*args):
    if DEBUG:
        print(*args, flush=True)


def crash_log(text):
    """崩溃兜底：任何线程的未捕获异常都落到用户数据区 crash.log。

    --noconsole 打包后 stderr 不存在，没有这个文件闪退就无迹可寻。
    """
    try:
        from paths import USER_DATA_DIR

        USER_DATA_DIR.mkdir(parents=True, exist_ok=True)
        with open(USER_DATA_DIR / "crash.log", "a", encoding="utf-8") as f:
            f.write(time.strftime("%Y-%m-%d %H:%M:%S ") + text.rstrip() + "\n")
    except OSError:
        pass


def _install_excepthooks():
    """主线程 + 所有线程的未捕获异常：写 crash_log（打包后这才是唯一可见出口）。"""

    def dump(kind, exc, tb):
        import traceback

        text = "%s: %s\n%s" % (kind, exc, "".join(traceback.format_exception(exc)))
        crash_log(text)
        log_kit.log("CRASH " + text.splitlines()[0])

    old_sys = sys.excepthook

    def sys_hook(t, v, tb):
        dump("sys.excepthook", v, tb)
        old_sys(t, v, tb)
    sys.excepthook = sys_hook

    def thread_hook(args):
        dump("thread %s" % getattr(args, "name", "?"), args.exc_value, None)
        old_thread = threading.excepthook
        # 不链旧钩子：默认行为是打印到不存在的 stderr
    threading.excepthook = lambda args: dump(
        "thread %s" % getattr(args, "name", "?"), args.exc_value, None
    )


# ---------- 单实例 ----------

MUTEX_NAME = r"Local\%s\SingleInstance" % APP_ID
ERROR_ALREADY_EXISTS = 183
_MUTEX_HANDLE = None


def acquire_single_instance():
    """命名互斥体保证只有一个托盘实例（house 标准，同 reme-helper）。

    双开会抢键盘钩子和音频设备，还会各写一份配置。测试/特殊场景设
    LST_ALLOW_MULTI=1 可跳过。返回 False 表示已有实例在跑。
    """
    global _MUTEX_HANDLE
    if os.environ.get("LST_ALLOW_MULTI") == "1":
        return True
    if os.name != "nt":
        return True
    import ctypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateMutexW.restype = ctypes.c_void_p
    handle = kernel32.CreateMutexW(None, False, MUTEX_NAME)
    if not handle or ctypes.get_last_error() == ERROR_ALREADY_EXISTS:
        if handle:
            kernel32.CloseHandle(handle)
        return False
    _MUTEX_HANDLE = handle
    return True


def warn_duplicate_instance():
    """重复启动提示：托盘里已经有一个在跑，本实例直接退出。"""
    import ctypes

    ctypes.windll.user32.MessageBoxW(
        0, "%s 已在运行：请使用托盘里的那个实例。" % APP_NAME, APP_NAME, 0x40)


# ---------- 配置 ----------

def load_config_dict():
    try:
        with open(CONFIG_PATH, "r", encoding="utf-8-sig") as f:
            return json.load(f)
    except Exception:
        return {}


def save_config_dict(cfg):
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)


# ---------- 开机自启 ----------

def get_autostart_cmd():
    if getattr(sys, "frozen", False):
        # 打包实例：自启指向稳定安装位（若本 exe 就是从那里启动的，两者相同）。
        # 开发态 exe（比如用户直接在 release 目录试用）启动时，仍注册稳定位——
        # 那里将来由更新器安装正式版；稳定位还没有 exe 时退回注册当前路径。
        from paths import INSTALL_EXE, is_stable_install

        if is_stable_install() or INSTALL_EXE.exists():
            return '"%s"' % str(INSTALL_EXE)
        return '"%s"' % os.path.abspath(sys.executable)
    pythonw = os.path.join(os.path.dirname(sys.executable), "pythonw.exe")
    script = os.path.abspath(__file__)
    if os.path.exists(pythonw):
        return '"%s" "%s"' % (pythonw, script)
    return '"%s" "%s"' % (sys.executable, script)


def is_autostart_enabled():
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_READ) as k:
            winreg.QueryValueEx(k, APP_NAME)
            return True
    except FileNotFoundError:
        return False
    except OSError:
        return False


def migrate_autostart():
    """自启键指向的 exe 若已不存在（旧时间戳包/版本目录被删），重写到当前 exe。

    历史：1.1.2 之前注册的是 out\\<时间戳>\\<工具名>-<版本>.exe——包一删就断链。
    现在正式实例的"家"是稳定安装位 INSTALL_DIR，更新器装新版本写那里，路径永不变。
    """
    try:
        current = os.path.abspath(sys.executable) if getattr(sys, "frozen", False) else None
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_READ) as k:
            value, _ = winreg.QueryValueEx(k, APP_NAME)
        wanted = '"%s"' % current
        if value != wanted and not os.path.exists(value.strip('"')):
            set_autostart(True)
            dprint("autostart migrated:", value, "->", wanted)
    except FileNotFoundError:
        pass
    except OSError:
        pass


def set_autostart(enabled):
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as k:
        if enabled:
            winreg.SetValueEx(k, APP_NAME, 0, winreg.REG_SZ, get_autostart_cmd())
        else:
            try:
                winreg.DeleteValue(k, APP_NAME)
            except FileNotFoundError:
                pass


# ---------- 托盘图标 ----------

def make_icon_image(fill=COLOR_IDLE, size=64):
    """托盘图标：与 icons.py 同一套麦克风设计（icons.draw_mic 的本地快实现）。"""
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    s = size / 64.0
    d.rounded_rectangle([22*s, 8*s, 42*s, 38*s], radius=10*s, fill=fill)
    for y in (15, 21, 27):
        d.rectangle([26*s, y*s, 38*s, (y+2)*s], fill=(255, 255, 255, 255))
    d.arc([18*s, 28*s, 46*s, 56*s], start=0, end=180, fill=fill, width=max(2, round(4*s)))
    d.rectangle([30*s, 46*s, 34*s, 55*s], fill=fill)
    return img


class Tray:
    """托盘：菜单可整体重建（语言切换后文案生效），更新状态用属性开关。"""

    def __init__(self, controller):
        self.controller = controller
        self.update_ready = None  # (latest,) 下载就绪前=可更新版本；None=无更新
        self.status_text = i18n.t("tray_loading") % APP_NAME  # 菜单第①段信息行
        self.icon = pystray.Icon(
            APP_NAME,
            make_icon_image(),
            i18n.t("tray_loading") % APP_NAME,
            self._build_menu(),
        )

    def _build_menu(self):
        """house 标准八段式（执行文档 D14）：信息 → 更新 → 默认入口 → 业务 → 打开 → 偏好 → 退出。"""
        return pystray.Menu(
            # ① 信息区（只读）
            pystray.MenuItem(lambda _item: "%s v%s" % (APP_NAME, VERSION), None, enabled=False),
            pystray.MenuItem(lambda _item: self.status_text, None, enabled=False),
            pystray.Menu.SEPARATOR,
            # ② 更新区
            pystray.MenuItem(i18n.t("menu_check_update"), self._check_update),
            pystray.MenuItem(
                i18n.t("menu_update_now"),
                self._apply_update,
                enabled=lambda item: self.update_ready is not None,
            ),
            pystray.Menu.SEPARATOR,
            # ③ 默认入口（双击托盘）：使用指引
            pystray.MenuItem(i18n.t("menu_help"), self._show_help, default=True),
            pystray.Menu.SEPARATOR,
            # ④ 业务区
            pystray.MenuItem(
                i18n.t("menu_gain"),
                self._toggle_gain,
                checked=lambda item: bool(load_config_dict().get("auto_gain", True)),
            ),
            pystray.MenuItem(i18n.t("menu_choose_model"), self._choose_model),
            pystray.MenuItem(i18n.t("menu_benchmark"), self._start_benchmark),
            pystray.MenuItem(i18n.t("menu_copy_model_prompt"), self._copy_model_prompt),
            pystray.Menu.SEPARATOR,
            # ⑤ 打开区
            pystray.MenuItem(i18n.t("menu_open_logs"), self._open_logs),
            pystray.Menu.SEPARATOR,
            # ⑥ 偏好区
            pystray.MenuItem(
                i18n.t("menu_autostart"),
                self._toggle_autostart,
                checked=lambda item: is_autostart_enabled(),
            ),
            pystray.MenuItem(i18n.t("menu_language"), self._toggle_language),
            pystray.Menu.SEPARATOR,
            # ⑦ 退出（恒最后）
            pystray.MenuItem(i18n.t("menu_quit"), self._quit),
        )

    def rebuild(self):
        try:
            self.icon.menu = self._build_menu()
            self.icon.update_menu()
        except Exception:
            pass

    def start(self):
        self.icon.run_detached()

    def stop(self):
        try:
            self.icon.stop()
        except Exception:
            pass

    def notify(self, msg, title=APP_NAME):
        try:
            self.icon.notify(msg, title)
        except Exception:
            pass

    def set_title(self, text):
        self.status_text = text  # 同步到菜单第①段信息行
        try:
            self.icon.title = text
        except Exception:
            pass

    def set_recording(self, recording):
        try:
            self.icon.icon = make_icon_image(COLOR_RECORDING if recording else COLOR_IDLE)
            self.icon.title = (
                i18n.t("tray_recording") % APP_NAME if recording else i18n.t("tray_idle") % APP_NAME
            )
        except Exception:
            pass

    def _toggle_autostart(self, icon, item):
        enabled = not is_autostart_enabled()
        set_autostart(enabled)
        self.notify(i18n.t("notify_autostart_on") if enabled else i18n.t("notify_autostart_off"))

    def _toggle_gain(self, icon, item):
        cfg = load_config_dict()
        cfg["auto_gain"] = not bool(cfg.get("auto_gain", True))
        save_config_dict(cfg)
        set_auto_gain(cfg["auto_gain"])
        self.notify(i18n.t("notify_gain_on") if cfg["auto_gain"] else i18n.t("notify_gain_off"))

    def _toggle_language(self, icon, item):
        new_lang = "en" if i18n.LANG == "zh" else "zh"
        i18n.init(new_lang)
        i18n.save_language_to_config(CONFIG_PATH, new_lang)
        self.notify("Language: English" if new_lang == "en" else "语言：中文")
        self.rebuild()

    def _check_update(self, icon, item):
        def worker():
            result = check_update(CONFIG_PATH, force=True)
            if result.get("newer"):
                self.controller.ui_q.put(("update_found", result["latest"]))
            elif result.get("error") == "no_repo":
                self.controller.ui_q.put(("update_status", i18n.t("update_no_repo")))
            elif result.get("error"):
                self.controller.ui_q.put(("update_status", i18n.t("update_check_fail") % result["error"]))
            elif result.get("latest"):
                self.controller.ui_q.put(("update_status", i18n.t("update_latest") % result["latest"]))
        threading.Thread(target=worker, daemon=True).start()

    def _apply_update(self, icon, item):
        if not self.update_ready:
            return
        latest = self.update_ready

        def worker():
            try:
                staged = download_update(CONFIG_PATH, latest, log=dprint)
                self.controller.ui_q.put(("update_staged", latest, staged))
            except Exception as e:
                self.controller.ui_q.put(("update_status", i18n.t("update_download_fail") % e))
        threading.Thread(target=worker, daemon=True).start()

    def _choose_model(self, icon, item):
        self.controller.ui_q.put(("choose_model",))

    def _show_help(self, icon, item):
        self.controller.ui_q.put(("help",))

    def _copy_model_prompt(self, icon, item):
        self.controller.ui_q.put(("copy_model_prompt",))

    def _start_benchmark(self, icon, item):
        self.controller.ui_q.put(("benchmark_start",))

    def _open_logs(self, icon, item):
        log_kit.open_log_dir()

    def _quit(self, icon, item):
        # 托盘点「退出」不直接退：走 UI 线程的二次确认（队列封送）
        self.controller.ui_q.put(("quit_confirm",))


# ---------- 浮窗 ----------

class Overlay:
    """始终置顶、不抢焦点的小浮窗，显示识别文字。

    文字变多时自动增高（底部锚定、向上生长），最高到 MAX_TEXT_LINES 行，
    超过部分在浮窗内部滚动，始终只显示最新内容且不超出屏幕。
    """

    def __init__(self):
        self.root = tk.Tk()
        self.root.withdraw()
        self.root.overrideredirect(True)
        self.root.attributes("-topmost", True)
        self._no_activate()

        self.status = tk.Label(
            self.root,
            text="",
            font=("Microsoft YaHei", 10),
            bg="#EEF1F4",
            fg="#5F6B76",
            anchor="w",
            padx=10,
        )
        self.status.pack(fill="x")

        self.text = tk.Text(
            self.root,
            width=56,
            height=MIN_TEXT_LINES,
            wrap="char",
            font=("Microsoft YaHei", 13),
            bg="#FFFFFF",
            fg="#1F1F1F",
            bd=0,
            highlightthickness=1,
            highlightbackground="#C8CDD3",
            insertwidth=0,
            state="disabled",
        )
        self.text.pack(fill="both", expand=True)
        self.text.tag_configure("live", foreground="#8A9199")

        self._line_h = int(
            tkfont.Font(font=self.text.cget("font")).metrics("linespace")
        )
        self._anchor_bottom = None  # 当前会话浮窗底边的屏幕 Y；None=未显示
        self._anchor_x = None       # 当前会话浮窗左边缘的屏幕 X；None=未显示
        self.text.bind("<Configure>", self._on_text_resize)

    def _no_activate(self):
        try:
            hwnd = user32.GetParent(self.root.winfo_id())
            if not hwnd:
                hwnd = self.root.winfo_id()
            ex = user32.GetWindowLongW(hwnd, -20)
            user32.SetWindowLongW(hwnd, -20, ex | 0x08000000 | 0x00000080)
        except Exception:
            pass

    # ---------- 尺寸与位置 ----------

    def _place(self, width, height):
        """把浮窗放到（当前屏幕内），底边锚定在上次的位置（向上生长）。"""
        sw = self.root.winfo_screenwidth()
        sh = self.root.winfo_screenheight()
        if self._anchor_x is None:
            self._anchor_x = min(max(self.root.winfo_pointerx() - 12, 8), sw - width - 8)
        bottom = self._anchor_bottom
        if bottom is None:
            y = self.root.winfo_pointery() + 26
            bottom = min(y + height, sh - 8)
            self._anchor_bottom = bottom
        y = min(max(bottom - height, 8), sh - height - 8)
        self.root.geometry(f"{width}x{height}+{self._anchor_x}+{y}")

    def _line_count(self):
        """当前内容实际占用的行数（按换行符和自动换行折算）。"""
        self.text.update_idletasks()
        try:
            return int(self.text.count("1.0", "end", "displaylines")[0])
        except Exception:
            return int(self.text.index("end-1c").split(".")[0])

    def _fit(self):
        """按内容行数调整浮窗高度：行数增加向上生长，行数减少向下收缩。"""
        lines = min(max(self._line_count(), MIN_TEXT_LINES), MAX_TEXT_LINES)
        old_lines = int(self.text.cget("height"))
        if lines == old_lines:
            return
        self.text.config(height=lines)
        height = lines * self._line_h + WINDOW_HEIGHT - MIN_TEXT_LINES * self._line_h
        self._place(WINDOW_WIDTH, height)

    def _on_text_resize(self, _ev):
        # 窗口实际渲染尺寸可能和估算略有出入，用真实行高修正一次锚点
        if self._anchor_bottom is not None and self.root.winfo_ismapped():
            self._anchor_bottom = min(
                self.root.winfo_rooty() + self.root.winfo_height(),
                self.root.winfo_screenheight() - 8,
            )

    def show(self, mode):
        self._anchor_bottom = None
        self._anchor_x = None
        self.text.config(height=MIN_TEXT_LINES)
        self._place(WINDOW_WIDTH, WINDOW_HEIGHT)
        self.root.deiconify()
        self.root.update()

    def hide(self):
        self.root.withdraw()
        self._anchor_bottom = None
        self._anchor_x = None

    def set_status(self, text):
        self.status.config(text=text)

    def set_text(self, committed, live):
        prev_bottom = self._anchor_bottom
        self.text.config(state="normal")
        self.text.delete("1.0", "end")
        if committed:
            self.text.insert("end", committed)
        if live:
            self.text.insert("end", live, "live")
        self.text.config(state="disabled")
        self._fit()
        # 内容更新后钉住可见部分的末尾：始终看得到最新文字
        self.text.see("end")
        if prev_bottom is not None:
            self._anchor_bottom = prev_bottom

    def quit(self):
        self.root.destroy()


class Controller:
    def __init__(self, overlay, engine):
        self.overlay = overlay
        self.engine = engine
        self.pipe = None
        self.active = False
        self.hold = False
        self.finishing = False
        self.ctrl_l = False
        self.last_toggle = 0.0
        self.monitor_thread = None
        self.committed = ""
        self.live = ""
        self.last_seg = 0
        self.ui_q = queue.Queue()
        self.on_finish = None
        self.notify = None
        self.on_state_change = None
        self.hook_started = False
        self.exit_requested = False
        self.tray = None
        self.update_cmd_path = None
        self._bench_running = False
        self._bench_win = None
        self.hook = KeyboardHook(on_down=self._on_down, on_up=self._on_up)

    # ---------- 键盘钩子 ----------

    def _on_down(self, vk, injected):
        dprint(f"[hook] down vk={vk:#x}")
        if vk == VK_RCONTROL:
            if not self.active:
                self.start("hold")
            return False
        if vk == VK_SPACE and (user32.GetAsyncKeyState(VK_LCONTROL) & 0x8000):
            now = time.time()
            if now - self.last_toggle > 0.35:
                self.last_toggle = now
                if self.active and not self.hold and not self.finishing:
                    self.finish(cancel=False)
                elif not self.active:
                    self.start("cont")
            return True
        if vk == VK_ESCAPE and self.active:
            self.finish(cancel=True)
            return True
        return False

    def _on_up(self, vk, injected):
        dprint(f"[hook] up vk={vk:#x}")
        if vk == VK_RCONTROL:
            if self.active and self.hold and not self.finishing:
                self.finish(cancel=False)
            return False
        return False

    # ---------- 会话控制 ----------

    def start(self, mode, use_audio=True):
        dprint(f"[ctrl] start mode={mode}")
        if self.active or self.engine is None:
            return
        self.pipe = Pipeline(self.engine, self.ui_q)
        if not self.pipe.start(mode, use_audio=use_audio):
            self.pipe = None
            return
        self.active = True
        self.hold = mode == "hold"
        self.finishing = False
        self.committed = ""
        self.live = ""
        self.last_seg = 0
        self._set_recording(True)
        self.ui_q.put(("show_ui", mode))
        if mode == "hold":
            self.monitor_thread = threading.Thread(target=self._monitor_hold_release, daemon=True)
            self.monitor_thread.start()

    def _monitor_hold_release(self):
        deadline = time.time() + 2.0
        while self.active and self.hold and not self.finishing:
            if user32.GetAsyncKeyState(VK_RCONTROL) & 0x8000:
                break
            if time.time() > deadline:
                return
            time.sleep(0.01)
        while self.active and self.hold and not self.finishing:
            pressed = user32.GetAsyncKeyState(VK_RCONTROL) & 0x8000
            if not pressed:
                self.finish(cancel=False)
                break
            time.sleep(0.01)

    def finish(self, cancel=False):
        if not self.active or self.pipe is None:
            return
        if cancel:
            self.pipe.finish(cancel=True)
        else:
            self.finishing = True
            self.ui_q.put(("status", i18n.t("status_recognizing")))
            self.pipe.finish(cancel=False)

    # ---------- 事件处理 ----------

    def poll(self):
        try:
            while True:
                ev = self.ui_q.get_nowait()
                self._handle(ev)
        except queue.Empty:
            pass
        if not self.exit_requested:
            self.overlay.root.after(40, self.poll)

    def _handle(self, ev):
        kind = ev[0]
        dprint(f"[ui] event {kind}")
        if kind == "show_ui":
            mode = ev[1]
            self.overlay.show(mode)
            if mode == "hold":
                self.overlay.set_status(i18n.t("status_listening_hold"))
            else:
                self.overlay.set_status(i18n.t("status_listening_cont"))
            self.overlay.set_text("", "")
        elif kind == "status":
            self.overlay.set_status(ev[1])
        elif kind == "live":
            _, seg_id, text = ev
            if seg_id >= self.last_seg:
                self.live = text
                self.overlay.set_text(self.committed, self.live)
        elif kind == "commit":
            _, seg_id, text = ev
            if seg_id > self.last_seg:
                self.last_seg = seg_id
                self.committed += text
                self.live = ""
                self.overlay.set_text(self.committed, "")
        elif kind == "error":
            self.overlay.set_status(i18n.t("status_error_prefix") + ev[1])
            self.overlay.set_text("", "")
            self.overlay.root.after(2500, self.overlay.hide)
            self._set_recording(False)
            self.active = False
            self.hold = False
            self.finishing = False
            self.pipe = None
        elif kind == "finish":
            cancel = ev[1]
            text = "" if cancel else (self.committed + self.live)
            if text:
                type_text(text)
            if self.on_finish is not None:
                cb = self.on_finish
                self.on_finish = None
                cb(text)
            self.overlay.hide()
            self._set_recording(False)
            self.active = False
            self.hold = False
            self.finishing = False
            self.committed = ""
            self.live = ""
            self.last_seg = 0
            self.pipe = None
        elif kind == "choose_model":
            self._choose_model_dir()
        elif kind == "rebuild_tray":
            if self.tray is not None:
                self.tray.rebuild()
        elif kind == "update_found":
            latest = ev[1]
            if self.tray is not None:
                self.tray.update_ready = latest
                self.tray.rebuild()
            self.notify(i18n.t("update_new") % (latest, VERSION))
        elif kind == "update_status":
            self.notify(ev[1])
        elif kind == "update_staged":
            _latest, staged = ev[1], ev[2]
            try:
                self.update_cmd_path = prepare_update_cmd(staged)
                self.notify(i18n.t("update_ready_restart"))
            except Exception as e:
                self.notify(i18n.t("update_download_fail") % e)
        elif kind == "help":
            self._show_help_dialog()
        elif kind == "copy_model_prompt":
            self._copy_model_prompt()
        elif kind == "benchmark_start":
            self._start_benchmark()
        elif kind == "benchmark_progress":
            self._bench_progress(ev[1], ev[2])
        elif kind == "benchmark_done":
            self._bench_done(ev[1])
        elif kind == "quit_confirm":
            self._confirm_quit()
        elif kind == "exit":
            self.exit_requested = True
            self.overlay.root.quit()

    def _show_help_dialog(self):
        top = tk.Toplevel(self.overlay.root)
        top.title(i18n.t("help_title"))
        top.geometry("660x520")
        top.attributes("-topmost", True)
        txt = tk.Text(top, wrap="word", font=("Microsoft YaHei", 10),
                      bd=0, highlightthickness=0, insertwidth=0)
        txt.pack(fill="both", expand=True, padx=10, pady=(10, 4))
        txt.insert("1.0", i18n.t("help_body"))
        txt.config(state="disabled")
        top.update_idletasks()
        sw, sh = top.winfo_screenwidth(), top.winfo_screenheight()
        top.geometry("+%d+%d" % ((sw - 660) // 2, max(40, (sh - 520) // 3)))
        btn = tk.Button(top, text=i18n.t("help_close"), command=top.destroy, width=12)
        btn.pack(pady=(0, 10))

    def _copy_model_prompt(self):
        body = i18n.t("copy_prompt_body").replace(
            "<MODELS_DIR>", os.path.join(RUN_DIR, "asr-modules"))
        try:
            import pyperclip
            pyperclip.copy(body)
            self.notify(i18n.t("copy_prompt_copied"))
        except Exception as e:
            self.notify(i18n.t("copy_prompt_fail") % e)

    def _start_benchmark(self):
        if self._bench_running:
            return
        self._bench_running = True
        win = tk.Toplevel(self.overlay.root)
        win.title(i18n.t("bench_title"))
        win.geometry("420x180")
        win.attributes("-topmost", True)
        lbl = tk.Label(win, text=i18n.t("bench_running"),
                       font=("Microsoft YaHei", 10), justify="left", anchor="w")
        lbl.pack(fill="both", expand=True, padx=14, pady=14)
        win.update_idletasks()
        sw, sh = win.winfo_screenwidth(), win.winfo_screenheight()
        win.geometry("+%d+%d" % ((sw - 420) // 2, max(40, (sh - 180) // 3)))
        self._bench_win = win

        def progress_cb(kind, name):
            self.ui_q.put(("benchmark_progress", kind, name))

        def worker():
            try:
                result = run_benchmark(os.path.join(RUN_DIR, "asr-modules"), progress_cb)
            except Exception as e:
                result = {"error": str(e)}
            self.ui_q.put(("benchmark_done", result))
        threading.Thread(target=worker, daemon=True).start()

    def _bench_progress(self, kind, name):
        if self._bench_win is not None and self._bench_win.winfo_exists():
            try:
                kids = self._bench_win.winfo_children()
                if kids:
                    kids[0].config(text=i18n.t("bench_working") % name)
            except Exception:
                pass

    def _bench_done(self, result):
        self._bench_running = False
        win = self._bench_win
        was_open = False
        if win is not None:
            try:
                was_open = bool(win.winfo_exists())
                if was_open:
                    win.destroy()
            except Exception:
                was_open = False
            self._bench_win = None
        if result.get("error"):
            self._bench_show_error(result)
            return
        if not was_open:
            # 用户提前关了进度窗：完成后主动弹出结果窗（需求明确要求）
            pass
        self._show_bench_result(result)

    def _bench_show_error(self, result):
        if result.get("error") == "no_audio":
            messagebox.showinfo(i18n.t("bench_title"), i18n.t("bench_no_audio"))
        else:
            messagebox.showerror(i18n.t("bench_title"),
                                 i18n.t("bench_failed") % result.get("error"))

    def _show_bench_result(self, result):
        top = tk.Toplevel(self.overlay.root)
        top.title(i18n.t("bench_result_title"))
        top.attributes("-topmost", True)
        cols = ("model", "type", "load", "rtf_short", "rtf_long", "verdict")
        heads = (i18n.t("bench_col_model"), i18n.t("bench_col_type"),
                 i18n.t("bench_col_load"), i18n.t("bench_col_rtf_short"),
                 i18n.t("bench_col_rtf_long"), i18n.t("bench_col_verdict"))
        try:
            from tkinter import ttk
            frame = tk.Frame(top)
            frame.pack(fill="both", expand=True, padx=10, pady=(10, 4))
            tree = ttk.Treeview(frame, columns=cols, show="headings", height=len(result["results"]))
            for cid, head in zip(cols, heads):
                tree.heading(cid, text=head)
            widths = (200, 90, 70, 80, 80, 80)
            for cid, w in zip(cols, widths):
                tree.column(cid, width=w, anchor="w")
            for r in result["results"]:
                if not r["ok"]:
                    verdict = i18n.t("bench_verdict_fail")
                elif r["rtf_long"] >= 1.0:
                    verdict = i18n.t("bench_verdict_slow")
                else:
                    verdict = i18n.t("bench_verdict_ok")
                tree.insert("", "end", values=(
                    r["name"], r["type"], r["load_s"],
                    r["rtf_short"], r["rtf_long"], verdict))
            tree.pack(fill="both", expand=True)
        except Exception:
            pass
        info = i18n.t("bench_audio_info") % (result.get("audio_sec", 0), result.get("long_sec", 0))
        if result.get("reco"):
            info += "\n" + i18n.t("bench_reco") % result["reco"]
        else:
            info += "\n" + i18n.t("bench_reco_none")
        lbl = tk.Label(top, text=info, font=("Microsoft YaHei", 10), justify="left", anchor="w")
        lbl.pack(fill="x", padx=10)
        expl = tk.Label(top, text=i18n.t("bench_explain"), font=("Microsoft YaHei", 9),
                        fg="#5F6B76", justify="left", anchor="w")
        expl.pack(fill="x", padx=10, pady=(6, 2))
        btn = tk.Button(top, text=i18n.t("help_close"), command=top.destroy, width=12)
        btn.pack(pady=(2, 10))
        top.update_idletasks()
        sw, sh = top.winfo_screenwidth(), top.winfo_screenheight()
        top.geometry("+%d+%d" % ((sw - 640) // 2, max(30, (sh - 480) // 3)))

    def _confirm_quit(self):
        """退出二次确认：用户点了确认才真正退出；关窗/取消都不退出。"""
        top = tk.Toplevel(self.overlay.root)
        top.title(i18n.t("quit_confirm_title"))
        top.resizable(False, False)
        top.attributes("-topmost", True)
        lbl = tk.Label(top, text=i18n.t("quit_confirm_body"),
                       font=("Microsoft YaHei", 10), justify="left")
        lbl.pack(padx=18, pady=(16, 10))
        btns = tk.Frame(top)
        btns.pack(pady=(0, 14))

        def do_quit():
            top.destroy()
            self.ui_q.put(("exit",))

        def cancel():
            top.destroy()

        yes = tk.Button(btns, text=i18n.t("quit_confirm_yes"), command=do_quit,
                        width=10, bg="#E5534B", fg="#FFFFFF", relief="flat")
        no = tk.Button(btns, text=i18n.t("quit_confirm_no"), command=cancel, width=10)
        yes.pack(side="left", padx=8)
        no.pack(side="left", padx=8)
        no.focus_set()
        top.protocol("WM_DELETE_WINDOW", cancel)
        top.update_idletasks()
        sw, sh = top.winfo_screenwidth(), top.winfo_screenheight()
        top.geometry("+%d+%d" % ((sw - top.winfo_width()) // 2, (sh - top.winfo_height()) // 2))
        top.grab_set()  # 模态：确认期间托盘重复点击不会再叠加弹窗

    def _set_recording(self, recording):
        if self.on_state_change:
            self.on_state_change(recording)

    def _choose_model_dir(self):
        initial = MODEL_DIR if os.path.isdir(MODEL_DIR) else os.path.dirname(os.path.abspath(MODEL_DIR))
        chosen = filedialog.askdirectory(title=i18n.t("menu_choose_model_title"), initialdir=initial)
        if not chosen:
            return
        try:
            new_engine = AsrEngine(model_dir=chosen)
        except Exception as e:
            if self.notify:
                self.notify(i18n.t("notify_model_failed") % e)
            return
        cfg = load_config_dict()
        cfg["model_dir"] = os.path.normpath(chosen)
        save_config_dict(cfg)
        load_config()
        self.engine = new_engine
        if not self.hook_started:
            self.hook_started = self.hook.start()
        if self.notify:
            self.notify(i18n.t("notify_model_updated") % (MODEL_DIR, new_engine.model_type))


def type_text(text):
    """剪贴板 + Ctrl+V 把文字键入当前窗口。"""
    if not text:
        return
    import pyperclip

    pyperclip.copy(text)
    time.sleep(0.06)
    user32.keybd_event(VK_CONTROL, 0, 0, 0)
    user32.keybd_event(VK_V, 0, 0, 0)
    user32.keybd_event(VK_V, 0, KEYEVENTF_KEYUP, 0)
    user32.keybd_event(VK_CONTROL, 0, KEYEVENTF_KEYUP, 0)


def main():
    _install_excepthooks()
    if not acquire_single_instance():
        warn_duplicate_instance()
        return 0
    i18n.init(i18n.load_language_from_config(CONFIG_PATH))
    process_pending_update()
    migrate_autostart()
    log_kit.log("startup %s v%s (pid %s)" % (APP_NAME, VERSION, os.getpid()))
    overlay = Overlay()
    ctrl = Controller(overlay, None)
    tray = Tray(ctrl)
    ctrl.tray = tray
    ctrl.notify = tray.notify
    ctrl.on_state_change = tray.set_recording

    tray.start()
    tray.set_title(i18n.t("tray_loading") % APP_NAME)
    tray.notify(i18n.t("notify_loading"))

    try:
        engine = AsrEngine()
    except Exception as e:
        dprint("model load failed:", e)
        log_kit.log("model load failed: %s" % e)
        tray.set_title(i18n.t("tray_load_failed") % APP_NAME)
        tray.notify(i18n.t("notify_load_failed"))
    else:
        ctrl.engine = engine
        ctrl.hook_started = ctrl.hook.start()
        tray.set_title(i18n.t("tray_ready") % (APP_NAME, engine.model_type))
        tray.notify(i18n.t("notify_ready") % engine.model_type)
        log_kit.log("model ready: %s" % engine.model_type)

    # 启动后后台节流检查更新（有配置 update_repo 才生效），有新版弹通知并点亮菜单
    def _startup_update_check():
        time.sleep(8)
        result = check_update(CONFIG_PATH, force=False)
        if result.get("newer"):
            ctrl.ui_q.put(("update_found", result["latest"]))
    threading.Thread(target=_startup_update_check, daemon=True).start()

    overlay.root.after(40, ctrl.poll)
    try:
        overlay.root.mainloop()
    finally:
        log_kit.log("exit")
        if ctrl.update_cmd_path:
            os.system('start "" /min "%s"' % ctrl.update_cmd_path)
        ctrl.hook.stop()
        tray.stop()


def smoke():
    """冒烟测试：加载配置和模型，结果写入 smoke.log。"""
    if getattr(sys, "frozen", False):
        base = os.path.dirname(os.path.abspath(sys.executable))
    else:
        base = os.path.dirname(os.path.abspath(__file__))
    log = os.path.join(base, "smoke.log")
    try:
        load_config()
        if not os.path.isdir(MODEL_DIR):
            raise RuntimeError("模型目录不存在: " + MODEL_DIR)
        engine = AsrEngine()
        del engine
        msg = "OK model_dir=" + MODEL_DIR
        with open(log, "w", encoding="utf-8") as f:
            f.write(msg)
        return 0
    except Exception as e:
        with open(log, "w", encoding="utf-8") as f:
            f.write("FAIL " + str(e))
        return 1


def autotest(wav_path):
    """自动测试：模拟按右 Ctrl -> 喂入 WAV 音频 -> 松手 -> 输出最终文本。"""
    import wave

    import numpy as np

    from pipeline import SAMPLE_RATE

    with wave.open(wav_path, "rb") as w:
        assert w.getnchannels() == 1 and w.getsampwidth() == 2
        data = w.readframes(w.getnframes())
    samples = np.frombuffer(data, dtype=np.int16).astype(np.float32) / 32768.0

    engine = AsrEngine()
    overlay = Overlay()
    ctrl = Controller(overlay, engine)
    result = {}
    done_ev = threading.Event()
    ctrl.on_finish = lambda text: (result.update(text=text), done_ev.set())
    overlay.root.after(40, ctrl.poll)

    block = int(SAMPLE_RATE * 0.1)

    def feed(i):
        if ctrl.active and i < len(samples):
            ctrl.pipe.add_samples(samples[i : i + block])
            overlay.root.after(20, feed, i + block)
        elif i >= len(samples):
            overlay.root.after(600, release)

    def release():
        ctrl._on_up(VK_RCONTROL, True)
        overlay.root.after(2000, finish_wait)

    def finish_wait():
        if not done_ev.is_set():
            overlay.root.after(500, finish_wait)
        else:
            overlay.root.quit()

    def start_drive():
        ctrl.start("hold", use_audio=False)
        overlay.root.after(300, feed, 0)

    overlay.root.after(500, start_drive)
    overlay.root.mainloop()
    ctrl.hook.stop()
    print("AUTOTEST_TEXT:", result.get("text", ""))


if __name__ == "__main__":
    if "--smoke" in sys.argv:
        sys.exit(smoke())
    elif len(sys.argv) > 1 and sys.argv[1] == "--autotest":
        autotest(sys.argv[2])
    else:
        sys.exit(main())
