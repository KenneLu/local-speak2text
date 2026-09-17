# -*- coding: utf-8 -*-
"""升级检查与自动升级：GitHub Releases API。

检查：GET {repo}/releases/latest，比对 tag 与 paths.VERSION，节流（默认 24h）。
升级：下载 zip + sha256 → 校验 → 解包暂存 → 写 update.pending.json → 托盘提示
「退出后自动完成升级」→ 用户退出托盘时主程序生成一次性 .cmd 做整目录替换。

安全边界：只覆盖 exe 所在目录（APP_DIR），不碰用户数据区；sha256 不匹配即中止。
"""
import hashlib
import json
import os
import time
import urllib.request
import zipfile

from paths import APP_DIR, UPDATE_DIR, UPDATE_PENDING, VERSION

CHECK_INTERVAL = 24 * 3600
STATE = {"checked_for": "", "latest": "", "at": 0.0, "asset_url": "", "asset_size": 0}


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


def download_update(config_path, latest, log=print):
    """下载对应版本的 zip（带 sha256 校验），解包到暂存目录。成功返回暂存目录路径。"""
    repo = _repo_from_config(config_path)
    if not repo:
        raise RuntimeError("no update_repo configured")
    base = f"https://github.com/{repo}/releases/download/v{latest}"
    stem = f"{APP_ID_PKG}-{latest}-windows-x64"
    zip_path = os.path.join(UPDATE_DIR, stem + ".zip")
    sha_path = zip_path + ".sha256"
    log("downloading", stem)
    _download(f"{base}/{stem}.zip", zip_path)
    try:
        _download(f"{base}/{stem}.zip.sha256", sha_path)
        expected = open(sha_path, "r", encoding="utf-8").read().split()[0].lower()
        actual = _sha256(zip_path).lower()
        if expected != actual:
            raise RuntimeError(f"sha256 mismatch: {actual}")
        log("sha256 ok")
    except FileNotFoundError:
        log("no sha256 file, skip verify")
    with zipfile.ZipFile(zip_path) as z:
        z.extractall(UPDATE_DIR)
    return os.path.join(UPDATE_DIR, APP_ID_PKG)


def prepare_update_cmd(staged_dir):
    """下载解包完成后调用：生成退出时执行的一次性安装脚本，返回脚本路径。

    目标是稳定安装位 INSTALL_DIR（自启注册表指向的路径，永不变）：
    用户退出托盘 -> main() finally 里 start 该脚本 -> 等本进程退出 ->
    robocopy 整目录镜像到 INSTALL_DIR -> 从 INSTALL_DIR 启动新 exe。
    首次安装时 INSTALL_DIR 还不存在，脚本先 mkdir 再 robocopy。
    """
    os.makedirs(UPDATE_DIR, exist_ok=True)
    exe = os.path.join(staged_dir, APP_ID_PKG + ".exe")
    if not os.path.exists(exe):
        raise RuntimeError("staged exe missing: " + exe)
    from paths import INSTALL_DIR, INSTALL_EXE

    UPDATE_PENDING.write_text(
        json.dumps({"staged": staged_dir, "target": str(INSTALL_DIR)}, ensure_ascii=False),
        encoding="utf-8",
    )
    cmd_path = os.path.join(UPDATE_DIR, "apply.cmd")
    script = (
        "@echo off\r\n"
        "if not exist \"%TARGET%\" mkdir \"%TARGET%\"\r\n"
        "timeout /t 2 /nobreak >nul\r\n"
        "robocopy \"%STAGED%\" \"%TARGET%\" /MIR /R:1 /W:1 /NFL /NDL /NP >nul\r\n"
        "del \"%APPDATA_MARK%\"\r\n"
        "start \"\" \"%NEWEXE%\"\r\n"
        "del \"%~f0\"\r\n"
    ).replace("%STAGED%", staged_dir).replace("%TARGET%", str(INSTALL_DIR)).replace("%APPDATA_MARK%", str(UPDATE_PENDING)).replace("%NEWEXE%", str(INSTALL_EXE))
    with open(cmd_path, "w", encoding="ascii") as f:
        f.write(script)
    return cmd_path
