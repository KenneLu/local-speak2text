# -*- coding: utf-8 -*-
"""对比基准：同一 WAV 喂完整流水线（VAD+识别），对比改动前后的出字耗时。

用法: python bench.py <wav路径> [旧代码标记]
仅在开发时临时使用，不属于工具本体。
"""
import sys
import threading
import time
import wave

import numpy as np


def run(tag):
    import pipeline as P

    with wave.open(WAV, "rb") as w:
        assert w.getnchannels() == 1 and w.getsampwidth() == 2
        data = w.readframes(w.getnframes())
    samples = np.frombuffer(data, dtype=np.int16).astype(np.float32) / 32768.0

    finish_ev = threading.Event()
    events = []

    class Sink:
        def put(self, ev):
            events.append((time.perf_counter(), ev))
            if ev[0] == "finish":
                finish_ev.set()

    print(f"加载模型… ({tag})")
    t0 = time.perf_counter()
    engine = P.AsrEngine()
    t_load = time.perf_counter() - t0

    pipe = P.Pipeline(engine, Sink())
    pipe.start("hold", use_audio=False)

    t_release = None
    block = int(P.SAMPLE_RATE * 0.1)
    print("喂音频…")
    t_feed0 = time.perf_counter()
    for i in range(0, len(samples), block):
        pipe.add_samples(samples[i : i + block])
        time.sleep(0.02)
    feed_dur = time.perf_counter() - t_feed0

    time.sleep(0.3)
    t_release = time.perf_counter()
    pipe.finish()
    finish_ev.wait(timeout=120)

    commits = [(t, ev[2]) for t, ev in events if ev[0] == "commit"]
    print(f"\n[{tag}] 模型加载 {t_load:.2f}s | 音频时长 {len(samples)/P.SAMPLE_RATE:.2f}s | 喂入耗时 {feed_dur:.2f}s")
    for t, txt in commits:
        print(f"  +{t - t_release:6.2f}s commit: {txt}")
    print(f"[{tag}] 松手→全部出字: {time.perf_counter() - t_release:.2f}s, 片段数 {len(commits)}")


if __name__ == "__main__":
    WAV = sys.argv[1] if len(sys.argv) > 1 else r"H:\Tools\my_diy_tools\local-speak2text\models\test_zh.wav"
    run("new")
