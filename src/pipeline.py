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
from pathlib import Path

import numpy as np
import sherpa_onnx

from modules.paths import APP_DIR, CONFIG_PATH as _USER_CONFIG_PATH, seed_config

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
MODELS_DIR = os.path.join(BASE_DIR, "asr-modules")            # 资源模块目录（1.4.0 起，原 models/ 自动迁移）
LEGACY_MODELS_DIR = os.path.join(BASE_DIR, "models")
if os.path.isdir(LEGACY_MODELS_DIR) and not os.path.isdir(MODELS_DIR):
    try:
        os.rename(LEGACY_MODELS_DIR, MODELS_DIR)   # 一次性迁移，用户已下载的模型不重下
    except OSError:
        pass
DEFAULT_MODEL_DIR = os.path.join(MODELS_DIR, "sensevoice-small-int8")   # 默认模型：更轻、RTF 更低（1.4.0 起）
MODEL_DIR = DEFAULT_MODEL_DIR
MODEL_NAME = os.path.basename(MODEL_DIR)
# 模型目录的**来源**（见 `_find_existing_model_dir`）：default / config / fallback / missing。
# 之所以要显式记着它：现在的门禁只靠"向上查找回退"才绿，来源不打印出来就查不到这件事。
MODEL_DIR_CONFIGURED = DEFAULT_MODEL_DIR   # 配置里写的（未回退前）的值
MODEL_DIR_SOURCE = "default"

AUTO_GAIN = True
SEGMENT_PADDING = 0.15
VAD_FLOOR = 0.005
NUM_THREADS_CFG = NUM_THREADS  # config.json 可覆盖


def _engine_default_model_dir():
    """`AsrEngine()` 不带参数时，**此刻**会用的模型目录（#46）。

    单独提出来，是为了让 `AsrEngine.__init__` 与 `describe_model_resolution()` 共用
    **同一条取值规则**。两边各写一遍正是 #46 的成因：一边在定义时求值、一边在调用时
    求值，于是"打印出来的目录"和"真正加载的目录"可以长期不一致，而谁也看不出来。
    """
    return MODEL_DIR


def _resolve_model_dir(value):
    if not value:
        return DEFAULT_MODEL_DIR
    if os.path.isabs(value):
        return value
    return os.path.normpath(os.path.join(BASE_DIR, value))


def _find_existing_model_dir(configured):
    """模型目录解析：配置值优先；不存在则向上层目录查找（release 包在仓库内时，
    配置的相对 models/ 在 exe 旁不存在，但仓库根有）。最后回退内置两个已知模型。

    返回 `(实际使用的目录, 来源)`，来源 ∈ {`"config"`, `"fallback"`, `"missing"`}。
    **为什么要返回来源**：本仓当前的状态是"配置里那个 `models\\…` 早已改名成
    `asr-modules\\…`"，于是**运行时**只是靠回退才绿。把回退暴露成可打印的事实，
    等于让"绿灯的原因"可见——和 GATE 3 从"不崩就绿"升级为文本断言是同一条思路。
    """
    candidates = [configured]
    here = Path(BASE_DIR)
    for parent in [here] + list(here.parents)[:3]:
        candidates.append(str(parent / "asr-modules" / "sensevoice-small-int8"))
        candidates.append(str(parent / "asr-modules" / "qwen3-asr-0.6B"))
        candidates.append(str(parent / "models" / "sensevoice-small-int8"))   # 1.3.x 旧位置兜底
    for i, cand in enumerate(candidates):
        if cand and os.path.isdir(cand):
            return cand, ("config" if i == 0 else "fallback")
    return configured, "missing"


MODEL_SOURCE_LABEL = {
    "config": "配置文件（命中）",
    "default": "内置默认（配置未指定）",
    "fallback": "向上查找回退（配置指定的路径不存在）",
    "missing": "未找到（加载将失败）",
}


