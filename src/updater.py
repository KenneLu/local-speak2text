# -*- coding: utf-8 -*-
# TEMPLATE-LOCAL-OVERRIDE: 本仓加固 fork（#32 切到模板模块后整体删除）
"""升级检查与自动升级：GitHub Releases API（稳定安装位变体）。

检查：GET {repo}/releases/latest，比对 tag 与 appconfig.VERSION，节流（默认 24h）。
升级：下载 zip + **强制 sha256 校验** → 解包暂存 → 写 update.pending.json →
托盘提示「退出后自动完成升级」→ 用户退出托盘时启动一次性替换脚本。

安全语义（2026-09-19 按 reme-helper 已验证更新链对齐）：
  * sha256 **期望值缺失即中止**（fail-closed）——拿不到 .sha256 就没有独立完整性依据，
    跳过校验等于把 HTTPS 之外的保障降级为零；
  * 替换脚本**等旧进程真正退出**（tasklist 写文件 + find 读文件，刻意不用管道：
    本脚本以 DETACHED 方式启动、无 console，`tasklist | find` 会永久阻塞）、带等待上限；
  * **替换前先快照当前安装目录，且只有拷贝成功才把快照轮转成 BACKUP**；
  * **robocopy rc >= 8 视为失败**：绝不再启动新 exe；从快照回铺并启动旧版；
    回铺也失败则**不启动任何 exe**、保留现场；
  * 失败写 `update.failed` marker，主程序下次启动读一次并提示（此时托盘已退出，
    只能下次说）——见 `pop_failed_update_note()`。

安全边界：只覆盖稳定安装位 INSTALL_DIR，不碰用户数据区里的 config/log；
暂存与日志在数据区，绝不在被替换的目录里。
"""
import hashlib
import json
import os
import shutil
import subprocess
import tempfile
import time
import urllib.error
import urllib.request
import zipfile
from pathlib import Path

from modules.appconfig import APP_ID, EXE_NAME, VERSION
from modules.paths import INSTALL_DIR, INSTALL_EXE, UPDATE_DIR, UPDATE_PENDING

CHECK_INTERVAL = 24 * 3600
STATE = {"checked_for": "", "latest": "", "at": 0.0, "asset_url": "", "asset_size": 0}

FAILED_MARKER_NAME = "update.failed"
# 等旧进程退出的上限：**轮询次数** × **每拍毫秒**（两个数必须一起看，别把次数当秒）。
#   `UPDATE_WAIT_LIMIT`   = 轮询次数
#   `UPDATE_WAIT_TICK_MS` = 每拍睡眠毫秒（脚本里由 `powershell Start-Sleep` 实现）
#   `UPDATE_WAIT_BUDGET_S`= 名义预算 = 次数 × 每拍 ÷ 1000（**下界**：每拍还要付 PowerShell 启动费）
#     ⚠️ 它只是**默认那一对**的取值；渲染进 bat 的预算一律由 `build_apply_script` 从
#     **实际传入的 `limit`** 现算，不得直接传这个常量（否则改了次数而预算文案不变）。
# ⚠️ 2026-09-19 缺陷（家族五份都在）：节拍原是 `ping -n 2 127.0.0.1`，本意“睡 1 秒”，在**丢弃
# loopback ICMP** 的机器上实测 **9.0 s/拍**（两次 4.5s 超时）→ 名义 120s 实际约 18 分钟，
# 而 `:giveup` 还打印 "after 120s"——**日志说谎**。教训：等待/超时的单位假设**必须实测量过**；
# 禁止 ping 当节拍已升级为机械判据 C-33。
UPDATE_WAIT_LIMIT = 120
UPDATE_WAIT_TICK_MS = 1000
UPDATE_WAIT_BUDGET_S = UPDATE_WAIT_LIMIT * UPDATE_WAIT_TICK_MS // 1000


def _repo_from_config(config_path):
    try:
        with open(config_path, "r", encoding="utf-8-sig") as f:
            return str(json.load(f).get("update_repo", "") or "")
    except Exception:
        return ""


