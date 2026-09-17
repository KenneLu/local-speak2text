# -*- coding: utf-8 -*-
"""轻量 i18n：t() 取词 + 中英词典 + 语言检测/持久化。

语言来源优先级：环境覆盖 > config.json 的 language 字段 > Windows UI 语言（auto）。
词典只覆盖界面文案；zh 键同时充当 key，英文缺失时回退中文，永远不会 KeyError。
"""
import ctypes
import json
import os

_ZH = {
    "app_title": "local-speak2text —— 本地离线语音转文字小工具",
    "menu_autostart": "开机自启",
    "menu_autostart_on": "已开启开机自启",
    "menu_autostart_off": "已关闭开机自启",
    "menu_gain": "自动增益",
    "menu_gain_on": "自动增益: 开",
    "menu_gain_off": "自动增益: 关",
    "menu_language": "Language 语言",
    "menu_choose_model": "选择模型目录...",
    "menu_choose_model_title": "选择 ASR 模型目录（Qwen3 / SenseVoice / FireRedASR / Paraformer）",
    "menu_check_update": "检查更新",
    "menu_update_now": "立即更新",
    "menu_open_logs": "打开日志目录",
    "menu_quit": "退出",
    "tray_loading": "%s - 正在加载模型...",
    "tray_ready": "%s - 就绪 [%s]",
    "tray_recording": "%s - 录制中...",
    "tray_idle": "%s - 就绪",
    "tray_load_failed": "%s - 模型加载失败",
    "notify_loading": "正在加载模型...",
    "notify_ready": "就绪：按住右 Ctrl 说话（模型: %s）",
    "notify_load_failed": "模型加载失败，请右键托盘选择模型目录",
    "notify_model_updated": "模型目录已更新: %s [%s]",
    "notify_model_failed": "模型加载失败: %s",
    "notify_gain_on": "自动增益: 开",
    "notify_gain_off": "自动增益: 关",
    "notify_autostart_on": "已开启开机自启",
    "notify_autostart_off": "已关闭开机自启",
    "status_listening_hold": "● 正在聆听... 松开右 Ctrl 结束",
    "status_listening_cont": "● 持续聆听中... 再次 Ctrl+空格 结束，Esc 取消",
    "status_recognizing": "识别中...",
    "status_error_prefix": "✗ ",
    "err_mic_open": "无法打开麦克风：所有音频接口尝试失败，请检查麦克风是否被其他程序占用",
    "err_mic_start": "麦克风启动失败：{e}",
    "update_checking": "正在检查更新...",
    "update_latest": "已是最新版本 %s",
    "update_new": "发现新版本 %s（当前 %s）",
    "update_check_fail": "检查更新失败: %s",
    "update_downloading": "正在下载更新 %s ...",
    "update_download_fail": "下载更新失败: %s",
    "update_ready_restart": "更新已就绪，退出后将自动完成升级",
    "update_no_repo": "未配置更新源（update_repo）",
    "quit_confirm_title": "退出确认",
    "quit_confirm_body": "确定要退出 local-speak2text 吗？\n\n退出后语音输入将不可用（开机自启开启时，下次开机自动恢复）。",
    "quit_confirm_yes": "退出",
    "quit_confirm_no": "取消",
    "menu_help": "使用指引...",
    "menu_copy_model_prompt": "复制添加模型方式（交给 AI 执行）",
    "menu_benchmark": "检测模型性能",
    "help_title": "local-speak2text 使用说明",
    "help_close": "关闭",
    "copy_prompt_copied": "已复制到剪贴板：粘贴给 AI 助手即可让它帮你添加模型",
    "copy_prompt_fail": "复制失败: %s",
    "bench_title": "模型性能检测",
    "bench_running": "正在检测模型性能…\n\n本窗口可以关闭，检测完成后会自动重新弹出结果。\n（要对每个模型做真实识别：短句一次 + 长音频一次）",
    "bench_working": "正在检测: %s",
    "bench_failed": "检测失败: %s",
    "bench_no_audio": "models 目录下没有找到 .wav 测试音频，无法检测。\n请放一个 16kHz 单声道 wav 到 models 目录后重试。",
    "bench_result_title": "模型性能检测结果",
    "bench_audio_info": "测试音频 %.1f 秒（长音频测试拼接为 %.1f 秒）",
    "bench_col_model": "模型",
    "bench_col_type": "类型",
    "bench_col_load": "加载(秒)",
    "bench_col_rtf_short": "RTF·短句",
    "bench_col_rtf_long": "RTF·长音频",
    "bench_col_verdict": "结论",
    "bench_verdict_ok": "可用",
    "bench_verdict_slow": "太慢",
    "bench_verdict_fail": "无输出",
    "bench_reco": "推荐使用: %s",
    "bench_reco_none": "没有模型达到可用标准（RTF < 1.0 且能正常出字）",
    "bench_explain": "指标说明（给不熟悉的读者）：\n"
        "· RTF（实时率）= 处理耗时 ÷ 音频时长。RTF 0.03 表示 10 秒音频约 0.3 秒处理完；\n"
        "  RTF 1.0 是及格线（跟得上你说话的速度），越小越快；大于 1 就是说完还要等。\n"
        "· 加载(秒)：切换到该模型时要等多久。\n"
        "· 结论：RTF < 1.0 且能正常出字 = 可用；RTF ≥ 1.0 说完要干等 = 太慢；识别不出文字 = 无输出。\n"
        "· 「推荐使用」= 可用模型里长音频 RTF 最小（最跟手）的那个。切换模型：托盘右键 → 选择模型目录。",
    "help_body": "local-speak2text —— 本地离线语音转文字\n\n"
        "【怎么用】\n"
        "· 按住右 Ctrl 说话，松手后文字自动键入当前窗口；\n"
        "· 左 Ctrl+空格 切换持续模式（一直说一直出字），再按一次结束；Esc 取消本次；\n"
        "· 全程离线，语音不上传。\n\n"
        "【如何导入模型】\n"
        "1. 在本工具目录下的 models 文件夹里新建一个文件夹（名字随意，如 my-model）；\n"
        "2. 把模型文件按类型放进去（自动识别，无需改配置）：\n"
        "   · Qwen3 系列：conv_frontend.onnx + encoder/decoder int8 onnx + tokenizer 子目录；\n"
        "   · SenseVoice：model.int8.onnx + tokens.txt；\n"
        "   · FireRedASR：encoder.int8.onnx + decoder.int8.onnx + tokens.txt；\n"
        "   · Paraformer：model.int8.onnx + tokens.txt；\n"
        "3. 托盘右键 → 选择模型目录 → 选中该文件夹即可。\n"
        "   模型可从 sherpa-onnx 官方发布页下载 int8 预编译包。也可以用\n"
        "   「复制添加模型方式（交给 AI 执行）」把完整步骤复制给 AI 助手代办。\n\n"
        "【检测模型性能】\n"
        "托盘右键 → 检测模型性能：对 models 下每个模型做真实识别测速（RTF），\n"
        "并给出是否可用的结论与推荐。换机器后建议跑一次。\n\n"
        "【配置与日志在哪】\n"
        "· 配置：%LOCALAPPDATA%\\local-speak2text\\config.json\n"
        "· 日志：%LOCALAPPDATA%\\local-speak2text\\log\\\n"
        "· 性能记录：每次识别都会追加一行耗时记录到上面的 log 里。\n\n"
        "【其他】\n"
        "· 托盘右键可切换界面语言（中文/English）、开机自启、自动增益；\n"
        "· 检查更新：配置 update_repo 后可用。"
    ,
    "copy_prompt_body": "请帮我给 local-speak2text（一个 Windows 本地离线语音转文字小工具，基于 sherpa-onnx）添加一个新 ASR 模型。要求：\n\n"
        "1. 模型放在工具目录的 models\\ 子目录下，新建一个独立文件夹（名字用模型名，如 qwen3-asr-1.7B）。\n"
        "2. 不同模型类型需要的文件（按此检查下载的包是否完整）：\n"
        "   - Qwen3-ASR 系列：conv_frontend.onnx、encoder.int8.onnx、decoder.int8.onnx、tokenizer\\ 子目录（含 tokenizer 配置与词表）；\n"
        "   - SenseVoice-Small：model.int8.onnx、tokens.txt；\n"
        "   - FireRedASR（AED 或 CTC）：encoder.int8.onnx、decoder.int8.onnx、tokens.txt（CTC 版无 decoder 则不适用）；\n"
        "   - Paraformer：model.int8.onnx、tokens.txt。\n"
        "3. 优先从 sherpa-onnx 官方发布页下载 int8 预编译包：\n"
        "   https://github.com/k2-fsa/sherpa-onnx/releases/tag/asr-models\n"
        "   （下载 <模型名>-int8-<日期>.tar.bz2，解压后把上表所需文件放进新文件夹。）\n"
        "4. 不需要改任何配置文件——工具按目录内文件布局自动识别模型类型；放好后由我在托盘菜单里选择该目录。\n"
        "5. 如果该模型在我这台 CPU 上明显跑不动（官方 RTF 或社区反馈远大于 0.5），请先提醒我再下载。\n"
        "6. 放好后运行工具托盘菜单的「检测模型性能」验证可用性。\n\n"
        "我的 models 目录在：<MODELS_DIR>"
    ,
}

