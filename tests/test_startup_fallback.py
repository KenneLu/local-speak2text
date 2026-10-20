# -*- coding: utf-8 -*-
"""启动兜底（1.4.7）：重复启动静默 + 托盘/窗口失败可读化 + 日志链 fail-open。

全部用替身：不启 Tk 窗口、不启托盘、不加载模型、不弹真 MessageBox、不碰用户 AppData。

四段，各自钉住一个用户可见缺陷：

  A 重复启动不再弹模态框
      `main()` 在单实例守卫拒绝时只写用户数据根 `show.request` 并**静默 return 0**；
      不构造 Overlay/Tray，不调 `warn_duplicate_instance`（旧实现的模态 MessageBox——
      用户把它当"报错"）。写请求失败也只落日志，不拦退出。

  B 常驻实例消费请求 → 托盘气泡
      `consume_show_request()` 删文件并 `notify`「已在运行」；`show_watch_loop()` 1 秒拍
      自动消费；没有托盘（`_TRAY_ICON is None`）或 notify 自己失败时都不抛。
      `--quit` 优先级：quit.request 由模板 quit_watch_loop 独立处理，show 循环不碰它
      （两文件/两路径），这里用"两个请求同时存在时 show 只消费自己的"来钉。
      启动时还会清掉上一轮残留的 show.request（已持锁 ⇒ 旧请求不可能属于活实例）。

  C 托盘/窗口创建失败 → 可读提示 + 崩溃日志 + 退出码 2
      * 同步失败（`Tray()` 抛 PermissionError）；
      * 异步失败（pystray `run_detached` 内部线程失败，只能由"就绪事件超时"观测到；
        详情从 threading.excepthook 记下的最近一次崩溃取）；
      * Tk 浮窗（Overlay）失败走同一条可读化路径；
      * 无头入口（`--smoke` 等）不弹窗；MessageBoxW 自身失败也不抛；
      * `main_entry()` 把其余启动期异常也转成 rc=2（不再甩英文 traceback）。

  D 日志链 fail-open（复核项）
      * `_log_handle()` 惰性初始化失败后缓退化闭包：`log()` / `open_log_dir()` 永不抛，
        且**只重试一次**（不是每次 log 都去撞注定失败的 mkdir）；
      * `crash_log()` 宽捕异常 + 三级落点（用户数据区 → 程序目录 → %TEMP%）；
      * `--smoke` 结果文件写不出时不再抛（旧实现 except 里的裸 open 会把冒烟结论变成
        解释器错误），成功/失败退出码照旧；
      * threading.excepthook 把未捕获异常记进 _LAST_CRASH 与 crash.log。
"""
import io
import os
import sys
import threading
import time
import types
from pathlib import Path

from _cleanup import rmtree_cleanup, scratch_dir  # noqa: E402  （同目录助手：隔离临时目录 + 删前放句柄）

# 实例隔离：必须在 import main 之前重定向数据根与配置，否则日志/请求文件会写进
# 用户真实的 %LOCALAPPDATA%\local-speak2text\（常驻实例的数据区）。
_TMP = scratch_dir("l-s2t-startfallback-")
os.environ["LOCAL_SPEAK2TEXT_DATA_DIR"] = _TMP
os.environ["LOCAL_SPEAK2TEXT_CONFIG"] = str(Path(_TMP) / "config.json")
# 测试不得打开真实资源管理器：open_log_dir() 会对临时目录 os.startfile，
# 临时目录清理后 Windows 会弹「位置不可用」错误框（2026-10-20 实测）。
os.startfile = lambda *a, **k: None  # type: ignore[assignment]

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import main as M  # noqa: E402
from template import i18n  # noqa: E402
from template.paths import LOG_PATH  # noqa: E402

# CI runner 的 Windows UI 语言是英文：main() 会按配置重新 init 语言（auto -> en），
# 而本测试断言中文可读文案/气泡。把「从配置读语言」钉成 zh；D5 里显式 init(en)
# 的本地化校验不经过 main()，不受影响。
i18n.init("zh")
i18n.load_language_from_config = lambda _cfg: "zh"

FAILS = []


def check(name, ok, detail=""):
    print(("  ok  " if ok else "  FAIL") + " " + name + ("  " + str(detail) if detail else ""),
          flush=True)
    if not ok:
        FAILS.append(name)


