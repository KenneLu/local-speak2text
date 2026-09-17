# -*- coding: utf-8 -*-
"""路径与版本单一事实源。

四个位置，职责分明（同 reme-helper 的设计）：
  APP_DIR         程序本体：打包后 = exe 所在目录；开发态 = 仓库根。模型目录也住这儿
                  （2GB+ 的大文件不适合放用户数据区，且打包版用相对路径指回工程）。
  RUN_DIR         「这次运行的这个包」的根：图标等静态资源、构建诊断输出。
  USER_DATA_DIR   用户数据：%LOCALAPPDATA%\\local-speak2text\\（config.json + log\\）。
                  理由：应用运行时 exe 旁边的文件会被锁（构建清不干净、原地更新要整目录替换）。
  CONFIG_PATH     USER_DATA_DIR\\config.json。旧位置（exe 旁边）只在首次播种时迁移一次。
"""
import os
import shutil
import sys
from pathlib import Path

APP_ID = "local-speak2text"
APP_NAME = "LocalSpeak2Text"
VERSION = "1.1.0"

if getattr(sys, "frozen", False):
    APP_DIR = Path(sys.executable).resolve().parent
else:
    APP_DIR = Path(__file__).resolve().parent
RUN_DIR = APP_DIR

USER_DATA_DIR = Path(
    os.environ.get("LOCALAPPDATA") or os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share"
) / APP_ID

# 测试/便携覆盖：环境变量显式指定配置文件位置
CONFIG_PATH = (
    Path(os.environ["LOCALSPEAK2TEXT_CONFIG"]).expanduser()
    if os.environ.get("LOCALSPEAK2TEXT_CONFIG")
    else USER_DATA_DIR / "config.json"
)
# 旧位置：exe/仓库根旁边的 config.json（历史版本的位置），仅播种时读一次
LEGACY_CONFIG_PATH = APP_DIR / "config.json"

LOG_DIR = USER_DATA_DIR / "log"
LOG_PATH = LOG_DIR / (APP_ID + ".log")
UPDATE_DIR = USER_DATA_DIR / "update"
UPDATE_PENDING = RUN_DIR / "update.pending.json"

TRAY_ICON_PATH = RUN_DIR / f"{APP_ID}.ico"
TASKBAR_ICON_PATH = RUN_DIR / f"{APP_ID}-taskbar.ico"


def ensure_user_dirs():
    USER_DATA_DIR.mkdir(parents=True, exist_ok=True)
    LOG_DIR.mkdir(parents=True, exist_ok=True)


def seed_config():
    """首次运行（AppData 里还没有 config.json）时，从旧位置迁移一份作初始配置。"""
    ensure_user_dirs()
    if CONFIG_PATH.exists():
        return CONFIG_PATH
    try:
        if LEGACY_CONFIG_PATH.exists():
            shutil.copyfile(LEGACY_CONFIG_PATH, CONFIG_PATH)
    except OSError:
        pass
    return CONFIG_PATH


def process_pending_update():
    """启动时处理上次会话遗留的更新任务（正常路径是退出时的批处理完成的兜底）。"""
    if not UPDATE_PENDING.exists():
        return False
    try:
        import json

        info = json.loads(UPDATE_PENDING.read_text(encoding="utf-8"))
        staged = Path(info["staged"])
        target = Path(info["target"])
        if staged.is_dir() and target.is_dir():
            os.system(f'robocopy "{staged}" "{target}" /MIR /R:1 /W:1 /NFL /NDL /NP >nul')
        UPDATE_PENDING.unlink(missing_ok=True)
        shutil.rmtree(UPDATE_DIR, ignore_errors=True)
        return True
    except Exception:
        return False
