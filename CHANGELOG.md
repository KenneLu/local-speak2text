# Changelog

All notable changes to local-speak2text are documented here.
The tagging convention matches the versions in this file.

## Unreleased

> 1.4.1 was never released: its single-instance root-cause fix is merged into this
> section and `VERSION` is rolled back to the last released version 1.4.0
> (STANDARDS G3 item 7: the version number changes only as part of a release).

- **Mechanism code now converges on the family template** (`my-diy-tool-template`
  modules, byte-identical copies): `icons` 2.0.0, `log_kit` 1.0.2, `paths` 1.1.2,
  `autostart` 1.1.1, `tray_kit` 2.0.1, plus the `appconfig` parameter file.
  `src/modules/` is now the home of shared mechanism; `main.py` keeps only
  tool-specific logic.
- `VERSION` moved to `src/modules/appconfig/appconfig.py` (still the single
  source of truth; `build.bat` / `release.bat` / `release.yml` read it there).
- **Fixed (GUI-verified): Esc did not close the quit confirmation dialog.**
  The quit dialog is now `tray_kit.confirm_quit_dialog`, which binds
  `<Escape>` to cancel; `tests/test_quit_confirm.py` presses Esc to pin it.
  Unconfirmed quits are impossible: rich dialog -> native `askyesno` ->
  proceed, never skipping confirmation.
- Tray menu rebuilds go through `tray_kit.MenuSignature` with a menu-open
  probe, so a rebuild can no longer yank an open right-click menu away.
- **Fixed: switching language did not refresh the tray menu** (user-reported).
  `main.py` read the package-level `i18n.LANG`, which the old `from .i18n import *`
  had copied into the package namespace — the value stayed `zh`, the menu
  signature never changed, and the menu stayed Chinese while notifications
  switched to English. Now reads `i18n.current_lang()` (template i18n 2.1.1,
  which no longer copies mutable state); pinned by `tests/test_i18n_menu.py`
  and `build.bat` GATE 2c.
- **Update chain hardened to reme-verified semantics** (three same-family defects):
  * **sha256 is now fail-closed** — `download_update` aborts when the `.sha256`
    asset is missing or does not match; the old `except FileNotFoundError: skip
    verify` silently downgraded the only integrity check.
  * **The apply script no longer guesses.** It waits for the old process to
    actually exit (`tasklist` to a file + `find`, never a pipe — the script runs
    detached with no console, where `tasklist | find` blocks forever) with a wait
    limit; it snapshots the current install **before** copying and only rotates
    that snapshot to `_backup` after a copy that succeeded; it checks the
    `robocopy` exit code (>=8 = failure) and then **never starts the new exe** —
    it restores from the snapshot and starts the previous version, or starts
    nothing and keeps the snapshot if the restore also fails; failures write an
    `update.failed` marker that the next launch reads once and surfaces to the
    user (`pop_failed_update_note`).
  * **`process_pending_update` no longer destroys evidence** — it parses the
    `robocopy` return code and, on failure, keeps `update.pending.json`, the
    staged files and writes the marker; the `os.system` string interpolation is
    replaced by `subprocess.run([...])`. It now lives in `updater.py` (the
    template's copy in `modules/paths` is left byte-identical and unused, pending
    the template fix).
  * Fixed the staged-dir detection: our `release.yml` zips the package **flat**,
    so `UPDATE_DIR/<APP_ID>` never existed and `prepare_update_cmd` would have
    raised "staged exe missing" — the auto-update had never been run end to end.
  * **An empty stage is intercepted before anything is touched.** `robocopy` from a
    stage with no payload returns rc 0–7 ("nothing copied, no error"), so the old
    code would call it success after `/purge` had already wiped the install dir —
    and the following `start` on the now-missing exe pops a modal box in a
    detached, console-less script (hangs forever). Now: no staged exe → don't
    touch the install dir, write the marker, keep the staged files.
  * **The apply script is launched without a console.** The exit path used
    `os.system('start "" /min ...')`, which goes through `cmd` and flashes a
    console window on the desktop. It now uses `launch_pending_cmd()` —
    `CREATE_NO_WINDOW | DETACHED_PROCESS`, the reme form — so the script
    outlives the parent without any visible window. If the launch fails the app
    logs it and notifies the user (the pending file stays, so the next start
    retries) instead of exiting silently.
    `tests/test_startup_path.py` now drives a **real exit flow** with a pending
    update staged and asserts the script was actually launched (marker file),
    on top of the flag assertions in `test_update_safety.py`.
  * New `tests/test_update_safety.py` (build.bat **GATE 2d**): the rendered
    `.bat` is really executed for both success and a failure injection
    (`robocopy` rc=16), asserting "failure starts the old version, never the new
    one, writes the marker and keeps the snapshot"; plus sha256 fail-closed and
    pending-evidence retention. The bat runs with `CREATE_NO_WINDOW` and a `.vbs`
    fake exe so it cannot pop a console window on the user's desktop.
- **Single-instance guard/probe converge on template `tray_kit` 2.2.0.** The
  inline `mutex_name_is_valid()` in `main.py` is deleted (no second definition);
  `--smoke` now calls `tray_kit.mutex_name_is_valid(APP_ID, mutex_name=MUTEX_NAME)`,
  which shares one naming criterion (`mutex_name_ok`) with the guard. The guard
  now fails **open** on an illegal name (logs it) instead of treating a
  `CreateMutexW` failure as "already running" — turning that programming error
  red is the build-time probe's job. `tests/test_single_instance.py` keeps the
  semantics with two assertions: guard passes + logs, probe says invalid.
- **New `--quit`**: asks a running instance to exit without the confirm
  dialog (request file lives under the redirectable data dir).
- Icon graphics are single-sourced from `appconfig.ICON_DRAW` (runtime tray
  and build-time `.ico` share one drawing function).
- `paths.py` carries **no override** any more: template 1.1.3 implements the
  `<APP>_CONFIG` env pin, and the env-var prefix is now the standard
  `APP_ID.upper().replace('-','_')` derivation. The two environment variables
  are therefore `LOCAL_SPEAK2TEXT_CONFIG` / `LOCAL_SPEAK2TEXT_DATA_DIR`
  (previously written without the underscore — a one-off name that is now
  retired, CONFORMANCE NAME-10).
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
- **Instance isolation**: `LOCAL_SPEAK2TEXT_DATA_DIR` redirects the whole
  data root (F11/D12, template `modules/paths`), so tests and build scripts
  no longer share config/log with a running tray instance.

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
