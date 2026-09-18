# -*- coding: utf-8 -*-
# TEMPLATE-FROM: my-diy-tool-template/modules/i18n/i18n.py | TEMPLATE-VER: 2.1.0
"""T5 · i18n v2 —— 机制与词表分离（数据驱动，蓝本 local-speak2text/i18n.py）。

代码只管机制（回退/格式化/持久化/探测）；词条是**数据**：工具根目录
`locales/zh.json` + `locales/en.json`（扁平 KV，utf-8）。工具加词条只改 JSON，
本文件与模板永远归一化一致（执行文档 N2/M1）。zh 键为基准，en 缺失回退 zh，
永不 KeyError。内置最小兜底表：locales 缺失时机制仍可用。

2.1.0：locales 目录解析内置 + 模块导入即自动加载——工具侧零样板，import 即得词条。
目录解析用**向上查找回退**（平铺与 src/modules 布局都命中），打包态回退 _MEIPASS。
"""
import json
import os
import sys
from pathlib import Path

_BUILTIN_ZH = {"menu_quit": "退出", "menu_open_logs": "打开日志目录"}
_BUILTIN_EN = {"menu_quit": "Quit", "menu_open_logs": "Open log folder"}

TABLES = {"zh": dict(_BUILTIN_ZH), "en": dict(_BUILTIN_EN)}
LANG = "zh"
# 门禁 2（D1）断言的核心键集：词表必须能回答这些键
KEY_MIN_SET = ("menu_quit", "menu_open_logs")


def load_tables(locales_dir):
    """从 locales_dir 合并 zh.json / en.json（数据文件，随工具分发）。失败静默。"""
    for lang, filename in (("zh", "zh.json"), ("en", "en.json")):
        path = os.path.join(str(locales_dir), filename)
        try:
            with open(path, encoding="utf-8") as f:
                TABLES[lang].update(json.load(f))
        except (OSError, ValueError):
            pass


def detect_system_lang():
    try:
        import ctypes
        return "zh" if ctypes.windll.kernel32.GetUserDefaultUILanguage() & 0xFF == 0x04 else "en"
    except Exception:
        return "zh"


def init(language="auto"):
    global LANG
    if language == "auto":
        language = detect_system_lang()
    LANG = language if language in TABLES else "zh"


def t(key, *args, **kwargs):
    """取词。支持 %s 与 {name} 两种填充。"""
    text = TABLES.get(LANG, {}).get(key) or _BUILTIN_ZH.get(key) or key
    if args and "%" in text:
        text = text % args
    if kwargs:
        text = text.format(**kwargs)
    return text


def available_langs():
    return sorted(TABLES.keys())


def load_language_from_config(config_path):
    try:
        with open(config_path, encoding="utf-8-sig") as f:
            return str(json.load(f).get("language", "auto"))
    except Exception:
        return "auto"


def save_language_to_config(config_path, language):
    try:
        cfg = {}
        if os.path.exists(config_path):
            with open(config_path, encoding="utf-8-sig") as f:
                cfg = json.load(f)
        cfg["language"] = language
        with open(config_path, "w", encoding="utf-8") as f:
            json.dump(cfg, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


def _locales_dir():
    """locales 数据目录：从本文件位置逐级向上查找（平铺与 src/modules 布局都命中）；
    打包态回退 _MEIPASS（PyInstaller --add-data 落点）。找不到时退回最后一级
    （load_tables 对缺失文件静默，兜底表保证机制可用）。"""
    here = Path(__file__).resolve().parent
    for base in (here, *here.parents):
        cand = base / "locales"
        if cand.is_dir():
            return cand
    meipass = getattr(sys, "_MEIPASS", "")
    return Path(meipass) / "locales" if meipass else here / "locales"


load_tables(_locales_dir())
