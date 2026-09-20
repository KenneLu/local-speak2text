@echo off
rem ---------------------------------------------------------------------------
rem local-speak2text build: gate tests -> icon -> PyInstaller -> frozen checks
rem
rem ASCII-only on purpose: cmd.exe parses .bat with the machine ANSI code page.
rem
rem Usage: build.bat [norun] [nopause]
rem   norun    do not start the built exe (starting it is the default)
rem   nopause  unattended (no "press any key") - used by CI
rem
rem Version comes from appconfig.VERSION (single source of truth).
rem ---------------------------------------------------------------------------
setlocal EnableExtensions
cd /d "%~dp0"

set RUN_AFTER=1
set NOPAUSE=
set BUILD_ARGS=%*
if not defined BUILD_ARGS goto :args_done
for %%a in (%BUILD_ARGS%) do (
  if /i "%%a"=="norun" set RUN_AFTER=
  if /i "%%a"=="nopause" set NOPAUSE=1
)
:args_done

set PY=H:\Tools\Python\Python313\python.exe
if not exist "%PY%" set PY=python
"%PY%" -c "import sys" >nul 2>nul
if errorlevel 1 (
  echo [ERROR] Python not found. Set PY=... at the top of build.bat.
  if not defined NOPAUSE pause
  exit /b 1
)

