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
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

# 实例隔离：必须在 import updater（它会 import modules.paths）之前重定向数据根。
_TMP_DATA = tempfile.mkdtemp(prefix="l-s2t-upd-")
os.environ["LOCAL_SPEAK2TEXT_DATA_DIR"] = _TMP_DATA

import updater  # noqa: E402

FAILS = []
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
def _stage(root, stage_missing=False, install_empty=False, stage_empty=False):
    install = root / "install"
    stage = root / "stage"
    work = root / "work"
    for d in (install, stage, work):
        if d.exists():
            shutil.rmtree(d, ignore_errors=True)
        d.mkdir(parents=True)
    if not install_empty:
        (install / "probe.vbs").write_text(_probe_vbs("started-old.txt"), encoding="ascii")
        (install / "data-old.txt").write_text("old", encoding="utf-8")
    if not stage_missing and not stage_empty:
        (stage / "probe.vbs").write_text(_probe_vbs("started-new.txt"), encoding="ascii")
        (stage / "data-new.txt").write_text("new", encoding="utf-8")
    pending = root / "update.pending.json"
    pending.write_text("{}", encoding="utf-8")
    return {
        "install": install,
        "stage": stage if not stage_missing else (root / "no-such-stage"),
        "work": work,
        "backup": root / "_backup",
        "snapshot": root / "_backup.pre",
        "failed": root / "update.failed",
        "log": root / "update.log",
        "pending": pending,
    }


def _run_bat(root, p):
    text = updater.build_apply_script(
        target_dir=p["install"], stage_dir=p["stage"], work_dir=p["work"],
        backup_dir=p["backup"], log_path=p["log"], snapshot_dir=p["snapshot"],
        failed_marker=p["failed"], pending_path=p["pending"],
        exe_name="probe.vbs", limit=2)
    bat = root / "apply.bat"
    bat.write_text(text, encoding="ascii", newline="")
    started = time.time()
    subprocess.run(["cmd.exe", "/c", str(bat)], cwd=str(root), timeout=60,
                   creationflags=CREATE_NO_WINDOW,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return time.time() - started


def _bat_success(root):
    # `start "" probe.vbs` goes through the shell association to wscript.exe. Under
    # heavy load (first run inside a build) that launch occasionally does not
    # materialize within the timeout while everything else succeeded, so allow one
    # retry - the semantics under test (what the script does) are unchanged.
    for attempt in (1, 2):
        p = _stage(root)
        _run_bat(root, p)
        if _wait_for(p["install"] / "started-new.txt"):
            break
        print("  .. success scenario retry %d (fake exe did not start)" % attempt, flush=True)
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


def _bat_failure(root):
    # Real rc>=8 injection: keep the staged payload readable, but hold one staged file
    # exclusively so the forward copy cannot read it. The install dir stays intact and
    # the snapshot restores cleanly, which exercises :install_failed -> restore -> start old.
    p = _stage(root)
    locked = p["stage"] / "locked.bin"
    locked.write_bytes(b"x")
    h = _lock_exclusive(locked)
    try:
        _run_bat(root, p)
    finally:
        _unlock(h)
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


def _bat_failure_no_old(root):
    """失败注入 + 目标目录里连旧 exe 都没有：回退后**不得**尝试启动任何 exe。

    否则 `start` 一个不存在的文件会弹出**模态错误框**，而脚本是无 console 的
    detached 进程，没人能点掉它——会永久卡住（模板同批也在修这一点）。
    """
    p = _stage(root, stage_missing=True, install_empty=True)
    _run_bat(root, p)
    check("bat no-old-exe: nothing started",
          not _wait_for(p["install"] / "started-old.txt", 3.0)
          and not (p["install"] / "started-new.txt").exists())
    log_text = p["log"].read_text(encoding="utf-8", errors="replace")
    check("bat no-old-exe: log says it refused to start", "not starting" in log_text,
          log_text[-100:].replace("\n", " | "))


def _bat_empty_stage(root):
    """空 STAGE（有目录、无 exe）：robocopy 会返回 rc=0（"没复制也没出错"）。

    若只看 rc 就判成功，/purge 已把安装目录清空，随后 start 一个不存在的 exe 会弹
    模态框、把无 console 的 detached 脚本永久卡死。正确行为：**在碰安装目录之前**就
    识别出来——不拷、不启动、写 marker、保留现场，脚本正常退出。
    """
    p = _stage(root, stage_empty=True)
    elapsed = _run_bat(root, p)
    check("bat empty-stage: script returned (no modal hang)", elapsed < 20.0,
          "%.1fs" % elapsed)
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


_root_b = Path(tempfile.mkdtemp(prefix="l-s2t-bat-"))
try:
    _bat_success(_root_b)
    _bat_failure(_root_b)
    _bat_failure_no_old(_root_b)
    _bat_empty_stage(_root_b)
finally:
    shutil.rmtree(_root_b, ignore_errors=True)


# ==================== C. process_pending_update 不销毁证据 ====================
_root_c = Path(tempfile.mkdtemp(prefix="l-s2t-pending-"))
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
finally:
    shutil.rmtree(_root_c, ignore_errors=True)
    shutil.rmtree(_TMP_DATA, ignore_errors=True)

print("UPDATE SAFETY TEST " + ("FAILED: " + ",".join(FAILS) if FAILS else "OK"), flush=True)
sys.exit(1 if FAILS else 0)
