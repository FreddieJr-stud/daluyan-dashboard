import requests
import csv
import datetime
import time
import threading
import os

# Import settings from config.py
from config import API_HOST, API_PORT, REQUEST_INPUTS, LOG_ROOT, AM_START, PM_START, PM_END

# Global busy flag (thread-safe with Lock)
busy = False
busy_lock = threading.Lock()

# ---------- Time window helpers ----------

def _to_minutes(hhmm: str) -> int:
    """Convert 'HH:MM' to minutes since midnight."""
    try:
        h, m = hhmm.split(":")
        h = int(h); m = int(m)
        if not (0 <= h < 24 and 0 <= m < 60):
            raise ValueError
        return h * 60 + m
    except Exception:
        # Fallback: 00:00 if misconfigured
        return 0

AM_START_MIN = _to_minutes(AM_START)
PM_START_MIN = _to_minutes(PM_START)
PM_END_MIN   = _to_minutes(PM_END)

def get_timestamp():
    """Return timestamp as YYYY/MM/DD HH:mm:ss:ms"""
    return datetime.datetime.now().strftime("%Y/%m/%d %H:%M:%S.%f")[:-3]

def _now_minutes(now=None) -> int:
    if now is None:
        now = datetime.datetime.now()
    return now.hour * 60 + now.minute

def get_time_window_name(now=None) -> str:
    """
    Windows from 3 boundaries (HH:MM):
      AM       = [AM_START, PM_START)
      PM       = [PM_START, PM_END)
      AM_off   = [00:00, AM_START)
      PM_off   = [PM_END, 24:00)
    Assumes: 00:00 <= AM_START < PM_START < PM_END <= 24:00
    If the ordering is violated, we still return a best-effort window.
    """
    t = _now_minutes(now)

    # Normal expected ordering
    if AM_START_MIN < PM_START_MIN < PM_END_MIN:
        if AM_START_MIN <= t < PM_START_MIN:
            return "AM"
        elif PM_START_MIN <= t < PM_END_MIN:
            return "PM"
        elif 0 <= t < AM_START_MIN:
            return "AM_off"
        else:
            return "PM_off"

    # Best-effort fallback if config is odd; check intervals explicitly
    if AM_START_MIN <= t < PM_START_MIN:
        return "AM"
    if PM_START_MIN <= t < PM_END_MIN:
        return "PM"
    if t < AM_START_MIN:
        return "AM_off"
    return "PM_off"

# ---------- Logging helpers ----------

def get_log_filename():
    """Return log filename grouped by month and time window."""
    now = datetime.datetime.now()
    month_dir = now.strftime("%Y%m")   # e.g., 202509
    os.makedirs(os.path.join(LOG_ROOT, month_dir), exist_ok=True)
    window = get_time_window_name(now)
    filename = f"{now.strftime('%Y%m%d')}_{window}.csv"
    return os.path.join(LOG_ROOT, month_dir, filename)

def ensure_log_file():
    """Ensure log file exists and has header."""
    logfile = get_log_filename()
    if not os.path.exists(logfile):
        with open(logfile, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(["timestamp", "request_input", "response_raw"])
    return logfile

def query_api(request_input):
    url = f"http://{API_HOST}:{API_PORT}/{request_input}"
    try:
        response = requests.get(url, timeout=5) #tried 30 seconds
        return response.text
    except requests.RequestException as e:
        return f"ERROR: {e}"

def log_to_csv(timestamp, request_input, response_text):
    # Skip logging if response is exactly an empty list
    if response_text.strip() == "[]":
        return
    logfile = ensure_log_file()
    with open(logfile, mode="a", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow([timestamp, request_input, response_text])

# ---------- Workers ----------

def worker(request_input, interval):
    """Daemon worker for each request_input with its own interval."""
    global busy
    while True:
        with busy_lock:
            if not busy:
                busy = True
                ts = get_timestamp()
                resp = query_api(request_input)
                log_to_csv(ts, request_input, resp)
                response_contents = resp.strip()
                if response_contents.startswith("ERROR:"):
                    print(f"[{ts}] \t\tERROR - Problem")
                elif response_contents != "[]":
                    # print(f"[{ts}] Logged '{request_input}' -> {get_time_window_name()}")
                    # print(f"[{ts}] Logged '{request_input}'")
                    print(f"[{ts}] Log")
                    # print(f"[{ts}] Logged: [{response_contents}]")
                    # pass
                busy = False
        time.sleep(interval)

def main():
    # Start one thread per request_input + interval
    for req, interval in REQUEST_INPUTS:
        t = threading.Thread(target=worker, args=(req, interval), daemon=True)
        t.start()

    # Keep daemon alive
    while True:
        time.sleep(1)

if __name__ == "__main__":
    main()
