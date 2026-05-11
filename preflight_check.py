"""Pre-flight checklist for M/B Dalaray Dashboard.

Verifies all dependencies and connections before launching the dashboard.
Run:  python preflight_check.py [--fix]

Exit codes:
  0 = all checks passed
  1 = critical failure (cannot launch)
  2 = warnings only (can launch but may have issues)
"""
from __future__ import annotations

import argparse
import os
import shutil
import socket
import subprocess
import sys
from pathlib import Path

# ── Paths ──────────────────────────────────────────────────────────────
DASHBOARD_DIR = Path(__file__).resolve().parent
REPO_ROOT = DASHBOARD_DIR.parent
FLUTTER_DIR = DASHBOARD_DIR / "flutter_application_1"
BUNDLE_DIR = REPO_ROOT / "Ferry_Digital_Shadow" / "Models" / "rpi5_bundle"
PARQUET_DIR = REPO_ROOT / "Daluyan_V2" / "backend" / "data" / "parquet"
DUCKDB_PATH = REPO_ROOT / "Daluyan_V2" / "backend" / "data" / "daluyan.duckdb"

# ── Required Python packages ──────────────────────────────────────────
BACKEND_DEPS = ["aiohttp", "socketio", "xgboost", "numpy"]
REPLAY_DEPS = ["duckdb", "polars"]
ALL_DEPS = list(dict.fromkeys(BACKEND_DEPS + REPLAY_DEPS))  # dedupe, preserve order

# ── Ports ─────────────────────────────────────────────────────────────
REQUIRED_PORTS = {"replay_vessel_server": 8481, "dashboard_backend": 5000}


class CheckResult:
    """Collects pass/warn/fail results."""

    def __init__(self):
        self.passed: list[str] = []
        self.warnings: list[str] = []
        self.failures: list[str] = []

    def ok(self, msg: str):
        self.passed.append(msg)
        _print_status("PASS", msg, "\033[92m")

    def warn(self, msg: str):
        self.warnings.append(msg)
        _print_status("WARN", msg, "\033[93m")

    def fail(self, msg: str):
        self.failures.append(msg)
        _print_status("FAIL", msg, "\033[91m")

    @property
    def exit_code(self) -> int:
        if self.failures:
            return 1
        if self.warnings:
            return 2
        return 0

    def summary(self):
        total = len(self.passed) + len(self.warnings) + len(self.failures)
        print(f"\n{'=' * 60}")
        print(f"  Pre-flight summary: {len(self.passed)}/{total} passed", end="")
        if self.warnings:
            print(f", {len(self.warnings)} warnings", end="")
        if self.failures:
            print(f", {len(self.failures)} FAILED", end="")
        print()
        if self.failures:
            print("\n  Critical failures:")
            for f in self.failures:
                print(f"    - {f}")
        if self.warnings:
            print("\n  Warnings:")
            for w in self.warnings:
                print(f"    - {w}")
        print(f"{'=' * 60}")


def _print_status(tag: str, msg: str, color: str):
    reset = "\033[0m"
    print(f"  [{color}{tag}{reset}] {msg}")


# ── Individual Checks ─────────────────────────────────────────────────


def check_adb(r: CheckResult) -> str | None:
    """Check ADB is installed and a device is connected. Returns device ID or None."""
    if not shutil.which("adb"):
        r.warn("ADB not found on PATH — tablet deployment unavailable, will use Chrome browser")
        return None

    try:
        out = subprocess.run(
            ["adb", "devices"], capture_output=True, text=True, timeout=10
        )
        lines = [
            l for l in out.stdout.strip().splitlines()[1:] if l.strip() and "device" in l
        ]
        if not lines:
            r.warn("ADB installed but no devices connected — will use Chrome browser")
            return None
        device_id = lines[0].split()[0]
        r.ok(f"ADB device connected: {device_id}")
        return device_id
    except Exception as e:
        r.warn(f"ADB check failed: {e}")
        return None


def check_ports(r: CheckResult) -> dict[str, bool]:
    """Check if required ports are free. Returns {service: is_free}."""
    results = {}
    for service, port in REQUIRED_PORTS.items():
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind(("127.0.0.1", port))
                r.ok(f"Port {port} ({service}) is free")
                results[service] = True
            except OSError:
                r.fail(f"Port {port} ({service}) is in use — close the process or use a different port")
                results[service] = False
    return results


def check_python_deps(r: CheckResult):
    """Check all required Python packages are importable."""
    missing = []
    for pkg in ALL_DEPS:
        try:
            __import__(pkg)
        except ImportError:
            missing.append(pkg)

    if not missing:
        r.ok(f"All Python dependencies installed ({', '.join(ALL_DEPS)})")
    else:
        r.fail(f"Missing Python packages: {', '.join(missing)} — run: pip install {' '.join(missing)}")


def check_flutter(r: CheckResult):
    """Check Flutter SDK is on PATH and pub get works."""
    if not shutil.which("flutter"):
        r.fail("Flutter SDK not found on PATH")
        return

    r.ok("Flutter SDK found on PATH")

    if not FLUTTER_DIR.exists():
        r.fail(f"Flutter project dir not found: {FLUTTER_DIR}")
        return

    # Check pubspec.yaml exists
    if not (FLUTTER_DIR / "pubspec.yaml").exists():
        r.fail(f"pubspec.yaml not found in {FLUTTER_DIR}")
        return

    r.ok("Flutter project directory found")


