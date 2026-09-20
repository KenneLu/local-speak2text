# -*- coding: utf-8 -*-
"""更新链安全语义的真实执行回归（模板 `modules/update_helper` 版）。

本文件随 **B5**（fork `src/updater.py` → 模板 `modules/update_helper/`，施工单
`UPDATER-SWAP-ls2t.md`）整体改写：断言对象从自家 fork 换成**模板件**，并补上施工单
§5 要求"切前必补"的四项验证：

  ① **两条 `start` 路径的存在性守卫回归**（模板 L237/L253 各处 start 各自验）；
  ② **`sweep_stale_update_dirs` 两类都清**（暂存目录 + `*-update.bat` 文件），带对照样本；
  ③ **F11 实例隔离**：`sweep` 会 glob `%TEMP%`，本测试把 `tempfile.tempdir` 钉到
     隔离目录，**绝不扫用户真实临时目录**（先自证隔离，再断言）；
  ④ **C-27 MUST-WIRE 三符号**在 `main.py` 真有引用（dsh/ocx 踩过"拷到位零引用"）。

保留的安全断言（语义与模板 README「替换脚本的语义要点」逐条对应）：
  A. sha256 期望值缺失 / 不匹配 → 失败（fail-closed）；
  B. 真跑替换脚本：成功铺新版且轮转备份；失败注入（rc>=8）回铺后启动旧版；
     回铺也失败（`:install_dead`）**什么都不启动**；空暂存包（`:stage_invalid`）
     **不碰安装目录、把旧版拉回来**（模板 1.4.2 起的行为，fork 没有）。
     ⚠️ 判定口径（2026-09-20 对齐 reme）：**决策**（走了哪个分支、安装目录有没有被动）
     用日志行 + 目录内容这些**确定性**证据断言；**"进程有没有被真的拉起来"**是异步副作用，
     按 `_observe_started` 只记录不判定——连续跑门禁时 `start` 被拒建进程是实测过的；
  D. `launch_pending_cmd`：CREATE_NO_WINDOW | DETACHED_PROCESS，list argv；
  E. 渲染文本的结构面：每处 `start` 各自带存在性守卫 + 每标签块 start 数 = 设计值；
  F. 单元级控制：把真跑中走不到的分支（超时红灯、只读自证兜底）跑一遍；
  G. sweep 两类都清 + 隔离 + 对照样本；
  H. 接线（C-27）。

隔离：数据根用 `LOCAL_SPEAK2TEXT_DATA_DIR` 重定向；替换脚本用 GUI 子系统 `.vbs`
当假 exe（R1「替身必须存在」——目标恒存在，判"是否被启动"只看副作用 marker）。
"""
import os
import re
import shutil
import subprocess
import stat
import sys
import tempfile
import time
from pathlib import Path

from _cleanup import clear_readonly, rmtree_cleanup, scratch_dir  # noqa: E402  （同目录助手）

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

# 实例隔离：必须在 import modules.update_helper（它会 import modules.paths）之前重定向数据根。
_TMP_DATA = scratch_dir("l-s2t-upd-")
os.environ["LOCAL_SPEAK2TEXT_DATA_DIR"] = _TMP_DATA

# F11（施工单 §5 第 3 项）：sweep_stale_update_dirs 会 glob `%TEMP%`。测试必须用**隔离的
# `%TEMP%`**，否则它会去扫用户真实临时目录（可能删掉别的工具/本工具在跑的更新残留）。
# `tempfile.tempdir` 显式钉死 + TEMP/TMP 环境变量一并改（对子进程也生效）。
_TMP_TEMP = scratch_dir("l-s2t-upd-temp-")
os.environ["TEMP"] = _TMP_TEMP
os.environ["TMP"] = _TMP_TEMP
tempfile.tempdir = _TMP_TEMP

from modules import update_helper as U  # noqa: E402
from modules.appconfig import APP_ID  # noqa: E402

FAILS = []
_CLEANED = []


def _clean(root):
    """删测试临时根；结果留到末尾统一断言（删不掉必须变红，见 tests/_cleanup.py）。"""
    _CLEANED.append((str(root), rmtree_cleanup(root)))


CREATE_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def check(name, ok, detail=""):
    print(("  ok  " if ok else "  FAIL") + " " + name + ("  " + detail if detail else ""),
          flush=True)
    if not ok:
        FAILS.append(name)


def _wait_for(path, seconds=30.0):
    # 30s: `start "" file.vbs` goes through the shell association to wscript.exe;
    # that first launch can take seconds under load (e.g. during a build). The
    # negative assertions pass a short timeout explicitly.
    deadline = time.time() + seconds
    while time.time() < deadline:
        if path.exists():
            return True
        time.sleep(0.2)
    return False


def _probe_vbs(marker, note=""):
    """假 exe：被 start 时在自身目录写一个 marker（GUI 子系统，不弹控制台）。

    为什么是 `.vbs` 而不是 `.bat`：更新器用 `start "" <exe>` 拉起它，而 start 一个 `.bat`
    会在用户桌面上闪一个控制台窗口——门禁跑在用户的机器上，那正属于本家族反复在治的
    "构建动作干扰用户桌面"一类。`wscript` 跑 `.vbs` 完全不建控制台，而真实产品起的是
    `--noconsole` 的 GUI exe，"什么都不显示"这一点上替身是faithful的。

    `note` **不是装饰**：robocopy 认为"大小 + 时间戳都相同"的目标文件就是同一个文件，
    会**直接跳过、不比对内容**。本文件的两份 probe 脚本曾经只差 `started-old.txt` /
    `started-new.txt`（**等长**），又是同一次时钟 tick 内写下的——于是铺新版时 robocopy
    会把它跳过，`install` 里留下旧的那份、"新版本被启动"随机变红。
    这条**不是推测**：`reme-helper/tests/test_update_bat.py` 已实测为"大约三次里一次"，
    并把 note 加长作为修法（2026-09-20 对齐全家族口径时移植过来）。
    """
    body = ('Set fso = CreateObject("Scripting.FileSystemObject")\r\n'
            'Set f = fso.CreateTextFile(fso.GetParentFolderName(WScript.ScriptFullName) '
            '& "\\%s")\r\n'
            'f.WriteLine "x"\r\n') % marker
    return ("' %s\r\n%s" % (note, body)) if note else body


