#!/usr/bin/env python3
"""Replay Vessel Server — serves historical Parquet telemetry via the same
HTTP interface as the real vessel gateway (/vessel, /device/OneAries_*).

Replaces mock_vessel_server.py for testing with real recorded data.

Usage:
    python replay_vessel_server.py \
        --parquet-dir ../Daluyan_V2/backend/data/parquet \
        --duckdb-path ../Daluyan_V2/backend/data/daluyan.duckdb \
        --date 2026-03-02 --port 8481
"""

import argparse
import asyncio
import csv
import json
import logging
import os
from datetime import datetime

from aiohttp import web
import duckdb
import polars as pl

log = logging.getLogger("replay")

# ── Parquet column → raw vessel JSON key ──────────────────────────
PARQUET_TO_VESSEL = {
    "latitude": "currentPositionLatitude",
    "longitude": "currentPositionLongitude",
    "speed_over_ground": "speedOverGround",
    "heading": "currentHeading",
    "soc_percent": "batteryStateOfChargePercent",
    "hv_battery_capacity": "hvBatteryCapacity",
    "motor_power_combined": "motorPowerCombined",
    "port_motor_power": "portMotorPower",
    "stbd_motor_power": "stbdMotorPower",
    "trip_nm": "trip",
    "battery_power": "currentBatteryPower",
    "vessel_state": "vesselState",
    "sog_valid": "sogValid",
    "port_soc_percent": "portBatteryStateOfChargePercent",
    "port_rpm": "portRpmShaft",
    "stbd_rpm": "stbdRpmShaft",
    "port_throttle": "portThrottleGearState",
    "stbd_throttle": "stbdThrottleGearState",
    "heading_destination": "headingDestination",
    "distance_destination": "distanceDestination",
}

# Docked gap ticks between segments in full-day mode
DOCKED_GAP_TICKS = 10


def _row_to_vessel_json(row: dict) -> dict:
    """Convert a Parquet row (clean names) to vessel gateway JSON (raw names)."""
    result = {}
    for parquet_col, vessel_key in PARQUET_TO_VESSEL.items():
        val = row.get(parquet_col, 0)
        result[vessel_key] = val if val is not None else 0
    # Derived / alias fields the dashboard_backend also reads
    result["stbdBatteryStateOfChargePercent"] = result.get(
        "batteryStateOfChargePercent", 0
    )
    result["motorPower"] = result.get("motorPowerCombined", 0)
    result["batteryPower"] = result.get("currentBatteryPower", 0)
    result["stbdMotorSpeed"] = result.get("stbdRpmShaft", 0)
    result["portMotorTemperature"] = 45.0
    result["stbdMotorTemperature"] = 45.0
    result["portMotorTorque"] = 0.0
    result["stbdMotorTorque"] = 0.0
    return result


def _synthetic_bms(soc: float, battery_power: float) -> dict:
    """Fallback synthetic BMS JSON when no real data available."""
    return {
        "gCellBalance": 0,
        "gMaxCellTemperature": 32,
        "gMinCellTemperature": 30,
        "gPackVoltage": 355,
        "gCurrent": -50.0 if battery_power > 0 else 0.0,
        "gStateOfCharge": soc,
        "gPower": -battery_power / 2000,  # watts to kW, negative = discharge
        "gAverageTemperature": 31,
    }


# BMS fields the dashboard_backend expects
_BMS_KEYS = [
    "gCellBalance", "gMaxCellTemperature", "gMinCellTemperature",
    "gPackVoltage", "gCurrent", "gStateOfCharge", "gPower",
    "gAverageTemperature",
]


def _unescape_csv_json(raw: str) -> str:
    """Handle double-escaped CSV JSON: strip outer quotes, "" → "."""
    if raw.startswith('"') and raw.endswith('"'):
        raw = raw[1:-1]
    return raw.replace('""', '"')


def _parse_bms_json(raw: str) -> dict | None:
    """Parse a BMS response_raw string into a dict with the 8 expected keys."""
    try:
        text = _unescape_csv_json(raw)
        data = json.loads(text)
        return {k: data.get(k, 0) for k in _BMS_KEYS}
    except (json.JSONDecodeError, ValueError):
        return None


