@echo off
rem ---------------------------------------------------------------------------
rem local-speak2text release: tag the current commit and push the tag.
rem
rem Pushing a v* tag triggers .github/workflows/release.yml, which builds the
rem Windows package and publishes the zip (plus sha256) as a GitHub Release.
rem Nothing is built here on purpose: release artifacts come from a clean
rem checkout, not from this machine.
rem
rem Usage: release.bat            tag and push (asks to confirm)
rem        release.bat --dry-run  show what would happen, change nothing
rem
rem ASCII-only on purpose.
rem ---------------------------------------------------------------------------
setlocal EnableExtensions
cd /d "%~dp0"

set "RELEASE_BRANCH=main"
set DRY_RUN=
if /i "%~1"=="--dry-run" set DRY_RUN=1

rem Version from appconfig.py - the app and the tag can never disagree.
rem Two-step parse (split on '=', drop quotes, first token) so a trailing comment
rem on the VERSION line can never leak into the tag name. Same as build.bat.
set VERSION=
for /f "tokens=2 delims==" %%a in ('%SystemRoot%\System32\findstr.exe /b /c:"VERSION = " src\modules\appconfig\appconfig.py') do set VERSION=%%a
for /f "tokens=1" %%a in ("%VERSION:"=%") do set VERSION=%%a
if not defined VERSION (
  echo [ERROR] Cannot read VERSION from src\modules\appconfig\appconfig.py.
  exit /b 1
)
set TAG=v%VERSION%
echo [VERSION] %VERSION%   [TAG] %TAG%

rem Refuse to tag a dirty tree: the release would not match any commit
git diff --quiet 2>nul
if errorlevel 1 (
  echo [ERROR] Working tree has uncommitted changes. Commit or stash them first.
  exit /b 1
)
git diff --cached --quiet 2>nul
if errorlevel 1 (
  echo [ERROR] Staged but uncommitted changes present. Commit them first.
  exit /b 1
)

rem A tag must point at a commit the world can already see
for /f "delims=" %%b in ('git rev-parse --abbrev-ref HEAD') do set BRANCH=%%b
if /i not "%BRANCH%"=="%RELEASE_BRANCH%" (
  echo [ERROR] On branch %BRANCH%, not %RELEASE_BRANCH%. Releases are tagged on %RELEASE_BRANCH%.
  exit /b 1
)
for /f "delims=" %%l in ('git rev-parse HEAD') do set LOCAL_SHA=%%l
for /f "delims=" %%r in ('git rev-parse @{u}') do set REMOTE_SHA=%%r
if not "%LOCAL_SHA%"=="%REMOTE_SHA%" (
  echo [ERROR] Local %RELEASE_BRANCH% is not what the remote has.
  echo         local  = %LOCAL_SHA%
  echo         remote = %REMOTE_SHA%
  echo         Push or pull first - a tag must point at a commit everyone can see.
  exit /b 1
)

git rev-parse -q --verify "refs/tags/%TAG%" >nul 2>nul
if not errorlevel 1 (
  echo [WARN] Tag %TAG% already exists.
  if defined DRY_RUN goto :dry_done
  set /p ANSWER=Delete and recreate it? [y/N] 
  if /i not "%ANSWER%"=="y" (
    echo [STOP] Keeping the existing tag.
    exit /b 1
  )
  git tag -d "%TAG%" || exit /b 1
)
:dry_done

if defined DRY_RUN (
  echo [DRY-RUN] would run: git tag %TAG%
  echo [DRY-RUN] would run: git push origin %TAG%
  echo [DRY-RUN] CI would then build and publish local-speak2text-%VERSION%-windows-x64.zip
  exit /b 0
)

git tag "%TAG%"
if errorlevel 1 (
  echo [ERROR] Failed to create tag %TAG%.
  exit /b 1
)
echo [OK] Tag %TAG% created.

git push origin "%TAG%"
if errorlevel 1 (
  echo [ERROR] Failed to push %TAG%. Is the remote configured? See: git remote -v
  exit /b 1
)
echo [OK] Tag %TAG% pushed - CI is building the release.