def _observe_started(marker, what):
    """**观察（不作为判据）**被 `start` 拉起的进程是否写下了 marker。

    口径来自 reme-helper 同一套门禁的裁定（已实测、已落地，2026-09-20 对齐到本仓）：
    `start ""` 是异步的，且连续跑门禁时 **Windows 可能拒绝新建进程/控制台**（桌面堆压力；
    reme 实测用 `.bat` 当假 exe 时是"约三次里一次"）。把这种"进程有没有被创建"当成判据，
    换来的是一条约三次红一次的门禁——而它**并不反映产品语义**。

    所以本文件改为：**启动决策**用确定性证据断言（install 目录里的文件内容 + 日志分支行），
    **守卫本身**用静态检查断言（E 段的"每处 start 各自带存在性守卫"），marker 只记录。
    这与 CI run 35488810525 的实测一致：那里 `start` 的 marker 没出现，而**同一份字节在
    本机 5/5 全绿**。
    """
    if _wait_for(marker, 5.0):
        print("  ok   observed: %s wrote its marker" % what, flush=True)
    else:
        print("  ..   observation skipped: %s marker absent (start may be refused under "
              "repeated runs; the deterministic checks above are the verdict)" % what,
              flush=True)


# ==================== A. sha256 fail-closed ====================
_payload = Path(_TMP_DATA) / "payload.bin"
_payload.write_bytes(b"hello-update")
_good = U._sha256(_payload)
check("sha256: missing expected value fails closed",
      U.verify_zip_sha256(_payload, "")[0] is False)
check("sha256: whitespace-only expected value fails closed",
      U.verify_zip_sha256(_payload, "   \n")[0] is False)
check("sha256: mismatch fails", U.verify_zip_sha256(_payload, "deadbeef")[0] is False)
check("sha256: match passes", U.verify_zip_sha256(_payload, _good)[0] is True)
check("sha256: real '<hash>  <name>' line passes",
      U.verify_zip_sha256(_payload, "%s  payload.bin" % _good)[0] is True)


# ==================== B. 替换脚本真跑（模板 bat） ====================
# R1（2026-09-19 lead 裁定，全家族硬性）：**替身必须永远存在**。
# `start "" "<不存在的目标>"` 会弹模态框——`.exe` 是"找不到文件"，`.vbs` 是
# Windows Script Host 的"无法找到脚本文件"，两者都会把无 console 的 detached 脚本
# 永久挂死，并在用户桌面上留一个点不掉的窗口（当天真实事故：桌面 15 个模态框）。
# 因此本文件**不再用"目标不存在"构造任何场景**：install 永远有 probe.vbs，
# "有没有被启动"一律看**副作用**（marker 文件是否被写）。
def _stage(root, stage_missing=False, stage_empty=False, bad_snapshot=False,
           lock_staged=False):
    install = root / "install"
    stage = root / "stage"
    work = root / "work"
    snapshot = root / "_backup.pre"
    backup = root / "_backup"
    # 重置：**每个**上一场景可能留下的目录都要先解只读再删——只读位会被 robocopy
    # 复制进快照/备份目录（实测），漏掉一处就会让下一场景的 rmtree 静默失败、
    # 进而写文件时报 PermissionError。
    for d in (install, stage, work, snapshot, backup):
        if d.exists():
            clear_readonly(d)
            if d.is_dir():
                shutil.rmtree(d, ignore_errors=True)
            else:
                try:
                    d.unlink()
                except OSError:
                    pass
    # 现场证据（marker + 日志 + 轮询文件）**每个场景都清空**。不清的话后面几个场景的
    # "marker 写了 / 日志记了"会**继承前一场景的产物**而变成假绿——2026-09-20 实测：
    # CI 上 `bat empty-stage: failure marker written` 就是靠 `_bat_failure` 留下的
    # marker 变绿的；而"日志末行是哪一行"也失去判别力（日志是 `>>` 累加的）。
    for f in (root / "update.failed", root / "update.log", root / "update.log.poll"):
        try:
            f.unlink()
        except OSError:
            pass
    for d in (install, stage, work):
        d.mkdir(parents=True)
    # R1：目标目录的替身**恒存在**——任何分支上的 `start` 都只会命中真实文件。
    (install / "probe.vbs").write_text(_probe_vbs("started-old.txt", note="old"),
                                       encoding="ascii")
    # 只读保险（lead 令，2026-09-19）：`del <file>` / `os.unlink` / Python `rmtree`
    # 都删不掉它，于是没有哪一步能把它弄丢、让后面的 `start` 指向空气。
    # ⚠️ 只读是部分保险，不是结构保证（`rmdir /s /q <父目录>` 与 `robocopy /e /purge`
    # 都能绕过它）。定位：多一层兜底，**不能替代** R1 + 三处 start 守卫 + R4 超时变红。
    os.chmod(install / "probe.vbs", stat.S_IREAD)
    (install / "data-old.txt").write_text("old", encoding="utf-8")
    if not stage_missing and not stage_empty:
        # note **故意比 old 那份长**：两份 probe 必须**大小不同**，否则 robocopy 会因
        # "大小 + 时间戳相同"把新版脚本当成同一个文件跳过（见 `_probe_vbs`）。
        (stage / "probe.vbs").write_text(
            _probe_vbs("started-new.txt", note="new version, longer than the old note"),
            encoding="ascii")
        (stage / "data-new.txt").write_text("new", encoding="utf-8")
    if lock_staged:
        (stage / "locked.bin").write_bytes(b"x")
    if bad_snapshot:
        # 让"快照"步骤失败：SNAPSHOT 路径上先放一个**文件**。实测 `rmdir /s /q`
        # 对它报"目录名无效"、`robocopy SNAPSHOT TARGET` 返回 rc=16，于是
        # :install_failed 的**回铺也失败** → 走到 :install_dead（且 TARGET 仍有 exe）。
        snapshot.write_text("not a directory", encoding="ascii")
    return {
        "install": install,
        "stage": stage if not stage_missing else (root / "no-such-stage"),
        "work": work,
        "backup": root / "_backup",
        "snapshot": snapshot,
        "failed": root / "update.failed",
        "log": root / "update.log",
    }


