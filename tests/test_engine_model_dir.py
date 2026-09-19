# -*- coding: utf-8 -*-
"""#46：`AsrEngine` 的 `model_dir` 默认参数是**导入期快照**，必须在调用时取值。

缺陷形态（`src/pipeline.py:337`）：
    def __init__(self, model_dir=MODEL_DIR, num_threads=None, model_type=None):
默认参数在**函数定义时**求值一次。`load_config()` 之后会把模块级 `MODEL_DIR` 重绑到
配置里的新目录，但那个默认值仍然握着旧字符串——于是 `load_config()` 之后再 `AsrEngine()`
加载的还是**老模型**。同一个签名里紧挨着的 `num_threads=None` 就是正解形态（sentinel +
函数体内取值），本文件钉住"model_dir 必须与它同形"。

判据三档，缺任何一档都挡不住退化：
  A 重绑 `MODEL_DIR` 后再实例化 → 必须用**新**目录（本文件主断言；修复前必红）
  B 显式传 `model_dir=` → 仍然优先（正对照：防止"修成忽略参数"）
  C 端到端：写 config.json → `load_config()` → 实例化 → 必须跟上（用户真实路径）
外加一条**判别力自证**：断言"导入期快照 != 新目录"，否则 A/C 可能碰巧通过而毫无证明力。

不加载真模型：只把 `_build` 换成记录器（它才是拿 `model_dir` 去摸 onnx 文件的那一步）。
"""
import json
import os
import sys
from pathlib import Path

from _cleanup import rmtree_cleanup, scratch_dir  # noqa: E402

# F11/D12 实例隔离：必须在 import pipeline 之前重定向数据根与配置，
# 否则导入期的 seed_config()/load_config() 会读写用户真实的 %LOCALAPPDATA%。
_TMP = scratch_dir("l-s2t-engdir-")
os.environ["LOCAL_SPEAK2TEXT_DATA_DIR"] = _TMP
os.environ["LOCAL_SPEAK2TEXT_CONFIG"] = str(Path(_TMP) / "config.json")

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import pipeline as P  # noqa: E402

FAILS = []
NEW_DIR = str(Path(_TMP) / "model-switched")
EXPLICIT_DIR = str(Path(_TMP) / "model-explicit")
os.makedirs(NEW_DIR, exist_ok=True)      # _find_existing_model_dir 只认已存在的目录
os.makedirs(EXPLICIT_DIR, exist_ok=True)


def check(name, ok, detail=""):
    print(("  ok  " if ok else "  FAIL") + " " + name + ("  " + detail if detail else ""),
          flush=True)
    if not ok:
        FAILS.append(name)


# 替身：记录 _build 实际拿到的目录，不碰 sherpa-onnx / 真模型文件
RECORDED = []
_real_build = P.AsrEngine._build
P.AsrEngine._build = lambda self, model_dir, num_threads: RECORDED.append(model_dir) or object()

# 导入已完成（pipeline.py:181-182 在导入期跑了 seed_config()+load_config()），所以
# 此刻的 MODEL_DIR 就是"导入期那个值"。用它做判别力对照，比去读 __defaults__ 更稳：
# 那是**行为**层面的事实，不绑定任何一种修法（sentinel / 显式传参都能通过）。
_IMPORT_MODEL_DIR = P.MODEL_DIR
_ORIGINAL_MODEL_DIR = P.MODEL_DIR

try:
    # ---------- A：重绑 MODEL_DIR 后实例化 → 必须用新目录 ----------
    P.MODEL_DIR = NEW_DIR
    RECORDED.clear()
    eng = P.AsrEngine()
    check("A engine takes MODEL_DIR in effect AT CALL TIME",
          eng.model_dir == NEW_DIR,
          "engine.model_dir=%r expected=%r" % (eng.model_dir, NEW_DIR))
    check("A the load path (_build) got the call-time dir too",
          RECORDED == [NEW_DIR], "recorded=%r" % (RECORDED,))

    # ---------- B：正对照——显式传参仍然优先 ----------
    RECORDED.clear()
    eng_b = P.AsrEngine(model_dir=EXPLICIT_DIR)
    check("B explicit model_dir still wins (no degenerate fix)",
          eng_b.model_dir == EXPLICIT_DIR and RECORDED == [EXPLICIT_DIR],
          "model_dir=%r recorded=%r" % (eng_b.model_dir, RECORDED))

    # ---------- C：端到端——用户改配置 → load_config() → 引擎跟上 ----------
    P.MODEL_DIR = _ORIGINAL_MODEL_DIR
    cfg_path = Path(os.environ["LOCAL_SPEAK2TEXT_CONFIG"])
    cfg = {}
    if cfg_path.is_file():
        try:
            cfg = json.loads(cfg_path.read_text(encoding="utf-8-sig"))
        except Exception:
            cfg = {}
    cfg["model_dir"] = NEW_DIR
    cfg_path.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")

    P.load_config()
    check("C1 load_config resolved the new config value",
          P.MODEL_DIR == NEW_DIR, "MODEL_DIR=%r expected=%r" % (P.MODEL_DIR, NEW_DIR))
    RECORDED.clear()
    eng_c = P.AsrEngine()
    check("C2 engine follows a config change made after import",
          eng_c.model_dir == NEW_DIR,
          "engine.model_dir=%r expected=%r" % (eng_c.model_dir, NEW_DIR))
finally:
    P.AsrEngine._build = _real_build
    P.MODEL_DIR = _ORIGINAL_MODEL_DIR

# ---------- 判别力自证：导入期那个值必须与新目录不同，否则 A/C 证明不了任何事 ----------
# 少了这一条，"引擎用的目录"与"新目录"若碰巧相等，A/C 会在缺陷仍然存在时变绿。
check("discriminating: import-time value differs from the switched dir",
      os.path.normcase(str(_IMPORT_MODEL_DIR)) != os.path.normcase(NEW_DIR),
      "import-time=%r switched=%r" % (_IMPORT_MODEL_DIR, NEW_DIR))

check("temp dir cleaned up (no %TEMP% leak)", rmtree_cleanup(_TMP), str(_TMP))
print("ENGINE MODEL_DIR TEST " + ("FAILED: " + ",".join(FAILS) if FAILS else "OK"), flush=True)
sys.exit(1 if FAILS else 0)
