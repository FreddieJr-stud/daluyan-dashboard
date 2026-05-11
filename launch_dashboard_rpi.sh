#!/usr/bin/env bash
# ============================================================
#  M/B Dalaray Dashboard — RPi5 Launcher
#  Replay mode: starts replay vessel server + dashboard backend
#  Live mode:   starts dashboard backend with auto-discovery
#  Tablet connects via WiFi (use settings gear to set URL)
#  Usage:
#    bash launch_dashboard_rpi.sh [--date YYYY-MM-DD]   (replay)
#    bash launch_dashboard_rpi.sh --live                 (live on ferry, auto-discover)
#    bash launch_dashboard_rpi.sh --live --vessel-host 192.168.137.1  (live, explicit IP)
# ============================================================
set -euo pipefail

DASHBOARD_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$DASHBOARD_DIR/.." && pwd)"
PARQUET_DIR="$REPO_ROOT/Daluyan_V2/backend/data/parquet"
DUCKDB_PATH="$REPO_ROOT/Daluyan_V2/backend/data/daluyan.duckdb"
REPLAY_DATE="2026-03-21"
REPLAY_PORT=8481
BACKEND_PORT=5000
LIVE_MODE=false
VESSEL_HOST=""

# --- Parse flags ---
while [[ $# -gt 0 ]]; do
    case "$1" in
        --date) REPLAY_DATE="$2"; shift 2 ;;
        --live) LIVE_MODE=true; shift ;;
        --vessel-host) VESSEL_HOST="$2"; shift 2 ;;
        *) echo "Unknown flag: $1"; exit 1 ;;
    esac
done

if $LIVE_MODE; then
    echo "============================================================"
    echo "  M/B Dalaray Dashboard Launcher — RPi5 (LIVE Mode)"
    echo "  Auto-discovers vessel API on local network"
    echo "============================================================"
else
    echo "============================================================"
    echo "  M/B Dalaray Dashboard Launcher — RPi5 (Replay Mode)"
    echo "============================================================"
fi
echo ""

# --- Activate venv ---
echo "[1/8] Activating virtual environment..."
if [[ ! -d "$DASHBOARD_DIR/venv" ]]; then
    echo "       venv not found. Creating one..."
    python3 -m venv "$DASHBOARD_DIR/venv"
fi
source "$DASHBOARD_DIR/venv/bin/activate"

# --- Install/update Python dependencies ---
echo "[2/8] Installing Python dependencies..."
pip install -r "$DASHBOARD_DIR/requirements.txt" --quiet 2>/dev/null || echo "       Install failed (no internet?). Run: pip install -r requirements.txt when online."
echo "       Done."
echo ""

# --- Run Flutter static analysis ---
echo "[3/8] Running Flutter static analysis..."
FLUTTER_DIR="$DASHBOARD_DIR/flutter_application_1"
if command -v flutter &>/dev/null && [[ -d "$FLUTTER_DIR" ]]; then
    cd "$FLUTTER_DIR"
    if flutter analyze --no-pub 2>&1 | grep -qi "error"; then
        echo ""
        echo "[WARN] Flutter analysis found errors. Dashboard will still launch."
        echo "       Review output above before using the app."
    else
        echo "       No analysis errors found."
    fi
    echo ""

    # --- Run Flutter unit tests (voice assistant) ---
    echo "[4/8] Running Dalaray voice assistant tests..."
    if flutter test test/voice_models_test.dart test/intent_matcher_test.dart --no-pub 2>/dev/null; then
        echo "       All voice tests passed."
    else
        echo ""
        echo "[WARN] Voice assistant tests failed. Dashboard will still launch."
        echo "       Review test output above before using voice features."
    fi
    cd "$DASHBOARD_DIR"
else
    echo "       Flutter not found or flutter_application_1 missing — skipping analysis & tests."
fi
echo ""

# --- Verify data files (replay mode only) ---
if ! $LIVE_MODE; then
    if [[ ! -f "$DUCKDB_PATH" ]]; then
        echo "[ERROR] DuckDB not found at: $DUCKDB_PATH"
        exit 1
    fi
    if [[ ! -d "$PARQUET_DIR" ]]; then
        echo "[ERROR] Parquet dir not found at: $PARQUET_DIR"
        exit 1
    fi
    echo "       DuckDB:  $DUCKDB_PATH"
    echo "       Parquet: $PARQUET_DIR"
    echo "       Date:    $REPLAY_DATE"
    echo ""

    # --- Stop Daluyan V2 backend (holds DuckDB lock) ---
    echo "[5/8] Stopping Daluyan V2 backend (frees DuckDB lock)..."
    sudo systemctl stop daluyan-backend 2>/dev/null || true
    echo "       Done."
    echo ""
fi

# --- Ensure MQTT broker (mosquitto) is running ---
STEP=$($LIVE_MODE && echo "5/7" || echo "6/8")
echo "[$STEP] Ensuring MQTT broker (mosquitto) is running..."
if ! command -v mosquitto &>/dev/null; then
    echo "       mosquitto not found — installing..."
    sudo apt-get update -qq && sudo apt-get install -y -qq mosquitto mosquitto-clients