def _kill_stray_wscript(root):
    """只杀**命令行里引用本次 root** 的 wscript/cscript：模态框的来源。

    绝不按映像名通杀——用户可能正在跑自己的 .vbs 脚本（误伤用户进程是不可接受的）。
    """
    try:
        ps = ("(Get-CimInstance Win32_Process -Filter \"Name='wscript.exe' or Name='cscript.exe'\")"
              " | Where-Object { $_.CommandLine -like '*%s*' } | ForEach-Object { $_.ProcessId }"
              % str(root))
        out = subprocess.run(["powershell", "-NoProfile", "-Command", ps],
                             capture_output=True, text=True, timeout=30,
                             creationflags=CREATE_NO_WINDOW)
        for tok in out.stdout.split():
            if tok.strip().isdigit():
                subprocess.run(["taskkill", "/f", "/pid", tok.strip()],
                               capture_output=True, timeout=15,
                               creationflags=CREATE_NO_WINDOW)
    except Exception:
        pass


def _run_bat(root, p, limit=25.0, echo_on=False):
    """真跑替换脚本，返回 (elapsed, timed_out)。

    R4：**超时即红**，并在消息里点名"疑似模态框"——挂死比失败更糟（CI 挂住不报错）。
    超时后尽力关掉本次 root 触发的 wscript/cscript，避免把模态框留在用户桌面上。

    stdout/stderr **落盘而不是丢弃**（2026-09-20 改）：旧写法用 `DEVNULL` 把 bat 自己
    的报错也一并吞了，于是 CI 上出现"bat 只写下一行日志就没了"时，**手上一条 cmd 的
    错误信息都没有**——只能靠猜（当晚连续证伪了 `rem` 里的 `|`、`rem` 里的 `>`、
    重定向失败中止批处理三条假说）。cmd 在"找不到批处理标签"这类情况下是**静默终止**
    批处理并把话只写在 stderr 上，所以这行捕获就是唯一的证词。

    `echo_on=True`（取证用）：把渲染出的 bat 首行 `@echo off` 换成 `@echo on`，让 cmd
    把自己**实际执行的每一行**（含变量展开后的文本）写进 stdout——`last executed line`
    直接指出"bat 死在哪一行"，比任何推断都硬。
    """
    # 模板 build_apply_script 签名（1.4.5）：无 pending_path（fork 的"落盘 pending"已随
    # 切模板消失）；exe_name= 是测试替身口子。
    text = U.build_apply_script(
        target_dir=p["install"], stage_dir=p["stage"], work_dir=p["work"],
        backup_dir=p["backup"], log_path=p["log"], snapshot_dir=p["snapshot"],
        failed_marker=p["failed"], exe_name="probe.vbs", limit=2)
    if echo_on:
        text = text.replace("@echo off", "@echo on", 1)
    bat = root / ("apply-echo.bat" if echo_on else "apply.bat")
    bat.write_text(text, encoding="ascii", newline="")
    out_path = root / (bat.stem + ".out")
    err_path = root / (bat.stem + ".err")
    started = time.time()
    timed_out = False
    try:
        with open(out_path, "wb") as fo, open(err_path, "wb") as fe:
            subprocess.run(["cmd.exe", "/c", str(bat)], cwd=str(root), timeout=limit,
                           creationflags=CREATE_NO_WINDOW, stdout=fo, stderr=fe)
    except subprocess.TimeoutExpired:
        timed_out = True
        _kill_stray_wscript(root)
    return time.time() - started, timed_out


def _dump_bat_scene(tag, root, p, bat_stem="apply"):
    """bat 行为不符预期时的取证块：**把手上能拿到的全部原始证据打出来**。

    刻意不做任何"聪明"的摘要——被摘掉的那一行往往正是答案。
    """
    print("  ---- diagnostics: %s ----" % tag, flush=True)
    print("    root=%s" % root, flush=True)
    print("    TEMP=%r gettempdir=%r" % (os.environ.get("TEMP"), tempfile.gettempdir()),
          flush=True)
    for name in ("%s.out" % bat_stem, "%s.err" % bat_stem):
        f = root / name
        if f.exists():
            body = f.read_bytes().decode("utf-8", "replace")
            print("    %s (%d bytes, tail 1200)=%r" % (name, len(body), body[-1200:]),
                  flush=True)
        else:
            print("    %s MISSING" % name, flush=True)
    # bat 自删是 `:cleanup_tail` 的标志：它还在 ⇒ 根本没走到收尾（提前终止的硬证据）。
    print("    %s.bat survived=%s" % (bat_stem, (root / ("%s.bat" % bat_stem)).exists()),
          flush=True)
    lg = p["log"]
    print("    LOG exists=%s body=%r" % (lg.exists(), _safe_read(lg)), flush=True)
    mk = p["failed"]
    print("    MARKER exists=%s body=%r" % (mk.exists(), _safe_read(mk)), flush=True)
    _gha_annotate("root=%s\n%s\n%s\nLOG=%r\nbat_survived=%s"
                  % (root,
                     _tail(root / ("%s.err" % bat_stem)),
                     _tail(root / ("%s.out" % bat_stem), limit=2500),
                     _safe_read(p["log"]), (root / ("%s.bat" % bat_stem)).exists()),
                  title="update-safety diagnostics (%s)" % tag)


