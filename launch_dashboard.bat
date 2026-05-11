@echo off
REM ============================================================
REM  M/B Dalaray Dashboard — One-Click Launcher
REM  Starts: replay vessel server, dashboard backend, Flutter app
REM  Auto-detects tablet; falls back to Chrome browser if not found
REM  Usage: double-click or run from CMD
REM  Flags: --skip-check  Skip pre-flight checks
REM         --release     Build Flutter in release mode
REM         --live        Live mode (auto-discover vessel API, skip replay)
REM         --vessel-host IP  Explicit vessel API IP (implies --live)
REM         --debug-panel Show debug panel on tablet (not just localhost)
REM ============================================================

set DASHBOARD_DIR=%~dp0
set REPO_ROOT=%DASHBOARD_DIR%..
set FLUTTER_DIR=%DASHBOARD_DIR%flutter_application_1
set DBGLOG=%DASHBOARD_DIR%launch_debug.log
echo [%TIME%] START > "%DBGLOG%"
set BUNDLE_DIR=%REPO_ROOT%\Ferry_digial_shadow\Models\rpi5_bundle
set PARQUET_DIR=%REPO_ROOT%\Daluyan_V2\backend\data\parquet
set DUCKDB_PATH=%REPO_ROOT%\Daluyan_V2\backend\data\daluyan.duckdb
set FLUTTER_BUILD_MODE=--debug
set SKIP_PREFLIGHT=0
set LIVE_MODE=0
set VESSEL_HOST=
set SHOW_DEBUG=0

REM --- Parse command-line flags ---
:parse_args
if "%~1"=="" goto :args_done
if /i "%~1"=="--skip-check" set SKIP_PREFLIGHT=1
if /i "%~1"=="--release" set FLUTTER_BUILD_MODE=--release
if /i "%~1"=="--live" set LIVE_MODE=1
if /i "%~1"=="--debug-panel" set SHOW_DEBUG=1
if /i "%~1"=="--vessel-host" (
    set VESSEL_HOST=%~2
    set LIVE_MODE=1
    shift
)
shift
goto :parse_args
:args_done

echo ============================================================
if %LIVE_MODE% EQU 1 (
    echo   M/B Dalaray Dashboard Launcher (LIVE Mode)
) else (
    echo   M/B Dalaray Dashboard Launcher (Replay Mode)
)
echo ============================================================
echo.

REM --- Pre-flight checks ---
if %SKIP_PREFLIGHT% NEQ 0 goto :skip_preflight
echo [0/7] Running pre-flight checks...
python "%DASHBOARD_DIR%preflight_check.py"
if %ERRORLEVEL% EQU 1 (
    echo.
    echo [ERROR] Pre-flight checks found critical failures. Fix them and retry.
    echo         Use --skip-check to bypass ^(not recommended^).
    pause
    exit /b 1
)
if %ERRORLEVEL% EQU 2 (
    echo.
    echo [WARN] Pre-flight checks found warnings. Continuing anyway...
)
echo.
goto :preflight_done
:skip_preflight
echo [0/7] Pre-flight checks skipped ^(--skip-check^)
echo.
:preflight_done

REM --- Build mode prompt (only when no --release flag and tablet detected) ---
if "%FLUTTER_BUILD_MODE%"=="--debug" (
    echo  Current build mode: DEBUG ^(default^)
    echo  To use release mode, restart with --release flag.
    echo.
)

