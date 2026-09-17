# -*- coding: utf-8 -*-
"""识别流水线：录音缓冲 + VAD 断句 + 滑动窗口实时识别。

与界面/热键解耦，事件通过 sink.put((类型, 参数)) 对外通知：
    ("live",   seg_id, 文本)  当前片段的最新实时结果
    ("commit", seg_id, 文本)  某个片段已定稿（断句完成/最终结果）
    ("finish", 是否取消)       整个会话结束，所有文本已提交完
    ("error",  消息)          录音启动失败等错误
"""
import os
import json
import queue
import sys
import threading
import time

import numpy as np
import sherpa_onnx

from paths import APP_DIR, CONFIG_PATH as _USER_CONFIG_PATH, seed_config

SAMPLE_RATE = 16000
NUM_THREADS = 8                # ONNX 解码线程数（config.json 可覆盖；实测本机 8 最优）
MAX_NEW_TOKENS = 384          # 单片段最多生成的 token 数（约 40 秒中文）

# VAD 参数
FRAME_SECONDS = 0.02          # 每帧 20ms
START_DEBOUNCE = 0.15         # 连续有声多久才认为开始说话
SILENCE_END = 1.00            # 静音多久断句
MAX_SEGMENT_SECONDS = 30.0    # 单片段硬上限（秒），超时强制断句
MIN_SEGMENT = 0.30            # 短于该时长且无结果的片段丢弃
PARTIAL_INTERVAL = 1.2        # 实时结果的刷新间隔（秒）
SEGMENT_PADDING = 0.15        # 断句前后各多留的余量（秒），避免吞掉轻声首尾
VAD_FLOOR = 0.005             # VAD 绝对音量下限（降低可捕获更轻的声音）

# 自动音量增益（AGC）：识别前把低音量音频放大到正常水平
AUTO_GAIN_TARGET_RMS = 0.08   # 目标音量（RMS）
AUTO_GAIN_MAX = 20.0          # 最大放大倍数（防止把噪声一起抬上天）

BASE_DIR = str(APP_DIR)
CONFIG_PATH = str(_USER_CONFIG_PATH)
DEFAULT_MODEL_DIR = os.path.join(BASE_DIR, "models", "qwen3-asr-0.6B")
MODEL_DIR = DEFAULT_MODEL_DIR
MODEL_NAME = os.path.basename(MODEL_DIR)

AUTO_GAIN = True
SEGMENT_PADDING = 0.15
VAD_FLOOR = 0.005
NUM_THREADS_CFG = NUM_THREADS  # config.json 可覆盖


def _resolve_model_dir(value):
    if not value:
        return DEFAULT_MODEL_DIR
    if os.path.isabs(value):
        return value
    return os.path.normpath(os.path.join(BASE_DIR, value))


def load_config():
    global AUTO_GAIN, SEGMENT_PADDING, VAD_FLOOR, MODEL_DIR, MODEL_NAME, NUM_THREADS_CFG
    try:
        with open(CONFIG_PATH, "r", encoding="utf-8-sig") as f:
            cfg = json.load(f)
        AUTO_GAIN = bool(cfg.get("auto_gain", True))
        SEGMENT_PADDING = float(cfg.get("segment_padding", 0.15))
        VAD_FLOOR = float(cfg.get("vad_floor", 0.005))
        MODEL_DIR = _resolve_model_dir(cfg.get("model_dir"))
        MODEL_NAME = os.path.basename(os.path.normpath(MODEL_DIR))
        NUM_THREADS_CFG = max(1, int(cfg.get("num_threads", NUM_THREADS)))
    except Exception:
        pass


def set_auto_gain(enabled):
    global AUTO_GAIN
    AUTO_GAIN = bool(enabled)


# 用户数据目录（config 迁移播种）要在首次读配置前完成
seed_config()
load_config()


def apply_auto_gain(samples):
    """检测低音量并放大到目标水平；正常音量原样返回。"""
    if not AUTO_GAIN or samples is None or len(samples) == 0:
        return samples
    rms = float(np.sqrt(np.mean(samples * samples)))
    if rms <= 0.0 or rms >= AUTO_GAIN_TARGET_RMS:
        return samples
    gain = min(AUTO_GAIN_TARGET_RMS / rms, AUTO_GAIN_MAX)
    boosted = samples * gain
    peak = float(np.max(np.abs(boosted)))
    if peak > 0.99:
        boosted = boosted * (0.99 / peak)  # 防削波
    return boosted


