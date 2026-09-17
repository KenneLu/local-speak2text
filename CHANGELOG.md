# Changelog

All notable changes to local-speak2text are documented here.
The tagging convention matches the versions in this file.

## 1.1.2

- Bilingual README: `README.md` (English, canonical) + `README.zh-CN.md`
  (Chinese), each linking to the other at the top - same shape as reme-helper.

## 1.1.1

- Tray Help dialog: usage, how to add models (per-type file requirements),
  where config/logs live - all bilingual.
- "Copy model-setup instructions (for an AI assistant)": copies a ready-made
  prompt (per-type file checklist, sherpa-onnx releases link, CPU-suitability
  caveat) so an AI assistant can fetch and install a model end-to-end.
- "Benchmark models": real recognition speed test for every model under
  models\ - load time, short-clip and long-clip RTF, usability verdict,
  recommendation, and plain-language metric notes. The progress window can be
  closed; results pop up automatically when the run finishes.
- Shipped config defaults to SenseVoice and sets update_repo to the GitHub
  repo, enabling the update check out of the box.
- Model enumeration now validates required files per type (an incomplete
  folder is no longer mistaken for the default qwen3 type).
- CI: add requirements.txt (setup-python pip cache requires it).

## 1.1.0

- Multi-model auto-detection: Qwen3 / SenseVoice / FireRedASR / Paraformer
  model folders are identified by file layout; switch from the tray menu.
- SenseVoice-Small int8 benchmark: RTF 0.026 on the dev machine, ~7.5x faster
  than Qwen3-0.6B with identical output plus built-in punctuation.
- Overlay window grows upward with content (bottom-anchored, max 12 lines,
  internal scrolling keeps the latest text visible).
- Recognition queue: final results preempt partial previews; stale partials
  are dropped before decoding (no wasted duplicate decode on finish).
- Perf log: every recognition appends model/audio duration/RTF/text to
  %LOCALAPPDATA%\local-speak2text\log\local-speak2text.log.
- i18n: Chinese/English UI, tray menu toggle, persisted in config.
- Config and logs moved to %LOCALAPPDATA%\local-speak2text\ (one-time
  migration from the exe-side config.json).
- Update check + self-update via GitHub Releases (zip + sha256, applied on
  quit by a one-shot robocopy swap).
- Code-generated icons (microphone, blue=idle / orange=recording): tray icon
  plus a high-DPI taskbar .ico; the exe itself carries the icon.
- Build rewritten: version single-sourced from paths.py, gate tests
  (compile / i18n / pipeline selftest), deliverable checks, frozen smoke test.
- CI: tests.yml on every push/PR; release.yml builds and publishes the zip on
  v* tags; release.bat tags from a clean, pushed main branch only.

## 1.0.0

- First packaged release as qwen-dictate: hold Right-Ctrl to dictate,
  Ctrl+Space for continuous mode, local Qwen3-ASR-0.6B int8 via sherpa-onnx.
