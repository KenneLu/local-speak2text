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

rem Version: read from appconfig.py so the script and the app cannot drift apart
set VERSION=
for /f "tokens=2,*" %%a in ('findstr /b /c:"VERSION = " src\modules\appconfig\appconfig.py') do set VERSION=%%~b
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

if exist "%RELEASE_DIR%" (
  echo [ERROR] %RELEASE_DIR% already exists. Delete it or bump VERSION in appconfig.py.
  if not defined NOPAUSE pause
  exit /b 1
)

rem No running instance: files would be locked and two trays would fight
tasklist /fo csv 2>nul | findstr /i /c:"%APPNAME%" >nul
if not errorlevel 1 (
  echo [ERROR] %APPNAME% is running. Exit it from the tray before building.
  if not defined NOPAUSE pause
  exit /b 1
)

rem ---------------------------------------------------------------------------
rem GATE 1: compile every module
rem ---------------------------------------------------------------------------
echo [TEST] compile check ...
"%PY%" -m py_compile src/main.py src/pipeline.py src/icons.py src/updater.py src/keyboard_hook.py src/wasapi_probe.py src/modules/i18n/i18n.py src/modules/appconfig/appconfig.py src/modules/paths/paths.py src/modules/log_kit/log_kit.py src/modules/autostart/autostart.py src/modules/tray_kit/tray_kit.py
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

rem ---------------------------------------------------------------------------
rem GATE 3: pipeline selftest with the default model (real ASR roundtrip)
rem ---------------------------------------------------------------------------
echo [TEST] pipeline selftest ...
"%PY%" src\pipeline.py
if errorlevel 1 (
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
robocopy "dist\%APPNAME%" "%RELEASE_DIR%" /E /R:1 /W:1 /NFL /NDL /NP >nul
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
