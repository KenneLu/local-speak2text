# Changelog

All notable changes to local-speak2text are documented here.
The tagging convention matches the versions in this file.

## 1.4.1

- **Fixed: the exe could not start at all since 1.2.0.** The single-instance
  mutex was named `Local\<app>\SingleInstance`; a named kernel object may not
  contain a second backslash after the `Local\` namespace prefix, so
  `CreateMutexW` always failed with err=3 (`ERROR_PATH_NOT_FOUND`). The guard
  treated a null handle as "another instance is running", so every launch
  showed the "already running" box and exited. Renamed to the family-standard
  `Local\<app>-single-instance`.
- **Guard now fails open.** When the guard itself cannot run, the app continues
  instead of refusing to start (STANDARDS D3.2). Only a confirmed
  `ERROR_ALREADY_EXISTS` cancels the launch. Both directions are now asserted
  by `tests/test_single_instance.py`.
- Last-error is cleared before `CreateMutexW` so a stale 183 cannot be
  misread as "already exists"; the duplicate path is logged instead of being
  silent.
- **New `tests/test_startup_path.py`**: runs the real `main()` with UI/model
  stubs, asserting the startup sequence is actually reached — `--smoke`
  bypasses the guard, which is why this defect survived three months of green
  builds. Both suites are now gates in `build.bat` (GATE 2b).
- **Instance isolation**: `LOCALSPEAK2TEXT_DATA_DIR` now redirects the whole
  data root (F11/D12, matches template `modules/paths` 1.1.2), so tests and
  build scripts no longer share config/log with a running tray instance.

## 1.4.0

- Model resources renamed: `models/` -> `asr-modules/` (auto-migrated once on
  first launch; keeps downloaded models intact).
- Default model is now SenseVoice-Small (int8) - lighter and faster RTF than
  the 0.6B default; Qwen3 remains selectable via "Choose model folder".
- Docs and locale strings updated to the new paths.

## 1.3.1

- Internal structure only: i18n moved into `modules/i18n.py` (family template
  layout, data-driven tables unchanged); imports updated. No behavior change.

## 1.3.0

- i18n v2: translation tables moved out of code into data files
  (`locales/zh.json` + `locales/en.json`, 74 entries each) - adding entries no
  longer touches code; mechanism aligned with the family template
  (my-diy-tool-template/modules/i18n). No user-visible behavior change.
- Build packages now bundle the locales folder.

## 1.2.0

- Single instance: a named mutex prevents a second tray instance from grabbing
  the keyboard hook and the audio device; a message box points to the running
  instance. Set `LST_ALLOW_MULTI=1` to bypass for tests.
- Rotating run log at `%LOCALAPPDATA%\local-speak2text\log\local-speak2text.log`
  (1 MB × 3 backups, reme-helper style) recording startup, model load, crashes
  and exit; new tray item "打开日志目录 / Open log folder".
- Tray menu restructured to the house standard (read-only info header on top,
  updates, business, open, preferences, quit last); "Guide..." is now the
  double-click default action.
- Fix: the updater referenced an undefined `APP_ID_PKG`, so downloading an
  update crashed with NameError before any file was written (regression from
  1.1.0's updater).

## 1.1.3

- Stable install location: in-place updates now install into
  `%LOCALAPPDATA%\local-speak2text\app\` and launch from there, so the
  autostart registry entry never goes stale across version updates.
- Autostart self-heal: on startup, if the registry entry points at an exe
  that no longer exists (old timestamped packages), it is rewritten to the
  current location.
- Quit confirmation: the tray "Quit" now asks before exiting (bilingual);
  cancel or closing the dialog keeps the app running.
- CI: release workflow now also fetches the test wav so the pipeline-selftest
  gate passes on clean runners (fixes the first v1.1.2 tag attempt).

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