_EN = {
    "app_title": "local-speak2text - local offline speech-to-text tool",
    "menu_autostart": "Start with Windows",
    "menu_autostart_on": "Autostart enabled",
    "menu_autostart_off": "Autostart disabled",
    "menu_gain": "Auto gain",
    "menu_gain_on": "Auto gain: on",
    "menu_gain_off": "Auto gain: off",
    "menu_language": "Language 语言",
    "menu_choose_model": "Choose model folder...",
    "menu_choose_model_title": "Choose an ASR model folder (Qwen3 / SenseVoice / FireRedASR / Paraformer)",
    "menu_check_update": "Check for updates",
    "menu_update_now": "Update now",
    "menu_open_logs": "Open log folder",
    "menu_quit": "Quit",
    "tray_loading": "%s - loading model...",
    "tray_ready": "%s - ready [%s]",
    "tray_recording": "%s - recording...",
    "tray_idle": "%s - ready",
    "tray_load_failed": "%s - model load failed",
    "notify_loading": "Loading model...",
    "notify_ready": "Ready: hold Right-Ctrl and speak (model: %s)",
    "notify_load_failed": "Model load failed. Right-click the tray icon to choose a model folder.",
    "notify_model_updated": "Model folder updated: %s [%s]",
    "notify_model_failed": "Model load failed: %s",
    "notify_gain_on": "Auto gain: on",
    "notify_gain_off": "Auto gain: off",
    "notify_autostart_on": "Autostart enabled",
    "notify_autostart_off": "Autostart disabled",
    "status_listening_hold": "● Listening... release Right-Ctrl to finish",
    "status_listening_cont": "● Continuous listening... Ctrl+Space to finish, Esc to cancel",
    "status_recognizing": "Recognizing...",
    "status_error_prefix": "✗ ",
    "err_mic_open": "Cannot open microphone: all audio backends failed. Check if another app is using it.",
    "err_mic_start": "Microphone failed to start: {e}",
    "update_checking": "Checking for updates...",
    "update_latest": "Already up to date (%s)",
    "update_new": "New version %s available (current %s)",
    "update_check_fail": "Update check failed: %s",
    "update_downloading": "Downloading update %s ...",
    "update_download_fail": "Update download failed: %s",
    "update_ready_restart": "Update ready - it will be applied after you quit",
    "update_no_repo": "Update source not configured (update_repo)",
    "quit_confirm_title": "Quit confirmation",
    "quit_confirm_body": "Quit local-speak2text?\n\nVoice input will be unavailable until you start it again (or at next boot if autostart is on).",
    "quit_confirm_yes": "Quit",
    "quit_confirm_no": "Cancel",
    "menu_help": "Guide...",
    "menu_copy_model_prompt": "Copy model-setup instructions (for an AI assistant)",
    "menu_benchmark": "Benchmark models",
    "help_title": "local-speak2text Help",
    "help_close": "Close",
    "copy_prompt_copied": "Copied to clipboard - paste it to your AI assistant",
    "copy_prompt_fail": "Copy failed: %s",
    "bench_title": "Model Benchmark",
    "bench_running": "Benchmarking models...\n\nYou can close this window; results will pop up automatically when done.\n(each model runs a real recognition pass: one short clip + one long clip)",
    "bench_working": "Benchmarking: %s",
    "bench_failed": "Benchmark failed: %s",
    "bench_no_audio": "No .wav test audio found under models\\.\nPut a 16kHz mono wav file into the models folder and retry.",
    "bench_result_title": "Benchmark Results",
    "bench_audio_info": "Test clip %.1fs (long test concatenated to %.1fs)",
    "bench_col_model": "Model",
    "bench_col_type": "Type",
    "bench_col_load": "Load(s)",
    "bench_col_rtf_short": "RTF short",
    "bench_col_rtf_long": "RTF long",
    "bench_col_verdict": "Verdict",
    "bench_verdict_ok": "Usable",
    "bench_verdict_slow": "Too slow",
    "bench_verdict_fail": "No output",
    "bench_reco": "Recommended: %s",
    "bench_reco_none": "No model meets the usable bar (RTF < 1.0 with valid output)",
    "bench_explain": "Metric notes (for readers new to ASR):\n"
        "- RTF (real-time factor) = processing time / audio duration. RTF 0.03 means a 10s clip takes ~0.3s;\n"
        "  1.0 is the pass line (keeps up with your speech); lower is faster; above 1.0 you wait after speaking.\n"
        "- Load(s): how long switching to that model takes.\n"
        "- Verdict: RTF < 1.0 with valid output = Usable; RTF >= 1.0 = Too slow; no text = No output.\n"
        "- 'Recommended' = the usable model with the lowest long-clip RTF (most responsive). Switch models: tray right-click > Choose model folder.",
    "help_body": "local-speak2text - local offline speech-to-text\n\n"
        "[How to use]\n"
        "- Hold Right-Ctrl and speak; on release the text is typed into the current window;\n"
        "- Ctrl+Space toggles continuous mode (speak and text keeps flowing); press again to finish; Esc cancels;\n"
        "- Fully offline - audio never leaves this machine.\n\n"
        "[How to add a model]\n"
        "1. Create a folder under the app's models folder (any name, e.g. my-model);\n"
        "2. Put model files in by type (auto-detected, no config change needed):\n"
        "   - Qwen3 family: conv_frontend.onnx + encoder/decoder int8 onnx + tokenizer subfolder;\n"
        "   - SenseVoice: model.int8.onnx + tokens.txt;\n"
        "   - FireRedASR: encoder.int8.onnx + decoder.int8.onnx + tokens.txt;\n"
        "   - Paraformer: model.int8.onnx + tokens.txt;\n"
        "3. Tray right-click > Choose model folder > pick it.\n"
        "   Get int8 packages from the sherpa-onnx releases page. Or use\n"
        "   'Copy model-setup instructions (for an AI assistant)' and let an AI do it for you.\n\n"
        "[Benchmark]\n"
        "Tray right-click > Benchmark models: real recognition speed test (RTF) for every\n"
        "model under models\\, with a usability verdict and a recommendation. Re-run after changing hardware.\n\n"
        "[Where are config and logs]\n"
        "- Config: %LOCALAPPDATA%\\local-speak2text\\config.json\n"
        "- Logs: %LOCALAPPDATA%\\local-speak2text\\log\\\n"
        "- Perf trace: one line per recognition is appended to the log above.\n\n"
        "[Other]\n"
        "- Tray right-click switches UI language (Chinese/English), autostart, auto gain;\n"
        "- Check for updates: available once update_repo is configured."
    ,
    "copy_prompt_body": "Please add a new ASR model to local-speak2text (a Windows local offline speech-to-text tray tool built on sherpa-onnx). Requirements:\n\n"
        "1. Models live under the app's models\\ subfolder; create one folder per model (name it after the model, e.g. qwen3-asr-1.7B).\n"
        "2. Required files per model type (use this to check the downloaded package):\n"
        "   - Qwen3-ASR family: conv_frontend.onnx, encoder.int8.onnx, decoder.int8.onnx, tokenizer\\ subfolder (tokenizer config + vocab);\n"
        "   - SenseVoice-Small: model.int8.onnx, tokens.txt;\n"
        "   - FireRedASR (AED or CTC): encoder.int8.onnx, decoder.int8.onnx, tokens.txt (CTC has no decoder - not applicable);\n"
        "   - Paraformer: model.int8.onnx, tokens.txt.\n"
        "3. Prefer official int8 prebuilt packages from the sherpa-onnx releases page:\n"
        "   https://github.com/k2-fsa/sherpa-onnx/releases/tag/asr-models\n"
        "   (download <model>-int8-<date>.tar.bz2, extract, copy the files listed above into the new folder.)\n"
        "4. No config edits are needed - the tool auto-detects the model type from the folder layout; I will pick the folder in the tray menu afterwards.\n"
        "5. If the model is clearly too heavy for my CPU (official/community RTF well above 0.5), warn me before downloading.\n"
        "6. When done, verify via the tray menu 'Benchmark models'.\n\n"
        "My models folder is: <MODELS_DIR>"
    ,
}