REM --- Auto-locate DuckDB and parquet if defaults don't exist (replay only) ---
if %LIVE_MODE% EQU 1 goto :skip_replay_paths
if not exist "%DUCKDB_PATH%" (
    echo       DuckDB not at default path, searching...
    for /f "delims=" %%f in ('where /R "%REPO_ROOT%" daluyan.duckdb 2^>nul') do (
        set DUCKDB_PATH=%%f
        echo       Found: %%f
    )
)
if not exist "%DUCKDB_PATH%" (
    echo [ERROR] Could not find daluyan.duckdb anywhere in the repo.
    pause
    exit /b 1
)
if not exist "%PARQUET_DIR%" (
    echo       Parquet dir not at default path, searching...
    for /f "delims=" %%d in ('where /R "%REPO_ROOT%" *.parquet 2^>nul') do (
        set PARQUET_DIR=%%~dpd
        echo       Found parquets in: %%~dpd
        goto :parquet_found
    )
    echo [ERROR] Could not find parquet files anywhere in the repo.
    pause
    exit /b 1
)
:parquet_found
:skip_replay_paths
if not exist "%BUNDLE_DIR%" (
    echo       Model bundle not at default path, searching...
    for /f "delims=" %%f in ('where /R "%REPO_ROOT%" soc_realtime_metadata.json 2^>nul') do (
        set BUNDLE_DIR=%%~dpf..
        echo       Found bundle near: %%f
        goto :bundle_found
    )
    echo [ERROR] Could not find rpi5_bundle anywhere in the repo.
    pause
    exit /b 1
)
:bundle_found
echo       DuckDB:  %DUCKDB_PATH%
echo       Parquet: %PARQUET_DIR%
echo       Bundle:  %BUNDLE_DIR%
echo.

REM --- Find Flutter on PATH ---
where flutter >nul 2>&1
if %ERRORLEVEL% NEQ 0 (
    echo [ERROR] Flutter not found on PATH. Please install Flutter
    echo         and add it to your system PATH.
    pause
    exit /b 1
)

REM --- Install/update Python dependencies ---
echo [1/7] Installing Python dependencies...
pip install -r "%DASHBOARD_DIR%requirements.txt" --quiet 2>nul
if %ERRORLEVEL% NEQ 0 (
    echo       Install failed ^(no internet?^). Run: pip install -r requirements.txt when online.
)
echo       Done.
echo.

REM --- Run Flutter static analysis ---
echo [2/7] Running Flutter static analysis...
cd /d "%FLUTTER_DIR%"
cmd /c flutter analyze --no-pub 2>&1 | findstr /I "error"
if %ERRORLEVEL% EQU 0 (
    echo.
    echo [WARN] Flutter analysis found errors. Dashboard will still launch.
    echo        Review output above before using the app.
    echo.
) else (
    echo       No analysis errors found.
)
echo.

REM --- Run Flutter unit tests (voice assistant) ---
echo [3/7] Running Dalaray voice assistant tests...
cmd /c flutter test test\voice_models_test.dart test\intent_matcher_test.dart --no-pub
if %ERRORLEVEL% NEQ 0 (
    echo.
    echo [WARN] Voice assistant tests failed. Dashboard will still launch.
    echo        Review test output above before using voice features.
    echo.
) else (
    echo       All voice tests passed.
)
cd /d "%DASHBOARD_DIR%"
echo.

REM --- Kill any old instances ---
echo [4/7] Cleaning up old instances...
taskkill /F /FI "WINDOWTITLE eq ReplayVessel" >nul 2>&1
taskkill /F /FI "WINDOWTITLE eq MockVessel" >nul 2>&1
taskkill /F /FI "WINDOWTITLE eq DashboardBackend" >nul 2>&1
echo       Done.
echo.

REM --- Start replay vessel server (replay mode only) ---
if %LIVE_MODE% EQU 1 goto :skip_replay_server
echo [5/7] Starting replay vessel server (port 8481)...
start "ReplayVessel" cmd /k "cd /d %DASHBOARD_DIR% && python replay_vessel_server.py --parquet-dir "%PARQUET_DIR%" --duckdb-path "%DUCKDB_PATH%" --date 2026-03-21 --port 8481"
timeout /t 3 /nobreak >nul
echo       Replay vessel server started.
echo [%TIME%] replay started >> "%DBGLOG%"
echo.
:skip_replay_server