def _read(path):
    try:
        return Path(path).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def _wait_for(predicate, timeout=3.0, step=0.02):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return True
        time.sleep(step)
    return predicate()


# 保存现场：每个替身/重定向都在 finally 里还原，避免污染同进程后续用例。
_SAVED = {
    "acquire": M.tray_kit.acquire_single_instance,
    "warn_dup": M.tray_kit.warn_duplicate_instance,
    "overlay": M.Overlay,
    "tray": M.Tray,
    "icon": M._TRAY_ICON,
    "show_path": M.SHOW_REQUEST_PATH,
    "msgbox": M._message_box,
    "show_failure": M._show_startup_failure,
    "hold_guard": M.hold_exe_delete_guard,
    "sweep": M.sweep_stale_update_dirs,
    "migrate": M.migrate_autostart,
    "engine": M.AsrEngine,
    "hooks": M._install_excepthooks,
    "tray_timeout": M.TRAY_READY_TIMEOUT,
    "log_handle": M._LOG_HANDLE,
    "log_init_error": M._LOG_INIT_ERROR,
    "last_crash": dict(M._LAST_CRASH),
    "user_data_dir": M.USER_DATA_DIR,
    "run_dir": M.RUN_DIR,
    "smoke_path": M._smoke_log_path,
    "load_config": M.load_config,
    "mutex_probe": M.tray_kit.mutex_name_is_valid,
    "main": M.main,
    "pipeline_model_dir": M.pipeline.MODEL_DIR,
    "sys_excepthook": sys.excepthook,
    "thread_excepthook": threading.excepthook,
    "argv": list(sys.argv),
}
MSG_BOX = []
NEVER_CREATED = []


class _FakeOverlay:
    def __init__(self):
        self.root = types.SimpleNamespace(after=lambda *a, **k: None,
                                          mainloop=lambda: None,
                                          destroy=lambda: None)


class _FakeTray:
    """常驻侧替身：只有 notify 需要可观察，其余动作都是 no-op。"""

    def __init__(self, notes=None):
        self.notes = [] if notes is None else notes

    def start(self):
        pass

    def stop(self):
        pass

    def set_title(self, *_a):
        pass

    def notify(self, message, title=None):
        self.notes.append((message, title))

    def rebuild(self):
        pass

    def set_recording(self, *_a):
        pass


def _record_msgbox(text, title=None):
    MSG_BOX.append((text, title))
    return True


def _stub_quiet_startup():
    """main() 里与本次断言无关的重资源/落盘动作全部打桩。"""
    M.Overlay = _FakeOverlay
    M.Tray = _FakeTray
    M.hold_exe_delete_guard = lambda **_k: True
    M.sweep_stale_update_dirs = lambda *a, **k: 0
    M.migrate_autostart = lambda **_k: None
    M.AsrEngine = lambda *a, **k: types.SimpleNamespace(model_type="stub")
    M._install_excepthooks = lambda: None