def _detect_model_type(model_dir):
    """根据目录内文件名识别模型类型，用于自动选择 sherpa-onnx loader。"""
    try:
        files = {f.lower() for f in os.listdir(model_dir)}
    except OSError:
        files = set()

    def has(*names):
        return all(any(f == n.lower() or f.startswith(n.lower()) for f in files) for n in names)

    if has("conv_frontend.onnx", "encoder"):
        return "qwen3_asr"
    if has("model.int8.onnx", "tokens.txt"):
        return "sense_voice"
    if has("encoder.int8.onnx", "decoder.int8.onnx", "tokens.txt"):
        return "fire_red_asr"
    if any(f.startswith("model.int8.onnx") or f == "model.onnx" for f in files) and has("tokens.txt"):
        return "paraformer"
    return "qwen3_asr"


def perf_log(msg):
    """轻量性能日志：追加到用户数据目录 local-speak2text.log，失败静默。"""
    try:
        from paths import LOG_DIR

        LOG_DIR.mkdir(parents=True, exist_ok=True)
        with open(LOG_DIR / "local-speak2text.log", "a", encoding="utf-8") as f:
            f.write(time.strftime("%Y-%m-%d %H:%M:%S ") + msg + "\n")
    except OSError:
        pass


class AsrEngine:
    """按模型目录自动选择 sherpa-onnx loader（qwen3_asr / sense_voice / fire_red_asr / paraformer）。"""

    def __init__(self, model_dir=MODEL_DIR, num_threads=None, model_type=None):
        if num_threads is None:
            num_threads = NUM_THREADS_CFG
        self.model_dir = model_dir
        self.model_type = model_type or _detect_model_type(model_dir)
        self.recognizer = self._build(model_dir, num_threads)

    def _build(self, model_dir, num_threads):
        t = self.model_type
        if t == "sense_voice":
            return sherpa_onnx.OfflineRecognizer.from_sense_voice(
                model=os.path.join(model_dir, "model.int8.onnx"),
                tokens=os.path.join(model_dir, "tokens.txt"),
                num_threads=num_threads,
                sample_rate=SAMPLE_RATE,
                decoding_method="greedy_search",
                language="auto",
                use_itn=True,
            )
        if t == "fire_red_asr":
            return sherpa_onnx.OfflineRecognizer.from_fire_red_asr(
                encoder=os.path.join(model_dir, "encoder.int8.onnx"),
                decoder=os.path.join(model_dir, "decoder.int8.onnx"),
                tokens=os.path.join(model_dir, "tokens.txt"),
                num_threads=num_threads,
                decoding_method="greedy_search",
            )
        if t == "paraformer":
            return sherpa_onnx.OfflineRecognizer.from_paraformer(
                paraformer=os.path.join(model_dir, "model.int8.onnx"),
                tokens=os.path.join(model_dir, "tokens.txt"),
                num_threads=num_threads,
                sample_rate=SAMPLE_RATE,
                decoding_method="greedy_search",
            )
        # qwen3_asr（默认）
        return sherpa_onnx.OfflineRecognizer.from_qwen3_asr(
            conv_frontend=os.path.join(model_dir, "conv_frontend.onnx"),
            encoder=os.path.join(model_dir, "encoder.int8.onnx"),
            decoder=os.path.join(model_dir, "decoder.int8.onnx"),
            tokenizer=os.path.join(model_dir, "tokenizer"),
            num_threads=num_threads,
            sample_rate=SAMPLE_RATE,
            feature_dim=128,
            decoding_method="greedy_search",
            max_new_tokens=MAX_NEW_TOKENS,
        )

    def recognize(self, samples):
        """识别一段 16kHz 单声道 float32 音频，返回文本。"""
        if samples is None or len(samples) == 0:
            return ""
        t0 = time.perf_counter()
        samples = apply_auto_gain(samples)
        stream = self.recognizer.create_stream()
        stream.accept_waveform(SAMPLE_RATE, samples.astype(np.float32))
        self.recognizer.decode_stream(stream)
        dt = time.perf_counter() - t0
        audio_sec = len(samples) / SAMPLE_RATE
        text = stream.result.text.strip()
        perf_log(
            "%s audio=%.2fs decode=%.3fs rtf=%.3f chars=%d text=%s"
            % (self.model_type, audio_sec, dt, dt / audio_sec if audio_sec else 0.0, len(text), text)
        )
        return text