def describe_model_resolution():
    """**只读**地描述模型目录解析，供 GATE 3 打印"绿灯的原因"。不改任何全局。

    三件事必须分开报，因为它们**不保证是同一个路径**——这正是要看见的东西：
      `engine`     `AsrEngine()` 此刻实际会加载的目录（走 `_engine_default_model_dir`，
                   与 `__init__` 同一条规则）。#46 修复前它是**导入期快照**，与
                   `resolved` 长期可以不一致；现在两者同源，若仍然不等，说明
                   `load_config()` 没在配置改动后重跑过（`MODEL_DIR` 是陈旧的）。
      `configured` 配置文件里 `model_dir` 解析后的路径（相对路径按 `BASE_DIR` 展开）。
      `resolved`   走完 `_find_existing_model_dir` 的路径与来源（config/fallback/missing）。
      `live_*`     **常驻实例**那份配置（`%LOCALAPPDATA%\\<APP_ID>\\config.json`）的状态。

    为什么还要单列 `live_*`：构建期把 `<APP>_DATA_DIR` 钉到 `build/` 之后，`CONFIG_PATH`
    会**跟着搬走**（它默认 = `USER_DATA_DIR/config.json`），而 `seed_config()` 会在新位置
    播下一份**出厂** config（`model_dir` 是新路径）——于是"用户配置陈旧、只能靠回退"
    这件事反而被遮住了。所以要单独、只读地去看常驻那份。
    """
    # `engine` = 此刻不带参数构造 `AsrEngine()` 会加载的目录。必须走**与 __init__ 同一条
    # 取值规则**（`_engine_default_model_dir`）——旧写法读默认参数 `signature(...).default`
    # 是把它当成"引擎实际会加载什么"的代理，而那个默认值恰恰是导入期快照（#46）。
    engine_dir = str(_engine_default_model_dir())

    def _model_dir_of(path):
        try:
            with open(path, "r", encoding="utf-8-sig") as f:
                return json.load(f).get("model_dir")
        except Exception:
            return None

    raw = _model_dir_of(CONFIG_PATH)
    configured = _resolve_model_dir(raw)
    resolved, hit = _find_existing_model_dir(configured)
    # 常驻配置：目录名 = APP_ID，与是否重定向数据根无关（重定向只换前缀，不换末级名）。
    live_path = Path(os.environ.get("LOCALAPPDATA", "")) / os.path.basename(
        os.path.dirname(str(_USER_CONFIG_PATH))) / "config.json"
    live_raw = _model_dir_of(str(live_path))
    live_configured = _resolve_model_dir(live_raw)
    return {
        "config_value": raw,
        "configured": configured,
        "configured_exists": os.path.isdir(configured),
        "resolved": resolved,
        "source": "default" if not raw else hit,
        "engine": engine_dir,
        "live_config": str(live_path),
        "live_config_exists": live_path.is_file(),
        "live_value": live_raw,
        "live_configured": live_configured,
        "live_configured_exists": os.path.isdir(live_configured),
    }


def load_config():
    global AUTO_GAIN, SEGMENT_PADDING, VAD_FLOOR, MODEL_DIR, MODEL_NAME, NUM_THREADS_CFG
    global MODEL_DIR_CONFIGURED, MODEL_DIR_SOURCE
    try:
        with open(CONFIG_PATH, "r", encoding="utf-8-sig") as f:
            cfg = json.load(f)
        AUTO_GAIN = bool(cfg.get("auto_gain", True))
        SEGMENT_PADDING = float(cfg.get("segment_padding", 0.15))
        VAD_FLOOR = float(cfg.get("vad_floor", 0.005))
        raw = cfg.get("model_dir")
        configured = _resolve_model_dir(raw)
        MODEL_DIR, hit = _find_existing_model_dir(configured)
        MODEL_DIR_CONFIGURED = configured
        # 来源要区分"配置没写"与"配置写了但没命中"——否则内置默认会被误报成"来自配置"。
        if not raw:
            MODEL_DIR_SOURCE = "default"
        else:
            MODEL_DIR_SOURCE = hit
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