def _load_bms_from_csvs(csv_paths: list[str]) -> dict[str, dict]:
    """Parse raw CSVs for BMS data, indexed by timestamp second.

    Returns: {
        "2026-03-02 10:25:30": {"port": {...}, "stbd": {...}},
        ...
    }
    """
    bms_index: dict[str, dict] = {}
    port_count = stbd_count = skip_count = 0

    for csv_path in csv_paths:
        if not os.path.exists(csv_path):
            log.warning("BMS CSV not found: %s", csv_path)
            continue
        log.info("Parsing BMS from %s ...", os.path.basename(csv_path))
        with open(csv_path, "r", encoding="utf-8", errors="replace") as f:
            reader = csv.reader(f)
            try:
                next(reader)  # skip header
            except StopIteration:
                continue
            for row in reader:
                if len(row) < 3:
                    continue
                ts_raw, req, resp = row[0], row[1], row[2]

                # Identify port vs starboard BMS
                if "OneAries_IP_3_ID_49" in req:
                    side = "port"
                elif "OneAries_IP_4_ID_49" in req:
                    side = "stbd"
                else:
                    continue

                # Parse the BMS JSON
                parsed = _parse_bms_json(resp)
                if parsed is None:
                    skip_count += 1
                    continue

                # Normalize timestamp to second: "2026/03/02 10:25:30.123" → "2026-03-02 10:25:30"
                try:
                    dt = datetime.strptime(ts_raw[:19], "%Y/%m/%d %H:%M:%S")
                    ts_key = dt.strftime("%Y-%m-%d %H:%M:%S")
                except ValueError:
                    skip_count += 1
                    continue

                if ts_key not in bms_index:
                    bms_index[ts_key] = {}
                bms_index[ts_key][side] = parsed

                if side == "port":
                    port_count += 1
                else:
                    stbd_count += 1

    log.info(
        "BMS loaded: %d timestamps, %d port, %d stbd, %d skipped",
        len(bms_index), port_count, stbd_count, skip_count,
    )
    return bms_index