REM --- Start dashboard backend ---
if %LIVE_MODE% EQU 1 goto :start_live_backend
echo [6/7] Starting dashboard backend (port 5000)...
start "DashboardBackend" cmd /k "cd /d %DASHBOARD_DIR% && python dashboard_backend.py --vessel-host localhost --vessel-port 8481 --port 5000"
goto :backend_started
:start_live_backend
echo [5/7] Starting dashboard backend - LIVE (port 5000)...
if defined VESSEL_HOST (
    start "DashboardBackend" cmd /k "cd /d %DASHBOARD_DIR% && python dashboard_backend.py --vessel-host %VESSEL_HOST% --port 5000"
) else (
    start "DashboardBackend" cmd /k "cd /d %DASHBOARD_DIR% && python dashboard_backend.py --auto-discover --port 5000"
)
:backend_started
timeout /t 5 /nobreak >nul
echo       Dashboard backend started.
echo [%TIME%] backend started >> "%DBGLOG%"
echo.

REM --- Auto-detect LAN IP (for tablet connections) ---
echo [%TIME%] LAN IP detection >> "%DBGLOG%"
set LAN_IP=localhost
REM Use Python UDP-connect trick to find the primary network interface IP
REM (automatically skips VPN/Tailscale/Hyper-V/WSL virtual adapters)
python -c "import socket;s=socket.socket(socket.AF_INET,socket.SOCK_DGRAM);s.connect(('8.8.8.8',53));print(s.getsockname()[0]);s.close()" > "%TEMP%\_lanip.txt" 2>nul
set /p LAN_IP=<"%TEMP%\_lanip.txt" 2>nul
del "%TEMP%\_lanip.txt" 2>nul
if "%LAN_IP%"=="" set LAN_IP=localhost
set SERVER_URL=http://%LAN_IP%:5000
echo       LAN IP detected: %LAN_IP%
echo       Server URL: %SERVER_URL%

REM --- Detect Flutter target device ---
echo [%TIME%] device detection >> "%DBGLOG%"
echo [7/7] Detecting Flutter target device...
set FLUTTER_DEVICE=chrome
set DEVICE_LABEL=Chrome browser (web)
set DART_DEFINES=

REM Check if adb exists before trying to use it
where adb >nul 2>&1
if %ERRORLEVEL% EQU 0 (
    echo [%TIME%] adb found, checking devices >> "%DBGLOG%"
    for /f "tokens=1" %%d in ('adb devices 2^>nul ^| findstr /R /C:"device$"') do (
        set FLUTTER_DEVICE=%%d
        set DEVICE_LABEL=Android tablet
        set DART_DEFINES=--dart-define=SERVER_URL=%SERVER_URL%
    )
)

if %SHOW_DEBUG% EQU 1 set DART_DEFINES=%DART_DEFINES% --dart-define=SHOW_DEBUG=true
echo       Target: %DEVICE_LABEL% (device: %FLUTTER_DEVICE%)
if %SHOW_DEBUG% EQU 1 echo       Debug panel: ENABLED
echo.

REM --- ADB reverse port forwarding (backup if WiFi fails) ---
if not "%FLUTTER_DEVICE%"=="chrome" (
    echo       Setting up ADB reverse port forwarding ^(backup^)...
    adb -s %FLUTTER_DEVICE% reverse tcp:5000 tcp:5000 >nul 2>&1
    if %ERRORLEVEL% EQU 0 (
        echo       ADB reverse tcp:5000 active ^(backup if WiFi unreachable^)
    )
    adb -s %FLUTTER_DEVICE% reverse tcp:8481 tcp:8481 >nul 2>&1
    echo.
    echo       WiFi ^(primary^): tablet connects to %SERVER_URL%
    echo       ADB  ^(backup^):  works while USB cable is connected
    echo.
    REM --- Grant mic permission to Google Speech Recognizer ---
    echo       Ensuring Google Speech Recognizer has mic permission...
    adb -s %FLUTTER_DEVICE% shell pm grant com.google.android.googlequicksearchbox android.permission.RECORD_AUDIO >nul 2>&1
    adb -s %FLUTTER_DEVICE% shell pm grant com.example.flutter_application_1 android.permission.RECORD_AUDIO >nul 2>&1
    echo       Speech recognition permissions granted.
    echo.
)