def _tail(path, limit=1200):
    """落盘文件的尾部（取证用；文件不在就明确说"不在"）。"""
    if not path.exists():
        return "%s: MISSING" % path.name
    body = path.read_bytes().decode("utf-8", "replace")
    return "%s (%d bytes, tail %d)=%r" % (path.name, len(body), limit, body[-limit:])


def _gha_annotate(text, title="update-safety diagnostics"):
    """把取证块以 GitHub Actions 的 `::error::` 工作流命令打出去。

    为什么非要有这条通道（2026-09-20 实测）：**CI 的步骤日志需要登录才能读**
    （匿名访问只看到 "Sign in to view logs"），而 run 摘要页上的**注解（annotation）
    是公开可读的文本**。本文件在 CI 上失败时，能把证据带出来的就只有注解。

    协议细节：工作流命令是**单行**的，消息里的换行必须写成 `%0A`，而 `%` 自身要先转义成
    `%25`（顺序不能反，否则会把转义符再转义一遍）。不转义的话第二行起会被 runner 当成
    普通输出丢弃——那正是"留了证据却没人看得见"。
    """
    body = text.replace("%", "%25").replace("\r", "").replace("\n", "%0A")
    for i in range(0, len(body), 60000):      # 注解有长度上限，超了切成多条
        print("::error title=%s::%s" % (title, body[i:i + 60000]), flush=True)


def _reached_terminal(log_text):
    """替换脚本**跑到终态**了吗——只看日志最后一条非空行。

    模板 `_APPLY_BAT` 的**每一条**收尾路径都会且只会写一行终态：
      L238 `done`（成功）／L244 `STAGE INVALID`（空暂存）／
      L262 `restored - starting previous version`（回铺后拉回旧版）／
      L266 `RESTORE FAILED`（回铺也失败）／L273 `aborted:`（等待超限）。
    所以"末行是终态标记" ⇔ "脚本走完了"。

    为什么要单独判这一条：它把 **harness 的执行环境问题**（批处理被扫描器/负载扰动、
    半路没了）与**产品语义问题**分开。缺了它，"脚本半路没了"会被记到**碰巧先执行的那条
    断言**头上——CI run 35488810525 报出来的是"日志没记拒绝"，与真实成因无关，
    当晚排查因此走了一大段弯路（四条候选机制全被独立探针证伪，见 module docstring）。
    """
    lines = [ln for ln in str(log_text).splitlines() if ln.strip()]
    if not lines:
        return False
    last = lines[-1]
    return (last.rstrip().endswith("done")
            or "STAGE INVALID" in last
            or "restored - starting previous version" in last
            or "RESTORE FAILED" in last
            or "aborted:" in last)


def _safe_read(path):
    """取证用读文件：**绝不因为读不到而中断取证本身**（目录/锁/编码都要能出结论）。"""
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        return "<unreadable: %s>" % type(exc).__name__


def _check_no_hang(label, elapsed, timed_out, limit=20.0):
    check("%s: script returned (no modal hang)" % label,
          (not timed_out) and elapsed < limit,
          "%.1fs%s" % (elapsed, " TIMEOUT - 疑似模态框挂死" if timed_out else ""))


def _readonly_selfproof(probe_path):
    """只读保险自证：删除**必须**失败。返回 (ok, detail)。"""
    try:
        os.remove(probe_path)
    except OSError as exc:
        return True, type(exc).__name__
    # 保护没生效：文件已经没了。**立刻写回**——绝不能带着缺失的 `start` 目标往下跑。
    probe_path.write_text(_probe_vbs("started-old.txt", note="old"), encoding="ascii")
    return False, "delete SUCCEEDED - read-only NOT in effect (file rewritten)"


def _bat_success(root):
    p = _stage(root)
    _ro_ok, _ro_detail = _readonly_selfproof(p["install"] / "probe.vbs")
    check("fake exe is read-only (self-proof: delete must fail)", _ro_ok, _ro_detail)
    elapsed, timed_out = _run_bat(root, p)
    _check_no_hang("bat success", elapsed, timed_out)
    # 判据（确定性）：新版**脚本正文**真的落进了 install——data-new.txt 只在 stage 里有，
    # 它出现就证明前向拷贝执行了且没被 robocopy 跳过（跳过那条路已由 `_probe_vbs` 的
    # 长度差堵死）；日志末行 `done` 证明走的是成功收尾而不是失败回铺。
    log_text = _safe_read(p["log"])
    check("bat success: install payload updated", (p["install"] / "data-new.txt").exists())
    check("bat success: log says done", "done" in log_text,
          log_text[-100:].replace("\n", " | "))
    check("bat success: old snapshot rotated into BACKUP",
          (p["backup"] / "data-old.txt").exists() and not p["snapshot"].exists())
    check("bat success: no failure marker", not p["failed"].exists())
    check("bat success: work dir cleaned", not p["work"].exists())
    # 观察（非判据）：见 `_observe_started`。
    _observe_started(p["install"] / "started-new.txt", "new version")


