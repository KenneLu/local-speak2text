# -*- coding: utf-8 -*-
"""验证 run_benchmark 核心（真跑三模型）。"""
import os
import sys
from pathlib import Path

from _cleanup import rmtree_cleanup, scratch_dir  # noqa: E402

# F11/D12 实例隔离：必须在 import pipeline 之前重定向数据根与配置——导入期的
# seed_config() 与 run_benchmark 的 perf_log() 都会落盘，不钉就会写用户真实的
# %LOCALAPPDATA%\local-speak2text\（用户红线：构建不得影响服务）。
_TMP = scratch_dir("l-s2t-bench-")
os.environ["LOCAL_SPEAK2TEXT_DATA_DIR"] = _TMP
os.environ["LOCAL_SPEAK2TEXT_CONFIG"] = str(Path(_TMP) / "config.json")

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import pipeline as P  # noqa: E402

events = []


def prog(kind, name):
    events.append((kind, name))
    print(f"[{kind}] {name}", flush=True)


result = P.run_benchmark(os.path.join(P.BASE_DIR, "asr-modules"), prog)
print("audio_sec =", result["audio_sec"], "| long_sec =", result["long_sec"])
for r in result["results"]:
    print(
        f"{r['name']:26s} type={r['type']:13s} load={r['load_s']:5.1f}s "
        f"rtf_s={r['rtf_short']:.3f} rtf_l={r['rtf_long']:.3f} chars={r['chars']} ok={r['ok']}"
    )
print("recommendation =", result["reco"])
print("progress events =", len(events))
assert events, "no progress events"
assert any(r["type"] == "sense_voice" for r in result["results"])
assert result["reco"], "expected a recommendation"
assert rmtree_cleanup(_TMP), "temp dir not cleaned (leak): %s" % _TMP
print("BENCH CORE OK")
