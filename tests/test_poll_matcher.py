# -*- coding: utf-8 -*-
"""`apply.bat` 的轮询判据必须具备**判别力**：进程在跑 ⇒ 匹配成功；不在 ⇒ 匹配失败。

缺陷形态（`src/updater.py` 的 `_APPLY_BAT`，渲染后）：
    tasklist /fi "imagename eq {exe}" /nh > "%POLL%" 2>nul
    find /i "{exe}" "%POLL%" >nul
    if errorlevel 1 goto gone
`find` 写的是**裸名**。裸名解析**取决于 PATH 顺序**，于是这条命令的判别力**随上下文翻转**。
两个上下文我都实测过（同一份 `probe.bat`，只有 PATH 不同）：
  * **上下文 A（Git-Bash 派生 PATH）**：`where find` 首命中 `H:\\Tools\\Git\\usr\\bin\\find.exe`
    （GNU find）。GNU find 把 `/i` 与镜像名都当**路径**去 stat ⇒ **含与不含镜像名都返回 1**
    （`find: '/i': No such file or directory`），**判别力为零**。此时 `if errorlevel 1 goto gone`
    第一拍就跳走、`%tries%` 恒为 1、`:giveup` 不可达，"等旧进程退出"整个消失。
  * **上下文 B（注册表合并 PATH = explorer 启动的应用、以及它 spawn 的 `apply.bat` 实际继承的
    环境）**：首命中 `C:\\Windows\\System32\\find.exe`（Windows find，`/i "串" 文件` 正是它的
    用法）⇒ **命中 0 / 未命中 1，判别力正常**。

⚠️ 准确的定性因此是：**这是一条"取决于 PATH 顺序"的潜伏缺陷，不是生产环境恒坏的缺陷。**
我的第一版证据取自上下文 A（bash 会把自己的 `usr\\bin` 前置），当时误当成普适结论；补测
上下文 B 后修正。修法（改用绝对路径）**依然正确且更有价值**：判别力从此**不再依赖 PATH 顺序**
（本机 msys64 的 GNU find 就排在 System32 之后，任何 PATH 编辑都可能把它翻上来），
这条命令的行为被钉成上下文无关。

**判据为什么这样写**：不去断言 bat 文本里"有没有绝对路径"（那是绑实现形态），
而是**直接量这条命令的判别力**——喂它两份 poll 文件（一份含镜像名、一份不含），
两条返回码**必须不同**。修前在上下文 A 里两条都是 1（红）；修后 0 / 1（绿），
且**两个上下文一致**（因为已是绝对路径）。
这份测试不依赖"此刻系统里恰好有哪些进程在跑"，因此可复现。

隔离：不写用户数据区；探针文件与 poll 文件都落在 `scratch_dir` 里。
"""
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

from _cleanup import rmtree_cleanup, scratch_dir  # noqa: E402

_TMP = scratch_dir("l-s2t-poll-")
os.environ["LOCAL_SPEAK2TEXT_DATA_DIR"] = _TMP
os.environ["LOCAL_SPEAK2TEXT_CONFIG"] = str(Path(_TMP) / "config.json")

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import updater as U  # noqa: E402

FAILS = []


def check(name, ok, detail=""):
    print(("  ok  " if ok else "  FAIL") + " " + name + ("  " + detail if detail else ""),
          flush=True)
    if not ok:
        FAILS.append(name)


# ---------- 渲染一份 apply.bat，取出那条匹配命令 ----------
_bat = U.build_apply_script(
    target_dir=str(Path(_TMP) / "t"), stage_dir=str(Path(_TMP) / "s"),
    work_dir=str(Path(_TMP) / "w"), backup_dir=str(Path(_TMP) / "b"),
    log_path=str(Path(_TMP) / "l.log"), snapshot_dir=str(Path(_TMP) / "snap"),
    failed_marker=str(Path(_TMP) / "f.marker"), pending_path=str(Path(_TMP) / "p.json"),
    exe_name="probe.exe", limit=2)

# ⚠️ 定位**不能**按命令拼写（`find /i`）来找——那会把判据绑死在实现形态上：
# 修复正是把裸名换成绝对路径，按拼写找会当场红成"找不到命令行"（我第一次就这么红的）。
# 锚在**这行在做什么**：它读 `%POLL%`（tasklist 写下的结果）、带 `/i`（忽略大小写）。
_match_line = None
for _line in _bat.split("\n"):
    low = _line.lower()
    if "%poll%" in low and "/i" in low and "tasklist" not in low:
        _match_line = _line.strip()
        break