def _lock_exclusive(path):
    """以 share=0 独占打开文件；robocopy 读不到它 → 前向拷贝 rc>=8（真实注入）。"""
    import ctypes
    from ctypes import wintypes
    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    k32.CreateFileW.restype = wintypes.HANDLE
    GENERIC_READ, OPEN_EXISTING, FILE_ATTRIBUTE_NORMAL = 0x80000000, 3, 0x80
    return k32.CreateFileW(str(path), GENERIC_READ, 0, None, OPEN_EXISTING,
                           FILE_ATTRIBUTE_NORMAL, None)


def _unlock(handle):
    import ctypes
    ctypes.WinDLL("kernel32").CloseHandle(handle)


def _lock_no_delete(path):
    """打开文件：**允许别人读写、但禁止删除**（share=READ|WRITE，不含 DELETE）。"""
    import ctypes
    from ctypes import wintypes
    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    k32.CreateFileW.restype = wintypes.HANDLE
    GENERIC_READ, OPEN_EXISTING, FILE_ATTRIBUTE_NORMAL = 0x80000000, 3, 0x80
    FILE_SHARE_READ, FILE_SHARE_WRITE = 0x1, 0x2
    return k32.CreateFileW(str(path), GENERIC_READ, FILE_SHARE_READ | FILE_SHARE_WRITE,
                           None, OPEN_EXISTING, FILE_ATTRIBUTE_NORMAL, None)


def _bat_failure(root):
    # Real rc>=8 injection: keep the staged payload readable, but hold one staged file
    # exclusively so the forward copy cannot read it. The install dir stays intact and
    # the snapshot restores cleanly, which exercises :install_failed -> restore -> start old.
    p = _stage(root, lock_staged=True)
    locked = p["stage"] / "locked.bin"
    h = _lock_exclusive(locked)
    try:
        elapsed, timed_out = _run_bat(root, p)
    finally:
        _unlock(h)
    _check_no_hang("bat failure", elapsed, timed_out)
    check("bat failure: new version NOT started",
          not _wait_for(p["install"] / "started-new.txt", 3.0))
    check("bat failure: install keeps old payload",
          (p["install"] / "data-old.txt").exists()
          and not (p["install"] / "data-new.txt").exists())
    check("bat failure: marker written", p["failed"].exists())
    check("bat failure: snapshot kept for manual recovery", p["snapshot"].exists())
    check("bat failure: work kept for manual recovery", p["work"].exists())
    log_text = p["log"].read_text(encoding="utf-8", errors="replace")
    check("bat failure: log records the failed rc", "INSTALL FAILED rc=" in log_text,
          log_text[-100:].replace("\n", " | "))
    # 判据（确定性）：日志末行是"回铺完成、准备拉旧版"——决策证据，不依赖进程真的起来。
    check("bat failure: log says the previous version is being restored",
          "restored - starting previous version" in log_text,
          log_text[-100:].replace("\n", " | "))
    # 观察（非判据）：见 `_observe_started`。
    _observe_started(p["install"] / "started-old.txt", "previous version")


def _bat_failure_no_restore(root):
    """回铺也失败（快照不可用）→ 必须走到 :install_dead 且**什么都不启动**。"""
    p = _stage(root, bad_snapshot=True, lock_staged=True)
    locked = p["stage"] / "locked.bin"
    h = _lock_exclusive(locked)
    try:
        elapsed, timed_out = _run_bat(root, p)
    finally:
        _unlock(h)
    _check_no_hang("bat no-restore", elapsed, timed_out)
    check("bat no-restore: nothing started (side-effect: no marker)",
          not _wait_for(p["install"] / "started-old.txt", 3.0)
          and not (p["install"] / "started-new.txt").exists())
    log_text = p["log"].read_text(encoding="utf-8", errors="replace")
    check("bat no-restore: really reached :install_dead", "RESTORE FAILED" in log_text,
          log_text[-140:].replace("\n", " | "))
    check("bat no-restore: failure marker written", p["failed"].exists())
    check("bat no-restore: target still holds a real exe (R1 invariant)",
          (p["install"] / "probe.vbs").exists())