class ReplayState:
    """Manages replay state: loading data, advancing rows, speed control."""

    def __init__(self, parquet_dir: str, duckdb_path: str, date: str,
                 raw_csv_paths: list[str] | None = None):
        self.parquet_dir = parquet_dir
        self.date = date
        self.speed_multiplier = 1
        self.segments: list[dict] = []
        self.segment_dfs: dict[str, pl.DataFrame] = {}
        self.full_day_rows: list[dict] = []

        # Playback state
        self.playing = False
        self.mode = "docked"  # "docked", "segment", "full_day"
        self.current_segment_idx = -1
        self.current_row = 0
        self.total_rows = 0
        self.current_data: dict = {}
        self.current_timestamp: str = ""  # for BMS lookup
        self._active_segment_rows: list[dict] = []  # current segment rows (with docked tail)

        # BMS data indexed by timestamp second
        self.bms_index: dict[str, dict] = {}
        if raw_csv_paths:
            self.bms_index = _load_bms_from_csvs(raw_csv_paths)

        # Between-segment gap counter (full-day mode)
        self._gap_remaining = 0

        # Store paths for date switching
        self.duckdb_path = duckdb_path

        self._load_segments(duckdb_path)
        self._load_parquets()
        self._build_full_day()
        self._set_docked_state()

    # ── Loading ───────────────────────────────────────────────────

    def _load_segments(self, duckdb_path: str) -> None:
        db = duckdb.connect(duckdb_path, read_only=True)
        rows = db.execute(
            """SELECT segment_id, departure_station, arrival_station,
                      direction, departure_time, arrival_time
               FROM segments
               WHERE CAST(departure_time AS DATE) = ?
               ORDER BY departure_time""",
            [self.date],
        ).fetchall()
        db.close()
        for r in rows:
            self.segments.append(
                {
                    "segment_id": r[0],
                    "departure_station": r[1],
                    "arrival_station": r[2],
                    "direction": r[3],
                    "departure_time": str(r[4]),
                    "arrival_time": str(r[5]),
                }
            )
        log.info("Loaded %d segments for %s", len(self.segments), self.date)

    def _load_parquets(self) -> None:
        for seg in self.segments:
            fname = f"{seg['segment_id']}.parquet"
            path = os.path.join(self.parquet_dir, fname)
            if os.path.exists(path):
                df = pl.read_parquet(path)
                self.segment_dfs[seg["segment_id"]] = df
                nrows = len(df)
                seg["row_count"] = nrows
                log.info(
                    "  %s: %s -> %s (%s, %d rows)",
                    seg["segment_id"],
                    seg["departure_station"],
                    seg["arrival_station"],
                    seg["direction"],
                    nrows,
                )
            else:
                seg["row_count"] = 0
                log.warning("  %s: parquet not found at %s", seg["segment_id"], path)

    def _make_docked_rows(self, df: pl.DataFrame, count: int) -> list[dict]:
        """Create docked rows (speed=0) from the last row of a segment."""
        last_row = dict(df.row(len(df) - 1, named=True))
        last_row["speed_over_ground"] = 0.0
        return [dict(last_row) for _ in range(count)]

    def _build_segment_with_docking(self, seg_id: str) -> list[dict]:
        """Build row list for a segment, appending docked rows for state machine."""
        df = self.segment_dfs.get(seg_id)
        if df is None:
            return []
        rows = [df.row(i, named=True) for i in range(len(df))]
        # Append docked rows so the backend's nav state machine
        # can detect arrival (needs speed < 1 kn for 3+ seconds)
        rows.extend(self._make_docked_rows(df, DOCKED_GAP_TICKS))
        return rows

    def _build_full_day(self) -> None:
        """Pre-build the full-day row list with docked gaps between segments."""
        self.full_day_rows = []
        for seg in self.segments:
            df = self.segment_dfs.get(seg["segment_id"])
            if df is None:
                continue
            self.full_day_rows.extend(
                self._build_segment_with_docking(seg["segment_id"])
            )
        log.info("Full-day: %d total rows (incl. gaps)", len(self.full_day_rows))

    def _set_docked_state(self) -> None:
        """Set current data to first segment's first row at speed=0."""
        if self.segments and self.segment_dfs:
            first_id = self.segments[0]["segment_id"]
            df = self.segment_dfs.get(first_id)
            if df is not None and len(df) > 0:
                row = df.row(0, named=True)
                self.current_data = _row_to_vessel_json(row)
                self.current_data["speedOverGround"] = 0.0
                return
        # Fallback
        self.current_data = {
            "currentPositionLatitude": 14.5547,
            "currentPositionLongitude": 121.0937,
            "speedOverGround": 0.0,
            "batteryStateOfChargePercent": 95.0,
            "hvBatteryCapacity": 160.0,
        }

    def _update_timestamp(self, row: dict) -> None:
        """Extract timestamp from Parquet row for BMS index lookup."""
        ts = row.get("timestamp")
        if ts is not None:
            # Polars datetime → string "YYYY-MM-DD HH:MM:SS"
            if isinstance(ts, datetime):
                self.current_timestamp = ts.strftime("%Y-%m-%d %H:%M:%S")
            else:
                self.current_timestamp = str(ts)[:19]

    def get_bms(self, side: str) -> dict:
        """Get BMS data for current timestamp. Falls back to synthetic."""
        if self.bms_index and self.current_timestamp:
            entry = self.bms_index.get(self.current_timestamp)
            if entry and side in entry:
                return entry[side]
        # Fallback to synthetic
        soc = self.current_data.get("batteryStateOfChargePercent", 0)
        power = self.current_data.get("currentBatteryPower", 0)
        return _synthetic_bms(soc, power)

    # ── Playback control ──────────────────────────────────────────

    def start_segment(self, segment_id: str) -> bool:
        idx = next(
            (i for i, s in enumerate(self.segments) if s["segment_id"] == segment_id),
            -1,
        )
        if idx < 0 or segment_id not in self.segment_dfs:
            return False
        # Build extended rows (with docked tail for state machine detection)
        self._active_segment_rows = self._build_segment_with_docking(segment_id)
        self.current_segment_idx = idx
        self.current_row = 0
        self.total_rows = len(self._active_segment_rows)
        self.mode = "segment"
        self.playing = True
        log.info("Started segment %s (%d rows incl. docked tail)", segment_id, self.total_rows)
        return True

    def start_full_day(self) -> bool:
        if not self.full_day_rows:
            return False
        self.current_row = 0
        self.total_rows = len(self.full_day_rows)
        self.mode = "full_day"
        self.playing = True
        log.info("Started full-day replay (%d rows)", self.total_rows)
        return True

    def stop(self) -> None:
        self.playing = False
        self.mode = "docked"
        self._set_docked_state()
        log.info("Replay stopped")

    def advance(self) -> bool:
        """Advance one row. Returns True if still playing."""
        if not self.playing:
            return False

        if self.mode == "segment":
            if self.current_row >= len(self._active_segment_rows):
                self.playing = False
                self.mode = "docked"
                seg_id = self.segments[self.current_segment_idx]["segment_id"]
                log.info("Segment %s finished", seg_id)
                return False
            row = self._active_segment_rows[self.current_row]
            self.current_data = _row_to_vessel_json(row)
            self._update_timestamp(row)
            self.current_row += 1
            return True

        elif self.mode == "full_day":
            if self.current_row >= len(self.full_day_rows):
                self.playing = False
                self.mode = "docked"
                self._set_docked_state()
                log.info("Full-day replay finished")
                return False
            row = self.full_day_rows[self.current_row]
            self.current_data = _row_to_vessel_json(row)
            self._update_timestamp(row)
            self.current_row += 1
            return True

        return False

    def get_available_dates(self) -> list[str]:
        """Query DuckDB for all dates that have segments."""
        try:
            db = duckdb.connect(self.duckdb_path, read_only=True)
            rows = db.execute(
                """SELECT DISTINCT CAST(departure_time AS DATE) AS d
                   FROM segments ORDER BY d DESC"""
            ).fetchall()
            db.close()
            return [str(r[0]) for r in rows]
        except Exception as e:
            log.warning("Failed to query available dates: %s", e)
            return [self.date]

    def change_date(self, new_date: str) -> bool:
        """Stop playback and reload segments for a new date."""
        self.stop()
        self.date = new_date
        self.segments = []
        self.segment_dfs = {}
        self.full_day_rows = []
        self._load_segments(self.duckdb_path)
        self._load_parquets()
        self._build_full_day()
        self._set_docked_state()
        log.info("Changed date to %s (%d segments)", new_date, len(self.segments))
        return len(self.segments) > 0

    def get_status(self) -> dict:
        seg = None
        if self.mode == "segment" and 0 <= self.current_segment_idx < len(self.segments):
            seg = self.segments[self.current_segment_idx]
        return {
            "playing": self.playing,
            "mode": self.mode,
            "speed_multiplier": self.speed_multiplier,
            "current_row": self.current_row,
            "total_rows": self.total_rows,
            "progress_pct": (
                round(100 * self.current_row / self.total_rows, 1)
                if self.total_rows > 0
                else 0
            ),
            "current_segment": seg,
            "date": self.date,
        }


