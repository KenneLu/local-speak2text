# -*- coding: utf-8 -*-
"""Help 弹窗 + 复制提示词（内容断言，不落剪贴板）+ 英文模式文案完整性。"""
import sys

sys.path.insert(0, r"H:\Tools\my_diy_tools\local-speak2text\src")
from modules import i18n
import main as M

for lang in ("zh", "en"):
    i18n.init(lang)
    overlay = M.Overlay()
    ctrl = M.Controller(overlay, None)
    overlay.root.after(40, ctrl.poll)

    # Help 弹窗
    ctrl._handle(("help",))
    overlay.root.update()
    tops = [w for w in overlay.root.winfo_children()
            if isinstance(w, __import__("tkinter").Toplevel)]
    assert tops, f"[{lang}] help window missing"
    assert i18n.t("help_title") not in (None, ""), f"[{lang}] empty help title"
    body = i18n.t("help_body")
    assert ("如何导入模型" in body) or ("How to add a model" in body), f"[{lang}] help missing import section"
    for w in tops:
        w.destroy()
    overlay.root.update()

    # 复制提示词内容（直接取替换后的正文断言，不碰剪贴板）
    prompt = i18n.t("copy_prompt_body").replace("<MODELS_DIR>", "X:\\models")
    assert "models" in prompt and "sherpa-onnx" in prompt and "tokens.txt" in prompt
    for kw in ("model.int8.onnx", "conv_frontend.onnx", "tokenizer"):
        assert kw in prompt, f"[{lang}] prompt missing {kw}"
    if lang == "en":
        assert not any("\u4e00" <= ch <= "\u9fff" for ch in prompt), "en prompt has Chinese"
        assert not any("\u4e00" <= ch <= "\u9fff" for ch in i18n.t("bench_running"))
        assert not any("\u4e00" <= ch <= "\u9fff" for ch in i18n.t("bench_explain"))
        assert not any("\u4e00" <= ch <= "\u9fff" for ch in i18n.t("bench_result_title"))
        assert not any("\u4e00" <= ch <= "\u9fff" for ch in i18n.t("update_ready_restart"))
    print(f"[{lang}] help + prompt OK")
    overlay.root.quit()
    overlay.root.destroy()
print("HELP/COPY/PROMPT TEST OK")