# 各类型模型必需的文件（用于严格校验，防止把不完整目录当 qwen3 默认类型）
MODEL_REQUIREMENTS = {
    "qwen3_asr": ("conv_frontend.onnx", "encoder.int8.onnx", "decoder.int8.onnx", "tokenizer"),
    "sense_voice": ("model.int8.onnx", "tokens.txt"),
    "fire_red_asr": ("encoder.int8.onnx", "decoder.int8.onnx", "tokens.txt"),
    "paraformer": ("model.int8.onnx", "tokens.txt"),
}


def _model_dir_complete(model_dir, mtype):
    """目录是否具备该类型必需的文件（qwen3 的 tokenizer 是子目录，单独判）。"""
    try:
        files = {f.lower() for f in os.listdir(model_dir)}
    except OSError:
        return False
    for req in MODEL_REQUIREMENTS[mtype]:
        if req == "tokenizer":
            if "tokenizer" not in files:
                return False
        elif not any(f == req or f.startswith(req) for f in files):
            return False
    return True


def iter_model_dirs(models_dir):
    """枚举 asr-modules 下可用的模型目录，返回 [(名称, 完整路径, 类型)]。"""
    out = []
    try:
        entries = sorted(os.listdir(models_dir))
    except OSError:
        return out
    for name in entries:
        d = os.path.join(models_dir, name)
        if not os.path.isdir(d):
            continue
        t = _detect_model_type(d)
        if t in MODEL_REQUIREMENTS and _model_dir_complete(d, t):
            out.append((name, d, t))
    return out


def find_bench_audio(models_dir):
    """找一段测试音频：优先 models\\test_zh.wav，其次 models 下任意 .wav。"""
    first = os.path.join(models_dir, "test_zh.wav")
    if os.path.exists(first):
        return first
    for root, _dirs, files in os.walk(models_dir):
        for f in sorted(files):
            if f.lower().endswith(".wav"):
                return os.path.join(root, f)
    return None


def run_benchmark(models_dir, progress=lambda kind, name: None):
    """性能检测核心（无 UI）：对 asr-modules 下每个模型测加载/短句/长音频。

    progress(kind, name)  kind ∈ {"load", "decode"}
    返回 {"audio_sec", "results": [...], "reco": 名或""}；无音频时 {"error": "no_audio"}。
    """
    import wave

    audio_path = find_bench_audio(models_dir)
    if not audio_path:
        return {"error": "no_audio"}
    with wave.open(audio_path, "rb") as w:
        assert w.getnchannels() == 1 and w.getsampwidth() == 2
        data = w.readframes(w.getnframes())
    seg = np.frombuffer(data, dtype=np.int16).astype(np.float32) / 32768.0
    audio_sec = len(seg) / SAMPLE_RATE
    long_audio = np.concatenate([seg] * 3) if audio_sec < 10 else seg
    long_sec = len(long_audio) / SAMPLE_RATE

    results = []
    for name, d, mtype in iter_model_dirs(models_dir):
        progress("load", name)
        t0 = time.perf_counter()
        eng = AsrEngine(model_dir=d)
        load_s = time.perf_counter() - t0
        try:
            progress("decode", name)
            eng.recognize(seg)  # 预热
            t0 = time.perf_counter()
            txt_short = eng.recognize(seg)
            dt_short = time.perf_counter() - t0
            t0 = time.perf_counter()
            txt_long = eng.recognize(long_audio)
            dt_long = time.perf_counter() - t0
            results.append({
                "name": name, "type": mtype, "load_s": round(load_s, 1),
                "rtf_short": round(dt_short / audio_sec, 3),
                "rtf_long": round(dt_long / long_sec, 3),
                "chars": len(txt_short), "ok": bool(txt_short.strip()),
            })
        finally:
            del eng
    usable = [r for r in results if r["ok"] and r["rtf_long"] < 1.0]
    reco = min(usable, key=lambda r: r["rtf_long"])["name"] if usable else ""
    return {"audio_sec": round(audio_sec, 1), "long_sec": round(long_sec, 1),
            "results": results, "reco": reco}