REM --- Load API keys from local_keys.env (gitignored) ---
set CLOUD_STT_KEY=
set GEMINI_API_KEY=
if exist "%FLUTTER_DIR%\local_keys.env" (
    for /f "tokens=1,* delims==" %%a in ('type "%FLUTTER_DIR%\local_keys.env" 2^>nul') do (
        if "%%a"=="CLOUD_STT_KEY" set CLOUD_STT_KEY=%%b
        if "%%a"=="GEMINI_API_KEY" set GEMINI_API_KEY=%%b
    )
)
if defined CLOUD_STT_KEY (
    set DART_DEFINES=%DART_DEFINES% --dart-define=CLOUD_STT_KEY=%CLOUD_STT_KEY%
    echo       Cloud STT API key loaded from local_keys.env
) else (
    echo       No Cloud STT key found — using on-device STT only
)
if defined GEMINI_API_KEY (
    echo       Gemini API key loaded from local_keys.env
) else (
    echo       No Gemini key found — using offline intent matching only
)

REM --- Launch Flutter ---
echo [%TIME%] FLUTTER_DIR=%FLUTTER_DIR% >> "%DBGLOG%"
echo [%TIME%] FLUTTER_DEVICE=%FLUTTER_DEVICE% >> "%DBGLOG%"
echo [%TIME%] launching flutter >> "%DBGLOG%"
echo Launching Flutter on %DEVICE_LABEL%...
echo.
start "FlutterDashboard" cmd /k "cd /d %FLUTTER_DIR% && flutter pub get && flutter run -d %FLUTTER_DEVICE% %DART_DEFINES% %FLUTTER_BUILD_MODE%"
echo [%TIME%] start command returned >> "%DBGLOG%"
echo ============================================================
echo   All services launched in separate windows:
echo     - ReplayVessel      (telemetry on :8481)
echo     - DashboardBackend  (ML models + Socket.IO on :5000)
echo     - FlutterDashboard  (%DEVICE_LABEL%)
echo.
echo   Flutter controls (in FlutterDashboard window):
echo     r = hot reload    R = hot restart    q = quit
echo.
echo   Replay controls (via debug panel):
echo     Tap bug icon (bottom-right) to open debug panel
echo     Use REPLAY section to load segments, set speed, play
echo     SOC COMPARISON shows actual vs predicted in real-time
echo.
echo   Dalaray Voice Assistant:
echo     Tap the blue mic button (bottom-right) to speak
echo     Tap again to stop listening
echo     Auto-announces: docking reachable stations, low SOC
echo.
echo   Settings:
echo     Tap gear icon (bottom-right, left of bug) to change backend URL
echo     URL is saved and persists across restarts
echo.
echo   USB cable:
echo     Keep USB connected until Flutter finishes building and the app
echo     launches on the tablet. Once you see the dashboard on screen,
echo     you can safely DISCONNECT the USB cable.
echo     The tablet will stay connected to the backend via WiFi (%SERVER_URL%).
echo     To use ADB backup, reconnect USB.
echo.
echo   Close this window to stop all services.
echo ============================================================
echo.
echo Press any key to stop all services and exit...
pause >nul
taskkill /F /FI "WINDOWTITLE eq ReplayVessel" >nul 2>&1
taskkill /F /FI "WINDOWTITLE eq DashboardBackend" >nul 2>&1
taskkill /F /FI "WINDOWTITLE eq FlutterDashboard" >nul 2>&1
echo All services stopped.