def _bat_empty_stage(root):
    """空 STAGE（有目录、无 exe）——模板 1.4.2 起的行为与 fork 不同，是本轮重点回归：

    模板 `:stage_invalid` **把旧版本拉回来**（`if exist "{newexe}" start "" "{newexe}"`，
    L245），fork 只写 marker + 日志、更新失败后应用一直关着。两者都**不碰安装目录**、
    不启动新版本、保留现场；差别在"旧版是否被拉回"（本文件按 `_observe_started` 的口径
    只**观察**这一条，判定用日志那行 `install untouched` + 目录未动的确定性证据）。

    **本场景整段可重试**（2026-09-20，CI red 后的收口）：重试的判据**不是任何产品断言**，
    而是两条前置条件——`_reached_terminal()`（"脚本跑到终态了吗"）与 `ok_log`
    （"走到 `:stage_invalid` 了吗"）。两条本身也都是 ok/FAIL，不允许静默。
      * 事实：CI run 35488810525（commit `ec8192d`，与本机 HEAD 同一份字节）上，实测日志
        **只有 start 行** —— 脚本在 `:wait`/`:gone` 之后、`:stage_invalid` 的 `echo` 之前
        就没了；而同一份字节在本机连跑 5 次 5 次全绿。
      * 当晚**逐条证伪**了四个候选机制，每个都有独立探针（`_verify-scratch/`）：`rem` 行里的
        `|`、`rem` 行里的 `>`、重定向失败中止批处理、LF-only 批处理。⇒ 真实机制**未定**。
      * 同批还对齐了 reme 已裁定、已落地的两条**实测**扰动源（见 `_probe_vbs` 的 `note`
        与 `_observe_started`）：robocopy 的"等大等时戳即同一文件"跳过（约三次一次），
        以及连续跑门禁时 `start` 被拒绝建进程（约三次一次）。前者本仓此前**确有**。
      * 因此这里的选择是：**"没跑到终态"记为 harness 侧、重跑同一场景**（2 次）；**"跑到了
        终态"则一条断言都不放**——产品语义仍然严格，确定性缺陷（重跑照样复现）仍然变红。
      * 残留风险（诚实记账）：若成因其实是确定性产品缺陷，重试会把它盖住。所以 `reached`
        **必须**自己成为一条 ok/FAIL，且失败时打印完整取证块（含 `@echo on` 的逐行 trace，
        那是"bat 死在哪一行"的直接证据）——不允许静默。
    """
    reached = ok_log = False
    for attempt in (1, 2):
        p = _stage(root, stage_empty=True)
        elapsed, timed_out = _run_bat(root, p)
        log_text = _safe_read(p["log"])
        reached = _reached_terminal(log_text)
        ok_log = "STAGE INVALID" in log_text
        if reached and ok_log:
            break
        print("  .. empty-stage attempt %d incomplete: reached_terminal=%s log=%s"
              % (attempt, reached, ok_log), flush=True)
        _dump_bat_scene("empty-stage attempt %d" % attempt, root, p)
        if attempt == 2:
            # 决定性取证：同一现场再跑一次，但让 cmd 把**实际执行的每一行**写进 stdout。
            # `@echo on` trace 的最后一行 = bat 真正停下来的地方，不再需要推断。
            p3 = _stage(root, stage_empty=True)
            e3, t3 = _run_bat(root, p3, echo_on=True)
            print("    echo-on rerun: %.1fs timed_out=%s" % (e3, t3), flush=True)
            _dump_bat_scene("empty-stage echo-on trace", root, p3, bat_stem="apply-echo")

    _check_no_hang("bat empty-stage", elapsed, timed_out)
    # 先报前置条件：它红了，"下面某条断言红了"就不该被读成产品语义问题。
    check("bat empty-stage: harness ran the script to a terminal state", reached)
    check("bat empty-stage: new version NOT started",
          not (p["install"] / "started-new.txt").exists())
    # 判据（确定性）：走到 `:stage_invalid` 的**决策**证据是日志那一行 + 安装目录分毫未动；
    # "旧版被真的拉起来"是异步副作用，按 `_observe_started` 的口径只记录、不判定。
    check("bat empty-stage: log records the refusal", ok_log,
          log_text[-100:].replace("\n", " | "))
    check("bat empty-stage: install dir untouched (old payload still there)",
          (p["install"] / "data-old.txt").exists()
          and (p["install"] / "probe.vbs").exists())
    check("bat empty-stage: failure marker written", p["failed"].exists())
    check("bat empty-stage: work kept for manual inspection", p["work"].exists())
    _observe_started(p["install"] / "started-old.txt", "previous version (untouched install)")


_root_b = Path(scratch_dir("l-s2t-bat-"))
try:
    _bat_success(_root_b)
    _bat_failure(_root_b)
    _bat_failure_no_restore(_root_b)
    _bat_empty_stage(_root_b)
finally:
    _clean(_root_b)


# ==================== D. launch_pending_cmd：无控制台 + 脱离父进程 ====================
_root_d = Path(scratch_dir("l-s2t-launch-"))
try:
    # D1 旗标断言：必须是 CREATE_NO_WINDOW | DETACHED_PROCESS，且是 list 形式（无 shell）
    seen = {}
    _real_popen = subprocess.Popen

    class _FakePopen:
        def __init__(self, args, **kwargs):
            seen["args"] = args
            seen["kwargs"] = kwargs

    U.subprocess.Popen = _FakePopen
    try:
        launched = U.launch_pending_cmd(str(_root_d / "fake.bat"))
    finally:
        U.subprocess.Popen = _real_popen
    flags = seen.get("kwargs", {}).get("creationflags", 0)
    check("launch: Popen used (list argv, no shell)", seen.get("args", [None])[0] == "cmd.exe",
          repr(seen.get("args")))
    check("launch: CREATE_NO_WINDOW set",
          bool(flags & getattr(subprocess, "CREATE_NO_WINDOW", 0)))
    check("launch: DETACHED_PROCESS set",
          bool(flags & getattr(subprocess, "DETACHED_PROCESS", 0)))
    check("launch: returns True", launched is True)

    # D2 真实拉起：脚本写 marker 后退出；调用立即返回，脚本继续跑完
    marker = _root_d / "ran.txt"
    script = _root_d / "probe.bat"
    script.write_text('@echo off\r\necho ok > "%~dp0ran.txt"\r\n',
                      encoding="ascii", newline="")
    check("launch: real start returned True",
          U.launch_pending_cmd(str(script)) is True)
    check("launch: detached script actually ran", _wait_for(marker, 15.0))
    check("launch: empty cmd returns False", U.launch_pending_cmd("") is False)
finally:
    _clean(_root_d)


