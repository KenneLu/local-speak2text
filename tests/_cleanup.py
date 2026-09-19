# -*- coding: utf-8 -*-
"""测试临时目录清理：先放句柄、再删、删后回读；删不掉就返回 False（由测试变红）。

为什么需要它（实测，不是推测）：
  `%TEMP%` 里积了 9 个 `l-s2t-*` 残留，签名高度一致——残留物只有
  `<TMP>/<app>/log/<app>.log`，有时再加一个刚写完的 `config.json`。
  两个成因都成立：
    ① `log_kit` 的 `RotatingFileHandler` 持有日志文件；Windows 下 Python 的
       `open()` **不带 FILE_SHARE_DELETE**，被打开的文件删不掉；
    ② 刚写完的 `config.json` 会被 Defender / 索引器短暂占用（瞬时锁，重试即过）。
  `shutil.rmtree(..., ignore_errors=True)` 把这两种"删不动"都变成"看起来成功"，
  于是泄漏无声积累（每跑一轮门禁就多几个目录）。本模块把"删干净"变成可断言的结论。

用法（在每个建了 `mkdtemp` 的测试末尾）：
    check("temp dir cleaned up (no %TEMP% leak)", rmtree_cleanup(_TMP), str(_TMP))

并加**兜底**（2026-09-19）：末尾那行只在测试跑到底时才执行。测试若是**中途抛异常**
（本文件头部记的那次 `TypeError` 崩溃就是活例：一次留 4 个目录），清理行根本轮不到。
故 `scratch_dir()` 建的根统一登记，`atexit` 兜底回收，且**回收时必须打印证据行**——
静默兜底等于 `rmtree(..., ignore_errors=True)`，同一个病。
"""
import atexit
import logging
import os
import shutil
import stat
import sys
import tempfile
import time
from pathlib import Path

# R2（2026-09-19 lead 裁定）：测试/探针的临时目录一律放 `H:\Tools\_verify-scratch\`，
# 不得在系统 `%TEMP%` 里留家族前缀的目录。可用 LS2T_SCRATCH_DIR 覆盖（CI 用）。
_SCRATCH_ENV = "LS2T_SCRATCH_DIR"
_DEFAULT_SCRATCH = r"H:\Tools\_verify-scratch"


def harden_stdout():
    """让 `print` 在中文 Windows 控制台（GBK）上**永不因编码而崩**。

    真实事故：替换脚本把 `robocopy` 的输出 `>>` 进日志，而 robocopy 在中文系统上
    用 **GBK** 输出本地化错误（"目录名无效"）。测试按 utf-8 读日志 → 不可解字节变成
    `U+FFFD`；再把这段文字打进 GBK 控制台 → `UnicodeEncodeError` 直接**中断测试**，
    于是"断言失败"变成了"测试崩在打印上"，后面的用例全不跑、清理也不跑。
    `errors="replace"` 保编码不变，只把不可编码字符降级为 `?`。
    """
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(errors="replace")
        except (AttributeError, ValueError):
            pass


# 四个测试都 import 本模块；在这里统一生效，免得有人忘了调。
harden_stdout()

# 登记表：scratch_dir 建的根 → 前缀。rmtree_cleanup 删成功即注销。
_LIVE = {}
# 兜底回收过的根（崩溃证据）。测试可断言它为空——非空即"有测试崩溃过"。
SWEPT = []


