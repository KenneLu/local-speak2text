# -*- coding: utf-8 -*-
# TEMPLATE-FROM: _template/log_kit.py | TEMPLATE-VER: 1.0.0
"""运行日志：RotatingFileHandler 单文件 1MB、保留 3 个滚存（总量 ~4MB 封顶）。

参数与 reme-helper 的日志方案一致（ house 标准，见执行文档 D13）：
日志跟数据区走 %LOCALAPPDATA%\\<工具名>\\log\\，托盘/菜单通过 open_log_dir()
一键到达。任何日志失败都静默——日志永远不能把主流程弄死。
"""
import os

from paths import APP_ID, LOG_DIR

LOG_MAX_BYTES = 1 << 20      # 1 MB per file
LOG_BACKUPS = 3              # <app>.log.1 ... .3

_logger = None


def get_logger():
    global _logger
    if _logger is None:
        import logging
        from logging.handlers import RotatingFileHandler

        LOG_DIR.mkdir(parents=True, exist_ok=True)
        lg = logging.getLogger(APP_ID)
        if not lg.handlers:
            handler = RotatingFileHandler(
                LOG_DIR / (APP_ID + ".log"),
                maxBytes=LOG_MAX_BYTES,
                backupCount=LOG_BACKUPS,
                encoding="utf-8",
            )
            handler.setFormatter(
                logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
            lg.addHandler(handler)
            lg.setLevel(logging.INFO)
            lg.propagate = False
        _logger = lg
    return _logger


def log(message):
    """便捷入口：写一行 INFO。失败静默。"""
    try:
        get_logger().info(message)
    except Exception:
        pass


def open_log_dir():
    """打开日志目录（托盘「打开日志目录」项的落地动作）。"""
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    os.startfile(str(LOG_DIR))  # noqa: S606
