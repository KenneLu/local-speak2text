# -*- coding: utf-8 -*-
"""SenseVoice vs Qwen3 同机对比：同一段音频，比解码速度和识别文本。"""
import sys
import time
import wave

import numpy as np

sys.path.insert(0, r"H:\Tools\my_diy_tools\local-speak2text")
import pipeline as P

QWEN_DIR = r"H:\Tools\my_diy_tools\local-speak2text\models\qwen3-asr-0.6B"
SV_DIR = r"H:\Tools\my_diy_tools\local-speak2text\build\dl\sherpa-onnx-sense-voice-zh-en-ja-ko-yue-int8-2024-07-17"

with wave.open(r"H:\Tools\my_diy_tools\local-speak2text\models\test_zh.wav", "rb") as w:
    data = w.readframes(w.getnframes())
seg = np.frombuffer(data, dtype=np.int16).astype(np.float32) / 32768.0
audio = np.concatenate([seg] * 3)  # ~16.6s
dur = len(audio) / P.SAMPLE_RATE
print(f"音频时长 {dur:.1f}s", flush=True)

print("detect(SV_DIR) =", P._detect_model_type(SV_DIR), flush=True)

# ---- SenseVoice ----
print("加载 SenseVoice…", flush=True)
sv = P.AsrEngine(model_dir=SV_DIR)
print("  type =", sv.model_type, flush=True)
sv.recognize(audio[: P.SAMPLE_RATE * 2])  # 预热
t0 = time.perf_counter()
sv_text_long = sv.recognize(audio)
sv_dt = time.perf_counter() - t0
sv_text_short = sv.recognize(seg)
print(f"  [SV ] decode={sv_dt:5.2f}s  RTF={sv_dt/dur:.3f}", flush=True)
print(f"  [SV ] test_zh 识别: {sv_text_short}", flush=True)
print(f"  [SV ] 长音频识别: {sv_text_long[:60]}…", flush=True)
del sv

# ---- Qwen3 ----
print("加载 Qwen3-0.6B…", flush=True)
qw = P.AsrEngine(model_dir=QWEN_DIR)
print("  type =", qw.model_type, flush=True)
qw.recognize(audio[: P.SAMPLE_RATE * 2])
t0 = time.perf_counter()
qw_text_long = qw.recognize(audio)
qw_dt = time.perf_counter() - t0
qw_text_short = qw.recognize(seg)
print(f"  [QW ] decode={qw_dt:5.2f}s  RTF={qw_dt/dur:.3f}", flush=True)
print(f"  [QW ] test_zh 识别: {qw_text_short}", flush=True)
print(f"  [QW ] 长音频识别: {qw_text_long[:60]}…", flush=True)

print(f"\n提速: x{qw_dt/sv_dt:.2f}")