class DictationSession:
    """一次录音会话：缓冲、VAD 状态、已定稿文本。"""

    def __init__(self, mode):
        self.mode = mode              # "hold" 或 "cont"
        self.buf = []                 # 全部采样（float32 列表）
        self.total = 0
        self.lock = threading.Lock()

        # VAD 状态
        self.vad_pos = 0              # 已扫描的采样位置
        self.seg_start = None         # 当前语音片段的起始采样下标
        self.lead_start = None        # 首次有声帧位置（去抖用）
        self.speech_frames = 0
        self.seg_state = "idle"       # idle / speaking
        self.trailing = 0.0           # 已持续静音秒数
        self.noise_rms = 0.01
        self.seg_id = 0
        self.last_partial = 0.0
        self.partial_pending = False

        self.finishing = False
        self.finish_posted = False
        self.cancel = False
        self.done = False
        self.last_final_seg = 0  # 最近已定稿的片段号（用于丢弃过期预览）

    def add(self, samples):
        with self.lock:
            self.buf.extend(float(x) for x in samples)
            self.total += len(samples)

    def slice_from(self, start, end=None):
        with self.lock:
            return np.asarray(
                self.buf[start : end if end is not None else self.total],
                dtype=np.float32,
            )


class Pipeline:
    """VAD 线程 + 识别线程。识别调用全部串行，保证同一片段内顺序。"""

    def __init__(self, engine, sink):
        self.engine = engine
        self.sink = sink
        self.session = None
        self.audio = None
        self.vad_thread = None
        self.recog_thread = None
        self.recog_q = queue.PriorityQueue()

    # ---------- 对外接口 ----------

    def start(self, mode, use_audio=True):
        self.session = DictationSession(mode)
        self.recog_q = queue.PriorityQueue()
        if use_audio:
            self.audio = open_mic_stream(self._on_audio)
            if self.audio is None:
                from i18n import t
                self.sink.put(("error", t("err_mic_open")))
                self.session = None
                return False
            try:
                self.audio.start()
            except Exception as e:
                from i18n import t
                self.sink.put(("error", t("err_mic_start", e=e)))
                self.session = None
                return False
        self.vad_thread = threading.Thread(target=self._vad_loop, daemon=True)
        self.recog_thread = threading.Thread(target=self._recog_loop, daemon=True)
        self.vad_thread.start()
        self.recog_thread.start()
        return True

    def add_samples(self, samples):
        """外部喂入采样（自测用）。"""
        if self.session is not None:
            self.session.add(samples)

    def finish(self, cancel=False):
        """结束会话。cancel=True 表示丢弃结果（Esc）。"""
        s = self.session
        if s is None:
            return
        s.cancel = cancel
        s.finishing = True
        if self.audio is not None:
            try:
                self.audio.stop()
            except Exception:
                pass
            self.audio = None
        if cancel:
            s.done = True
            self.sink.put(("finish", True))

    # ---------- 内部 ----------

    def _on_audio(self, indata, frames, time_info, status):
        if self.session is not None:
            self.session.add(indata[:, 0])

    def _vad_loop(self):
        s = self.session
        frame = int(SAMPLE_RATE * FRAME_SECONDS)
        while not s.done:
            now = time.time()
            with s.lock:
                if s.vad_pos < s.total:
                    end = min(s.vad_pos + frame, s.total)
                    chunk = np.asarray(s.buf[s.vad_pos:end], dtype=np.float32)
                    s.vad_pos = end
                    got = True
                else:
                    got = False
            if got:
                rms = float(np.sqrt(np.mean(chunk * chunk))) if len(chunk) else 0.0
                self._vad_frame(s, rms, now, len(chunk))
            else:
                time.sleep(0.004)
            if s.finishing and not s.finish_posted:
                self._force_finalize()
                self.recog_q.put(((9, 0), ("finish",)))
                s.finish_posted = True
                s.done = True

    def _vad_frame(self, s, rms, now, frame_len):
        thr = max(s.noise_rms * 2.2, VAD_FLOOR)
        is_speech = rms > thr

        if not is_speech:
            s.noise_rms = 0.95 * s.noise_rms + 0.05 * rms

        if s.seg_state == "idle":
            if is_speech:
                if s.lead_start is None:
                    s.lead_start = s.vad_pos - frame_len
                s.speech_frames += 1
                if s.speech_frames * FRAME_SECONDS >= START_DEBOUNCE:
                    s.seg_start = s.lead_start
                    s.seg_state = "speaking"
                    s.seg_id += 1
                    s.trailing = 0.0
                    s.last_partial = now
                    s.partial_pending = False
                    self.sink.put(("live", s.seg_id, ""))
            else:
                s.lead_start = None
                s.speech_frames = 0
            return

        # speaking
        if (s.vad_pos - s.seg_start) / SAMPLE_RATE >= MAX_SEGMENT_SECONDS:
            self._finalize_segment(s)
            return
        if is_speech:
            s.trailing = 0.0
        else:
            s.trailing += FRAME_SECONDS
            if s.trailing >= SILENCE_END:
                self._finalize_segment(s)
                return

        if (
            s.seg_start is not None
            and not s.partial_pending
            and now - s.last_partial >= PARTIAL_INTERVAL
        ):
            s.last_partial = now
            s.partial_pending = True
            self.recog_q.put(((1, s.seg_id), ("partial", s.seg_id, self._padded_slice(s, s.seg_start, s.vad_pos))))

    def _padded_slice(self, s, start, end):
        """截取片段并前后各多留 SEGMENT_PADDING 秒，保护边界轻声。"""
        pad = int(SAMPLE_RATE * SEGMENT_PADDING)
        lo = max(0, start - pad)
        hi = min(s.total, end + pad)
        return s.slice_from(lo, hi)

    def _finalize_segment(self, s):
        if s.seg_start is None:
            return
        samples = self._padded_slice(s, s.seg_start, s.vad_pos)
        if len(samples) / SAMPLE_RATE >= MIN_SEGMENT:
            self.recog_q.put(((0, s.seg_id), ("final", s.seg_id, samples)))
        s.seg_start = None
        s.lead_start = None
        s.speech_frames = 0
        s.seg_state = "idle"
        s.trailing = 0.0
        s.partial_pending = False
        s.last_partial = time.time()
        self._maybe_compact(s)

    def _maybe_compact(self, s):
        """空闲时丢弃已处理的音频，防止长会话内存膨胀。"""
        with s.lock:
            if s.seg_state == "idle" and s.lead_start is None and s.vad_pos > SAMPLE_RATE * 10:
                del s.buf[: s.vad_pos]
                s.total -= s.vad_pos
                s.vad_pos = 0

    def _force_finalize(self):
        """结束会话时，把未定稿的片段立即定稿；同时丢弃还没跑的过期预览任务。"""
        s = self.session
        if s.seg_start is not None:
            samples = self._padded_slice(s, s.seg_start, s.vad_pos)
            if len(samples) / SAMPLE_RATE >= MIN_SEGMENT:
                self.recog_q.put(((0, s.seg_id), ("final", s.seg_id, samples)))
            s.seg_start = None
            s.seg_state = "idle"
        self._drop_stale_partials()

    def _drop_stale_partials(self):
        """清掉队列里还在等待的 partial 任务（内容与马上要算的 final 重复）。"""
        s = self.session
        last_final_seg = s.seg_id if s.seg_start is None else s.seg_id - 1
        dropped = []
        try:
            while True:
                dropped.append(self.recog_q.get_nowait())
        except queue.Empty:
            pass
        for pri, item in dropped:
            if item[0] == "partial" and item[1] <= last_final_seg:
                continue  # 该片段马上会有 final，预览已无意义
            self.recog_q.put((pri, item))

    def _recog_loop(self):
        s = self.session
        while True:
            job = self.recog_q.get()[1]
            if job[0] == "finish":
                self.sink.put(("finish", s.cancel))
                break
            if s.cancel:
                continue
            kind, seg_id, samples = job
            if kind == "partial" and (seg_id <= s.last_final_seg or s.finishing):
                # 过期预览：片段已定稿或正在收尾，直接丢掉，省一遍解码
                continue
            text = self.engine.recognize(samples)
            if kind == "partial":
                self.sink.put(("live", seg_id, text))
            else:
                s.last_final_seg = max(s.last_final_seg, seg_id)
                self.sink.put(("commit", seg_id, text))


