# -*- coding: utf-8 -*-
"""线程数扫描：不同 num_threads 下 Qwen3-ASR int8 的单段解码耗时。"""
import sys
import time
import wave

import numpy as np

sys.path.insert(0, r"H:\Tools\my_diy_tools\local-speak2text")
import pipeline as P

WAV = r"H:\Tools\my_diy_tools\local-speak2text\models\test_zh.wav"
with wave.open(WAV, "rb") as w:
    data = w.readframes(w.getnframes())
seg = np.frombuffer(data, dtype=np.int16).astype(np.float32) / 32768.0
# 拼成 ~17s 长音频，模拟较长的说话内容
audio = np.concatenate([seg] * 3)

for nt in (4, 8, 16):
    eng = P.AsrEngine(num_threads=nt)
    eng.recognize(audio[: P.SAMPLE_RATE * 2])  # 预热
    t0 = time.perf_counter()
    text = eng.recognize(audio)
    dt = time.perf_counter() - t0
    dur = len(audio) / P.SAMPLE_RATE
    print(f"threads={nt:2d}  decode={dt:5.2f}s  audio={dur:.1f}s  RTF={dt/dur:.3f}  chars={len(text)}", flush=True)
    del eng