def _atexit_sweep():
    """解释器退出时兜掉未清理的 scratch 根，**并打印证据行**。

    覆盖范围：异常 / `sys.exit()` / 正常走到结尾。比逐测试 `try/finally` 更宽——
    后者只在有 `try` 包裹时才成立，而本仓测试是**模块级脚本**，没有包裹点。
    两者对"硬崩溃"（native 段错误、被 kill）都无效，`atexit` 不更差。
    打印而非静默：静默兜底无法与"本来就干净"区分（C-30 的同一课）。
    """
    try:
        pending = [p for p in list(_LIVE) if os.path.exists(p)]
        for p in pending:
            rmtree_cleanup(p)          # 成功即从 _LIVE 注销
        still = [p for p in pending if os.path.exists(p)]
        SWEPT.extend(pending)
        if pending:
            print("[LEAK-SWEPT] 测试未清理 %d 个 scratch 根（多半中途抛异常）：%s"
                  % (len(pending), pending), flush=True)
        if still:
            print("[LEAK-SWEPT] 兜底仍删不掉（真残留）：%s" % (still,), flush=True)
    except Exception as exc:            # 兜底自身绝不能再抛
        print("[LEAK-SWEPT] 兜底清理自身出错: %r" % (exc,), flush=True)


atexit.register(_atexit_sweep)


def scratch_dir(prefix):
    """建一个测试临时根：优先 `H:\\Tools\\_verify-scratch\\`，不可用才回落 `%TEMP%`。

    回落也必须能被 `rmtree_cleanup` 删干净——泄漏判据与位置无关。
    建好即登记，供 `_atexit_sweep` 兜底。
    """
    base = os.environ.get(_SCRATCH_ENV) or _DEFAULT_SCRATCH
    try:
        p = Path(base)
        p.mkdir(parents=True, exist_ok=True)
        made = tempfile.mkdtemp(prefix=prefix, dir=str(p))
    except Exception:
        made = tempfile.mkdtemp(prefix=prefix)
    _LIVE[str(made)] = prefix
    return made


def _drop_log_handlers():
    """close 并摘掉所有 logging handler——释放 RotatingFileHandler 占住的日志文件。

    只 `logging.shutdown()` 不够：它 close 掉 handler 但仍留在 logger.handlers 里，
    且 log_kit 惰性缓存的 logger 对象还在；这里两件事都做，幂等。
    """
    for name in list(logging.Logger.manager.loggerDict):
        try:
            lg = logging.getLogger(name)
        except Exception:
            continue
        for h in lg.handlers[:]:
            try:
                h.close()
            except Exception:
                pass
            try:
                lg.removeHandler(h)
            except Exception:
                pass
    try:
        logging.shutdown()
    except Exception:
        pass


def clear_readonly(path):
    """递归清掉只读位——只读文件在 Windows 上删不掉（`os.unlink` → PermissionError）。

    测试**故意**把假 exe 设成只读当保险（见 test_update_safety），所以清理前必须
    先解开，否则"零残留"断言会红。

    用 `os.chmod` 而不是起 `attrib.exe`：**不产生任何子进程**。构建机上起一个控制台
    子进程会在用户桌面闪一下黑框——那正是本家族反复在治的那类事故，能用 API 就别起进程。
    实测：`os.chmod(p, stat.S_IREAD)` → 模式 `0o100444`，`os.remove` 报 PermissionError；
    `os.chmod(p, stat.S_IWRITE)` 后即可删除。
    """
    root = Path(path)
    if not root.exists():
        return
    for p in [root, *root.rglob("*")]:
        try:
            os.chmod(p, stat.S_IWRITE)
        except OSError:
            pass


def rmtree_cleanup(path, tries=10, delay=0.2):
    """删掉测试临时目录；**返回 True 仅当删后回读确认不存在**。

    先解只读、再放句柄、再删；对瞬时锁重试；每次重试前都重做前两步（句柄可能在
    删除过程中被重新建立——log_kit 的 `get_logger` 是惰性 + 模块级缓存）。
    删成功即从 `_LIVE` 注销，`_atexit_sweep` 便不会再报它。
    """
    path = str(path)
    for _ in range(max(1, tries)):
        clear_readonly(path)
        _drop_log_handlers()
        shutil.rmtree(path, ignore_errors=True)
        if not os.path.exists(path):
            _LIVE.pop(path, None)
            return True
        time.sleep(delay)
    ok = not os.path.exists(path)
    if ok:
        _LIVE.pop(path, None)
    return ok