try:
    i18n.init("zh")
    M.SHOW_REQUEST_PATH = Path(_TMP) / "data" / "show.request"

    # ================= A. 重复启动：写 show.request + 静默 rc=0，不弹模态框 =================
    print("\n[A] duplicate launch is silent", flush=True)
    modal_calls = []
    M.tray_kit.acquire_single_instance = lambda *_a, **_k: False
    M.tray_kit.warn_duplicate_instance = lambda *_a, **_k: modal_calls.append("modal")
    M._TRAY_ICON = _FakeTray()

    class _NeverOverlay:
        def __init__(self):
            NEVER_CREATED.append("overlay")
            raise AssertionError("duplicate launch must not create the overlay")

    class _NeverTray:
        def __init__(self, ctrl):
            NEVER_CREATED.append("tray")
            raise AssertionError("duplicate launch must not create the tray")

    M.Overlay = _NeverOverlay
    M.Tray = _NeverTray
    rc = M.main()
    check("A second instance returns 0 (silent hand-off)", rc == 0, "rc=%r" % (rc,))
    check("A second instance writes show.request", M.SHOW_REQUEST_PATH.is_file(),
          M.SHOW_REQUEST_PATH)
    check("A no modal dialog is shown (old behaviour removed)",
          not modal_calls and not MSG_BOX, "modal=%r msgbox=%r" % (modal_calls, MSG_BOX))
    check("A no window/tray is created by the duplicate launch",
          not NEVER_CREATED, NEVER_CREATED)

    # A2：请求文件写不进去也只落日志——不许把"已经有一个实例在跑"变成崩溃。
    _blocker = Path(_TMP) / "blocker-file"
    _blocker.write_text("x", encoding="utf-8")
    M.SHOW_REQUEST_PATH = _blocker / "show.request"
    try:
        rc = M.main()
        check("A unwritable show.request still exits 0 (never raises)", rc == 0, "rc=%r" % (rc,))
    except Exception as exc:  # noqa: BLE001 - 本条断言本身就是"不许抛"
        check("A unwritable show.request still exits 0 (never raises)", False, repr(exc))
    finally:
        M.SHOW_REQUEST_PATH = Path(_TMP) / "data" / "show.request"
        _blocker.unlink()

    # ================= B. 常驻侧消费 → 托盘气泡 =================
    print("\n[B] resident consumes show.request -> tray balloon", flush=True)
    if M.SHOW_REQUEST_PATH.exists():       # A 段留下的请求不算"没有请求"
        M.SHOW_REQUEST_PATH.unlink()
    fake_tray = _FakeTray()
    M._TRAY_ICON = fake_tray
    check("B no request -> consume returns False", M.consume_show_request() is False)
    M.SHOW_REQUEST_PATH.parent.mkdir(parents=True, exist_ok=True)
    M.SHOW_REQUEST_PATH.write_text("request\n", encoding="utf-8")
    consumed = M.consume_show_request()
    check("B consume returns True", consumed is True, consumed)
    check("B show.request is deleted after consumption", not M.SHOW_REQUEST_PATH.exists())
    check("B tray balloon says 'already running'",
          bool(fake_tray.notes) and "已在运行" in fake_tray.notes[0][0], fake_tray.notes)
    check("B balloon is posted in the configured language (zh)",
          bool(fake_tray.notes) and i18n.current_lang() == "zh" and "已在运行" in i18n.t(
              "notify_already_running", M.APP_NAME), fake_tray.notes)

    # B2：1 秒拍循环自动消费（真实线程，短节拍）。
    fake_tray.notes.clear()
    M.SHOW_REQUEST_PATH.write_text("request\n", encoding="utf-8")
    stop = threading.Event()
    watcher = threading.Thread(target=M.show_watch_loop, args=(stop,), kwargs={"beat": 0.05})
    watcher.start()
    try:
        got = _wait_for(lambda: bool(fake_tray.notes) and not M.SHOW_REQUEST_PATH.exists())
    finally:
        stop.set()
        watcher.join(1.0)
    check("B watch loop consumes the request without anyone calling consume()", got,
          fake_tray.notes)
    check("B watch loop thread stops on its stop event", not watcher.is_alive())

    # B3：quit.request 与 show.request 同时存在 → show 循环只消费自己的（--quit 优先级不受影响）。
    quit_path = M.tray_kit.make_quit_request_path(M.USER_DATA_DIR)
    quit_path.parent.mkdir(parents=True, exist_ok=True)
    quit_path.write_text("quit", encoding="utf-8")
    M.SHOW_REQUEST_PATH.write_text("request\n", encoding="utf-8")
    fake_tray.notes.clear()
    stop2 = threading.Event()
    watcher2 = threading.Thread(target=M.show_watch_loop, args=(stop2,), kwargs={"beat": 0.05})
    watcher2.start()
    try:
        got = _wait_for(lambda: bool(fake_tray.notes))
    finally:
        stop2.set()
        watcher2.join(1.0)
    check("B show request is consumed while a quit request is pending", got, fake_tray.notes)
    check("B the quit request file is NOT touched by the show loop (quit stays authoritative)",
          quit_path.is_file(), str(quit_path))
    quit_path.unlink()

    # B4：没有托盘 / notify 自己失败 → 消费结果仍为 True，且不抛。
    M._TRAY_ICON = None
    M.SHOW_REQUEST_PATH.write_text("request\n", encoding="utf-8")
    try:
        check("B consuming without a tray icon is still a successful consume",
              M.consume_show_request() is True)
    except Exception as exc:  # noqa: BLE001
        check("B consuming without a tray icon is still a successful consume", False, repr(exc))

    class _BoomNotifyTray:
        def notify(self, *_a, **_k):
            raise RuntimeError("simulated: balloon failed")

    M._TRAY_ICON = _BoomNotifyTray()
    M.SHOW_REQUEST_PATH.write_text("request\n", encoding="utf-8")
    try:
        check("B a failing balloon does not break consumption",
              M.consume_show_request() is True)
    except Exception as exc:  # noqa: BLE001
        check("B a failing balloon does not break consumption", False, repr(exc))

    # B5：启动时清残留请求（上一轮在 1 秒拍消费前就退出的场景），否则下次启动会弹
    # 一个误导性的"已在运行"气泡。
    M.SHOW_REQUEST_PATH.write_text("stale\n", encoding="utf-8")
    M.clear_stale_show_request()
    check("B startup clears a stale show.request", not M.SHOW_REQUEST_PATH.exists())
    try:
        M.clear_stale_show_request()   # 没有文件时也必须静默
        check("B clearing when there is nothing to clear does not raise", True)
    except Exception as exc:  # noqa: BLE001
        check("B clearing when there is nothing to clear does not raise", False, repr(exc))

    # ================= C. 托盘/窗口失败 → 可读提示 + 崩溃日志 + 退出码 2 =================
    print("\n[C] tray/window startup failure is readable", flush=True)
    # 可读化文案同时也会 print 到 stderr（那是给人看的兜底出口）；这里收进证据桶，
    # 既证明"确实写到了 stderr"，又不把整个 build 日志刷屏。
    _real_stderr, sys.stderr = sys.stderr, io.StringIO()
    M.tray_kit.acquire_single_instance = lambda *_a, **_k: True   # C 段要走进"启动"分支
    M.tray_kit.warn_duplicate_instance = _SAVED["warn_dup"]
    M._message_box = _record_msgbox
    _stub_quiet_startup()
    M.Overlay = _FakeOverlay
    M._TRAY_ICON = None
    crash_path = M._crash_log_paths()[0]
    if crash_path.exists():
        crash_path.unlink()

    # C1：同步失败（构造托盘时 PermissionError —— 受限终端/沙箱的实测形态）。
    class _AccessDeniedTray:
        def __init__(self, ctrl):
            raise PermissionError(5, "Access is denied", "ChangeWindowMessageFilterEx")

    MSG_BOX.clear()
    M.Tray = _AccessDeniedTray
    rc = M.main()
    text = MSG_BOX[0][0] if MSG_BOX else ""
    check("C1 tray PermissionError -> exit code 2", rc == 2, "rc=%r" % (rc,))
    check("C1 exactly one readable dialog is shown", len(MSG_BOX) == 1,
          "dialogs=%d" % len(MSG_BOX))
    check("C1 headline says the tray could not be created", "托盘" in text,
          "hit=%s" % ("托盘" in text))
    check("C1 gives an actionable hint (start from Explorer / restart Explorer)",
          "资源管理器" in text and "重启" in text,
          "explorer_hint=%s restart_hint=%s" % ("资源管理器" in text, "重启" in text))
    check("C1 includes the technical detail for the maintainer",
          "PermissionError" in text and "ChangeWindowMessageFilterEx" in text,
          "traceback_tail=%s" % (text[-60:].replace("\n", " ") if text else ""))
    check("C1 best-effort crash log is written",
          crash_path.is_file() and "托盘" in _read(crash_path), str(crash_path))
    check("C1 failure is also logged", "tray startup failed" in _read(LOG_PATH), str(LOG_PATH))

    # C2：异步失败（pystray run_detached 内部线程抛异常，只能观测到"就绪超时"）。
    # 详情来自 threading.excepthook 的最近一次崩溃记录。
    class _SilentFailTray(_FakeTray):
        def wait_ready(self, timeout):
            return False

    MSG_BOX.clear()
    M._LAST_CRASH["text"] = (
        "thread Thread-7: [WinError 5] Access is denied\n"
        "Traceback (most recent call last):\n"
        "PermissionError: [WinError 5] Access is denied")
    M.Tray = _SilentFailTray
    rc = M.main()
    text = MSG_BOX[0][0] if MSG_BOX else ""
    check("C2 tray thread failure (readiness timeout) -> exit code 2", rc == 2, "rc=%r" % (rc,))
    check("C2 dialog carries the captured thread failure detail",
          "WinError 5" in text, "winerror5=%s" % ("WinError 5" in text))

    # C3：Tk 浮窗创建失败（Overlay 抛 PermissionError）→ 同一条可读化路径。
    class _BoomOverlay:
        def __init__(self):
            raise PermissionError(5, "Access is denied", "Tk")

    MSG_BOX.clear()
    M.Overlay = _BoomOverlay
    M.Tray = _FakeTray
    rc = M.main()
    text = MSG_BOX[0][0] if MSG_BOX else ""
    check("C3 window (Tk) failure -> exit code 2", rc == 2, "rc=%r" % (rc,))
    check("C3 headline is about the window, not the tray", "窗口" in text,
          "window_headline=%s" % ("窗口" in text))
    check("C3 gives the same actionable hints", "资源管理器" in text,
          "explorer_hint=%s" % ("资源管理器" in text))

    # C4：无头入口不弹窗（构建/CI 里弹窗会把流水线挂住）。
    MSG_BOX.clear()
    sys.argv = ["local-speak2text.exe", "--smoke"]
    try:
        M._show_startup_failure("simulated headless failure")
    finally:
        sys.argv = list(_SAVED["argv"])
    check("C4 headless entry point never shows a MessageBox", not MSG_BOX, MSG_BOX)

    # C5：MessageBoxW 本身失败（没有桌面/没有 user32）不许反过来崩。
    real_ctypes = M.ctypes
    real_message_box = _SAVED["msgbox"]

    class _BoomUser32:
        @staticmethod
        def MessageBoxW(*_a):
            raise OSError("simulated: no desktop")

    class _BoomCtypes:
        windll = types.SimpleNamespace(user32=_BoomUser32())

    M.ctypes = _BoomCtypes
    try:
        check("C5 MessageBoxW failure returns False instead of raising",
              real_message_box("x") is False)
    finally:
        M.ctypes = real_ctypes

    def _boom_msgbox(*_a, **_k):
        raise RuntimeError("simulated: dialog layer broken")

    M._message_box = _boom_msgbox
    try:
        M._show_startup_failure("simulated: dialog layer broken")
        check("C5 _show_startup_failure never raises when the dialog layer fails", True)
    except Exception as exc:  # noqa: BLE001
        check("C5 _show_startup_failure never raises when the dialog layer fails", False,
              repr(exc))
    finally:
        M._message_box = _record_msgbox
    MSG_BOX.clear()

    # C6：main_entry 把其余启动期异常也转成可读提示 + rc=2（不甩英文 traceback）。
    def _boom_main():
        raise RuntimeError("simulated: unexpected startup error")

    M.main = _boom_main
    M._show_startup_failure = _record_msgbox
    rc = M.main_entry()
    text = MSG_BOX[0][0] if MSG_BOX else ""
    check("C6 main_entry converts an unexpected startup error into exit code 2",
          rc == 2, "rc=%r" % (rc,))
    check("C6 main_entry shows the generic startup headline",
          "启动失败" in text and "RuntimeError" in text,
          "headline=%s runtime_error=%s" % ("启动失败" in text, "RuntimeError" in text))

    _captured_stderr = sys.stderr.getvalue()
    sys.stderr = _real_stderr
    check("C the readable failure text also goes to stderr (visible even headless)",
          "无法创建系统托盘图标" in _captured_stderr and len(_captured_stderr) > 500,
          "captured %d bytes" % len(_captured_stderr))

    # ================= D. 日志链 fail-open（复核项） =================
    print("\n[D] log chain is fail-open", flush=True)
    M._install_excepthooks = _SAVED["hooks"]

    # D1：惰性初始化失败 → log()/open_log_dir() 不抛，且只重试一次。
    calls = []

    def _boom_make_logger(_log_dir):
        calls.append(1)
        raise PermissionError(13, "Access is denied", str(_log_dir))

    real_make_logger = M.log_kit.make_logger
    M.log_kit.make_logger = _boom_make_logger
    M._LOG_HANDLE = None
    M._LOG_INIT_ERROR = None
    try:
        try:
            M.log("first", 1)
            M.log("second", 2)
            M.open_log_dir()
            check("D1 log()/open_log_dir() never raise when lazy init fails", True)
        except Exception as exc:  # noqa: BLE001
            check("D1 log()/open_log_dir() never raise when lazy init fails", False, repr(exc))
        check("D1 lazy init is attempted only once (failure is cached, not retried)",
              len(calls) == 1, "make_logger calls=%d" % len(calls))
        check("D1 the init failure is recorded for the startup-failure text",
              isinstance(M._LOG_INIT_ERROR, PermissionError), repr(M._LOG_INIT_ERROR))
        check("D1 the startup-failure text mentions that logs are unwritable",
              "日志目录也不可写" in M._readable_failure_text("headline", "detail"))
    finally:
        M.log_kit.make_logger = real_make_logger
        M._LOG_HANDLE = _SAVED["log_handle"]
        M._LOG_INIT_ERROR = _SAVED["log_init_error"]

    # D2：crash_log 宽捕异常 + 三级落点（用户数据区不可写 → 程序目录）。
    class _UnwritableCrashPath:
        def mkdir(self, *_a, **_k):
            # 非 OSError：旧实现只吞 OSError，这里必须靠"宽捕 Exception"才过得去。
            raise RuntimeError("simulated: data dir is not writable")

    class _UnwritableDataDir:
        def __truediv__(self, _name):
            return _UnwritableCrashPath()

    fallback_run_dir = Path(_TMP) / "run-dir"
    M.USER_DATA_DIR = _UnwritableDataDir()
    M.RUN_DIR = fallback_run_dir
    try:
        written = M.crash_log("simulated crash payload")
        check("D2 crash_log falls back when the user data dir is unwritable",
              written == fallback_run_dir / "crash.log", written)
        check("D2 the fallback crash log really contains the payload",
              "simulated crash payload" in _read(fallback_run_dir / "crash.log"))
    finally:
        M.USER_DATA_DIR = _SAVED["user_data_dir"]
        M.RUN_DIR = _SAVED["run_dir"]

    # D3：--smoke 结果文件写不出时不抛，成功/失败退出码照旧。
    M.tray_kit.mutex_name_is_valid = lambda *_a, **_k: True
    M.load_config = lambda: None
    M.pipeline.MODEL_DIR = _TMP
    M.AsrEngine = lambda *a, **k: types.SimpleNamespace(model_type="stub")
    bad_path = str(Path(_TMP) / "no-such-dir" / "deeper" / "smoke.log")
    good_path = str(Path(_TMP) / "smoke-result.log")
    M._smoke_log_path = lambda: bad_path
    try:
        rc = M.smoke()
        check("D3 smoke() with an unwritable result file returns the success code, no raise",
              rc == 0, "rc=%r" % (rc,))
    except Exception as exc:  # noqa: BLE001
        check("D3 smoke() with an unwritable result file returns the success code, no raise",
              False, repr(exc))
    M._smoke_log_path = lambda: good_path
    rc = M.smoke()
    check("D3 smoke() writes its verdict when the path is writable",
          rc == 0 and _read(good_path).startswith("OK model_dir="), _read(good_path))
    M.tray_kit.mutex_name_is_valid = lambda *_a, **_k: False
    M._smoke_log_path = lambda: bad_path
    try:
        rc = M.smoke()
        check("D3 smoke() failure branch also survives an unwritable result file",
              rc == 1, "rc=%r" % (rc,))
    except Exception as exc:  # noqa: BLE001
        check("D3 smoke() failure branch also survives an unwritable result file",
              False, repr(exc))
    M.tray_kit.mutex_name_is_valid = _SAVED["mutex_probe"]
    M.load_config = _SAVED["load_config"]
    M._smoke_log_path = _SAVED["smoke_path"]
    M.pipeline.MODEL_DIR = _SAVED["pipeline_model_dir"]
    M.AsrEngine = _SAVED["engine"]

    # D4：threading.excepthook 记录最近一次崩溃（托盘线程异步失败的详情来源）并落盘。
    M._LAST_CRASH["kind"] = ""
    M._LAST_CRASH["text"] = ""
    M._install_excepthooks()
    try:
        threading.excepthook(types.SimpleNamespace(
            name="probe-thread",
            exc_value=PermissionError(5, "Access is denied", "ChangeWindowMessageFilterEx")))
    finally:
        sys.excepthook = _SAVED["sys_excepthook"]
        threading.excepthook = _SAVED["thread_excepthook"]
    check("D4 uncaught thread exception is captured for the failure dialog",
          "probe-thread" in M._LAST_CRASH["text"] and "PermissionError" in M._LAST_CRASH["text"],
          M._LAST_CRASH["text"][:200])
    check("D4 the last crash is also persisted to crash.log",
          "probe-thread" in _read(_SAVED["user_data_dir"] / "crash.log"),
          str(_SAVED["user_data_dir"] / "crash.log"))

    # D5：新增词条两种语言都齐全、英文不含中文（双语 i18n 回归）。
    keys = ("notify_already_running", "startup_failure_title", "tray_failed_headline",
            "window_failed_headline", "startup_failed_headline", "gui_failed_reason",
            "gui_failed_hint_explorer", "gui_failed_hint_restart", "failure_detail_hint",
            "log_dir_unwritable_note")
    i18n.init("zh")
    zh_text = {k: i18n.t(k) for k in keys}
    check("D5 every new key exists in the zh table",
          all(zh_text[k] != k for k in keys), [k for k in keys if zh_text[k] == k])
    i18n.init("en")
    en_text = {k: i18n.t(k) for k in keys}
    check("D5 every new key exists in the en table",
          all(en_text[k] != k for k in keys), [k for k in keys if en_text[k] == k])
    check("D5 en strings contain no Chinese characters",
          not any("\u4e00" <= ch <= "\u9fff" for v in en_text.values() for ch in v),
          {k: v for k, v in en_text.items() if any("\u4e00" <= ch <= "\u9fff" for ch in v)})
    i18n.init("zh")
    check("D5 the balloon text renders the app name through the %s placeholder",
          M.APP_NAME in i18n.t("notify_already_running", M.APP_NAME),
          i18n.t("notify_already_running", M.APP_NAME))
