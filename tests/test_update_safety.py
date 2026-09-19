# -*- coding: utf-8 -*-
"""更新链安全语义的真实执行回归（sha256 fail-closed / 替换脚本 rc 与回退 / pending 不销毁证据）。

背景（2026-09-19，与全家族刚修的一类缺陷同源）：
  ① `download_update` 拿不到 `.sha256` 就 `skip verify` = **fail-open**；
  ② `apply.cmd` 用固定 `timeout /t 2` 等旧进程、**不判 robocopy rc**、**无条件**
     启动新 exe——铺设失败也会去拉半铺的安装目录；
  ③ `paths.process_pending_update` 不判 rc，失败时照样删 pending 与整个 update 目录，
     把**暂存源连同失败证据一起销毁**。

本测试**真跑**替换脚本（不 mock bat），用 GUI 子系统的 `.vbs` 当假 exe 观察"到底
启动了哪个版本"：
  * 脚本执行一律 `creationflags=CREATE_NO_WINDOW`——否则控制台子系统会**在用户桌面
    弹出可见窗口**，窗口 cwd 还会让收尾删除失败、留下空壳目录（用户已截图报障）；
  * 假 exe 用 `.vbs`（`start` 关联到 GUI 的 `wscript.exe`），不开控台窗口。

三组断言：
  A. sha256：期望值缺失 / 不匹配 → 失败；匹配 → 通过。
  B. 替换脚本真跑：成功路径铺新版；失败注入（STAGE 不存在 ⇒ robocopy rc=16）
     **不启动新版本**、回退后启动旧版本、写 `update.failed`、保留快照。
  C. `process_pending_update`：成功才清 pending 与暂存；rc>=8（注入）时 pending、
     暂存、现场全保留并写 marker。
"""
import json
import os
import shutil
import subprocess
import stat
import sys
import tempfile
import time
from pathlib import Path
from _cleanup import clear_readonly, rmtree_cleanup, scratch_dir  # noqa: E402  （同目录助手）

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

# 实例隔离：必须在 import updater（它会 import modules.paths）之前重定向数据根。
_TMP_DATA = scratch_dir("l-s2t-upd-")
os.environ["LOCAL_SPEAK2TEXT_DATA_DIR"] = _TMP_DATA

import updater  # noqa: E402

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


def _probe_vbs(marker):
    """假 exe：被 start 时在自身目录写一个 marker（GUI 子系统，不弹控制台）。"""
    return ('Set fso = CreateObject("Scripting.FileSystemObject")\r\n'
            'Set f = fso.CreateTextFile(fso.GetParentFolderName(WScript.ScriptFullName) '
            '& "\\%s")\r\n'
            'f.WriteLine "x"\r\n') % marker


# ==================== A. sha256 fail-closed ====================
_payload = Path(_TMP_DATA) / "payload.bin"
_payload.write_bytes(b"hello-update")
_good = updater._sha256(_payload)
check("sha256: missing expected value fails closed",
      updater.verify_zip_sha256(_payload, "")[0] is False)
check("sha256: whitespace-only expected value fails closed",
      updater.verify_zip_sha256(_payload, "   \n")[0] is False)
check("sha256: mismatch fails", updater.verify_zip_sha256(_payload, "deadbeef")[0] is False)
check("sha256: match passes", updater.verify_zip_sha256(_payload, _good)[0] is True)
check("sha256: real '<hash>  <name>' line passes",
      updater.verify_zip_sha256(_payload, "%s  payload.bin" % _good)[0] is True)