check("the rendered script has a poll-matcher line (reads %POLL% with /i)",
      _match_line is not None, repr(_match_line))

if _match_line is None:
    check("temp dir cleaned up", rmtree_cleanup(_TMP), str(_TMP))
    print("POLL MATCHER TEST FAILED: find line not found", flush=True)
    sys.exit(1)

# ---------- 两份 poll 文件：一份含镜像名，一份不含 ----------
_poll_hit = Path(_TMP) / "poll_hit.txt"
_poll_miss = Path(_TMP) / "poll_miss.txt"
_poll_hit.write_bytes(b"probe.exe   1234 Console   1   10,000 K\r\n")
_poll_miss.write_bytes(b"other.exe   5678 Console   1   10,000 K\r\n")


def run_matcher(poll_path, shadow_dir=None, line_override=None):
    """在真实 cmd.exe 里跑那条匹配命令，返回 (rc, stderr)。

    `shadow_dir` 非空时把它**前置**到子进程的 PATH——用于人为构造"一个 `find`
    排在前面"的世界（见下方"抢占世界"一节）；`line_override` 用来跑对照组。
    """
    line = line_override if line_override is not None else _match_line
    line = line.replace("%POLL%", str(poll_path)).replace('"%POLL%"', '"%s"' % poll_path)
    bat = Path(_TMP) / ("probe_%s.bat" % poll_path.stem)
    bat.write_bytes(("@echo off\r\n" + line + "\r\necho RC=%errorlevel%\r\n").encode("ascii"))
    env = None
    if shadow_dir is not None:
        env = dict(os.environ)
        env["PATH"] = str(shadow_dir) + os.pathsep + env.get("PATH", "")
    r = subprocess.run(["cmd.exe", "/c", str(bat)], capture_output=True, timeout=120,
                       encoding="oem", errors="replace", env=env)
    out = (r.stdout or "") + (r.stderr or "")
    m = re.search(r"RC=(\d+)", out)
    return (int(m.group(1)) if m else None), out.strip()


# ---------- 抢占世界：把"PATH 顺序变了"变成一条**环境无关**的判据 ----------
# 为什么需要它：本测试的第一次版本继承**调用者 shell** 的 PATH，于是它的红/绿取决于
# "谁跑 build.bat"——从 Git-Bash 跑（usr\bin 被前置）会红，从 cmd 跑（System32 在前）
# 即使把修复回退成裸名**也照样绿**，回归门禁形同虚设。
# 做法：自己造一个目录，里面放一个**不是 System32 那个**的 `find.exe`，前置到子进程
# PATH ⇒ 裸名必然解析到它，绝对路径必然无视它。于是"这条命令是否依赖 PATH 顺序"
# 变成可复现的断言，与跑测试的 shell 无关。
#
# ⚠️ 抢占件必须是**真 .exe**，不能是 `find.bat`：批处理之间无 `call` 调用会**接管控制权**
# 不返回，于是被它"劫持"的那条命令之后的所有行（含 `echo RC=`）都不会执行，读数变成
# 空值——我第一版就是这样，而且 `None != 0` 让断言**假绿**通过。这是"0 命中其实是没扫到"
# 的新变体：**任何 `is not None` 都没写的比较，都要怀疑**。


def _find_shadow_source():
    """找一个"不是 System32 那个"的 find.exe 来真实构造抢占世界。

    首选真 GNU find（本家族的机器都有 Git）：它正是真实事故里抢到解析权的那一个。
    退路是 `cmd.exe` 的副本（任何 Windows 都在，且它被当 find 用时同样**无判别力**）。
    """
    sys32 = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32"
    # 1) 由 `git` 反推它旁边的 usr\bin（Git-Bash 的 find 就在那儿）
    try:
        r = subprocess.run(["where", "git"], capture_output=True, timeout=30,
                           encoding="oem", errors="replace")
        for ln in (r.stdout or "").splitlines():
            ln = ln.strip()
            if ln.lower().endswith("git.exe"):
                cand = Path(ln).parent.parent / "usr" / "bin" / "find.exe"
                if cand.is_file():
                    return str(cand), "real GNU find next to git: %s" % cand
    except Exception:
        pass
    # 2) PATH 上任何一个不在 System32 的 find.exe
    for entry in os.environ.get("PATH", "").split(os.pathsep):
        if not entry:
            continue
        cand = Path(entry) / "find.exe"
        try:
            if cand.is_file() and cand.parent.resolve() != sys32.resolve():
                return str(cand), "find.exe shadowing System32 on PATH: %s" % cand
        except OSError:
            pass
    # 3) 兜底：cmd.exe 的副本（真 exe，被当 find 用时两种输入同码）
    cmd = sys32 / "cmd.exe"
    if cmd.is_file():
        return str(cmd), "fallback: a copy of cmd.exe used as find.exe"
    return None, "no shadow source available"