def open_mic_stream(callback, sample_rate=SAMPLE_RATE):
    """按优先级尝试打开麦克风：WASAPI 共享(自动转换) -> MME 默认 -> MME 显式设备。"""
    import sounddevice as sd

    devices = sd.query_devices()
    hostapis = sd.query_hostapis()
    wasapi_host = next((i for i, h in enumerate(hostapis) if "WASAPI" in h["name"]), None)
    default_in = sd.default.device[0]
    default_in_name = devices[default_in].get("name", "") if default_in is not None else ""

    wasapi_candidates = []
    if wasapi_host is not None:
        for i, d in enumerate(devices):
            if d.get("max_input_channels", 0) > 0 and d.get("hostapi") == wasapi_host:
                wasapi_candidates.append(i)
    wasapi_candidates.sort(key=lambda i: 0 if devices[i]["name"] == default_in_name else 1)

    attempts = []
    for dev in wasapi_candidates:
        attempts.append((
            f"WASAPI dev={dev}",
            dict(
                samplerate=sample_rate,
                channels=1,
                dtype="float32",
                blocksize=int(sample_rate * 0.1),
                callback=callback,
                device=dev,
                extra_settings=sd.WasapiSettings(exclusive=False, auto_convert=True),
            ),
        ))

    attempts.append((
        "MME 默认",
        dict(
            samplerate=sample_rate,
            channels=1,
            dtype="float32",
            blocksize=int(sample_rate * 0.1),
            callback=callback,
        ),
    ))
    if default_in is not None:
        attempts.append((
            f"MME dev={default_in}",
            dict(
                device=default_in,
                samplerate=sample_rate,
                channels=1,
                dtype="float32",
                blocksize=int(sample_rate * 0.1),
                callback=callback,
            ),
        ))

    for name, kw in attempts:
        try:
            stream = sd.InputStream(**kw)
            return stream
        except Exception:
            continue
    return None