# ==================== E. 渲染文本的结构面（每处 start 自带守卫 + 分支 start 数） ====================
# 施工单 §5 第 1 项：两条 `start` 路径的存在性守卫回归。模板 L237/L253 是"每处 start
# 各自验"，不能靠别处的守卫代证。运行期由 B 组三个场景覆盖"守卫在时不会挂"，这里再钉
# "守卫本身在文本里存在"——守卫被删掉时，B 组可能因"目标恰好还在"而侥幸通过，只有这条会红。
_root_e = Path(scratch_dir("l-s2t-guards-"))
try:
    _failed = _root_e / "update.failed"
    _text = U.build_apply_script(
        target_dir=_root_e / "install", stage_dir=_root_e / "stage",
        work_dir=_root_e / "work", backup_dir=_root_e / "backup",
        log_path=_root_e / "update.log", snapshot_dir=_root_e / "snap",
        failed_marker=_failed, exe_name="probe.vbs", limit=2)
    _newexe = str(_root_e / "install" / "probe.vbs")   # 渲染后 {newexe} 已展开

    check("script: empty-stage guard precedes any copy (template L223)",
          'if not exist "%STAGE%\\probe.vbs" goto stage_invalid' in _text)
    check("script: :stage_invalid brings the previous version back (template >= 1.4.2)",
          'if exist "%s" start "" "%s"' % (_newexe, _newexe) in _text)
    check("script: success path routes a missing exe to :install_failed (never bare start)",
          'if not exist "%s" goto install_failed' % _newexe in _text)
    check("script: restore path has its own exe guard before start (template L261)",
          'if not exist "%s" goto install_dead' % _newexe in _text)
    check("script: fork-only :start_missing is gone with the fork",
          ":start_missing" not in _text)

    # 逐分支断言（施工单 §5 第 1 项）：每个标签块内的 start 数 = 设计值，且该块的 start
    # **自带守卫**。模板的守卫形态与 fork 不同（不止"紧邻上一行"）：
    #   :gone          -> 前几行有 `if not exist "{newexe}" goto install_failed`
    #   :stage_invalid -> 同一行 `if exist "{newexe}" start "" "{newexe}"`
    #   :install_failed-> 前几行有 `if not exist "{newexe}" goto install_dead`
    # 所以判"块内是否有守卫"，不判行距——行距会被中间的 rmdir/move/echo 打散。
    _LABELS = (":gone", ":stage_invalid", ":install_failed", ":install_dead", ":giveup")

    def _label_block(lab):
        s = _text.index(lab + "\n")
        ends = [e for e in (_text.find(o + "\n", s + 1) for o in _LABELS) if e != -1]
        return _text[s:min(ends)] if ends else _text[s:]

    _want = {":gone": 1, ":stage_invalid": 1, ":install_failed": 1,
             ":install_dead": 0, ":giveup": 0}
    _mismatch = ["%s start=%d want=%d" % (lab, _label_block(lab).count('start ""'), n)
                 for lab, n in _want.items()
                 if _label_block(lab).count('start ""') != n]
    check("script: per-branch start count exactly as designed (template 3 starts + giveup)",
          not _mismatch, " | ".join(_mismatch))

    _goto_failed = 'if not exist "%s" goto install_failed' % _newexe
    _goto_dead = 'if not exist "%s" goto install_dead' % _newexe
    _inline_old = 'if exist "%s" start "" "%s"' % (_newexe, _newexe)
    check("script: :gone start is guarded (goto install_failed in the same block)",
          _goto_failed in _label_block(":gone"))
    check("script: :stage_invalid start is guarded inline",
          _inline_old in _label_block(":stage_invalid"))
    check("script: :install_failed start is guarded (goto install_dead in the same block)",
          _goto_dead in _label_block(":install_failed"))

    # "不启动"的分支必须**写明**不启动，否则后人只看到"没有 start"，分不清是设计还是漏了。
    check("script: :install_dead refuses explicitly (not silently)",
          "RESTORE FAILED" in _label_block(":install_dead"))
finally:
    _clean(_root_e)


# ==================== F. 单元级控制：把"存在但从未走到"的分支跑一遍 ====================
# 来源：复核员自查（2026-09-19）——分支存在 ≠ 分支被覆盖。
_c_unit = Path(scratch_dir("l-s2t-unitctrl-"))
try:
    # F1 只读自证的**兜底分支**：保护未生效（文件可写）时必须 (a) 返回 False (b) 把文件写回。
    _w = _c_unit / "probe.vbs"
    _w.write_text(_probe_vbs("started-old.txt"), encoding="ascii")
    _ok_w, _det_w = _readonly_selfproof(_w)
    check("unit: self-proof FAILS on a writable file (protection absent)",
          _ok_w is False, repr(_det_w))
    check("unit: self-proof rewrites the target when protection is absent (R1 kept)",
          _w.is_file() and "started-old.txt" in _w.read_text(encoding="ascii"),
          "exists=%s" % _w.is_file())

    # F2 同一条自证在**只读**文件上必须返回 True。
    os.chmod(_w, stat.S_IREAD)
    _ok_r, _det_r = _readonly_selfproof(_w)
    check("unit: self-proof PASSES on a read-only file", _ok_r is True, repr(_det_r))

    # F3 超时判定：`_check_no_hang` 的"红灯"路径真跑中从未走到（没有真挂死）。
    _real_check = check
    _recorded = []
    globals()["check"] = lambda name, ok, detail="": _recorded.append((name, ok, detail))
    try:
        _check_no_hang("unit-probe", elapsed=1.0, timed_out=False)
        _check_no_hang("unit-probe", elapsed=1.0, timed_out=True)
        _check_no_hang("unit-probe", elapsed=99.0, timed_out=False)   # 超阈值但未标记超时
    finally:
        globals()["check"] = _real_check
    check("unit: _check_no_hang is green on a normal return",
          _recorded[0][1] is True, repr(_recorded[0]))
    check("unit: _check_no_hang turns RED on timed_out=True (the branch never hit live)",
          _recorded[1][1] is False and "模态框" in _recorded[1][2], repr(_recorded[1]))
    check("unit: _check_no_hang turns RED when elapsed exceeds the limit",
          _recorded[2][1] is False, repr(_recorded[2]))
