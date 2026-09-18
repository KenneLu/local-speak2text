# local-speak2text

English | [简体中文](README.zh-CN.md)

Local, offline speech-to-text dictation for Windows. Hold a hotkey, speak, text lands at your cursor. Multi-engine ASR (Qwen3 / SenseVoice / FireRedASR / Paraformer) with auto-detection, 100% on-device.

A tiny Windows tray tool: hold **Right-Ctrl** and speak — a floating window shows the text live; release and it is typed into whatever window you are in. **Ctrl+Space** toggles continuous mode. Audio never leaves the machine.

## Install

1. Download `local-speak2text-<version>-windows-x64.zip` from [Releases](../../releases) and unpack it anywhere.
2. Download an ASR model (see [Models](#models)) into an `asr-modules\` folder - or use your own. The default model is SenseVoice-Small (int8) when present.
3. Run `local-speak2text.exe`. It lives in the tray.

## Hotkeys

| Key | Action |
|---|---|
| Hold Right-Ctrl | A floating window appears; text streams in live. Release to type it into the current window |
| Ctrl+Space | Toggle continuous mode: speak and text keeps flowing. Press again to finish and type |
| Esc | Cancel the current utterance (nothing is typed) |

Tray menu (right-click the icon): autostart, auto gain, **choose model folder**, **Language** (中文/English), **Help**, **Copy model-setup instructions**, **Benchmark models**, check for updates, quit.

## Models

Drop a model folder under `asr-modules\` next to the exe — the type is auto-detected from the file layout, no config change needed:

| Files in the folder | Detected as |
|---|---|
| `conv_frontend.onnx` + `encoder*.onnx` + `tokenizer/` | Qwen3-ASR |
| `model.int8.onnx` + `tokens.txt` | SenseVoice / Paraformer |
| `encoder.int8.onnx` + `decoder.int8.onnx` + `tokens.txt` | FireRedASR |

Ready-made int8 packages: [sherpa-onnx releases](https://github.com/k2-fsa/sherpa-onnx/releases/tag/asr-models). Or click **Copy model-setup instructions** in the tray and hand the prompt to an AI assistant — it covers the per-type file checklist and where to download.

**Benchmark models** (tray menu) runs a real recognition speed test on every model and prints RTF per model with a plain-language verdict and a recommendation.

Measured on the dev machine (16.6 s clip, CPU-only):

| Model | Decode | RTF | Verdict |
|---|---|---|---|
| SenseVoice-Small int8 | **0.43s** | **0.026** | default choice, built-in punctuation |
| Qwen3-ASR-0.6B int8 | 3.23s | 0.194 | baseline |
| FireRedASR2-AED int8 | 27.66s | 1.662 | too slow on CPU (more accurate, but unusable here) |

RTF = processing time ÷ audio duration. Below 1.0 keeps up with your speech; lower is faster.

## Configuration and data

Everything the app writes lives in `%LOCALAPPDATA%\local-speak2text\`, never in the folder you unpacked:

```text
config.json    settings (model folder, language, hotkey tuning)
log\           the app's log, one perf line per recognition (model, audio s, decode s, RTF, text)
crash.log      uncaught exceptions land here if the app ever dies
```

Key settings: `language` (`zh` / `en` / `auto`), `update_repo` (`owner/repo`, enables update checks), `num_threads` (ONNX threads — 8 measured fastest on a 16-thread CPU), `model_dir`. Point `LOCALSPEAK2TEXT_CONFIG` at a config file for tests/portable use.

## Updating

Use **Check for updates** in the tray menu. A new release downloads with SHA-256 verification and replaces the app when you quit the tray; your settings live in `%LOCALAPPDATA%` and survive untouched.

## Troubleshooting

- **"Cannot open microphone"**: another app is holding the mic (remote-desktop tools often do). Close it and retry.
- **Text did not appear**: typing uses clipboard + Ctrl+V; a few apps (games, elevated windows) block paste.
- **Crash / no tray icon**: check `%LOCALAPPDATA%\local-speak2text\crash.log` and `log\`.

## Development

```bat
build.bat            :: gates (compile, i18n, pipeline selftest) + icon + package + frozen smoke, then start it
build.bat norun nopause  :: unattended, used by CI
release.bat          :: tag v<version> and push; CI builds and publishes the zip
```

The version lives in `paths.py` (`VERSION`) — the single source of truth for the app, the release folder, and the git tag; pushing a `v*` tag is what publishes a release. Icons are code-generated (`icons.py`), no art assets. The UI is bilingual (`i18n.py`). See [CHANGELOG.md](CHANGELOG.md).

## License

[MIT](LICENSE) © 2026 KenneLu
