# -*- coding: utf-8 -*-
"""#47：`main` 侧的模型目录必须是**冻结副本的反面**（取用时的值，不是导入时的）。

缺陷形态（`src/main.py:36-45`）：
    from pipeline import (AsrEngine, CONFIG_PATH, MODEL_DIR, MODEL_NAME, ...)
`from ... import X` 把 `X` 绑成 `main` 命名空间里的**静态副本**；而 `pipeline.load_config()`
之后重绑的是 `pipeline.MODEL_DIR`。于是 `main` 里所有读 `MODEL_DIR` 的地方都停在导入那一刻。

**用户可见的症状**（本文件两条断言分别钉它们）：
  ① 托盘「选择模型目录」的对话框**初始目录**是旧的 —— 第二次换目录时尤其明显；
  ② 换目录成功后的通知**打印旧目录**（`notify_model_updated` 的文案里那个路径）。
两条都是"取用时的值"这一条性质的不同出口，所以两条都钉——只钉一条时，
"把某一处改成 new_engine.model_dir"这种**局部补丁**也能通过。

判别力自证：断言"导入期那个目录确实 ≠ 切换后的目录"，否则两条都会因为碰巧相等而失去意义。
不启 Tk、不弹对话框：`filedialog.askdirectory` 与 `AsrEngine` 都换替身。
"""
import os
import sys
from pathlib import Path

from _cleanup import rmtree_cleanup, scratch_dir  # noqa: E402

# F11/D12 实例隔离：必须在 import main/pipeline 之前重定向数据根与配置，
# 否则导入期的 seed_config()/load_config() 会读写用户真实的 %LOCALAPPDATA%。
_TMP = scratch_dir("l-s2t-maindir-")
os.environ["LOCAL_SPEAK2TEXT_DATA_DIR"] = _TMP
os.environ["LOCAL_SPEAK2TEXT_CONFIG"] = str(Path(_TMP) / "config.json")

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import json  # noqa: E402

import pipeline as P  # noqa: E402
import main as M  # noqa: E402

FAILS = []
DIR_A = str(Path(_TMP) / "model-a")
DIR_B = str(Path(_TMP) / "model-b")
os.makedirs(DIR_A, exist_ok=True)
os.makedirs(DIR_B, exist_ok=True)
_CFG = Path(os.environ["LOCAL_SPEAK2TEXT_CONFIG"])


def check(name, ok, detail=""):
    print(("  ok  " if ok else "  FAIL") + " " + name + ("  " + detail if detail else ""),
          flush=True)
    if not ok:
        FAILS.append(name)


def set_config_model_dir(path):
    cfg = {}
    if _CFG.is_file():
        try:
            cfg = json.loads(_CFG.read_text(encoding="utf-8-sig"))
        except Exception:
            cfg = {}
    cfg["model_dir"] = path
    _CFG.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")


# 导入期的值：pipeline 在导入时跑过 seed_config()+load_config()，此刻 MODEL_DIR 就是"快照值"
_IMPORT_DIR = P.MODEL_DIR

# 先把它切到 A（模拟"上一次选择"），再切到 B（模拟"用户这次选择"）
set_config_model_dir(DIR_A)
P.load_config()
check("pipeline follows the config to A", P.MODEL_DIR == DIR_A, "P.MODEL_DIR=%r" % P.MODEL_DIR)
set_config_model_dir(DIR_B)
P.load_config()
check("pipeline follows the config to B", P.MODEL_DIR == DIR_B, "P.MODEL_DIR=%r" % P.MODEL_DIR)

# ---------- 判别力自证 ----------
check("discriminating: import-time dir differs from B (else this test proves nothing)",
      os.path.normcase(_IMPORT_DIR) != os.path.normcase(DIR_B),
      "import-time=%r  B=%r" % (_IMPORT_DIR, DIR_B))


# ---------- 替身：不启 Tk、不弹对话框、不加载真模型 ----------
class _Self:
    def __init__(self):
        self.engine = None
        self.hook_started = True      # 跳过 hook.start()
        self.hook = None
        self.notes = []

    def notify(self, text):
        self.notes.append(text)


class _FakeEngine:
    def __init__(self, model_dir=None, num_threads=None, model_type=None):
        self.model_dir = model_dir
        self.model_type = "fake"


_captured = {}
_real_dialog = M.filedialog.askdirectory
_real_engine = M.AsrEngine
M.i18n.init("zh")
M.filedialog.askdirectory = lambda **kw: (_captured.update(kw), DIR_B)[1]
M.AsrEngine = _FakeEngine
try:
    me = _Self()
    M.Controller._choose_model_dir(me)
finally:
    M.filedialog.askdirectory = _real_dialog
    M.AsrEngine = _real_engine

# ---------- ① 对话框初始目录 = 当前目录（不是导入期那个） ----------
check("picker opens at the CURRENT model dir",
      os.path.normcase(str(_captured.get("initialdir", ""))) == os.path.normcase(DIR_B),
      "initialdir=%r  expected=%r" % (_captured.get("initialdir"), DIR_B))

# ---------- ② 换目录后的通知里写的是新目录 ----------
_last = me.notes[-1] if me.notes else ""
check("'model updated' notification names the NEW dir",
      os.path.normcase(DIR_B) in os.path.normcase(_last),
      "notify=%r" % (_last[:120],))

check("temp dir cleaned up (no %TEMP% leak)", rmtree_cleanup(_TMP), str(_TMP))
print("MAIN MODEL_DIR TEST " + ("FAILED: " + ",".join(FAILS) if FAILS else "OK"), flush=True)
sys.exit(1 if FAILS else 0)