TABLES = {"zh": _ZH, "en": _EN}
LANG = "zh"  # 运行时语言，由 init() 设置


def detect_system_lang():
    try:
        return "zh" if ctypes.windll.kernel32.GetUserDefaultUILanguage() & 0xFF == 0x04 else "en"
    except Exception:
        return "zh"


def init(language="auto"):
    """language: 'zh' | 'en' | 'auto'。"""
    global LANG
    if language == "auto":
        language = detect_system_lang()
    LANG = language if language in TABLES else "zh"


def t(key, *args, **kwargs):
    """取词。zh 键为基准，en 缺失回退中文；支持 %s 与 {name} 两种填充。"""
    text = TABLES.get(LANG, _ZH).get(key) or _ZH.get(key) or key
    if args:
        text = text % args if "%" in text else text
    if kwargs:
        text = text.format(**kwargs)
    return text


def available_langs():
    return sorted(TABLES.keys())


def load_language_from_config(config_path, encoding="utf-8-sig"):
    try:
        with open(config_path, "r", encoding=encoding) as f:
            return str(json.load(f).get("language", "auto"))
    except Exception:
        return "auto"


def save_language_to_config(config_path, language, encoding="utf-8"):
    try:
        cfg = {}
        if os.path.exists(config_path):
            with open(config_path, "r", encoding=encoding) as f:
                cfg = json.load(f)
        cfg["language"] = language
        with open(config_path, "w", encoding=encoding) as f:
            json.dump(cfg, f, ensure_ascii=False, indent=2)
    except Exception:
        pass
