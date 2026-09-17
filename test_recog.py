# -*- coding: utf-8 -*-
"""验证 Qwen3-ASR-0.6B int8 模型在本机的识别效果。"""
import sys
import time
import wave
import os

import numpy as np
import sherpa_onnx

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
MODEL_DIR = os.path.join(BASE_DIR, "models", "qwen3-asr-0.6B")
SAMPLE_RATE = 16000


def load_recognizer():
    return sherpa_onnx.OfflineRecognizer.from_qwen3_asr(
        conv_frontend=f"{MODEL_DIR}/conv_frontend.onnx",
        encoder=f"{MODEL_DIR}/encoder.int8.onnx",
        decoder=f"{MODEL_DIR}/decoder.int8.onnx",
        tokenizer=f"{MODEL_DIR}/tokenizer",
        num_threads=4,
        sample_rate=SAMPLE_RATE,
        feature_dim=128,
        decoding_method="greedy_search",
    )


def read_wav(path):
    with wave.open(path, "rb") as w:
        assert w.getnchannels() == 1
        assert w.getsampwidth() == 2
        data = w.readframes(w.getnframes())
    samples = np.frombuffer(data, dtype=np.int16).astype(np.float32) / 32768.0
    return samples


def recognize(recognizer, samples, rate=SAMPLE_RATE):
    stream = recognizer.create_stream()
    stream.accept_waveform(rate, samples)
    recognizer.decode_stream(stream)
    return stream.result.text.strip()


def main():
    path = sys.argv[1] if len(sys.argv) > 1 else os.path.join(BASE_DIR, "models", "test_zh.wav")
    t0 = time.time()
    recognizer = load_recognizer()
    print(f"模型加载耗时: {time.time() - t0:.1f}s")

    samples = read_wav(path)
    print(f"音频时长: {len(samples) / SAMPLE_RATE:.2f}s")

    t0 = time.time()
    text = recognize(recognizer, samples)
    elapsed = time.time() - t0
    print(f"识别结果: {text}")
    print(f"识别耗时: {elapsed:.2f}s ({len(samples) / SAMPLE_RATE / elapsed:.1f}x 实时)")


if __name__ == "__main__":
    main()