finally:
    M.tray_kit.acquire_single_instance = _SAVED["acquire"]
    M.tray_kit.warn_duplicate_instance = _SAVED["warn_dup"]
    M.Overlay = _SAVED["overlay"]
    M.Tray = _SAVED["tray"]
    M._TRAY_ICON = _SAVED["icon"]
    M.SHOW_REQUEST_PATH = _SAVED["show_path"]
    M._message_box = _SAVED["msgbox"]
    M._show_startup_failure = _SAVED["show_failure"]
    M.hold_exe_delete_guard = _SAVED["hold_guard"]
    M.sweep_stale_update_dirs = _SAVED["sweep"]
    M.migrate_autostart = _SAVED["migrate"]
    M.AsrEngine = _SAVED["engine"]
    M._install_excepthooks = _SAVED["hooks"]
    M.TRAY_READY_TIMEOUT = _SAVED["tray_timeout"]
    M._LOG_HANDLE = _SAVED["log_handle"]
    M._LOG_INIT_ERROR = _SAVED["log_init_error"]
    M._LAST_CRASH.clear()
    M._LAST_CRASH.update(_SAVED["last_crash"])
    M.USER_DATA_DIR = _SAVED["user_data_dir"]
    M.RUN_DIR = _SAVED["run_dir"]
    M._smoke_log_path = _SAVED["smoke_path"]
    M.load_config = _SAVED["load_config"]
    M.tray_kit.mutex_name_is_valid = _SAVED["mutex_probe"]
    M.main = _SAVED["main"]
    M.pipeline.MODEL_DIR = _SAVED["pipeline_model_dir"]
    sys.excepthook = _SAVED["sys_excepthook"]
    threading.excepthook = _SAVED["thread_excepthook"]
    sys.argv = list(_SAVED["argv"])
    try:
        sys.stderr = _real_stderr    # C 段中途抛异常时也要把 stderr 还回去
    except NameError:
        pass

check("temp dir cleaned up (no %TEMP% leak)", rmtree_cleanup(_TMP), str(_TMP))
print("STARTUP FALLBACK TEST " + ("FAILED: " + ",".join(FAILS) if FAILS else "OK"), flush=True)
sys.exit(1 if FAILS else 0)