fi
if systemctl is-active --quiet mosquitto; then
    echo "       mosquitto already running."
else
    echo "       Starting mosquitto..."
    sudo systemctl enable mosquitto 2>/dev/null || true
    sudo systemctl start mosquitto
    sleep 1
    if systemctl is-active --quiet mosquitto; then
        echo "       mosquitto started successfully."
    else
        echo "[WARNING] mosquitto failed to start — passenger counting will be disabled."
    fi
fi
echo ""

# --- Grant mic permission to Google Speech Recognizer (if tablet connected via USB) ---
if command -v adb &>/dev/null; then
    TABLET_ID=$(adb devices 2>/dev/null | grep -w "device$" | awk '{print $1}')
    if [[ -n "$TABLET_ID" ]]; then
        echo "       Tablet detected ($TABLET_ID) — granting speech recognition permissions..."
        adb -s "$TABLET_ID" shell pm grant com.google.android.googlequicksearchbox android.permission.RECORD_AUDIO 2>/dev/null || true
        adb -s "$TABLET_ID" shell pm grant com.example.flutter_application_1 android.permission.RECORD_AUDIO 2>/dev/null || true
        echo "       Speech recognition permissions granted."
        echo ""
    fi
fi

# --- Kill any old instances on our ports ---
STEP=$($LIVE_MODE && echo "6/7" || echo "7/8")
echo "[$STEP] Cleaning up old instances..."
if ! $LIVE_MODE; then
    fuser -k ${REPLAY_PORT}/tcp 2>/dev/null || true
fi
fuser -k ${BACKEND_PORT}/tcp 2>/dev/null || true
echo "       Done."
echo ""

# --- Detect LAN IP ---
LAN_IP=$(python3 -c "import socket;s=socket.socket(socket.AF_INET,socket.SOCK_DGRAM);s.connect(('8.8.8.8',53));print(s.getsockname()[0]);s.close()" 2>/dev/null || echo "unknown")
echo "       RPi5 LAN IP: $LAN_IP"
echo ""

# --- Start servers ---
STEP=$($LIVE_MODE && echo "7/7" || echo "8/8")
echo "[$STEP] Starting servers..."
cd "$DASHBOARD_DIR"

REPLAY_PID=""
if ! $LIVE_MODE; then
    python3 replay_vessel_server.py \
        --parquet-dir "$PARQUET_DIR" \
        --duckdb-path "$DUCKDB_PATH" \
        --date "$REPLAY_DATE" \
        --port $REPLAY_PORT &
    REPLAY_PID=$!
    sleep 3
    echo "       Replay vessel server started (PID $REPLAY_PID, port $REPLAY_PORT)"
fi

echo "       Starting dashboard backend (port $BACKEND_PORT)..."
echo ""
echo "============================================================"
if $LIVE_MODE; then
    if [[ -n "$VESSEL_HOST" ]]; then
        echo "  Dashboard running on RPi5 (LIVE → $VESSEL_HOST):"
        echo "    - DashboardBackend  :$BACKEND_PORT (vessel API: $VESSEL_HOST)"
    else
        echo "  Dashboard running on RPi5 (LIVE):"
        echo "    - DashboardBackend  :$BACKEND_PORT (auto-discover enabled)"
    fi
    echo "    - MQTT Broker       :1883 (passenger counters + sleep/wake)"
else
    echo "  All servers running on RPi5:"
    echo "    - ReplayVessel      :$REPLAY_PORT (PID $REPLAY_PID)"
    echo "    - DashboardBackend  :$BACKEND_PORT (starting below)"
    echo "    - MQTT Broker       :1883 (passenger counters + sleep/wake)"
fi
echo ""
echo "  Connect tablet:"
echo "    1. Open the dashboard app on the tablet"
echo "    2. Tap the gear icon (bottom-right)"
echo "    3. Set backend URL to: http://$LAN_IP:$BACKEND_PORT"
echo "    4. Tap 'Save & Reconnect'"
echo ""
echo "  Press Ctrl+C to stop all servers."
echo "============================================================"
echo ""

# --- Cleanup on exit ---
cleanup() {
    echo ""
    echo "Stopping servers..."
    if [[ -n "$REPLAY_PID" ]]; then
        kill $REPLAY_PID 2>/dev/null || true
        wait $REPLAY_PID 2>/dev/null || true
    fi
    echo "All servers stopped."
}
trap cleanup EXIT INT TERM

# Run backend in foreground with sudo (bypasses user-level process limits on RPi5)
VENV_PYTHON="$DASHBOARD_DIR/venv/bin/python3"
if $LIVE_MODE; then
    if [[ -n "$VESSEL_HOST" ]]; then
        sudo "$VENV_PYTHON" dashboard_backend.py \
            --vessel-host "$VESSEL_HOST" \
            --port $BACKEND_PORT
    else
        sudo "$VENV_PYTHON" dashboard_backend.py \
            --auto-discover \
            --port $BACKEND_PORT
    fi
else
    sudo "$VENV_PYTHON" dashboard_backend.py \
        --vessel-host localhost \
        --vessel-port $REPLAY_PORT \
        --port $BACKEND_PORT
fi
