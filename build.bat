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
rem Version comes from app_params.py VERSION (single source of truth; Wave 2 moved it
rem out of the template borrow into the tool-owned parameter card).
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

rem Version: read from app_params.py so the script and the app cannot drift apart.
rem Robust parse: take everything after '=', drop quotes, then keep the FIRST
rem space-delimited token. A trailing comment on the VERSION line can therefore
rem never leak into the version string / release path (same fix in the template).
set VERSION=
for /f "tokens=2 delims==" %%a in ('%SystemRoot%\System32\findstr.exe /b /c:"VERSION = " src\app_params.py') do set VERSION=%%a
for /f "tokens=1" %%a in ("%VERSION:"=%") do set VERSION=%%a
if not defined VERSION (
  echo [ERROR] Cannot read VERSION from src\app_params.py.
  if not defined NOPAUSE pause
  exit /b 1
)
set VERSION=%VERSION:"=%
set APPNAME=local-speak2text
set PACKAGE=%APPNAME%-%VERSION%
rem Naming rule (2026-10-26): the exe name and every folder the app / updater /
rem user resolves are STABLE - no version. The version lives in the exe's PE
rem metadata (generated below) and in the release ASSET name only; the
rem versioned release build dir below is an internal build artifact.
set RELEASE_DIR=release\%PACKAGE%
set FROZEN_EXE=%RELEASE_DIR%\%APPNAME%.exe
set VERSION_INFO=%CD%\build\version_info.txt

echo [VERSION] %VERSION%  release: %RELEASE_DIR%

rem release-layout RELAXED (2026-09-19): target-dir existence is INFO, not a refusal.
rem The refusal condition is the running-instance guard below (build-run-detect); safety comes
rem from exe-delete-guard - the live instance holds its own exe (no FILE_SHARE_DELETE), so the
rem kernel rejects deleting it with winerror 32 rather than emptying it silently.
rem CLEANLINESS IS NOT RELAXED: the old dir is removed right after that guard, so
rem the build always assembles from scratch and never reuses a stale file.
if exist "%RELEASE_DIR%" echo [INFO] %RELEASE_DIR% exists - will be removed and rebuilt from scratch.

rem ---------------------------------------------------------------------------
rem Running-instance guard (build-run-detect, refined 2026-09-19): refuse ONLY when the live
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
rem was HOLLOWED OUT (exe survives via the exe-delete-guard handle, but `_internal/`,
rem `locales/`, `README.md` were all deleted) before the lock made it fail.
rem That is exactly the 2026-09-19 incident this guard exists to prevent.
rem Fix = same idiom as dsh/ocx (substring on the ACTION side; the `:~` ban in
rem the no-tilde-substr-in-if criterion applies to `if` CONDITIONS, not to `set`).
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

rem release-layout relaxed: remove the existing same-version dir NOW (after the guard) so the
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
"%PY%" -m py_compile src/main.py src/pipeline.py src/icons.py src/keyboard_hook.py src/wasapi_probe.py src/app_params.py src/template/i18n/i18n.py src/template/appconfig/appconfig.py src/template/paths/paths.py src/template/log_kit/log_kit.py src/template/autostart/autostart.py src/template/tray_kit/tray_kit.py src/template/update_helper/update_helper.py
if errorlevel 1 (
  echo [ERROR] compile check failed.
  if not defined NOPAUSE pause
  exit /b 1
)

rem ---------------------------------------------------------------------------
rem GATE 2: i18n coverage - zh/en tables must answer the core keys
rem ---------------------------------------------------------------------------
echo [TEST] i18n coverage ...
"%PY%" -c "import sys; sys.path.insert(0, 'src'); from template import i18n; i18n.init('zh'); assert i18n.t('menu_quit')=='\u9000\u51fa'; i18n.init('en'); assert i18n.t('menu_quit')=='Quit'; print('i18n OK')"
if errorlevel 1 (
  echo [ERROR] i18n check failed.
  if not defined NOPAUSE pause
  exit /b 1
)

rem sync_check gate: the template repo only exists on dev machines (CI checks
rem out a single repo) - skipped there, local builds keep it ON.
rem Family rule: every build.bat must gate on template drift.
if not exist "..\my-diy-tool-template\sync_check.py" goto :sync_skip
echo [GATE] template sync check ...
"%PY%" ..\my-diy-tool-template\sync_check.py --roots local-speak2text
if errorlevel 1 goto :sync_fail
goto :sync_done
:sync_skip
echo [SKIP] template sync check: my-diy-tool-template not present (CI single-repo checkout)
goto :sync_done
:sync_fail
echo [ERROR] template drift detected. See my-diy-tool-template/sync_check.py output above.
if not defined NOPAUSE pause
exit /b 1
:sync_done

rem ---------------------------------------------------------------------------
rem harness pin (2026-09-19): every suite below pins its own data root, but
rem that is per-file discipline - a NEW test that forgets it gets a green build while
rem writing the user's live %LOCALAPPDATA% root. reme's build pins once around its
rem whole test section (scripts/build.bat:22); do the same here so this class of
rem accident cannot recur. Cleared right after GATE 2f.
rem ---------------------------------------------------------------------------
set "LOCAL_SPEAK2TEXT_DATA_DIR=%CD%\build\test-data"

rem ---------------------------------------------------------------------------
rem GATE 2b..2j：**glob 逐个跑**（`tests\test_*.py`）——否证 5 收口：点名清单会漏掉
rem   新增测试（实测 18 个文件、点名只 10 个）。各测试的回归背景见下：
rem
rem   2b single_instance / startup_path：单实例守卫 + 正常启动路径（headless）。
rem     回归 1.2.0-1.4.0：非法 mutex 名 → CreateMutexW 失败 → 守卫误判「已在运行」，
rem     exe 永远起不来；--smoke 绕过守卫，故这两条是唯一走真实启动路径的闸。
rem   2c i18n_menu：语言切换必须重建托盘菜单（回归模板 i18n 把 LANG 拷进包命名空间，
rem     通知切英文而菜单仍是中文）。
rem   2d update_safety：更新链安全（真跑渲染出的 apply.bat：成功/失败注入 + sha256
rem     fail-closed + pending 证据保留）。
rem   2e quit_failopen：退出决策三态必须分开（链路不可用→放行退出但不应用更新；
rem     用户取消→不退出；确认→退出并按勾选应用）。
rem   2f engine_model_dir / 2g main_model_dir：模型目录必须在**调用/使用**时读，
rem     不能是 import 期快照（回归 #46/#47：改配置不生效）。
rem   2h poll_matcher：更新脚本的轮询匹配必须有**判别力**（回归裸名 find 的 PATH 顺序
rem     依赖：Git-Bash PATH 下永远返回 1 → 等待循环从不等待）。
rem   2i delete_guard_wired：exe-delete-guard 必须**早**接（顺序 guard < overlay < tray）。
rem   2j startup_fallback：重复启动必须静默；托盘/窗口创建失败必须可读 + 崩溃日志 +
rem     退出码 2；日志/烟雾/崩溃尾巴必须 fail-open。
rem ---------------------------------------------------------------------------
rem 门禁自证（放最前）：自证内部会 gate_save 覆盖基线、且会建注入目录。
rem 放测试前跑完并回滚——注入目录不污染基线，也不掩测试期的泄漏。
"%PY%" tests\temp_gate_selfcheck.py
if errorlevel 1 (
  echo [ERROR] gate self-check failed.
  if not defined NOPAUSE pause
  exit /b 1
)
rem 临时目录泄漏门禁（temp_kit）：跑测试前后扫 %TEMP%\<APP_ID>\（收窄：只认工具目录本身），本次新增 = 0。
rem 先跑完所有测试再跑门禁——**测试失败也要检查泄漏**（先记 TESTFAIL，门禁跑完再一起红）。
"%PY%" tests\temp_gate.py --save
if errorlevel 1 (
  echo [ERROR] temp baseline failed.
  if not defined NOPAUSE pause
  exit /b 1
)
set "TESTFAIL=0"
for %%t in (tests\test_*.py) do (
  "%PY%" "%%t"
  if errorlevel 1 (
    echo [ERROR] test failed: %%t
    set "TESTFAIL=1"
  )
)
"%PY%" tests\temp_gate.py
if errorlevel 1 (
  echo [ERROR] temp-dir leak: %TEMP%\%APPNAME%\ gained NEW entries during the tests.
  set "TESTFAIL=1"
)
if not "%TESTFAIL%"=="0" (
  echo [ERROR] one or more test gates failed - see [ERROR] test failed above.
  if not defined NOPAUSE pause
  exit /b 1
)

set "LOCAL_SPEAK2TEXT_DATA_DIR="
if exist "%CD%\build\test-data" rmdir /s /q "%CD%\build\test-data"

rem ---------------------------------------------------------------------------
rem GATE 3: pipeline selftest with the default model (real ASR roundtrip)
rem
rem pin: the toolchain must not share ANY on-disk file with a resident
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
echo [TEST] local OTA acceptance (template ota_test) ...
"%PY%" src\template\ota_test\run_local_ota_test.py --app-id %APPNAME%
if errorlevel 1 (
  echo [ERROR] local OTA acceptance test failed - package-root resolution, replacement,
  echo         backup rotation or cleanup broke. See the test output above.
  if not defined NOPAUSE pause
  exit /b 1
)

echo [BUILD] version metadata (PE FileVersion/ProductVersion) ...
if not exist build mkdir build
"%PY%" src\template\build_release\version_file.py "%VERSION_INFO%" %VERSION% %APPNAME% KenneLu
if errorlevel 1 (
  echo [ERROR] version metadata generation failed.
  if not defined NOPAUSE pause
  exit /b 1
)

echo [BUILD] PyInstaller onedir noconsole ...
"%PY%" -m PyInstaller --paths "%CD%\src" --noconfirm --clean --onedir --noconsole ^
  --name %APPNAME% ^
  --version-file "%VERSION_INFO%" ^
  --icon "%CD%\%APPNAME%-taskbar.ico" ^
  --add-data "%CD%\%APPNAME%.ico;." ^
  --add-data "%CD%\%APPNAME%-taskbar.ico;." ^
  --add-data "%CD%\locales;locales" ^
  --add-data "%CD%\resources;resources" ^
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
"%PY%" -c "import json,os; cfg=json.load(open('config.json',encoding='utf-8-sig')) if os.path.exists('config.json') else {'auto_gain':True,'vad_floor':0.005,'segment_padding':0.15,'num_threads':8,'language':'auto','update_repo':'KenneLu/local-speak2text'}; cfg['model_dir']='asr-template/sensevoice-small-int8'; json.dump(cfg,open(r'%RELEASE_DIR%\config.json','w',encoding='utf-8'),ensure_ascii=False,indent=2)"
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
rem (model_dir resolves via the upward fallback to the repo's asr-template/).
rem LOCAL_SPEAK2TEXT_DATA_DIR redirects the WHOLE data root into the release
rem dir (instance isolation): without it the smoke writes its log into
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