# ── Background ticker ─────────────────────────────────────────────

async def replay_ticker(state: ReplayState):
    """Advance replay at 1Hz * speed_multiplier."""
    while True:
        if state.playing:
            state.advance()
        await asyncio.sleep(1.0 / max(state.speed_multiplier, 1))


# ── HTTP Handlers ─────────────────────────────────────────────────

async def handle_vessel(request: web.Request) -> web.Response:
    state: ReplayState = request.app["state"]
    return web.json_response(state.current_data)


async def handle_bms_port(request: web.Request) -> web.Response:
    state: ReplayState = request.app["state"]
    return web.json_response(state.get_bms("port"))


async def handle_bms_stbd(request: web.Request) -> web.Response:
    state: ReplayState = request.app["state"]
    return web.json_response(state.get_bms("stbd"))


async def handle_segments(request: web.Request) -> web.Response:
    state: ReplayState = request.app["state"]
    return web.json_response(state.segments)


async def handle_replay_start(request: web.Request) -> web.Response:
    state: ReplayState = request.app["state"]
    body = await request.json()
    if body.get("mode") == "full_day":
        ok = state.start_full_day()
    else:
        ok = state.start_segment(body.get("segment_id", ""))
    return web.json_response({"ok": ok, "status": state.get_status()})