finally:
    _clean(_c_unit)

# ---------- :giveup 的三个数必须同源：polls / tick / nominal budget ----------
def _budget_fields(text):
    m = re.search(r"after %tries% polls x (\d+)ms \(nominal budget (\d+)s", text)
    return (int(m.group(1)), int(m.group(2))) if m else (None, None)


_render = lambda lim: U.build_apply_script(       # noqa: E731
    target_dir="T", stage_dir="S", work_dir="W", backup_dir="B", log_path="L",
    snapshot_dir="SN", failed_marker="F", exe_name="probe.vbs", limit=lim)
for _lim in (U.UPDATE_WAIT_LIMIT, 2, 7):
    _tick, _budget = _budget_fields(_render(_lim))
    check("giveup text: limit=%d renders a consistent budget" % _lim,
          _tick is not None and _budget == _lim * _tick // 1000,
          "polls=%s tick=%s budget=%s expected=%s"
          % (_lim, _tick, _budget, _lim * _tick // 1000))
check("giveup text: default render still equals UPDATE_WAIT_BUDGET_S",
      _budget_fields(_render(U.UPDATE_WAIT_LIMIT))[1] == U.UPDATE_WAIT_BUDGET_S,
      "rendered=%s constant=%s" % (_budget_fields(_render(U.UPDATE_WAIT_LIMIT))[1],
                                   U.UPDATE_WAIT_BUDGET_S))


# ==================== G. sweep_stale_update_dirs：两类都清（施工单 §5 第 2/3 项） ====================
# F11 隔离自证：**先**证明 gettempdir 指向隔离目录，再做清扫断言；否则这个测试会去
# 扫、甚至删掉用户真实 %TEMP% 里的东西。
check("sweep: gettempdir is the isolated dir (F11 - this test never touches real %TEMP%)",
      Path(tempfile.gettempdir()) == Path(_TMP_TEMP),
      "gettempdir=%s isolated=%s" % (tempfile.gettempdir(), _TMP_TEMP))
check("sweep: TEMP_PREFIX matches the two artifact classes",
      U.TEMP_PREFIX == APP_ID + "-update", "TEMP_PREFIX=%s" % U.TEMP_PREFIX)

_root_g = Path(_TMP_TEMP)
_old = time.time() - 7200.0     # 2h 前 > max_age=3600
_old_dir = _root_g / (APP_ID + "-update-olddir")
_old_dir.mkdir()
(_old_dir / "staged-payload.bin").write_bytes(b"x")
_old_bat = _root_g / (APP_ID + "-update.bat")          # 中断的替换脚本（文件）
_old_bat.write_text("@echo off\r\n", encoding="ascii")
# 对照样本 1：同前缀但**新鲜**（正在进行的更新）——绝不能碰
_fresh_dir = _root_g / (APP_ID + "-update-fresh")
_fresh_dir.mkdir()
_fresh_bat = _root_g / (APP_ID + "-update-new.bat")
_fresh_bat.write_text("@echo off\r\n", encoding="ascii")
# 对照样本 2：非本应用前缀——绝不能碰
_other = _root_g / "some-other-app-update-old"
_other.mkdir()
for _p in (_old_dir, _old_bat, _fresh_dir, _fresh_bat, _other):
    _t = _old if _p in (_old_dir, _old_bat) else time.time()
    os.utime(_p, (_t, _t))

_removed = U.sweep_stale_update_dirs(max_age=3600.0)
check("sweep: stale staged DIR removed", not _old_dir.exists())
check("sweep: stale replacement .bat FILE removed (the >=1.4.4 defect)",
      not _old_bat.exists())
check("sweep: fresh same-prefix artifacts kept (an in-flight update is untouched)",
      _fresh_dir.exists() and _fresh_bat.exists())
check("sweep: non-matching prefix kept", _other.exists())
check("sweep: returns the exact count of removed artifacts", _removed == 2,
      "removed=%s" % _removed)
# 原位对照（负控）：把 max_age=0 再跑一次，新鲜的两个也必须被清 —— 证明它们不是
# 因为"匹配不到"而幸存（否则上面那条"kept"是空真）。
_removed2 = U.sweep_stale_update_dirs(max_age=0.0)
check("sweep negative control: with max_age=0 the fresh ones ARE removed (not vacuous)",
      not _fresh_dir.exists() and not _fresh_bat.exists() and _removed2 == 2,
      "removed2=%s" % _removed2)
check("sweep negative control: non-matching prefix still kept",
      _other.exists())


# ==================== H. 接线：C-27 MUST-WIRE 三符号（施工单 §5 第 4 项） ====================
# dsh/ocx 踩过"拷到位但零引用"：机械哈希全绿，README 承诺的 sweep/pop 从未发生。
_main_src = (Path(__file__).resolve().parents[1] / "src" / "main.py").read_text(
    encoding="utf-8")
for _sym in ("sweep_stale_update_dirs", "pop_failed_update_note", "launch_pending_cmd"):
    check("wiring (C-27): main.py references %s" % _sym,
          re.search(r"\b%s\b" % re.escape(_sym), _main_src) is not None)
check("wiring: the fork module is gone (no src/updater.py consumer left)",
      not (Path(__file__).resolve().parents[1] / "src" / "updater.py").exists())


_clean(_TMP_DATA)
_clean(_TMP_TEMP)

_left = [p for p, gone in _CLEANED if not gone]
check("temp dirs cleaned up (no %TEMP% leak)", not _left, " | ".join(_left))

print("UPDATE SAFETY TEST " + ("FAILED: " + ",".join(FAILS) if FAILS else "OK"), flush=True)
sys.exit(1 if FAILS else 0)