# ==================== B. 替换脚本真跑 ====================
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
    # 进而写文件时报 PermissionError（本文件 2026-09-19 就这样红过一次）。
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
    for d in (install, stage, work):
        d.mkdir(parents=True)
    # R1：目标目录的替身**恒存在**——任何分支上的 `start` 都只会命中真实文件。
    (install / "probe.vbs").write_text(_probe_vbs("started-old.txt"), encoding="ascii")
    # 只读保险（lead 令，2026-09-19）：`del <file>` / `os.unlink` / Python `rmtree`
    # 都删不掉它，于是没有哪一步能把它弄丢、让后面的 `start` 指向空气。
    #
    # ⚠️⚠️ **只读是部分保险，不是结构保证 —— 而"只读让弹窗在文件系统层面不可能发生"
    # 这句是早期误述（lead 本人更正，复核员曾照抄进 harness 的 docstring）。别再抄它。**
    # 实测边界如下（本机 Windows，2026-09-19）：
    #   挡得住：`del <file>` / `os.remove` / `shutil.rmtree`      → PermissionError
    #   挡不住：`rmdir /s /q <父目录>`                            → rc=0，目录消失
    #           `robocopy /e /purge` 覆盖                          → rc=3，内容被覆盖且 R 位被清掉
    # 定位：它是"多一层删不掉"的兜底，**不能替代**——R1（替身常在）+ 三处 `start`
    # 存在性守卫（C-26 结构断言）+ R4 超时变红。三者才是让弹窗不可能发生的那套。
    # 真正让这条注释不可反驳的是 F 组的单元级控制：它们证明这些分支**真的会红**，
    # 而不只是"写在文档里"。
    os.chmod(install / "probe.vbs", stat.S_IREAD)
    (install / "data-old.txt").write_text("old", encoding="utf-8")
    if not stage_missing and not stage_empty:
        (stage / "probe.vbs").write_text(_probe_vbs("started-new.txt"), encoding="ascii")
        (stage / "data-new.txt").write_text("new", encoding="utf-8")
    if lock_staged:
        (stage / "locked.bin").write_bytes(b"x")
    if bad_snapshot:
        # 让"快照"步骤失败：SNAPSHOT 路径上先放一个**文件**。实测 `rmdir /s /q`
        # 对它报"目录名无效"、`robocopy TARGET SNAPSHOT` 返回 rc=16，于是
        # :install_failed 的**回铺也失败** → 走到 :install_dead（且 TARGET 仍有 exe）。
        snapshot.write_text("not a directory", encoding="ascii")
    pending = root / "update.pending.json"
    pending.write_text("{}", encoding="utf-8")
    return {
        "install": install,
        "stage": stage if not stage_missing else (root / "no-such-stage"),
        "work": work,
        "backup": root / "_backup",
        "snapshot": snapshot,
        "failed": root / "update.failed",
        "log": root / "update.log",
        "pending": pending,
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


def _run_bat(root, p, limit=25.0):
    """真跑替换脚本，返回 (elapsed, timed_out)。

    R4：**超时即红**，并在消息里点名"疑似模态框"——挂死比失败更糟（CI 挂住不报错）。
    超时后尽力关掉本次 root 触发的 wscript/cscript，避免把模态框留在用户桌面上。
    """
    text = updater.build_apply_script(
        target_dir=p["install"], stage_dir=p["stage"], work_dir=p["work"],
        backup_dir=p["backup"], log_path=p["log"], snapshot_dir=p["snapshot"],
        failed_marker=p["failed"], pending_path=p["pending"],
        exe_name="probe.vbs", limit=2)
    bat = root / "apply.bat"
    bat.write_text(text, encoding="ascii", newline="")
    started = time.time()
    timed_out = False
    try:
        subprocess.run(["cmd.exe", "/c", str(bat)], cwd=str(root), timeout=limit,
                       creationflags=CREATE_NO_WINDOW,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except subprocess.TimeoutExpired:
        timed_out = True
        _kill_stray_wscript(root)
    return time.time() - started, timed_out


def _check_no_hang(label, elapsed, timed_out, limit=20.0):
    check("%s: script returned (no modal hang)" % label,
          (not timed_out) and elapsed < limit,
          "%.1fs%s" % (elapsed, " TIMEOUT - 疑似模态框挂死" if timed_out else ""))


def _readonly_selfproof(probe_path):
    """只读保险自证：删除**必须**失败。返回 (ok, detail)。

    抽成函数的理由（复核员方法，2026-09-19）：这段原本内联在 `_bat_success` 里，于是
    "删成功了 → 立刻把替身写回"这条**兜底分支**在 35+ 次真跑中一次都没被覆盖过
    （每次都抛 PermissionError）。**分支存在 ≠ 分支被覆盖**——抽出来之后可以在
    `_unit_controls()` 里用可写文件直接调它，不跑 bat、不 start、更不用造"目标缺失"。
    """
    try:
        os.remove(probe_path)
    except OSError as exc:
        return True, type(exc).__name__
    # 保护没生效：文件已经没了。**立刻写回**——绝不能带着缺失的 `start` 目标往下跑
    # （那才是弹模态框的形态）。红灯由调用方的 check 给出。
    probe_path.write_text(_probe_vbs("started-old.txt"), encoding="ascii")
    return False, "delete SUCCEEDED - read-only NOT in effect (file rewritten)"


def _bat_success(root):
    # `start "" probe.vbs` goes through the shell association to wscript.exe. Under
    # heavy load (first run inside a build) that launch occasionally does not
    # materialize within the timeout while everything else succeeded, so allow one
    # retry - the semantics under test (what the script does) are unchanged.
    for attempt in (1, 2):
        p = _stage(root)
        # 自证（lead 令）：只读保险必须**真的生效**，否则这条加固等于没加。
        # 在测试窗口期内尝试删除替身——必须失败。用副作用判据，不看属性字符串。
        _ro_ok, _ro_detail = _readonly_selfproof(p["install"] / "probe.vbs")
        check("fake exe is read-only (self-proof: delete must fail)", _ro_ok, _ro_detail)
        elapsed, timed_out = _run_bat(root, p)
        if _wait_for(p["install"] / "started-new.txt"):
            break
        print("  .. success scenario retry %d (fake exe did not start)" % attempt, flush=True)
    _check_no_hang("bat success", elapsed, timed_out)
    check("bat success: new version started",
          (p["install"] / "started-new.txt").exists())
    check("bat success: install payload updated", (p["install"] / "data-new.txt").exists())
    check("bat success: old snapshot rotated into BACKUP",
          (p["backup"] / "data-old.txt").exists() and not p["snapshot"].exists())
    check("bat success: no failure marker", not p["failed"].exists())
    check("bat success: work dir cleaned", not p["work"].exists())
    check("bat success: pending marker removed", not p["pending"].exists())


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
    """打开文件：**允许别人读写、但禁止删除**（share=READ|WRITE，不含 DELETE）。

    和 `_lock_exclusive(share=0)` 的区别很关键——share=0 会把**读**也挡住，
    那样注入的是"读失败"，不是我们要测的"删失败"。Windows 上 `os.unlink` 只要有
    一个句柄没带 FILE_SHARE_DELETE 就会失败，而 read/write 不受影响。
    """
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
    check("bat failure: previous version started after restore",
          _wait_for(p["install"] / "started-old.txt"))
    check("bat failure: install keeps old payload",
          (p["install"] / "data-old.txt").exists()
          and not (p["install"] / "data-new.txt").exists())
    check("bat failure: marker written", p["failed"].exists())
    check("bat failure: snapshot kept for manual recovery", p["snapshot"].exists())
    check("bat failure: pending kept for diagnosis", p["pending"].exists())
    log_text = p["log"].read_text(encoding="utf-8", errors="replace")
    check("bat failure: log records the failed rc", "INSTALL FAILED rc=" in log_text,
          log_text[-100:].replace("\n", " | "))


def _bat_failure_no_restore(root):
    """回铺也失败（快照不可用）→ 必须走到 :install_dead 且**什么都不启动**。

    ⚠️ 场景构造按 R1 改写：**不再**用"目标里没有 exe"来制造这条路径（那等于把
    测试变成模态框炸弹——守卫一旦回归，`start` 一个不存在的 `.vbs` 会让 WSH 弹
    "无法找到脚本文件"并永久挂死）。现在 TARGET **始终有** probe.vbs，
    用"快照路径是文件"让回铺失败：
      stage 里一个文件被独占锁 → 前向拷贝 rc>=8 → :install_failed
      → 从 SNAPSHOT 回铺（SNAPSHOT 是文件）→ rc=16 → :install_dead
    判"没启动"看**副作用**：两个 marker 都不该出现（若守卫回归真启动了旧版，
    started-old.txt 会被写出来 → 红灯；而且命中的是**存在的**文件，不会弹模态框）。
    """
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
    """空 STAGE（有目录、无 exe）：robocopy 会返回 rc=0（"没复制也没出错"）。

    若只看 rc 就判成功，/purge 已把安装目录清空，随后 start 一个不存在的 exe 会弹
    模态框、把无 console 的 detached 脚本永久卡死。正确行为：**在碰安装目录之前**就
    识别出来——不拷、不启动、写 marker、保留现场，脚本正常退出。
    """
    p = _stage(root, stage_empty=True)
    elapsed, timed_out = _run_bat(root, p)
    _check_no_hang("bat empty-stage", elapsed, timed_out)
    check("bat empty-stage: nothing started",
          not (p["install"] / "started-new.txt").exists()
          and not (p["install"] / "started-old.txt").exists())
    check("bat empty-stage: install dir untouched (old payload still there)",
          (p["install"] / "data-old.txt").exists()
          and (p["install"] / "probe.vbs").exists())
    check("bat empty-stage: failure marker written", p["failed"].exists())
    check("bat empty-stage: pending kept for diagnosis", p["pending"].exists())
    log_text = p["log"].read_text(encoding="utf-8", errors="replace")
    check("bat empty-stage: log records the refusal", "STAGED EXE MISSING" in log_text,
          log_text[-100:].replace("\n", " | "))


_root_b = Path(scratch_dir("l-s2t-bat-"))
try:
    _bat_success(_root_b)
    _bat_failure(_root_b)
    _bat_failure_no_restore(_root_b)
    _bat_empty_stage(_root_b)
finally:
    _clean(_root_b)


# ==================== C. process_pending_update 不销毁证据 ====================
_root_c = Path(scratch_dir("l-s2t-pending-"))
try:
    # C1 真实成功：robocopy 真跑，rc<8 → 清 pending 与暂存
    staged = _root_c / "staged"
    target = _root_c / "app"
    work = _root_c / "update"
    staged.mkdir(); target.mkdir(); work.mkdir()
    (staged / "new.txt").write_text("n", encoding="utf-8")
    (work / "leftover.txt").write_text("l", encoding="utf-8")
    pending = _root_c / "update.pending.json"
    pending.write_text(json.dumps({"staged": str(staged), "target": str(target)}),
                       encoding="utf-8")
    ok = updater.process_pending_update(pending_path=pending, update_dir=work)
    check("pending success: returns True", ok is True)
    check("pending success: file copied", (target / "new.txt").exists())
    check("pending success: pending removed", not pending.exists())
    check("pending success: update dir removed", not work.exists())

    # C2 被打断：staged 不存在 → 早退且**什么都不动**
    work2 = _root_c / "update2"; work2.mkdir()
    pending2 = _root_c / "update2.pending.json"
    pending2.write_text(json.dumps({"staged": str(_root_c / "no-such"),
                                    "target": str(target)}), encoding="utf-8")
    ok = updater.process_pending_update(pending_path=pending2, update_dir=work2)
    check("pending incomplete: returns False", ok is False)
    check("pending incomplete: pending kept", pending2.exists())
    check("pending incomplete: update dir kept", work2.exists())

    # C3 rc>=8（注入 robocopy 返回码）：不删 pending、不删暂存、写 marker
    work3 = _root_c / "update3"; work3.mkdir()
    (work3 / "evidence.txt").write_text("e", encoding="utf-8")
    staged3 = _root_c / "staged3"; staged3.mkdir()
    pending3 = _root_c / "update3.pending.json"
    pending3.write_text(json.dumps({"staged": str(staged3), "target": str(target)}),
                        encoding="utf-8")
    _real_run = subprocess.run

    class _Fail:
        returncode = 16

    updater.subprocess.run = lambda *a, **k: _Fail()
    try:
        ok = updater.process_pending_update(pending_path=pending3, update_dir=work3)
    finally:
        updater.subprocess.run = _real_run
    check("pending rc>=8: returns False", ok is False)
    check("pending rc>=8: pending kept (evidence not destroyed)", pending3.exists())
    check("pending rc>=8: staged files kept", (work3 / "evidence.txt").exists())
    check("pending rc>=8: failure marker written",
          updater.failed_marker_path(work3).exists(),
          str(updater.failed_marker_path(work3)))

    note = updater.pop_failed_update_note(work3)
    check("failed note: readable once", bool(note))
    check("failed note: marker deleted after read",
          not updater.failed_marker_path(work3).exists())

    # C4【顺序缺陷回归，2026-09-19】marker 删不掉时**不得吞掉提示**。
    # 旧写法把 unlink 和 read_text 放同一个 try：unlink 抛 OSError（文件被
    # Defender/索引器瞬时锁住，本仓库实测过）就走 except 直接 return ""——
    # detail 明明读到了，用户却看不到升级失败提示。真实注入：独占锁住 marker。
    work4 = _root_c / "update4"; work4.mkdir()
    marker4 = updater.failed_marker_path(work4)
    marker4.write_text("install rc=16", encoding="utf-8")
    _h = _lock_no_delete(marker4)          # 能读、不能删
    try:
        note4 = updater.pop_failed_update_note(work4)
    finally:
        _unlock(_h)
    check("locked marker: note still returned (delete failure must not eat the note)",
          bool(note4) and "install rc=16" in note4, repr(note4))
    check("locked marker: evidence kept for the next launch", marker4.exists())
    marker4.unlink()                        # 解锁后清掉，避免影响后续断言
finally:
    _clean(_root_c)


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

    updater.subprocess.Popen = _FakePopen
    try:
        launched = updater.launch_pending_cmd(str(_root_d / "fake.bat"))
    finally:
        updater.subprocess.Popen = _real_popen
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
          updater.launch_pending_cmd(str(script)) is True)
    check("launch: detached script actually ran", _wait_for(marker, 15.0))
    check("launch: empty cmd returns False", updater.launch_pending_cmd("") is False)
finally:
    _clean(_root_d)


# ==================== E. 成功路径的残留窄口：拷完却没有 exe ====================
# 真实 robocopy 造不出这条（前置校验要求 stage 里有 exe，拷贝又成功 ⇒ 目标必有 exe），
# 所以对**渲染出的脚本**做结构断言：必须走 :start_missing（写 marker + 保留现场），
# 而不是旧的"只记日志，然后 goto cleanup（删 WORK 与 pending）"。
_root_e = Path(scratch_dir("l-s2t-startmissing-"))
try:
    _failed = _root_e / "update.failed"
    _text = updater.build_apply_script(
        target_dir=_root_e / "install", stage_dir=_root_e / "stage",
        work_dir=_root_e / "work", backup_dir=_root_e / "backup",
        log_path=_root_e / "update.log", snapshot_dir=_root_e / "snap",
        failed_marker=_failed, pending_path=_root_e / "pending.json",
        exe_name="probe.vbs", limit=2)
    check("script: success path routes a missing exe to :start_missing",
          "goto start_missing" in _text)
    check("script: old 'log only then cleanup' shape is gone",
          "new exe missing - not starting" not in _text)
    _block = _text.split(":start_missing", 1)[1].split(":cleanup", 1)[0]
    check("script: :start_missing writes the failure marker",
          ("> \"%s\"" % _failed) in _block,
          " | ".join(_block.strip().splitlines()[:2]))
    check("script: :start_missing keeps the scene (cleanup_keep)",
          "goto cleanup_keep" in _block)

    # C-26 的结构面：**每一处 `start` 都必须自带存在性守卫**。运行期已由 B 组四个场景
    # 覆盖"守卫在时不会挂"，这里再钉"守卫本身在文本里存在"——守卫被删掉时，
    # B 组会因为"目标恰好还在"而侥幸通过，只有这条会红（反之亦然）。
    _newexe = str(_root_e / "install" / "probe.vbs")   # 渲染后 {newexe} 已展开
    _guard_inline = 'if exist "%s" start "" "%s"' % (_newexe, _newexe)
    _guard_goto = 'if not exist "%s" goto start_missing' % _newexe
    check("script: every start is guarded against a missing exe (C-26)",
          _text.count('start ""') == 2 and _guard_goto in _text and _guard_inline in _text,
          "sites=%d goto-guard=%s inline-guard=%s"
          % (_text.count('start ""'), _guard_goto in _text, _guard_inline in _text))
    # 守卫有两种合法形态：**同一行**的 `if exist … start`，或**紧邻上一行**的
    # `if not exist … goto <失败标签>`。逐行判，别用"删字符串"——那只认得第一种。
    _lines = _text.splitlines()
    _unguarded = []
    for _i, _l in enumerate(_lines):
        if 'start ""' not in _l or _guard_inline in _l:
            continue
        if _i and _lines[_i - 1].strip() == _guard_goto:
            continue
        _unguarded.append(_l.strip())
    check("script: no unguarded start remains", not _unguarded, " | ".join(_unguarded))

    # 逐分支断言（lead 令，覆盖 :gone / :install_failed / :install_dead / :start_missing）。
    # ⚠️ 实测我方脚本只有**两处** start（:gone 与 :install_failed）；`:install_dead` 与
    # `:start_missing` **一处都没有**——不是漏加守卫，而是**根本不启动**，比"守卫住 start"
    # 更强。所以断言按"每个标签块内的 start 数必须恰好等于设计值"来写：
    # 任何一块被改坏（多出 start / 少掉 start）都会红，而不是只盯 :start_missing 一处。
    _LABELS = (":gone", ":stage_invalid", ":install_failed", ":install_dead",
               ":start_missing", ":giveup")

    def _label_block(lab):
        s = _text.index(lab + "\n")
        ends = [e for e in (_text.find(o + "\n", s + 1) for o in _LABELS) if e != -1]
        return _text[s:min(ends)] if ends else _text[s:]

    _want = {":gone": 1, ":stage_invalid": 0, ":install_failed": 1,
             ":install_dead": 0, ":start_missing": 0, ":giveup": 0}
    _mismatch = ["%s start=%d want=%d" % (lab, _label_block(lab).count('start ""'), n)
                 for lab, n in _want.items()
                 if _label_block(lab).count('start ""') != n]
    check("script: per-branch start count exactly as designed (4 branches + giveup)",
          not _mismatch, " | ".join(_mismatch))

    # "不启动"的分支必须**写明**不启动，否则后人只看到"没有 start"，分不清是设计还是漏了。
    for _lab, _why in ((":install_dead", "RESTORE FAILED"), (":start_missing", "NEW EXE MISSING")):
        check("script: %s refuses explicitly (not silently)" % _lab,
              _why in _label_block(_lab),
              " | ".join(_label_block(_lab).strip().splitlines()[-2:]))

finally:
    _clean(_root_e)
    _clean(_TMP_DATA)

_left = [p for p, gone in _CLEANED if not gone]
check("temp dirs cleaned up (no %TEMP% leak)", not _left, " | ".join(_left))

# ==================== F. 单元级控制：把"存在但从未走到"的分支跑一遍 ====================
# 来源：复核员自查（2026-09-19）——他的"写回兜底"分支在 35 次真跑里一次没执行过，
# 因为每次都是 PermissionError。**分支存在 ≠ 分支被覆盖**。
# 端到端触发这些分支必须造出 R1 禁止的形态（目标缺失／真挂死），所以改用**单元级控制**：
# 直接调函数、喂构造好的入参，不跑 bat、不 start、不碰真实目标。
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

    # F2 同一条自证在**只读**文件上必须返回 True（与真跑里的断言同源，此处独立复验）。
    os.chmod(_w, stat.S_IREAD)
    _ok_r, _det_r = _readonly_selfproof(_w)
    check("unit: self-proof PASSES on a read-only file", _ok_r is True, repr(_det_r))

    # F3 超时判定：`_check_no_hang` 的"红灯"路径真跑中从未走到（没有真挂死）。
    # 用替身换掉全局 check，喂 timed_out=True，断言**它确实报了失败**，再还原。
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
# 缺陷（2026-09-19，家族正本与四份副本同形）：`budget_s` 传的是**模块常量**
# `UPDATE_WAIT_BUDGET_S`，而次数传的是 `limit` **实参**。本文件 `_run_bat` 恰恰用
# `limit=2` 保持等待短——于是**测试一直在渲染** "2 polls x 1000ms (nominal budget 120s)"，
# 只是从没人断言过这行文本。**自相矛盾的日志比没有日志更坏**：它看着像证据。
# 口径："日志里的数必须是被测过的数"（与 C-33 的"日志说谎"同族）。
def _budget_fields(text):
    import re as _re
    m = _re.search(r"after %tries% polls x (\d+)ms \(nominal budget (\d+)s", text)
    return (int(m.group(1)), int(m.group(2))) if m else (None, None)


_render = lambda lim: updater.build_apply_script(       # noqa: E731
    target_dir="T", stage_dir="S", work_dir="W", backup_dir="B", log_path="L",
    snapshot_dir="SN", failed_marker="F", pending_path="P", limit=lim)
for _lim in (updater.UPDATE_WAIT_LIMIT, 2, 7):
    _tick, _budget = _budget_fields(_render(_lim))
    check("giveup text: limit=%d renders a consistent budget" % _lim,
          _tick is not None and _budget == _lim * _tick // 1000,
          "polls=%s tick=%s budget=%s expected=%s"
          % (_lim, _tick, _budget, _lim * _tick // 1000))
check("giveup text: default render still equals UPDATE_WAIT_BUDGET_S",
      _budget_fields(_render(updater.UPDATE_WAIT_LIMIT))[1] == updater.UPDATE_WAIT_BUDGET_S,
      "rendered=%s constant=%s" % (_budget_fields(_render(updater.UPDATE_WAIT_LIMIT))[1],
                                   updater.UPDATE_WAIT_BUDGET_S))

print("UPDATE SAFETY TEST " + ("FAILED: " + ",".join(FAILS) if FAILS else "OK"), flush=True)
sys.exit(1 if FAILS else 0)
