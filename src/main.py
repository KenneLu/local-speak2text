# -*- coding: utf-8 -*-
"""local-speak2text 主程序（本地离线语音转文字）：托盘版。

用法:
  python main.py             源码运行（保留控制台输出）
  local-speak2text.exe              打包运行（右下角托盘常驻）
  local-speak2text.exe --smoke      冒烟测试，结果写入 exe 同目录 smoke.log

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
from pathlib import Path
from tkinter import filedialog, font as tkfont, messagebox

import pystray

from modules import i18n, log_kit, tray_kit   # noqa: E402
from modules.appconfig import (APP_ID, APP_NAME, COLOR_IDLE, COLOR_RECORDING,
                               ICON_DRAW, VERSION)
from modules.autostart import is_autostart_enabled, migrate_autostart, set_autostart
from modules.paths import (LOG_DIR, RUN_DIR, USER_DATA_DIR,
                           hold_exe_delete_guard)
from updater import (check_update, download_update, prepare_update_cmd,
                     process_pending_update, pop_failed_update_note,
                     launch_pending_cmd)
from keyboard_hook import KeyboardHook
# ⚠️ `MODEL_DIR` / `MODEL_NAME` 有意**不**在这里 from-import：`from ... import X` 绑的是
# **导入那一刻的静态副本**，而 `pipeline.load_config()` 之后重绑的是 `pipeline.MODEL_DIR`。
# 两者一旦不同步，用户就会看到"换了模型目录、对话框还开在旧目录、通知还印旧目录"（#47）。
# 需要它们时一律现取：`pipeline.MODEL_DIR`。
import pipeline
from pipeline import (
    AsrEngine,
    CONFIG_PATH,
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

def dprint(*args):
    if DEBUG:
        print(*args, flush=True)


# ---------- 运行日志（T12 log_kit） ----------

_LOG_HANDLE = None


def _log_handle():
    """惰性初始化：守卫/异常钩子在 main() 之前也可能要记日志。"""
    global _LOG_HANDLE
    if _LOG_HANDLE is None:
        _LOG_HANDLE = log_kit.make_logger(LOG_DIR)
    return _LOG_HANDLE


def log(*parts):
    """写一行 INFO，**print 形态**（可变参数，空格拼接）。

    形态必须与模板件的调用方式一致：`tray_kit` / `autostart` / `update_helper` 都按
    print 形态调用（`log("downloading", stem)`、`log("update staged:", staged, "->", target)`），
    单参包装会在模板件内部直接 TypeError（C-29 判据；dsh/ocx 早有 `def log(*parts)`）。
    拼接后**只传一个字符串**给 log_kit，因此对 1.0.2（单参闭包）与 1.0.3（print 形态）都成立。
    日志失败静默——日志永远不能把主流程弄死。
    """
    try:
        _log_handle()[0](" ".join(str(p) for p in parts))
    except Exception:
        pass


def open_log_dir():
    """托盘「打开日志目录」的落地动作。"""
    try:
        _log_handle()[1]()
    except Exception:
        pass


def crash_log(text):
    """崩溃兜底：任何线程的未捕获异常都落到用户数据区 crash.log。

    --noconsole 打包后 stderr 不存在，没有这个文件闪退就无迹可寻。
    """
    try:
        from modules.paths import USER_DATA_DIR

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
        log("CRASH " + text.splitlines()[0])

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


# ---------- 单实例（T7 tray_kit；本文件只留 --smoke 的合法性探针） ----------

# 命名内核对象：命名空间前缀 `Local\` 之后**不允许再出现反斜杠**。
# 1.2.0~1.4.0 写成 r"Local\%s\SingleInstance"（多一个反斜杠）→ CreateMutexW 返回
# NULL + err=3(ERROR_PATH_NOT_FOUND)，而旧代码把 NULL 当"已有实例"→ 每次启动都误报
# "已在运行"，工具完全打不开。运行期守卫改由 tray_kit 派生同名互斥体；
# test_single_instance 会真实占用一次、再用本名字探测，把「派生名 == 本名字」钉死。
MUTEX_NAME = r"Local\%s-single-instance" % APP_ID


# 说明：探针已收敛到模板 tray_kit 2.2.0 的 `mutex_name_is_valid(app_id, mutex_name)`——
# 它与守卫共用同一份命名判据 `mutex_name_ok()`（此处不再保留第二份定义）。
# MUTEX_NAME 仍留在本文件：--smoke 显式把名字交给探针，同时也被 test_single_instance
# 用来断言"派生名 == 这个名字"。


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


# ---------- 开机自启（T3 autostart；target="stable" = 指向稳定安装位） ----------

# ---------- 托盘图标 ----------

def make_icon_image(fill=COLOR_IDLE, size=64):
    """托盘图标：图形唯一来源是 appconfig.ICON_DRAW（与构建期 ico 同一套设计）。"""
    return ICON_DRAW(size, fill=fill)


GUI_INMENUMODE = 0x00000004


def menu_is_open():
    """系统弹出菜单是否正开着（E2-09）。

    菜单开着时重建菜单会把菜单销毁重造（pystray 的 update_menu 是
    DestroyMenu+CreatePopupMenu），表现就是"鼠标滑着滑着突然失焦"——所以先问一句。
    探测：菜单模态标记 GUI_INMENUMODE 挂在调用 TrackPopupMenu 的那个线程上，
    遍历本进程线程去问；再以"前台窗口是系统菜单类 #32768"兜底。探测失败当没开着。
    """
    if os.name != "nt":
        return False
    try:
        from ctypes import wintypes

        class GUITHREADINFO(ctypes.Structure):
            _fields_ = [("cbSize", wintypes.DWORD), ("flags", wintypes.DWORD),
                        ("hwndActive", wintypes.HWND), ("hwndFocus", wintypes.HWND),
                        ("hwndCapture", wintypes.HWND), ("hwndMenuOwner", wintypes.HWND),
                        ("hwndMoveSize", wintypes.HWND), ("hwndCaret", wintypes.HWND),
                        ("rcCaret", wintypes.RECT)]

        for thread in threading.enumerate():
            tid = getattr(thread, "native_id", None)
            if not tid:
                continue
            info = GUITHREADINFO()
            info.cbSize = ctypes.sizeof(GUITHREADINFO)
            if not user32.GetGUIThreadInfo(int(tid), ctypes.byref(info)):
                continue
            if info.flags & GUI_INMENUMODE:
                return True
        hwnd = user32.GetForegroundWindow()
        if hwnd:
            name = ctypes.create_unicode_buffer(32)
            user32.GetClassNameW(hwnd, name, 32)
            if name.value == "#32768":
                return True
        return False
    except Exception:   # 探测失败就当没开着
        return False


class Tray:
    """托盘：菜单可整体重建（语言切换后文案生效），更新状态用属性开关。"""

    def __init__(self, controller):
        self.controller = controller
        self.update_ready = None  # (latest,) 下载就绪前=可更新版本；None=无更新
        self.status_text = i18n.t("tray_loading") % APP_NAME  # 菜单第①段信息行
        self._stop = threading.Event()
        # E2-09：签名变了才重建菜单，菜单开着时推迟——根治右键菜单突然失焦
        self._menu_sig = tray_kit.MenuSignature(
            self.rebuild, menu_is_open=menu_is_open, log=log)
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
        """强制重建菜单（MenuSignature 的落地动作）。"""
        try:
            self.icon.menu = self._build_menu()
            self.icon.update_menu()
        except Exception:
            pass

    def _menu_signature(self):
        """菜单上会"显示出来"的状态；只有它变了才值得重建。"""
        return (
            i18n.current_lang(),
            self.update_ready is not None,
            bool(load_config_dict().get("auto_gain", True)),
            is_autostart_enabled(),
        )

    def refresh(self):
        """签名驱动重画：菜单开着时自动推迟，由 _menu_refresh_loop 补画。"""
        self._menu_sig.update(self._menu_signature())

    def _menu_refresh_loop(self):
        """1.5s 补画拍：只补"菜单开着时被推迟"的重画（tray_kit 三循环之②）。"""
        while not self._stop.wait(1.5):
            try:
                self.refresh()
                self._menu_sig.flush_deferred()
            except Exception:
                pass

    def start(self):
        self.icon.run_detached()
        threading.Thread(target=self._menu_refresh_loop, daemon=True).start()

    def stop(self):
        self._stop.set()
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
        new_lang = "en" if i18n.current_lang() == "zh" else "zh"
        i18n.init(new_lang)
        i18n.save_language_to_config(CONFIG_PATH, new_lang)
        self.notify(i18n.t("notify_lang_switched"))
        self.refresh()

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
        open_log_dir()

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
        self.quit_apply_update = True   # 退出确认框勾选项的最终值（默认沿用既有行为）
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
                self.tray.refresh()
        elif kind == "update_found":
            latest = ev[1]
            if self.tray is not None:
                self.tray.update_ready = latest
                self.tray.refresh()
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
        """退出二次确认（T7 tray_kit.confirm_quit_dialog；G4.1 条款 4 / G4.2 条款 5）。

        旧内联版没有 <Escape> 绑定——GUI 实测按 Esc 关不掉弹窗；模板版有。
        降级链（禁止跳过确认）：富对话框 → 原生 askyesno → 链路不可用时放行退出。
        勾选项 = 退出后是否自动安装已下载的更新；勾选动作即落盘（点取消也留存）。

        三态必须分开（#44-A，与 dsh/ocx 的 `_decide_quit` 同形）：
          None              → 弹窗链路整个不可用（**不是**用户作答）⇒ 放行退出，
                              且 `quit_apply_update = False`（**不沿用已存勾选**）
          {"go": False}     → 用户明确取消（Esc / 关窗 / 「取消」）⇒ 不退出
          {"go": True, ...} → 用户确认 ⇒ 退出，并按已存勾选决定是否应用更新
        两条边界都要守住：
          *「不可用 ⇒ 放行」**不等于**「默认 go=True」——确认框没被拆掉时问到就听用户的；
          *「不可用 ⇒ 放行退出」**也不等于**「不可用时照用户上次的勾选执行副作用」——
            用户这次没被问过，就必须选"保住现场"的那一侧（dsh/ocx 末级硬编码 False）。
        依据：tray_kit.confirm_quit_dialog 的 docstring 第 161 行说「取消返回 None」，
        但实现里取消只 destroy，result 保持 `{"go": False, ...}`，第 220 行
        `return result or None` 因此**恒为 dict**——取消不会被误当成「链路不可用」，
        这正是三态能分开的前提。（该 docstring 与实现不符，已上报模板侧。）
        """
        cfg = load_config_dict()
        checked = bool(cfg.get("quit_apply_update", True))

        def _persist(value):
            c = load_config_dict()
            c["quit_apply_update"] = bool(value)
            save_config_dict(c)

        # 本函数由 ui_q 的 "quit_confirm" 事件在 Tk 线程上派发（见 poll），所以
        # confirm_quit_dialog 可直接拿 self.overlay.root 当 parent，无需 ui_post 封送。
        choice = None
        try:
            # 2.0.2：弹窗全部用户可见文案经参数注入 i18n 词条（模板不再硬编码中文）
            choice = tray_kit.confirm_quit_dialog(
                APP_NAME, i18n.t("quit_confirm_cleanup"), checked,
                parent=self.overlay.root, on_change=_persist,
                title=i18n.t("quit_confirm_title"),
                body_text=i18n.t("quit_confirm_body"),
                confirm_text=i18n.t("quit_confirm_yes"),
                cancel_text=i18n.t("quit_confirm_no"))
        except Exception as exc:
            log("quit dialog failed (%s: %s); falling back to native confirm"
                % (type(exc).__name__, exc))
            try:
                go = messagebox.askyesno(APP_NAME, i18n.t("quit_confirm_body"),
                                         parent=self.overlay.root)
                choice = {"go": bool(go), "stop_service": checked}
            except Exception as exc2:
                # Tk 运行时缺失 / 会话不可交互：这**不是**用户作答，交给下面 None 分支放行。
                log("native confirm failed (%s: %s)" % (type(exc2).__name__, exc2))
                choice = None
        if choice is None:
            # 链路不可用 ⇒ **用户这次根本没被问过**，所以不得沿用他上次在"有确认框"
            # 语境下保存的勾选去执行破坏性动作（这里 = 退出时应用已下载的更新，见
            # main() 的 finally）。按"保住现场"那一侧倒 —— 这正是 dsh/ocx 末级
            # 硬编码 False 的同一形态："没问到"与"用户选了"必须分开。
            log("quit confirm unavailable; quitting WITHOUT applying the pending update")
            self.quit_apply_update = False
            self.ui_q.put(("exit",))
            return
        if not choice.get("go"):
            log("quit cancelled by user")
            return
        # 勾选状态已随勾选动作落盘；记住最终值供退出收尾决定是否执行更新替换
        self.quit_apply_update = bool(load_config_dict().get("quit_apply_update", True))
        self.ui_q.put(("exit",))

    def _set_recording(self, recording):
        if self.on_state_change:
            self.on_state_change(recording)

    def _choose_model_dir(self):
        # 现取：对话框的初始目录必须是**此刻**的模型目录（#47），不是导入期的快照
        current = pipeline.MODEL_DIR
        initial = current if os.path.isdir(current) else os.path.dirname(os.path.abspath(current))
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
            # 同上：通知里印的必须是刚生效的那个目录（`load_config()` 已在上面跑过）
            self.notify(i18n.t("notify_model_updated") % (pipeline.MODEL_DIR, new_engine.model_type))


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
    # i18n 先于单实例守卫初始化：重复实例的提示框也要出正确的语言
    i18n.init(i18n.load_language_from_config(CONFIG_PATH))
    if not tray_kit.acquire_single_instance(APP_ID, log=log):
        # 2.0.2：整段文案经 message/title 注入 i18n，英文模式不再出现中文外壳
        tray_kit.warn_duplicate_instance(
            APP_NAME,
            message="\n\n".join([i18n.t("dup_running") % APP_NAME,
                                 i18n.t("dup_hint"),
                                 i18n.t("dup_cancelled")]),
            title=APP_NAME)
        return 0
    # C-2（paths 1.1.4）：让**内核**替我们拒绝"删除/改名正在运行的实例目录"，而不是靠纪律。
    # **必须在托盘/窗口创建之前**（README 采纳步骤第 4 条："顺序不能再往后挪"）——所以放在
    # 守卫放行之后、`Overlay()`/`Tray()` 之前，而不是紧贴 `Overlay()`：这样更新兜底与自启
    # 自愈这两步也落在保护窗口内。失败放行 / dev 态跳过都在被调函数里（D3.2），这里不判返回值。
    hold_exe_delete_guard(log=log)
    process_pending_update(log=log)
    migrate_autostart(log=log)
    log("startup %s v%s (pid %s)" % (APP_NAME, VERSION, os.getpid()))
    # C-38 启动自证（唯一正本样例，CONFORMANCE §4.1.38）：把**解析后**的数据根 / 配置路径
    # 写进产物自带的日志（不是默认字面量、不是别名）。下一次 %TEMP% 残留归属不明时，
    # 只有这两行能把实例钉到具体的数据根与配置文件。
    log("data root: %s" % USER_DATA_DIR)
    log("config   : %s" % CONFIG_PATH)
    overlay = Overlay()
    ctrl = Controller(overlay, None)
    tray = Tray(ctrl)
    ctrl.tray = tray
    ctrl.notify = tray.notify
    ctrl.on_state_change = tray.set_recording

    tray.start()
    tray.set_title(i18n.t("tray_loading") % APP_NAME)
    tray.notify(i18n.t("notify_loading"))

    # 上次自动更新失败？托盘已退出、失败只能下次启动说（读一次即删）。
    failed_note = pop_failed_update_note(log=log)
    if failed_note:
        tray.notify(failed_note, APP_NAME)

    # --quit 请求文件监视（tray_kit 三循环之③）：走与托盘退出同一条清理路径。
    # 纪律（F11）：请求文件落在数据区，必须随 <APP>_DATA_DIR 重定向。
    quit_stop = threading.Event()
    threading.Thread(
        target=tray_kit.quit_watch_loop,
        args=(quit_stop, tray_kit.make_quit_request_path(USER_DATA_DIR),
              lambda: ctrl.ui_q.put(("exit",))),
        kwargs={"log": log},
        daemon=True,
    ).start()

    try:
        engine = AsrEngine()
    except Exception as e:
        dprint("model load failed:", e)
        log("model load failed: %s" % e)
        tray.set_title(i18n.t("tray_load_failed") % APP_NAME)
        tray.notify(i18n.t("notify_load_failed"))
    else:
        ctrl.engine = engine
        ctrl.hook_started = ctrl.hook.start()
        tray.set_title(i18n.t("tray_ready") % (APP_NAME, engine.model_type))
        tray.notify(i18n.t("notify_ready") % engine.model_type)
        log("model ready: %s" % engine.model_type)

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
        log("exit")
        quit_stop.set()
        if ctrl.update_cmd_path and ctrl.quit_apply_update:
            # 无控制台、脱离父进程地拉起替换脚本（旧 os.system('start /min') 会闪黑框）
            if not launch_pending_cmd(ctrl.update_cmd_path, log=log):
                # 拉不起来不能无声退出：pending 还在，下次启动会重试（update.pending.json），
                # 但用户此刻应当知道"这次更新没装上"。
                log("pending update NOT launched; next start will retry")
                try:
                    tray.notify(i18n.t("update_launch_failed"), APP_NAME)
                except Exception:
                    pass
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
        # D3.1：冒烟必须覆盖单实例守卫——用 tray_kit 探针（只验名字合法，不占锁、
        # 不弹窗），与运行期守卫共用同一份命名判据（2.2.0 的 mutex_name_ok）。
        if not tray_kit.mutex_name_is_valid(APP_ID, mutex_name=MUTEX_NAME):
            raise RuntimeError(i18n.t("smoke_mutex_invalid", MUTEX_NAME))
        load_config()
        # 现取：`load_config()` 刚把 `pipeline.MODEL_DIR` 更新过，校验值 / 引擎实际加载值 /
        # 打印值必须是**同一个** —— 旧写法三处各读一次快照，可以互不相同（#47 的裂缝）
        if not os.path.isdir(pipeline.MODEL_DIR):
            raise RuntimeError(i18n.t("smoke_model_dir_missing", pipeline.MODEL_DIR))
        engine = AsrEngine()
        del engine
        msg = "OK model_dir=" + pipeline.MODEL_DIR
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


def request_quit():
    """`--quit`：给运行中的实例留一个退出请求文件（T7 quit_watch_loop 消费）。

    程序化退出路径**不经二次确认框**（EXIT-03）；请求文件在数据区，
    随 <APP>_DATA_DIR 重定向，绝不会误伤用户常驻实例（F11）。
    """
    path = tray_kit.make_quit_request_path(USER_DATA_DIR)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("quit", encoding="utf-8")
        return 0
    except OSError as exc:
        dprint("quit request failed:", exc)
        return 1


if __name__ == "__main__":
    if "--smoke" in sys.argv:
        sys.exit(smoke())
    elif "--quit" in sys.argv:
        sys.exit(request_quit())
    elif len(sys.argv) > 1 and sys.argv[1] == "--autotest":
        autotest(sys.argv[2])
    else:
        sys.exit(main())
