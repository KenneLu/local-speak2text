# -*- coding: utf-8 -*-
"""语言切换后菜单必须重画（CONFORMANCE E4-02；用户实测缺陷的回归）。

背景（2026-09-19 用户报告）：托盘有中英切换、通知也变成了英文，但再次右键菜单
仍是中文。根因在模板 i18n 包：`from .i18n import *` 把 `LANG` **拷贝**成静态副本，
`i18n.init('en')` 只改子模块真值；`_menu_signature()` 从包读到过期值 'zh' →
签名不变 → `MenuSignature` 判定"无需重建" → 菜单永远停在中文。模板 2.1.1 已把
包门面改为"不复制状态"（PEP 562 `__getattr__` 委派）+ `current_lang()` 访问器。

断言三条：
  ① **从包命名空间**读：`i18n.init('en')` 后 `i18n.LANG == 'en'`（旧包这里是 'zh'，
     这正是本 bug 的判据；只读子模块测不出来）；
  ② `t()` 跟随语言（通知路径，本来就没坏，一起钉住防回归）；
  ③ **`_menu_signature()` 的元组随语言变化**（"菜单会不会重画"的直接判据）：
     zh 的签名 == 切回 zh 的签名，且 != en 的签名。
"""
import os
import shutil
import sys
import tempfile
from pathlib import Path

# 实例隔离（F11/D12）：import main 之前重定向数据根，避免碰到用户真实 AppData。
_TMP = tempfile.mkdtemp(prefix="l-s2t-i18n-")
os.environ["LOCAL_SPEAK2TEXT_DATA_DIR"] = _TMP

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import main as M  # noqa: E402
from modules import i18n  # noqa: E402

FAILS = []


def check(name, ok, detail=""):
    print(("  ok  " if ok else "  FAIL") + " " + name + ("  " + detail if detail else ""),
          flush=True)
    if not ok:
        FAILS.append(name)


# ---------- ① 包命名空间读到的是真值（旧包会读到 'zh'） ----------
i18n.init("zh")
check("package reads zh after init(zh)", i18n.LANG == "zh", repr(i18n.LANG))
i18n.init("en")
check("package reads en after init(en)  <-- the reported bug", i18n.LANG == "en",
      repr(i18n.LANG))
check("accessor agrees with package", i18n.current_lang() == "en",
      repr(i18n.current_lang()))

# ---------- ② t() 跟随语言 ----------
check("t() follows the language", i18n.t("menu_quit") == "Quit",
      repr(i18n.t("menu_quit")))

# ---------- ②b 结构不变量：包命名空间不得绑 LANG（PEP 562 委派的前提） ----------
# 这一条比"读到 en"更根本：只要有人把 LANG 写回包里的 import，vars() 立刻多出它，
# 委派即失效、bug 结构性回归——即使当时的读取恰好还对。
impl = i18n.i18n   # 子模块（真值来源；包门面 via `from . import i18n` 暴露）
check("package namespace does not bind LANG (delegation intact)",
      "LANG" not in vars(i18n), repr(sorted(k for k in vars(i18n) if k == "LANG")))
check("package LANG tracks submodule truth", i18n.LANG == impl.LANG,
      "pkg=%r impl=%r" % (i18n.LANG, impl.LANG))
check("package TABLES is the submodule dict (containers not copied)",
      i18n.TABLES is impl.TABLES)

try:
    i18n.NO_SUCH_ATTRIBUTE  # noqa: B018
    _unknown_ok = False
except AttributeError:
    _unknown_ok = True
check("unknown attribute still raises AttributeError", _unknown_ok)

# ---------- ③ 菜单签名随语言变化（决定 MenuSignature 是否重画） ----------
# 用 object.__new__ 绕过 Tray.__init__（不创建 pystray 图标，headless 安全）；
# _menu_signature 只读 self.update_ready 与模块级状态。
tray = object.__new__(M.Tray)
tray.update_ready = None

i18n.init("zh")
sig_zh = M.Tray._menu_signature(tray)
i18n.init("en")
sig_en = M.Tray._menu_signature(tray)
i18n.init("zh")
sig_zh_again = M.Tray._menu_signature(tray)

check("signature language slot follows the package language",
      sig_zh[0] == "zh" and sig_en[0] == "en",
      "zh[0]=%r en[0]=%r" % (sig_zh[0], sig_en[0]))
check("signature CHANGES on zh -> en (menu rebuilds)",
      sig_zh != sig_en, "%r == %r" % (sig_zh, sig_en))
check("signature changes back on en -> zh",
      sig_en != sig_zh_again and sig_zh == sig_zh_again,
      "zh=%r en=%r zh2=%r" % (sig_zh, sig_en, sig_zh_again))

shutil.rmtree(_TMP, ignore_errors=True)
print("I18N MENU TEST "
      + ("FAILED: " + ",".join(FAILS) if FAILS else "OK"), flush=True)
sys.exit(1 if FAILS else 0)
