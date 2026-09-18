# -*- coding: utf-8 -*-
"""验证 run_benchmark 核心（真跑三模型）。"""
import os
import sys

sys.path.insert(0, r"H:\Tools\my_diy_tools\local-speak2text")
import pipeline as P

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
print("BENCH CORE OK")
