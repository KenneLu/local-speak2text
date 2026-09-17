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