_SHADOW = Path(_TMP) / "shadow"
_SHADOW.mkdir()
_shadow_src, _shadow_why = _find_shadow_source()
if _shadow_src:
    shutil.copy2(_shadow_src, _SHADOW / "find.exe")

check("control: a shadowing `find.exe` could be installed (else this section is vacuous)",
      _shadow_src is not None and (_SHADOW / "find.exe").is_file(), _shadow_why)

# 对照组同时是**自证**：抢占件若没真的赢下解析权，下面这条就会红——防止"抢占没生效、
# 判据空真"这种假绿。注意每个比较都写了 `is not None`：**空读数绝不能算通过**。
_bare_line = "find /i \"probe.exe\" \"%POLL%\" >nul"
_ctl_hit, _ctl_hit_out = run_matcher(_poll_hit, _SHADOW, _bare_line)
_ctl_miss, _ctl_miss_out = run_matcher(_poll_miss, _SHADOW, _bare_line)
check("control: the shadow really wins for a bare name (it stops discriminating)",
      _ctl_hit is not None and _ctl_miss is not None and _ctl_hit == _ctl_miss,
      "bare-name under shadow: hit=%s miss=%s  %s"
      % (_ctl_hit, _ctl_miss, (_ctl_hit_out or "")[:70]))

rc_hit, out_hit = run_matcher(_poll_hit)
rc_miss, out_miss = run_matcher(_poll_miss)
rc_hit_sh, out_hit_sh = run_matcher(_poll_hit, _SHADOW)
rc_miss_sh, out_miss_sh = run_matcher(_poll_miss, _SHADOW)

check("matcher reports a hit when the image name IS in the poll output",
      rc_hit == 0, "rc=%s  %s" % (rc_hit, out_hit[:90]))
check("matcher reports a miss when the image name is NOT in the poll output",
      rc_miss is not None and rc_miss != 0, "rc=%s  %s" % (rc_miss, out_miss[:90]))
# 这条是**判别力**本身：两种情况必须给出不同的返回码，否则调用方无法据它决定
# "还要不要继续等"（这正是本缺陷的机理：两种情况同码）。
check("the matcher has DISCRIMINATING POWER (hit rc != miss rc)",
      rc_hit is not None and rc_miss is not None and rc_hit != rc_miss,
      "hit rc=%s  miss rc=%s" % (rc_hit, rc_miss))
# 关键一条：把"有一个 find 排在前面"这个变量加进来，结论必须**一字不变**。
# 裸名做不到（对照组已证），绝对路径做得到 —— 这就是"不依赖 PATH 顺序"的操作化定义，
# 也是这条门禁**不再取决于谁跑的 build.bat** 的原因。
check("shadowing a `find` does NOT change the verdict (PATH-order independence)",
      rc_hit_sh is not None and rc_miss_sh is not None
      and rc_hit_sh == rc_hit and rc_miss_sh == rc_miss,
      "prod=%s/%s  shadowed=%s/%s" % (rc_hit, rc_miss, rc_hit_sh, rc_miss_sh))
check("still discriminating under the shadow",
      rc_hit_sh is not None and rc_miss_sh is not None and rc_hit_sh != rc_miss_sh,
      "hit rc=%s  miss rc=%s" % (rc_hit_sh, rc_miss_sh))

check("temp dir cleaned up (no %TEMP% leak)", rmtree_cleanup(_TMP), str(_TMP))
print("POLL MATCHER TEST " + ("FAILED: " + ",".join(FAILS) if FAILS else "OK"), flush=True)
sys.exit(1 if FAILS else 0)