rem Version: read from appconfig.py so the script and the app cannot drift apart.
rem Robust parse: take everything after '=', drop quotes, then keep the FIRST
rem space-delimited token. A trailing comment on the VERSION line can therefore
rem never leak into the version string / release path (same fix in the template).
set VERSION=
for /f "tokens=2 delims==" %%a in ('%SystemRoot%\System32\findstr.exe /b /c:"VERSION = " src\modules\appconfig\appconfig.py') do set VERSION=%%a
for /f "tokens=1" %%a in ("%VERSION:"=%") do set VERSION=%%a
if not defined VERSION (
  echo [ERROR] Cannot read VERSION from src\modules\appconfig\appconfig.py.
  if not defined NOPAUSE pause
  exit /b 1
)
set VERSION=%VERSION:"=%
set APPNAME=local-speak2text
set PACKAGE=%APPNAME%-%VERSION%
rem The release folder keeps the version; the exe must NOT: the autostart
rem registry value stores the full path, a versioned name would strand it.
set RELEASE_DIR=release\%PACKAGE%
set FROZEN_EXE=%RELEASE_DIR%\%APPNAME%.exe

echo [VERSION] %VERSION%  release: %RELEASE_DIR%

rem G1 RELAXED (2026-09-19, C2): target-dir existence is INFO, not a refusal.
rem The refusal condition is the running-instance guard below (D1-02); safety comes
rem from C2 - the live instance holds its own exe (no FILE_SHARE_DELETE), so the
rem kernel rejects deleting it with winerror 32 rather than emptying it silently.
rem CLEANLINESS IS NOT RELAXED: the old dir is removed right after that guard, so
rem the build always assembles from scratch and never reuses a stale file.
if exist "%RELEASE_DIR%" echo [INFO] %RELEASE_DIR% exists - will be removed and rebuilt from scratch.

rem ---------------------------------------------------------------------------
rem Running-instance guard (D1-02, refined 2026-09-19): refuse ONLY when the live
rem instance runs FROM THE TARGET release dir. Building a DIFFERENT version dir is
rem safe - files differ, the frozen smoke pins _CONFIG/_DATA_DIR and never takes
rem the mutex. What IS unsafe is deleting/overwriting the dir a live instance runs
rem from (2026-09-19 incident: release\...-1.4.1 was hollowed out while a tray
rem instance was running inside it). The same guard must precede any manual rm.
rem ---------------------------------------------------------------------------
set "RUNNING_EXE="
for /f "usebackq delims=" %%p in (`powershell -NoProfile -Command "(Get-Process -Name %APPNAME% -ErrorAction SilentlyContinue).Path | Select-Object -First 1"`) do set "RUNNING_EXE=%%p"
set "RUNNING_DIR="
if defined RUNNING_EXE for %%d in ("%RUNNING_EXE%") do set "RUNNING_DIR=%%~dpd"
rem Normalize a trailing backslash WITHOUT the `"%~1"=="\"` idiom: cmd parses
rem the sequence backslash-quote specially and aborts the whole script with
rem "The syntax of the command is incorrect." -- and it fires on the
rem "no instance running" path, i.e. the guard broke the very build it exists
rem to protect.
rem
rem MEASURED 2026-09-20 (verifier): `%%~fd` does NOT strip the trailing
rem backslash here -- `for %%d in ("C:\aa\bb\") do ... %%~fd` yields `C:\aa\bb\`
rem unchanged. The previous line relied on that false premise, so RUNNING_DIR
rem kept its trailing `\` and NEVER matched TARGET_DIR (which comes from
rem `"%CD%\%RELEASE_DIR%"`, no trailing `\`) => the running-instance guard was
rem dead, and the `rmdir /s /q` below went first: a live instance's release dir
rem was HOLLOWED OUT (exe survives via the C2 handle, but `_internal/`,
rem `locales/`, `README.md` were all deleted) before the lock made it fail.
rem That is exactly the 2026-09-19 incident this guard exists to prevent.
rem Fix = same idiom as dsh/ocx (substring on the ACTION side; the `:~` ban in
rem the C-43 criterion applies to `if` CONDITIONS, not to `set`).
if defined RUNNING_DIR set "RUNNING_DIR=%RUNNING_DIR:~0,-1%"
set "TARGET_DIR="
for %%d in ("%CD%\%RELEASE_DIR%") do set "TARGET_DIR=%%~fd"
if defined RUNNING_DIR if /i "%RUNNING_DIR%"=="%TARGET_DIR%" (
  echo [ERROR] A %APPNAME% instance is running FROM %RELEASE_DIR%.
  echo [ERROR] Exit it from the tray before building that directory.
  if not defined NOPAUSE pause
  exit /b 1
)
if defined RUNNING_DIR echo [INFO] %APPNAME% running from "%RUNNING_DIR%" - not the target dir, build continues.
if not defined RUNNING_EXE (
  %SystemRoot%\System32\tasklist.exe /fo csv 2>nul | %SystemRoot%\System32\findstr.exe /i /c:"%APPNAME%.exe" >nul
  if not errorlevel 1 echo [WARN] %APPNAME%.exe is running but its path could not be read; target dir not verified.
)

rem G1 relaxed: remove the existing same-version dir NOW (after the guard) so the
rem assembly below starts from zero. A live instance would have been refused above;
rem any other lock makes rmdir fail loudly right here instead of silently reusing.
if exist "%RELEASE_DIR%" (
  echo [INFO] removing %RELEASE_DIR% - rebuild from scratch ...
  rmdir /s /q "%RELEASE_DIR%"
)
if exist "%RELEASE_DIR%" (
  echo [ERROR] could not remove %RELEASE_DIR% - it is locked, possibly by a live instance.
  if not defined NOPAUSE pause
  exit /b 1
)

rem ---------------------------------------------------------------------------
rem GATE 1: compile every module
rem ---------------------------------------------------------------------------
echo [TEST] compile check ...
"%PY%" -m py_compile src/main.py src/pipeline.py src/icons.py src/keyboard_hook.py src/wasapi_probe.py src/modules/i18n/i18n.py src/modules/appconfig/appconfig.py src/modules/paths/paths.py src/modules/log_kit/log_kit.py src/modules/autostart/autostart.py src/modules/tray_kit/tray_kit.py src/modules/update_helper/update_helper.py
if errorlevel 1 (
  echo [ERROR] compile check failed.
  if not defined NOPAUSE pause
  exit /b 1
)

rem ---------------------------------------------------------------------------
rem GATE 2: i18n coverage - zh/en tables must answer the core keys
rem ---------------------------------------------------------------------------
echo [TEST] i18n coverage ...
"%PY%" -c "import sys; sys.path.insert(0, 'src'); from modules import i18n; i18n.init('zh'); assert i18n.t('menu_quit')=='\u9000\u51fa'; i18n.init('en'); assert i18n.t('menu_quit')=='Quit'; print('i18n OK')"
if errorlevel 1 (
  echo [ERROR] i18n check failed.
  if not defined NOPAUSE pause
  exit /b 1
)

rem ---------------------------------------------------------------------------
rem F11/D12 harness pin (2026-09-19): every suite below pins its own data root, but
rem that is per-file discipline - a NEW test that forgets it gets a green build while
rem writing the user's live %LOCALAPPDATA% root. reme's build pins once around its
rem whole test section (scripts/build.bat:22); do the same here so this class of
rem accident cannot recur. Cleared right after GATE 2f.
rem ---------------------------------------------------------------------------
set "LOCAL_SPEAK2TEXT_DATA_DIR=%CD%\build\test-data"

rem ---------------------------------------------------------------------------
rem GATE 2b: single-instance guard + normal startup path (headless, no GUI)
rem   Regression for the 1.2.0-1.4.0 defect: an illegal mutex name made
rem   CreateMutexW fail (err=3) and the guard treated that failure as
rem   "already running", so the exe could never start. --smoke bypasses the
rem   guard, so these two suites are the only gates that exercise the real
rem   startup path.
rem ---------------------------------------------------------------------------
echo [TEST] single instance guard ...
"%PY%" tests\test_single_instance.py
if errorlevel 1 (
  echo [ERROR] single instance guard test failed.
  if not defined NOPAUSE pause
  exit /b 1
)

echo [TEST] startup path ...
"%PY%" tests\test_startup_path.py
if errorlevel 1 (
  echo [ERROR] startup path test failed.
  if not defined NOPAUSE pause
  exit /b 1
)

rem GATE 2c: language switch must rebuild the tray menu. Regression for the
rem template i18n package copying LANG into its namespace: the notification
rem switched to English while the menu stayed Chinese. The test reads the
rem language from the PACKAGE and asserts _menu_signature() changes.
echo [TEST] i18n menu refresh ...
"%PY%" tests\test_i18n_menu.py
if errorlevel 1 (
  echo [ERROR] i18n menu refresh test failed.
  if not defined NOPAUSE pause
  exit /b 1
)

rem GATE 2d: update-chain safety, with REAL execution of the rendered apply.bat
rem (success + failure injection) plus sha256 fail-closed and pending-evidence
rem retention. The bat is run with CREATE_NO_WINDOW and a .vbs fake exe so it
rem cannot pop a console window onto the user's desktop.
echo [TEST] update chain safety ...
"%PY%" tests\test_update_safety.py
if errorlevel 1 (
  echo [ERROR] update chain safety test failed.
  if not defined NOPAUSE pause
  exit /b 1
)

rem GATE 2e: quit decision - the three states must stay distinct.
rem   link unavailable (both dialog links raise) -> exit anyway, but do NOT apply a
rem   pending update (the user was never asked this time); user cancel -> no exit;
rem   confirmed -> exit and honour the persisted checkbox. Also asserts exactly ONE
rem   exit event per decision, since a double release runs the exit tail twice.
echo [TEST] quit decision (fail-open + tri-state) ...
"%PY%" tests\test_quit_failopen.py
if errorlevel 1 (
  echo [ERROR] quit decision test failed.
  if not defined NOPAUSE pause
  exit /b 1
)

rem GATE 2f: AsrEngine must read MODEL_DIR at CALL time, not as an import-time
rem   snapshot. Regression for #46: changing model_dir in the config had no effect
rem   on the engine, so it kept loading the old model.
echo [TEST] engine model dir (call-time, not snapshot) ...
"%PY%" tests\test_engine_model_dir.py
if errorlevel 1 (
  echo [ERROR] engine model dir test failed.
  if not defined NOPAUSE pause
  exit /b 1
)

rem GATE 2g: the MAIN side must read the model dir at USE time, not hold an
rem   import-time copy. Regression for #47: after switching the model dir, the
rem   picker still opened at the old dir and the notification printed the old dir.
echo [TEST] main-side model dir (use-time, not a frozen copy) ...
"%PY%" tests\test_main_model_dir.py
if errorlevel 1 (
  echo [ERROR] main-side model dir test failed.
  if not defined NOPAUSE pause
  exit /b 1
)

rem GATE 2h: the update script's polling matcher must have DISCRIMINATING POWER.
rem   Regression for the bare-name `find`. A bare name resolves by PATH ORDER, so the
rem   outcome flips with the environment (measured, same probe, two contexts):
rem     * Git-Bash-derived PATH -> Git's GNU find first -> returns 1 whether the
rem       process runs or not -> zero discriminating power, the "wait for the old
rem       process to exit" loop never waited;
rem     * registry-merged PATH (what an explorer-launched app, and the apply.bat it
rem       spawns, really inherit) -> System32 find first -> correct.
rem   i.e. PATH-ORDER-dependent LATENT defect, not a universally broken one. The fix
rem   is an absolute path so the outcome no longer depends on PATH order. This test
rem   feeds two poll files and requires the two exit codes to DIFFER.
echo [TEST] update poll matcher (discriminating power) ...
"%PY%" tests\test_poll_matcher.py
if errorlevel 1 (
  echo [ERROR] update poll matcher test failed.
  if not defined NOPAUSE pause
  exit /b 1
)

rem GATE 2i: the C-2 delete-guard must be WIRED, and wired EARLY. The mechanical
rem   check (C-27) only proves the symbol is referenced somewhere; the template
rem   README's requirement is a TIMING one ("before the tray/window is created -
rem   the order may not move later"), so a call placed after Tray() would satisfy
rem   "is referenced" while violating what the README actually asks for. This
rem   test records the call order and asserts guard < overlay < tray. Proven to
rem   discriminate: with the call moved after Tray() the ordering assertions go
rem   red while "called exactly once" stays green; with the call deleted, three go red.
echo [TEST] C-2 delete-guard wiring (order: guard before window/tray) ...
"%PY%" tests\test_delete_guard_wired.py
if errorlevel 1 (
  echo [ERROR] delete-guard wiring test failed.
  if not defined NOPAUSE pause
  exit /b 1
)

set "LOCAL_SPEAK2TEXT_DATA_DIR="
if exist "%CD%\build\test-data" rmdir /s /q "%CD%\build\test-data"

rem ---------------------------------------------------------------------------
rem GATE 3: pipeline selftest with the default model (real ASR roundtrip)
rem
rem F11/D12 pin: the toolchain must not share ANY on-disk file with a resident
rem instance. Without it the selftest writes into the user's live
rem %LOCALAPPDATA%\local-speak2text\ (user's rule: the build must never affect
rem the running service). Same pin as the frozen smoke below.
rem CONFIG is deliberately NOT pinned: the selftest prints where the model dir
rem came from, and pinning the config would hide the user's real state.
rem ---------------------------------------------------------------------------
set "LOCAL_SPEAK2TEXT_DATA_DIR=%CD%\build\selftest-data"
echo [TEST] pipeline selftest ...
"%PY%" src\pipeline.py
set SELFTEST_RC=%errorlevel%
set "LOCAL_SPEAK2TEXT_DATA_DIR="
if exist "%CD%\build\selftest-data" rmdir /s /q "%CD%\build\selftest-data"
if not "%SELFTEST_RC%"=="0" (
  echo [ERROR] pipeline selftest failed.
  if not defined NOPAUSE pause
  exit /b 1
)

rem ---------------------------------------------------------------------------
rem Icon: generate tray + taskbar .ico (code-drawn, no art assets)
rem ---------------------------------------------------------------------------
echo [BUILD] icon ...
"%PY%" src\icons.py
if errorlevel 1 (
  echo [ERROR] icon generation failed.
  if not defined NOPAUSE pause
  exit /b 1
)

rem ---------------------------------------------------------------------------
rem PyInstaller onedir noconsole
rem ---------------------------------------------------------------------------
echo [BUILD] PyInstaller onedir noconsole ...
"%PY%" -m PyInstaller --paths "%CD%\src" --noconfirm --clean --onedir --noconsole ^
  --name %APPNAME% ^
  --icon "%CD%\%APPNAME%-taskbar.ico" ^
  --add-data "%CD%\%APPNAME%.ico;." ^
  --add-data "%CD%\%APPNAME%-taskbar.ico;." ^
  --add-data "%CD%\locales;locales" ^
  --hidden-import pyperclip ^
  --hidden-import pystray ^
  --hidden-import PIL.ImageDraw ^
  --collect-all sherpa_onnx ^
  --collect-all sounddevice ^
  src\main.py
if errorlevel 1 (
  echo [ERROR] PyInstaller failed.
  if not defined NOPAUSE pause
  exit /b 1
)

echo [PACK] assembling %RELEASE_DIR% ...
if not exist "%RELEASE_DIR%" mkdir "%RELEASE_DIR%"
%SystemRoot%\System32\Robocopy.exe "dist\%APPNAME%" "%RELEASE_DIR%" /E /R:1 /W:1 /NFL /NDL /NP >nul
if errorlevel 8 (
  echo [ERROR] package copy failed.
  if not defined NOPAUSE pause
  exit /b 1
)
if exist README.md copy /y README.md "%RELEASE_DIR%" >nul
if exist README.zh-CN.md copy /y README.zh-CN.md "%RELEASE_DIR%" >nul

rem Packaged config: model_dir sits NEXT TO the exe (the natural layout for an
rem unpacked zip; the 2GB models folder is never shipped inside the package).
rem Falls back to defaults when config.json is absent (fresh CI checkout).
echo [CONFIG] writing packaged config.json ...
"%PY%" -c "import json,os; cfg=json.load(open('config.json',encoding='utf-8-sig')) if os.path.exists('config.json') else {'auto_gain':True,'vad_floor':0.005,'segment_padding':0.15,'num_threads':8,'language':'auto','update_repo':'KenneLu/local-speak2text'}; cfg['model_dir']='asr-modules/sensevoice-small-int8'; json.dump(cfg,open(r'%RELEASE_DIR%\config.json','w',encoding='utf-8'),ensure_ascii=False,indent=2)"
if errorlevel 1 (
  echo [ERROR] write config failed.
  if not defined NOPAUSE pause
  exit /b 1
)

rem ---------------------------------------------------------------------------
rem Deliverable checks: exe + runtime - guards against a silently empty package
rem ---------------------------------------------------------------------------
if not exist "%FROZEN_EXE%" (
  echo [ERROR] %APPNAME%.exe missing from the release.
  if not defined NOPAUSE pause
  exit /b 1
)
if not exist "%RELEASE_DIR%\_internal\base_library.zip" (
  echo [ERROR] _internal has no runtime - the package is incomplete.
  if not defined NOPAUSE pause
  exit /b 1
)
if not exist "%RELEASE_DIR%\_internal\%APPNAME%-taskbar.ico" (
  echo [ERROR] taskbar icon asset missing from the release.
  if not defined NOPAUSE pause
  exit /b 1
)

rem ---------------------------------------------------------------------------
rem Frozen check: the packaged exe must prove itself before shipping.
rem LOCAL_SPEAK2TEXT_CONFIG pins the run to THIS package's shipped config
rem (model_dir resolves via the upward fallback to the repo's asr-modules/).
rem LOCAL_SPEAK2TEXT_DATA_DIR redirects the WHOLE data root into the release
rem dir (F11/D12 instance isolation): without it the smoke writes its log into
rem the user's live %LOCALAPPDATA%\local-speak2text\log, i.e. build tooling
rem touches the running instance's files. Same as dsh/opencodex-helper.
rem ---------------------------------------------------------------------------
set "PYTHONUTF8=1"
set "LOCAL_SPEAK2TEXT_CONFIG=%CD%\%RELEASE_DIR%\config.json"
set "LOCAL_SPEAK2TEXT_DATA_DIR=%CD%\%RELEASE_DIR%\smoke-data"
echo [TEST] smoke test ...
"%FROZEN_EXE%" --smoke
set SMOKE_RC=%errorlevel%
set "LOCAL_SPEAK2TEXT_CONFIG="
set "LOCAL_SPEAK2TEXT_DATA_DIR="
if exist "%RELEASE_DIR%\smoke.log" del /q "%RELEASE_DIR%\smoke.log"
if exist "%RELEASE_DIR%\log" rmdir /s /q "%RELEASE_DIR%\log"
if exist "%RELEASE_DIR%\smoke-data" rmdir /s /q "%RELEASE_DIR%\smoke-data"
if not "%SMOKE_RC%"=="0" (
  echo [ERROR] smoke test failed.
  if not defined NOPAUSE pause
  exit /b 1
)
echo smoke OK
if errorlevel 1 (
  echo [ERROR] smoke test failed. See %RELEASE_DIR%\log
  if not defined NOPAUSE pause
  exit /b 1
)
type "%RELEASE_DIR%\log\smoke.log" 2>nul
type "%RELEASE_DIR%\smoke.log" 2>nul
echo.
echo [DONE] release: %FROZEN_EXE%
if defined RUN_AFTER (
  echo [RUN] starting %APPNAME%.exe ...
  start "" "%FROZEN_EXE%"
)
if not defined NOPAUSE pause
exit /b 0