async def handle_replay_stop(request: web.Request) -> web.Response:
    state: ReplayState = request.app["state"]
    state.stop()
    return web.json_response({"ok": True, "status": state.get_status()})


async def handle_replay_speed(request: web.Request) -> web.Response:
    state: ReplayState = request.app["state"]
    body = await request.json()
    m = int(body.get("multiplier", 1))
    state.speed_multiplier = max(1, min(m, 10))
    log.info("Speed multiplier set to %dx", state.speed_multiplier)
    return web.json_response(
        {"ok": True, "speed_multiplier": state.speed_multiplier}
    )


async def handle_replay_status(request: web.Request) -> web.Response:
    state: ReplayState = request.app["state"]
    return web.json_response(state.get_status())


async def handle_dates(request: web.Request) -> web.Response:
    state: ReplayState = request.app["state"]
    return web.json_response({
        "dates": state.get_available_dates(),
        "current": state.date,
    })


async def handle_change_date(request: web.Request) -> web.Response:
    state: ReplayState = request.app["state"]
    body = await request.json()
    new_date = body.get("date", "")
    ok = state.change_date(new_date)
    return web.json_response({
        "ok": ok,
        "date": state.date,
        "segments": state.segments,
        "status": state.get_status(),
    })


# ── App lifecycle ─────────────────────────────────────────────────

async def start_background(app: web.Application):
    app["ticker"] = asyncio.create_task(replay_ticker(app["state"]))


async def cleanup_background(app: web.Application):
    app["ticker"].cancel()
    try:
        await app["ticker"]
    except asyncio.CancelledError:
        pass


# ── Main ──────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Replay vessel server — serves historical telemetry"
    )
    _script_dir = os.path.dirname(os.path.abspath(__file__))
    _default_parquet = os.path.join(_script_dir, "..", "Daluyan_V2", "backend", "data", "parquet")
    _default_duckdb = os.path.join(_script_dir, "..", "Daluyan_V2", "backend", "data", "daluyan.duckdb")
    parser.add_argument(
        "--parquet-dir",
        default=_default_parquet,
        help="Directory containing trip Parquet files",
    )
    parser.add_argument(
        "--duckdb-path",
        default=_default_duckdb,
        help="Path to Daluyan DuckDB database",
    )
    parser.add_argument(
        "--date",
        default="2026-03-02",
        help="Date to replay (YYYY-MM-DD)",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=8481,
        help="HTTP port (default: 8481)",
    )
    parser.add_argument(
        "--raw-csv",
        nargs="+",
        default=[],
        help="Raw CSV file(s) for BMS data (e.g., 20260302_AM.csv 20260302_PM.csv)",
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(name)s] %(message)s",
        datefmt="%H:%M:%S",
    )

    state = ReplayState(
        args.parquet_dir, args.duckdb_path, args.date,
        raw_csv_paths=args.raw_csv if args.raw_csv else None,
    )

    app = web.Application()
    app["state"] = state

    # Same endpoints as real vessel gateway
    app.router.add_get("/vessel", handle_vessel)
    app.router.add_get("/device/OneAries_IP_3_ID_49", handle_bms_port)
    app.router.add_get("/device/OneAries_IP_4_ID_49", handle_bms_stbd)

    # Replay control
    app.router.add_get("/segments", handle_segments)
    app.router.add_get("/dates", handle_dates)
    app.router.add_post("/replay/start", handle_replay_start)
    app.router.add_post("/replay/stop", handle_replay_stop)
    app.router.add_post("/replay/speed", handle_replay_speed)
    app.router.add_post("/replay/change_date", handle_change_date)
    app.router.add_get("/replay/status", handle_replay_status)

    app.on_startup.append(start_background)
    app.on_cleanup.append(cleanup_background)

    print(f"\n{'='*60}")
    print(f"  Replay Vessel Server")
    print(f"  Date: {args.date} | Segments: {len(state.segments)}")
    print(f"  Port: {args.port}")
    print(f"{'='*60}\n")
    for s in state.segments:
        print(f"  {s['segment_id']}: {s['departure_station']} -> {s['arrival_station']} ({s['direction']}, {s['row_count']} rows)")
    print()

    web.run_app(app, host="0.0.0.0", port=args.port, print=None)


if __name__ == "__main__":
    main()