def selftest(wav_path):
    """用 WAV 文件模拟完整流水线（不进界面），打印定稿文本。"""
    import wave

    with wave.open(wav_path, "rb") as w:
        assert w.getnchannels() == 1 and w.getsampwidth() == 2
        data = w.readframes(w.getnframes())
    samples = np.frombuffer(data, dtype=np.int16).astype(np.float32) / 32768.0

    finish_ev = threading.Event()

    class Sink:
        def __init__(self):
            self.events = []

        def put(self, ev):
            self.events.append(ev)
            if ev[0] == "finish":
                finish_ev.set()
            elif ev[0] == "live":
                print(f"[live]   {ev[2]}")
            elif ev[0] == "commit":
                print(f"[commit] {ev[2]}")

    print("加载模型…")
    engine = AsrEngine()
    sink = Sink()
    pipe = Pipeline(engine, sink)
    print("开始流水线…")
    pipe.start("hold", use_audio=False)

    block = int(SAMPLE_RATE * 0.1)
    for i in range(0, len(samples), block):
        pipe.add_samples(samples[i : i + block])
        time.sleep(0.02)

    time.sleep(0.5)
    pipe.finish()
    finish_ev.wait(timeout=60)

    committed = "".join(ev[2] for ev in sink.events if ev[0] == "commit")
    print("=" * 40)
    print("定稿文本:", committed)


if __name__ == "__main__":
    import sys

    selftest(sys.argv[1] if len(sys.argv) > 1 else os.path.join(BASE_DIR, "models", "test_zh.wav"))