def _tag_to_version(tag):
    return tag[1:] if tag.startswith("v") else tag


def _version_is_newer(latest, current):
    def nums(v):
        return [int(x) for x in v.split(".") if x.isdigit()]
    try:
        return nums(latest) > nums(current)
    except Exception:
        return False


def check_latest(repo, timeout=8.0):
    """返回 (tag, version)；网络失败抛异常。"""
    req = urllib.request.Request(
        f"https://api.github.com/repos/{repo}/releases/latest",
        headers={"Accept": "application/vnd.github+json", "User-Agent": APP_ID},
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    tag = str(data.get("tag_name") or "")
    if not tag:
        raise ValueError("no tag_name in release")
    return tag, _tag_to_version(tag)


def check_update(config_path, force=False):
    """节流检查。返回 dict(latest/current/newer/error)。"""
    repo = _repo_from_config(config_path)
    if not repo:
        return {"error": "no_repo", "latest": "", "current": VERSION, "newer": False}
    if (
        not force
        and STATE.get("checked_for") == VERSION
        and time.time() - STATE.get("at", 0) < CHECK_INTERVAL
    ):
        return {"latest": STATE["latest"], "current": VERSION,
                "newer": _version_is_newer(STATE["latest"], VERSION), "error": ""}
    try:
        tag, latest = check_latest(repo)
        STATE.update(checked_for=VERSION, latest=latest, at=time.time(), error="")
    except Exception as exc:
        STATE.update(checked_for=VERSION, at=time.time(), error=str(exc))
    newer = bool(STATE["latest"]) and _version_is_newer(STATE["latest"], VERSION)
    return {"latest": STATE.get("latest", ""), "current": VERSION, "newer": newer, "error": STATE.get("error", "")}


def _download(url, dest, timeout=60.0):
    req = urllib.request.Request(url, headers={"User-Agent": APP_ID})
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    with urllib.request.urlopen(req, timeout=timeout) as resp, open(dest, "wb") as f:
        while True:
            chunk = resp.read(1 << 16)
            if not chunk:
                break
            f.write(chunk)


def _sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def verify_zip_sha256(zip_path, sha_text):
    """校验下载包，返回 (ok, detail)。**期望值缺失也算失败**（绝不静默放行）。"""
    wanted = str(sha_text or "").strip()
    if not wanted:
        return False, "更新包缺少 .sha256 校验文件，已中止（无法校验完整性）"
    wanted = wanted.split()[0].strip().lower()
    actual = _sha256(str(zip_path)).lower()
    if wanted != actual:
        return False, ("更新包 sha256 不匹配（期望 %s… 实际 %s…）"
                       % (wanted[:12], actual[:12]))
    return True, ""


def _staged_dir(update_dir):
    """解包后的暂存目录：兼容 zip 带一层顶层目录与扁平两种打包方式。"""
    update_dir = Path(update_dir)
    if (update_dir / EXE_NAME).is_file():
        return update_dir
    for cand in sorted(update_dir.iterdir()):
        if cand.is_dir() and (cand / EXE_NAME).is_file():
            return cand
    return None


def download_update(config_path, latest, log=print):
    """下载对应版本的 zip（**强制** sha256 校验），解包到暂存目录。返回暂存目录路径。"""
    repo = _repo_from_config(config_path)
    if not repo:
        raise RuntimeError("no update_repo configured")
    base = f"https://github.com/{repo}/releases/download/v{latest}"
    stem = f"{APP_ID}-{latest}-windows-x64"
    zip_path = os.path.join(UPDATE_DIR, stem + ".zip")
    sha_path = zip_path + ".sha256"
    log("downloading", stem)
    _download(f"{base}/{stem}.zip", zip_path)
    try:
        _download(f"{base}/{stem}.zip.sha256", sha_path)
    except urllib.error.URLError as exc:
        raise RuntimeError(
            "发布页缺少 %s.zip.sha256 校验文件，已中止更新（无法校验完整性）：%s"
            % (stem, exc)) from exc
    ok, detail = verify_zip_sha256(zip_path, open(sha_path, "r", encoding="utf-8").read())
    if not ok:
        raise RuntimeError(detail)
    log("sha256 ok")
    with zipfile.ZipFile(zip_path) as z:
        z.extractall(UPDATE_DIR)
    staged = _staged_dir(UPDATE_DIR)
    if staged is None:
        raise RuntimeError("staged exe missing after extract: " + str(UPDATE_DIR))
    return str(staged)


# 替换脚本（ASCII-only：cmd 按机器 ANSI 代码页解析）。
# 刻意不用括号块（cmd 对块内 errorlevel 解析不可靠），全程 goto。
# 标签：:gone（铺新）→ :install_failed（回退）→ :install_dead（回退也失败，不启动）。
_APPLY_BAT = r"""@echo off
setlocal
set "TARGET={target}"
set "STAGE={stage}"
set "WORK={work}"
set "BACKUP={backup}"
set "SNAPSHOT={snapshot}"
set "FAILED={failed}"
set "LOG={log}"
echo [{stamp}] start target=%TARGET% backup=%BACKUP% >> "%LOG%"
set "POLL=%TEMP%\{app}-update-poll.txt"
set /a tries=0
:wait
rem NO PIPE HERE, on purpose: this script is spawned with DETACHED_PROCESS and has no
rem console; "tasklist | find" then NEVER RETURNS (find blocks on stdin forever) and the
rem update silently never happens. tasklist writes a file; find reads that file.
tasklist /fi "imagename eq {exe}" /nh > "%POLL%" 2>nul
rem ABSOLUTE PATH, never the bare name `find`: a bare name resolves by PATH order,
rem so the answer flips with the environment. Measured in two contexts, one probe:
rem   A) Git-Bash-derived PATH: `where find` hits Git's usr\bin\find.exe (GNU find)
rem      first; GNU find stats `/i` and the image name as PATHS, so it returns 1
rem      whether the process runs or not => `if errorlevel 1 goto gone` fires on the
rem      FIRST tick, the wait loop never waits and :giveup is unreachable.
rem   B) registry-merged PATH (what an explorer-launched app, and therefore this
rem      script spawned by it, actually inherits): System32\find.exe is first, and
rem      there the matcher is correct - 0 when the image name is present, 1 when
rem      it is absent.
rem So this is a PATH-ORDER-dependent LATENT defect, not a universally broken one.
rem The absolute path makes the outcome independent of PATH order: Windows' find is
rem the one this command line was written for. Correctness must not hinge on which
rem `find` happens to come first. Check: tests/test_poll_matcher.py (two poll files;
rem the two exit codes must DIFFER). NOTE: this template is written to disk as a
rem .bat and must stay ASCII-only (C-22) - that is also why this is English.
%SystemRoot%\System32\find.exe /i "{exe}" "%POLL%" >nul
if errorlevel 1 goto gone
set /a tries+=1
if %tries% geq {limit} goto giveup
rem Sleep one tick. NOT `ping -n 2 127.0.0.1`: that idiom means "1 second" only when
rem loopback ICMP answers - on a machine that drops it, each tick costs 2 x 4.5s
rem timeout = 9.0s (measured), so a nominal 120s budget really took ~18 minutes
rem while the log still said "120s". Start-Sleep is ICMP-free; it does pay a
rem PowerShell startup (~0.3s here, measured 1.29s per 1000ms tick), which is why
rem the timeout line below reports a lower bound instead of a precise total.
rem Spawned from a DETACHED_PROCESS bat, so the child has no console and no window
rem appears (same reason `tasklist`/`find` in this file stay windowless).
powershell -NoProfile -Command "Start-Sleep -Milliseconds {tick_ms}" >nul 2>nul
goto wait
:gone
rem Intercept an empty/incomplete stage BEFORE touching the install dir. robocopy from a
rem dir with no payload returns 0-7 - i.e. "success" by rc - and /purge would WIPE the
rem install dir; the old exe would be gone and the later start would hit a missing file,
rem popping a modal box in this detached, console-less script: it hangs forever.
if not exist "{stage_exe}" goto stage_invalid
rem Snapshot the CURRENT install first; the previous BACKUP is NOT deleted here - it is
rem the rollback source and is rotated only AFTER a copy that succeeded.
if not exist "%TARGET%" mkdir "%TARGET%"
if exist "%SNAPSHOT%" rmdir /s /q "%SNAPSHOT%"
robocopy "%TARGET%" "%SNAPSHOT%" /e /njh /njs /nfl /ndl >nul
echo [{stamp}] snapshot rc=%ERRORLEVEL% >> "%LOG%"
rem /purge removes files the previous version left behind.
robocopy "%STAGE%" "%TARGET%" /e /purge /njh /njs /nfl /ndl >> "%LOG%" 2>&1
set "RC=%ERRORLEVEL%"
echo [{stamp}] copied rc=%RC% >> "%LOG%"
if %RC% geq 8 goto install_failed
if exist "%BACKUP%" rmdir /s /q "%BACKUP%"
move /y "%SNAPSHOT%" "%BACKUP%" >nul 2>nul
del "{pending}" >nul 2>nul
rem Copy judged successful but no exe in TARGET: that is a failure, not a log line.
rem Starting a missing exe pops a MODAL box (no one can dismiss it in this detached,
rem console-less script), and silently falling through to :cleanup would delete WORK
rem and pending and destroy the scene. Align with :stage_invalid: marker + keep all.
if not exist "{newexe}" goto start_missing
start "" "{newexe}"
echo [{stamp}] done >> "%LOG%"
goto cleanup
:install_failed
rem robocopy: 0-7 = success, >=8 = failure. On failure NEVER start the new exe; restore
rem the previous install from the snapshot and start the old version instead.
> "{failed}" echo update failed {stamp}: install rc=%RC%
echo [{stamp}] INSTALL FAILED rc=%RC% - restoring from snapshot >> "%LOG%"
robocopy "%SNAPSHOT%" "%TARGET%" /e /purge /njh /njs /nfl /ndl >> "%LOG%" 2>&1
if errorlevel 8 goto install_dead
echo [{stamp}] restored - starting previous version >> "%LOG%"
rem Same guard as the success path: never start a missing exe (modal box, no console).
if not exist "{newexe}" echo [{stamp}] previous exe missing - not starting >> "%LOG%"
if exist "{newexe}" start "" "{newexe}"
goto cleanup_keep
:install_dead
echo [{stamp}] RESTORE FAILED - not starting; snapshot kept at %SNAPSHOT% >> "%LOG%"
goto cleanup_keep
:stage_invalid
rem Nothing was copied, so the install dir still holds the previous (working) version.
rem Report the failure and keep the staged files as evidence for manual inspection.
> "{failed}" echo update failed {stamp}: staged exe missing at %STAGE%
echo [{stamp}] STAGED EXE MISSING - install dir untouched, not starting >> "%LOG%"
goto cleanup_keep
:start_missing
rem The copy reported success but TARGET has no exe. Do not start (modal box) and do not
rem clean up: the rolled-out BACKUP and the staged WORK are the recovery material.
> "{failed}" echo update failed {stamp}: no exe in TARGET after copy
echo [{stamp}] NEW EXE MISSING AFTER COPY - not starting; kept WORK and BACKUP >> "%LOG%"
goto cleanup_keep
:giveup
rem Report the poll count and the per-tick sleep, not a fake "seconds" figure: the
rem real elapsed time is >= {limit} x {tick_ms}ms because every tick also pays a
rem PowerShell startup. The old wording said "after 120s" while it had actually
rem been waiting ~18 minutes - a log that lies is worse than no log.
echo [{stamp}] aborted: {exe} still running after %tries% polls x {tick_ms}ms (nominal budget {budget_s}s, lower bound) >> "%LOG%"
goto cleanup
:cleanup
rem Success path: drop the staged package (tens of MB) and the pending marker.
if exist "{pending}" del "{pending}" >nul 2>nul
if exist "%WORK%" rmdir /s /q "%WORK%"
goto cleanup_tail
:cleanup_keep
rem Keep WORK and SNAPSHOT for manual recovery; the marker notifies the user next start.
goto cleanup_tail
:cleanup_tail
del "%POLL%" >nul 2>nul
(goto) 2>nul & del "%~f0"
"""


def build_apply_script(target_dir, stage_dir, work_dir, backup_dir, log_path,
                       snapshot_dir, failed_marker, pending_path,
                       exe_name=EXE_NAME, limit=UPDATE_WAIT_LIMIT):
    """生成替换脚本文本（**纯函数**，便于回归断言其语义要点）。"""
    return _APPLY_BAT.format(
        target=target_dir, stage=stage_dir, work=work_dir, backup=backup_dir,
        snapshot=snapshot_dir, failed=failed_marker, log=log_path,
        pending=pending_path, app=APP_ID, exe=exe_name,
        stage_exe=os.path.join(str(stage_dir), exe_name),
        newexe=os.path.join(str(target_dir), exe_name),
        # budget_s **必须由同一次渲染实际使用的 limit/tick 算出**。旧写法传的是模块常量
        # `UPDATE_WAIT_BUDGET_S`，而次数用的是 `limit` 实参——于是 `limit=2` 会渲染出
        # 「2 polls x 1000ms (nominal budget 120s)」这种**自相矛盾**的日志。
        # 这正是本轮已立的口径：**日志里的数必须是被测过的数**（C-33 那次"日志说谎"的同族）。
        limit=limit, tick_ms=UPDATE_WAIT_TICK_MS,
        budget_s=limit * UPDATE_WAIT_TICK_MS // 1000,
        stamp=time.strftime("%Y-%m-%d %H:%M:%S"),
    )


def launch_pending_cmd(cmd=None, log=lambda *_a: None):
    """在退出收尾处拉起替换脚本，返回是否已拉起。

    必须**无控制台且脱离父进程**（`CREATE_NO_WINDOW | DETACHED_PROCESS`，reme 形态）：
    本进程马上就要退出，bat 要活到替换完成；若它挂着控制台，用户桌面会闪黑框。
    旧写法 `os.system('start "" /min ...')` 会经由 cmd 起一个控制台——正是要消除的那一下。
    """
    if not cmd or os.name != "nt":
        return False
    flags = (getattr(subprocess, "CREATE_NO_WINDOW", 0)
             | getattr(subprocess, "DETACHED_PROCESS", 0))
    try:
        subprocess.Popen(["cmd.exe", "/c", str(cmd)], creationflags=flags, close_fds=True)
    except OSError as exc:
        log("launch pending failed: %s" % exc)
        return False
    log("pending update launched: %s" % cmd)
    return True


def failed_marker_path(update_dir=None):
    """失败 marker 位置：数据区一眼可见，且与会被删的暂存目录分开。"""
    return Path(update_dir or UPDATE_DIR).parent / FAILED_MARKER_NAME


def pop_failed_update_note(update_dir=None, log=lambda *a: None):
    """读一次"上次更新失败"的 marker，返回人话（无 marker 则空串），并删除 marker。

    **顺序：先算好文案 → 再报告 → 最后才删证据**（2026-09-19 修）。
    旧写法把 `marker.unlink()` 与 `read_text()` 放在**同一个 try** 里，于是 unlink 抛
    OSError（marker 被 Defender/索引器短暂锁住——本仓库实测过这类瞬时锁）会走 except
    分支直接 `return ""`：**detail 明明已经读到了，用户却看不到升级失败提示**，
    只因为"删证据"这一步失败。删不掉不该惩罚读者。
    """
    marker = failed_marker_path(update_dir)
    try:
        if not marker.is_file():
            return ""
        detail = marker.read_text(encoding="utf-8", errors="replace").strip()
        note = ("上次自动更新失败，已回退到原版本并保留现场；详见 update.log"
                + (("（%s）" % detail) if detail else ""))
    except OSError as exc:
        log("failed-update marker read error:", exc)
        return ""
    log("previous update failed:", detail)
    # 最后一步、且独立 try：删不掉就留给下次启动再报一次——
    # 比"吞掉提示"或"吞掉证据"都好。
    try:
        marker.unlink()
    except OSError as exc:
        log("failed-update marker not removed (will report again):", exc)
    return note


def prepare_update_cmd(staged_dir, target_dir=None, update_dir=None,
                       exe_name=EXE_NAME, log=print):
    """下载解包完成后调用：生成退出时执行的一次性替换脚本，返回脚本路径。

    目标 = 稳定安装位 INSTALL_DIR（自启注册表指向的路径，更新整目录替换后路径不变）。
    脚本放 %TEMP%（不能放暂存目录：收尾要删它，正在执行的脚本会被锁）。
    """
    target_dir = Path(target_dir or INSTALL_DIR)
    update_dir = Path(update_dir or UPDATE_DIR)
    staged = Path(staged_dir)
    if not (staged / exe_name).is_file():
        raise RuntimeError("staged exe missing: " + str(staged / exe_name))
    os.makedirs(update_dir, exist_ok=True)
    pending_path = UPDATE_PENDING
    pending_path.write_text(
        json.dumps({"staged": str(staged), "target": str(target_dir)}, ensure_ascii=False),
        encoding="utf-8")
    script = build_apply_script(
        target_dir, staged, update_dir,
        backup_dir=update_dir.parent / "_backup",
        log_path=update_dir.parent / "update.log",
        snapshot_dir=update_dir.parent / "_backup.pre",
        failed_marker=failed_marker_path(update_dir),
        pending_path=pending_path, exe_name=exe_name)
    cmd_path = Path(tempfile.gettempdir()) / f"{APP_ID}-update.bat"
    try:
        # cmd.exe 按机器 ANSI 代码页解析 .bat ⇒ 按 ANSI 落盘（路径可能含中文）
        cmd_path.write_text(script, encoding="mbcs", errors="replace")
    except (LookupError, UnicodeError):
        cmd_path.write_text(script, encoding="utf-8")
    log("update staged:", str(staged), "->", str(target_dir), "(bat %s)" % cmd_path)
    return str(cmd_path)


def process_pending_update(pending_path=None, update_dir=None, log=lambda *a: None):
    """启动兜底：处理退出时没跑完的更新（上一次替换脚本被打断等）。

    **失败绝不销毁证据**：robocopy rc >= 8 时不动 pending、不动 update_dir，
    并写 update.failed marker 供下次启动提示（旧实现在失败时照样删 pending 与
    整个 update 目录，把暂存源和失败证据一起清掉）。
    """
    pending_path = Path(pending_path or UPDATE_PENDING)
    update_dir = Path(update_dir or UPDATE_DIR)
    if not pending_path.exists():
        return False
    try:
        info = json.loads(pending_path.read_text(encoding="utf-8"))
        staged = Path(info["staged"])
        target = Path(info["target"])
    except Exception as exc:
        log("pending update unreadable:", exc)
        return False
    if not (staged.is_dir() and target.is_dir()):
        log("pending update incomplete; keeping for diagnosis")
        return False
    rc = subprocess.run(
        ["robocopy", str(staged), str(target), "/e", "/purge",
         "/njh", "/njs", "/nfl", "/ndl"],
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    ).returncode
    if rc >= 8:
        marker = failed_marker_path(update_dir)
        try:
            marker.write_text("update failed: startup fallback rc=%d" % rc, encoding="utf-8")
        except OSError:
            pass
        log("pending update failed rc=%s; keeping staged files" % rc)
        return False
    pending_path.unlink(missing_ok=True)
    shutil.rmtree(update_dir, ignore_errors=True)
    return True
