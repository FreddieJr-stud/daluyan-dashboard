import os
import json
import datetime
import time

# Import config values (LOG_ROOT, AM_START, PM_START, PM_END)
from config import LOG_ROOT, AM_START, PM_START, PM_END

# Which keys to show first
PRIORITY_KEYS = ["vesselState","batteryStateOfChargePercent", "speedThroughWater", "speedOverGround", "speedOverGroundFixed", "portRpmShaft", "stbdRpmShaft", "motorPowerCombined", "portMotorPower", "stbdMotorPower", "trip", "hvBatteryCapacity", "currentPositionLatitude", "currentPositionLongitude"]

# Output file (overwritten every second)
OUTPUT_FILE = "pretty.txt"


# ---------- Time window helpers ----------

def _to_minutes(hhmm: str) -> int:
    """Convert 'HH:MM' string to minutes since midnight, safe fallback to 0."""
    try:
        h, m = hhmm.split(":")
        h = int(h); m = int(m)
        if not (0 <= h < 24 and 0 <= m < 60):
            raise ValueError
        return h * 60 + m
    except Exception:
        return 0


AM_START_MIN = _to_minutes(AM_START)
PM_START_MIN = _to_minutes(PM_START)
PM_END_MIN   = _to_minutes(PM_END)


def get_time_window_name(now=None) -> str:
    """Return one of: AM, PM, AM_off, PM_off"""
    if now is None:
        now = datetime.datetime.now()
    t_min = now.hour * 60 + now.minute

    # Normal, expected ordering:
    if AM_START_MIN < PM_START_MIN < PM_END_MIN:
        if AM_START_MIN <= t_min < PM_START_MIN:
            return "AM"
        if PM_START_MIN <= t_min < PM_END_MIN:
            return "PM"
        if t_min < AM_START_MIN:
            return "AM_off"
        return "PM_off"

    # Best-effort fallback if config odd
    if AM_START_MIN <= t_min < PM_START_MIN:
        return "AM"
    if PM_START_MIN <= t_min < PM_END_MIN:
        return "PM"
    if t_min < AM_START_MIN:
        return "AM_off"
    return "PM_off"


def get_current_log_file():
    """Return path to the current CSV log file based on LOG_ROOT and window."""
    now = datetime.datetime.now()
    month_dir = now.strftime("%Y%m")
    base_dir = os.path.join(LOG_ROOT, month_dir)
    os.makedirs(base_dir, exist_ok=True)
    window = get_time_window_name(now)
    filename = now.strftime("%Y%m%d") + f"_{window}.csv"
    return os.path.join(base_dir, filename)


# ---------- File-reading (scan last N lines) ----------

def get_latest_valid_vessel_row(filename: str, max_scan_lines: int = 10):
    """
    Scan backwards and examine up to `max_scan_lines` non-header lines.
    Return the newest valid (and non-empty-list) vessel row as (ts, raw_json),
    or (None, None) if none found.
    """
    if not os.path.exists(filename):
        return None, None

    latest_candidate = (None, None)
    scanned_non_header = 0

    # Open in binary to reliably seek/read from end
    with open(filename, "rb") as f:
        f.seek(0, os.SEEK_END)
        pos = f.tell()
        buffer = b""

        # read backward until we've checked enough lines or reached file start
        while pos > 0 and scanned_non_header < max_scan_lines:
            step = min(4096, pos)
            pos -= step
            f.seek(pos)
            chunk = f.read(step)
            buffer = chunk + buffer
            parts = buffer.split(b"\n")

            # keep first partial (older) in buffer, process rest
            if pos > 0:
                buffer = parts[0]
                lines = parts[1:]
            else:
                # we reached the start; all parts are full lines
                buffer = b""
                lines = parts

            # iterate newest -> older within this chunk
            for raw_line in reversed(lines):
                try:
                    line = raw_line.decode("utf-8", errors="ignore").strip()
                except Exception:
                    continue
                if not line:
                    continue
                if line.startswith("timestamp"):
                    continue  # skip header

                scanned_non_header += 1

                try:
                    ts_str, topic, rest = line.split(",", 2)
                except ValueError:
                    continue

                if topic.strip().lower() != "vessel":
                    continue

                if rest.strip().strip('"') == "[]":
                    continue

                try:
                    ts = datetime.datetime.strptime(ts_str, "%Y/%m/%d %H:%M:%S.%f")
                except Exception:
                    continue

                raw_json = rest
                if raw_json.startswith('"') and raw_json.endswith('"'):
                    raw_json = raw_json[1:-1]

                return ts, raw_json  # newest valid row

    return latest_candidate


# ---------- Prettify single row and write to file ----------

def prettify_and_write(ts, raw_json):
    """Pretty-print only one vessel row (priority keys + others) and overwrite OUTPUT_FILE."""
    if ts is None or raw_json is None:
        with open(OUTPUT_FILE, "w", encoding="utf-8") as out:
            out.write("⚠️ No valid vessel row found in the last scan.\n")
        return

    try:
        clean_json = raw_json.replace('""', '"')
        data = json.loads(clean_json)
    except Exception:
        with open(OUTPUT_FILE, "w", encoding="utf-8") as out:
            out.write(f"⚠️ Failed to parse JSON for row at {ts}\n")
            out.write(f"Raw: {raw_json}\n")
        return

    with open(OUTPUT_FILE, "w", encoding="utf-8") as out:
        out.write(f"=== Vessel Log @ {ts.strftime('%Y/%m/%d %H:%M:%S.%f')[:-3]} ===\n\n")
        out.write("Priority Info:\n")
        for k in PRIORITY_KEYS:
            out.write(f"  {k}: {data.get(k, '')}\n")
        out.write("\nOthers:\n")
        for k, v in data.items():
            if k not in PRIORITY_KEYS:
                out.write(f"  {k}: {v}\n")


# ---------- Main loop ----------

def main():
    print("Watching latest vessel data (updates pretty.txt every second)...")
    while True:
        logfile = get_current_log_file()
        ts, raw_json = get_latest_valid_vessel_row(logfile, max_scan_lines=30)
        prettify_and_write(ts, raw_json)
        time.sleep(1)


if __name__ == "__main__":
    main()
