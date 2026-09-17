# -*- coding: utf-8 -*-
"""三模型同机对比：SenseVoice vs Qwen3 vs FireRedASR2-AED，同一段音频比速度和文本。"""
import sys
import time
import wave

import numpy as np

sys.path.insert(0, r"H:\Tools\my_diy_tools\local-speak2text")
import pipeline as P

DIRS = {
    "SenseVoice": r"H:\Tools\my_diy_tools\local-speak2text\models\sensevoice-small-int8",
    "Qwen3-0.6B": r"H:\Tools\my_diy_tools\local-speak2text\models\qwen3-asr-0.6B",
    "FireRedASR2-AED": r"H:\Tools\my_diy_tools\local-speak2text\models\fireredasr2-aed-int8",
}

with wave.open(r"H:\Tools\my_diy_tools\local-speak2text\models\test_zh.wav", "rb") as w:
    data = w.readframes(w.getnframes())
seg = np.frombuffer(data, dtype=np.int16).astype(np.float32) / 32768.0
audio = np.concatenate([seg] * 3)
dur = len(audio) / P.SAMPLE_RATE
print(f"音频时长 {dur:.1f}s\n", flush=True)

for name, d in DIRS.items():
    t_load0 = time.perf_counter()
    eng = P.AsrEngine(model_dir=d)
    t_load = time.perf_counter() - t_load0
    eng.recognize(seg)  # 预热
    t0 = time.perf_counter()
    text = eng.recognize(audio)
    dt = time.perf_counter() - t0
    t_short0 = time.perf_counter()
    short = eng.recognize(seg)
    dt_short = time.perf_counter() - t_short0
    print(f"[{name}] type={eng.model_type} load={t_load:.1f}s", flush=True)
    print(f"  长音频({dur:.1f}s): decode={dt:.2f}s RTF={dt/dur:.3f}", flush=True)
    print(f"  短句(4.8s): decode={dt_short:.2f}s RTF={dt_short/4.8:.3f}", flush=True)
    print(f"  文本: {short}", flush=True)
    print(f"  长文本: {text[:50]}…\n", flush=True)
    del eng