def perf_log(msg):
    """轻量性能日志：追加到用户数据目录 local-speak2text.log，失败静默。"""
    try:
        from modules.paths import LOG_DIR

        LOG_DIR.mkdir(parents=True, exist_ok=True)
        with open(LOG_DIR / "local-speak2text.log", "a", encoding="utf-8") as f:
            f.write(time.strftime("%Y-%m-%d %H:%M:%S ") + msg + "\n")
    except OSError:
        pass


class AsrEngine:
    """按模型目录自动选择 sherpa-onnx loader（qwen3_asr / sense_voice / fire_red_asr / paraformer）。"""

    def __init__(self, model_dir=None, num_threads=None, model_type=None):
        # `model_dir=None` 是 sentinel，不是"用一个默认目录"——真正的取值发生在**调用时**。
        # 旧写法 `model_dir=MODEL_DIR` 的默认参数在**函数定义时**求值一次，即导入期的快照；
        # `load_config()` 之后重绑模块级 MODEL_DIR 对它无效，于是"用户在托盘里换了模型目录、
        # 引擎却还在加载老模型"（#46，实测见 tests/test_engine_model_dir.py）。
        # 紧挨着的 num_threads 本来就是 Sentinel + 体内取值，两者现在同形。
        if model_dir is None:
            model_dir = _engine_default_model_dir()
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