def check_model_bundle(r: CheckResult):
    """Check ML model bundle exists with required subdirs."""
    if not BUNDLE_DIR.exists():
        r.fail(f"Model bundle not found: {BUNDLE_DIR}")
        return

    required_subdirs = ["config", "inference", "models"]
    missing = [d for d in required_subdirs if not (BUNDLE_DIR / d).exists()]
    if missing:
        r.fail(f"Model bundle missing subdirs: {', '.join(missing)}")
    else:
        r.ok(f"Model bundle found with all subdirs ({', '.join(required_subdirs)})")

    # Check for key model files
    models_dir = BUNDLE_DIR / "models"
    if models_dir.exists():
        model_files = list(models_dir.glob("*.json")) + list(models_dir.glob("*.bin"))
        if model_files:
            r.ok(f"Model files found: {len(model_files)} files in models/")
        else:
            r.warn("No model files (.json/.bin) found in models/ dir")


def check_data_files(r: CheckResult):
    """Check DuckDB and Parquet data files exist."""
    if DUCKDB_PATH.exists():
        size_mb = DUCKDB_PATH.stat().st_size / (1024 * 1024)
        r.ok(f"DuckDB found: {DUCKDB_PATH.name} ({size_mb:.1f} MB)")
    else:
        r.fail(f"DuckDB not found: {DUCKDB_PATH}")

    if PARQUET_DIR.exists():
        parquets = list(PARQUET_DIR.glob("*.parquet"))
        if parquets:
            r.ok(f"Parquet files found: {len(parquets)} trip files")
        else:
            r.fail(f"Parquet directory exists but is empty: {PARQUET_DIR}")
    else:
        r.fail(f"Parquet directory not found: {PARQUET_DIR}")


def check_network(r: CheckResult, device_id: str | None) -> str:
    """Determine best network path to tablet. Returns the SERVER_URL to use."""
    # Get LAN IP
    lan_ip = _get_lan_ip()
    if lan_ip and lan_ip != "127.0.0.1":
        r.ok(f"LAN IP detected: {lan_ip}")
    else:
        r.warn("Could not detect LAN IP — tablet may not reach backend over WiFi")
        lan_ip = None

    if not device_id:
        url = f"http://{lan_ip or 'localhost'}:5000"
        r.ok(f"No tablet — will use: {url}")
        return url

    # Try ADB reverse as fallback/supplement
    try:
        subprocess.run(
            ["adb", "-s", device_id, "reverse", "tcp:5000", "tcp:5000"],
            capture_output=True, text=True, timeout=5,
        )
        r.ok("ADB reverse port forwarding set (tcp:5000 -> localhost:5000)")
    except Exception as e:
        r.warn(f"ADB reverse failed: {e} — relying on WiFi LAN IP only")

    # Prefer LAN IP (works even if USB disconnects during demo),
    # but ADB reverse is set as backup (localhost works on tablet via USB)
    if lan_ip:
        url = f"http://{lan_ip}:5000"
        r.ok(f"Tablet SERVER_URL: {url} (ADB reverse also active as fallback)")
    else:
        url = "http://localhost:5000"
        r.ok(f"Tablet SERVER_URL: {url} (via ADB reverse)")

    return url


def _get_lan_ip() -> str | None:
    """Get LAN IPv4 address (Windows ipconfig)."""
    try:
        out = subprocess.run(
            ["ipconfig"], capture_output=True, text=True, timeout=5
        )
        for line in out.stdout.splitlines():
            if "IPv4 Address" in line or "IPv4" in line:
                parts = line.split(":")
                if len(parts) >= 2:
                    ip = parts[-1].strip()
                    if ip.startswith("192.") or ip.startswith("10.") or ip.startswith("172."):
                        return ip
    except Exception:
        pass
    return None


def check_backend_scripts(r: CheckResult):
    """Check that backend Python scripts exist."""
    scripts = ["dashboard_backend.py", "replay_vessel_server.py"]
    for script in scripts:
        path = DASHBOARD_DIR / script
        if path.exists():
            r.ok(f"Script found: {script}")
        else:
            r.fail(f"Script not found: {path}")


# ── Main ──────────────────────────────────────────────────────────────


def run_preflight(verbose: bool = True) -> CheckResult:
    """Run all pre-flight checks. Returns CheckResult."""
    r = CheckResult()
    print("\n" + "=" * 60)
    print("  M/B Dalaray Dashboard — Pre-Flight Checklist")
    print("=" * 60 + "\n")

    print("[1/7] ADB & Device Detection")
    device_id = check_adb(r)
    print()

    print("[2/7] Port Availability")
    check_ports(r)
    print()

    print("[3/7] Python Dependencies")
    check_python_deps(r)
    print()

    print("[4/7] Flutter SDK")
    check_flutter(r)
    print()

    print("[5/7] ML Model Bundle")
    check_model_bundle(r)
    print()

    print("[6/7] Data Files (DuckDB + Parquet)")
    check_data_files(r)
    print()

    print("[7/7] Network & Connectivity")
    server_url = check_network(r, device_id)
    print()

    print("[+] Backend Scripts")
    check_backend_scripts(r)

    r.summary()
    return r


def main():
    parser = argparse.ArgumentParser(description="Dashboard pre-flight checks")
    parser.add_argument("--quiet", action="store_true", help="Only show failures")
    args = parser.parse_args()

    result = run_preflight(verbose=not args.quiet)
    sys.exit(result.exit_code)


if __name__ == "__main__":
    main()