def _similarity(actual, reference):
    """两个字符串的**字符级重合率**（0..1）：`difflib` 的最长匹配块占比。

    为什么不用"命中词数"：词表判据**只在输入被钉住时才成立**，而本门禁的测试 wav
    并非仓库资产（本地 `asr-modules/` 与 CI 下载的是两句不同的话，见 `selftest` 里的长注释）。
    重合率对"同一句话 + ASR 少量波动"给高分（>=0.9），对"另一句话/乱码"给低分（<0.4），
    既保留"识别出乱码必须红"的判别力，又不把判据绑死在某一份 wav 上。

    只做标点/空白归一化（标点有无是 ASR 的正常波动），不做分词——不引第三方依赖。
    """
    import difflib
    import re as _re
    strip = lambda s: _re.sub(r"[\s，。、！？,.!?；;：:\"'“”‘’（）()]", "", s)
    a, b = strip(actual or ""), strip(reference or "")
    if not a or not b:
        return 0.0
    return difflib.SequenceMatcher(None, a, b).ratio()


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

    # 让"绿灯的原因"可见（lead 裁定 2026-09-19）：模型目录从哪来、是否靠回退。
    # 不判 FAIL —— 配置陈旧是用户侧状态，不是代码缺陷；最多 OUTPUT + WARN。
    info = describe_model_resolution()
    print("[selftest] engine  模型目录: %s" % info["engine"])
    print("[selftest] config  model_dir: %r -> %s (%s)"
          % (info["config_value"], info["configured"],
             "存在" if info["configured_exists"] else "不存在"))
    print("[selftest] 解析结果: %s  来源=%s"
          % (info["resolved"], MODEL_SOURCE_LABEL.get(info["source"], info["source"])))
    if info["source"] == "fallback":
        print("[WARN] 本次生效配置指定的模型目录不存在，靠向上查找回退才跑通；"
              "请更新配置里的 model_dir 以消除这条隐式依赖。")
    # 常驻实例那份配置：**用户侧状态陈旧**，不是代码缺陷 → 只报 WARN，不判 FAIL。
    print("[selftest] 常驻配置: %s (%s)"
          % (info["live_config"], "存在" if info["live_config_exists"] else "不存在"))
    if info["live_config_exists"]:
        print("[selftest] 常驻 model_dir: %r -> %s (%s)"
              % (info["live_value"], info["live_configured"],
                 "存在" if info["live_configured_exists"] else "不存在"))
        if not info["live_configured_exists"]:
            print("[WARN] 常驻实例配置里的 model_dir 指向的目录在磁盘上不存在；"
                  "该实例运行时只能靠向上查找回退才找得到模型——请更新那份配置。")
    if os.path.normcase(info["engine"]) != os.path.normcase(info["resolved"]):
        print("[WARN] AsrEngine() 此刻会加载的目录（%s）与解析结果（%s）不是同一个——"
              "两者已共用同一条取值规则（#46），所以这通常意味着配置改过之后没有重跑 "
              "`load_config()`，模块级 MODEL_DIR 是陈旧的。" % (info["engine"], info["resolved"]))
    # #46 回归探针：把"正确形态"直接钉成构建期可见的事实——默认参数必须是 None sentinel，
    # 一旦有人改回 `model_dir=MODEL_DIR`（导入期快照），这里立刻说出来。
    # 与本节其余条目同级：WARN，不判 FAIL（它说的是代码形态，但构建不该因此停下）。
    from inspect import signature as _sig
    _default = _sig(AsrEngine.__init__).parameters["model_dir"].default
    if _default is not None:
        print("[WARN] AsrEngine 的 model_dir 默认参数又内嵌了目录（%r）——"
              "那是定义时求值的导入期快照，改配置后引擎不会跟着换目录（#46 回归）。"
              % (_default,))

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
    # 返回值必须判（2026-09-19 修）：`Event.wait()` 超时返回 False，旧写法把它丢弃，
    # "超时"与"正常完成"在输出上完全一样——这条门禁因此永远不会变红。
    if not finish_ev.wait(timeout=60):
        raise RuntimeError(
            "自检超时：60s 内没有收到 finish 事件（识别未完成或流水线卡住）")

    committed = "".join(ev[2] for ev in sink.events if ev[0] == "commit")
    print("=" * 40)
    print("定稿文本:", committed)
    # 结果断言（2026-09-19 补）：旧写法只断言 wav 格式，识别出乱码也照样绿。
    #
    # ⚠ 2026-09-20 修（CI 连红三轮的真凶，v1.4.1/.2/.3 都卡在这里）：
    # **本门禁的"期望文本"依赖一个仓库没有钉住的输入** —— 测试 wav 是本地 `asr-modules/`
    # 里放的那一份，而 CI 的 release.yml 下载的是 **sensevoice 那个 release 自带的
    # `test_wavs/zh.wav`**，两份**根本不是同一句话**。实测：
    #   * 本机 wav（paraformer 那句）→「欢迎大家来体验达摩院推出的语音识别模型」
    #   * CI 下载的 wav          →「开饭时间早上9点至下午5点。」
    # 旧写法只认 `("欢迎","达摩院","语音")` ⇒ CI 上必红、本机必绿，且**与新代码毫无关系**
    # （v1.4.0 发版时这条断言还不存在，所以"以前是绿的"）。
    #
    # 修法：把已知的两句都列为参照，用**字符级重合率**判定——容忍 ASR 的小波动，
    # 但乱码/空输出仍然必红（乱码对哪一句的重合率都极低）。这比"钉词表"更贴合实际：
    # **期望值必须跟着输入走，而输入此刻并未被仓库钉住**。
    # 若哪天 CI/本机换成第三份 wav，报错会把识别文本和两个重合率一并打出来 —— 加一行参照即可。
    if not committed.strip():
        raise RuntimeError("自检失败：定稿文本为空（模型加载成功但没有任何输出）")
    _REFS = (
        "欢迎大家来体验达摩院推出的语音识别模型",   # 本机 asr-modules/ 的 test_zh.wav
        "开饭时间早上9点至下午5点",                 # CI 下载的 sensevoice release test_wavs/zh.wav
    )
    _ratios = [(_ref, _similarity(committed, _ref)) for _ref in _REFS]
    _best_ref, _best = max(_ratios, key=lambda kv: kv[1])
    print("与参照文本的重合率:", ["%s=%.2f" % (r[:6], v) for r, v in _ratios])
    if _best < 0.6:
        raise RuntimeError(
            "自检失败：定稿文本与任何参照都相差过大（最高 %.2f < 0.6，参照 %r，"
            "实测 %r）。若换过测试 wav，把它的正确文本加进 _REFS 即可。"
            % (_best, [r for r, _ in _ratios], committed))


if __name__ == "__main__":
    import sys

    selftest(sys.argv[1] if len(sys.argv) > 1 else os.path.join(MODELS_DIR, "test_zh.wav"))
