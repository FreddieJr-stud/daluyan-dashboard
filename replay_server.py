"""Socket.IO replay server for the M/B Dalaray Flutter Dashboard.

Replays historical trip data from the Daluyan pipeline through Socket.IO,
running XGBoost ML models for real-time SOC prediction and motor anomaly
detection on each 1Hz telemetry tick.

Usage:
    python replay_server.py --date 2026-03-02
    python replay_server.py --date 2026-03-02 --test-mode --dock-time 0
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import signal
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import aiohttp.web
import duckdb
import numpy as np
import polars as pl
import socketio

# ---------------------------------------------------------------------------
# Paths (relative to this script)
# ---------------------------------------------------------------------------
SCRIPT_DIR = Path(__file__).resolve().parent
DALUYAN_DIR = SCRIPT_DIR / ".." / "Daluyan_V2" / "backend" / "data"
DUCKDB_PATH = DALUYAN_DIR / "daluyan.duckdb"
PARQUET_DIR = DALUYAN_DIR / "parquet"
RPI5_BUNDLE = SCRIPT_DIR / ".." / "Ferry_Digital_Shadow" / "Models" / "rpi5_bundle"
MODELS_DIR = RPI5_BUNDLE / "models"
CONFIG_DIR = RPI5_BUNDLE / "config"

# ---------------------------------------------------------------------------
# Station registry (canonical order, GPS, cumulative km)
# ---------------------------------------------------------------------------
STATIONS = [
    {"name": "Napindan",   "order": 0, "lat": 14.55713, "lon": 121.06836, "km": 0.0},
    {"name": "Guadalupe",  "order": 1, "lat": 14.5681100, "lon": 121.0478946, "km": 6.5},
    {"name": "Hulo",       "order": 2, "lat": 14.5679545, "lon": 121.0336782, "km": 8.3},
    {"name": "Valenzuela", "order": 3, "lat": 14.5739778, "lon": 121.0257656, "km": 9.8},
    {"name": "Lambingan",  "order": 4, "lat": 14.5872813, "lon": 121.0184560, "km": 11.2},
    {"name": "Sta Ana",    "order": 5, "lat": 14.5827238, "lon": 121.0119451, "km": 12.7},
    {"name": "PUP",        "order": 6, "lat": 14.5960355, "lon": 121.0107013, "km": 14.0},
    {"name": "Quinta",     "order": 7, "lat": 14.5957803, "lon": 120.9814485, "km": 15.6},
    {"name": "Escolta",    "order": 8, "lat": 14.5963832, "lon": 120.9775262, "km": 16.0},
]
STATION_BY_NAME = {s["name"]: s for s in STATIONS}
STATION_NAMES = [s["name"] for s in STATIONS]

# ---------------------------------------------------------------------------
# WMO weather code -> human-readable description
# ---------------------------------------------------------------------------
WMO_DESCRIPTIONS = {
    0: "Clear Sky", 1: "Mainly Clear", 2: "Partly Cloudy", 3: "Overcast",
    45: "Foggy", 48: "Foggy",
    51: "Drizzle", 53: "Drizzle", 55: "Drizzle",
    61: "Rain", 63: "Rain", 65: "Rain",
    80: "Showers", 81: "Showers", 82: "Showers",
    95: "Thunderstorm", 96: "Thunderstorm", 99: "Thunderstorm",
}

# Nominal battery capacity for Model 1A
NOMINAL_HV_CAPACITY = 160.0

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("replay")

# ---------------------------------------------------------------------------
# Load ML model inference modules from the RPi5 bundle
# ---------------------------------------------------------------------------
_bundle_str = str(RPI5_BUNDLE.resolve())
if _bundle_str not in sys.path:
    sys.path.insert(0, _bundle_str)

from inference.inference_soc_trip import SOCTripPredictor        # noqa: E402
from inference.inference_soc_realtime import SOCRealtimePredictor  # noqa: E402
from inference.inference_anomaly import MotorAnomalyDetector      # noqa: E402
from inference.features.tide import compute_tide_features         # noqa: E402


# ===================================================================
# Data loading helpers
# ===================================================================

def load_segments(con: duckdb.DuckDBPyConnection, date_str: str) -> list[dict]:
    """Load segment metadata for a given date from DuckDB, sorted by departure_time."""
    rows = con.execute(
        """
        SELECT s.segment_id, s.departure_station, s.arrival_station,
               s.direction, s.departure_time, s.arrival_time,
               ss.first_soc, ss.last_soc, ss.distance_km, ss.avg_speed,
               ss.duration_seconds
        FROM segments s
        JOIN segment_statistics ss ON s.segment_id = ss.segment_id
        WHERE CAST(s.departure_time AS DATE) = ?
        ORDER BY s.departure_time
        """,
        [date_str],
    ).fetchall()
    cols = [
        "segment_id", "departure_station", "arrival_station",
        "direction", "departure_time", "arrival_time",
        "first_soc", "last_soc", "distance_km", "avg_speed",
        "duration_seconds",
    ]
    return [dict(zip(cols, r)) for r in rows]


def load_ridership(con: duckdb.DuckDBPyConnection, segment_ids: list[str]) -> dict[str, int]:
    """Load ridership per segment (returns empty dict if table is empty)."""
    if not segment_ids:
        return {}
    placeholders = ", ".join(["?"] * len(segment_ids))
    rows = con.execute(
        f"SELECT segment_id, passengers_on_board FROM segment_ridership "
        f"WHERE segment_id IN ({placeholders})",
        segment_ids,
    ).fetchall()
    return {r[0]: int(r[1]) for r in rows if r[1] is not None}


def load_weather(con: duckdb.DuckDBPyConnection, date_str: str) -> dict[int, dict]:
    """Load hourly weather for a date. Returns dict keyed by hour (0-23)."""
    rows = con.execute(
        """
        SELECT time, temperature_c, relative_humidity, wind_speed_kn,
               wind_direction_deg, wind_gusts_kn, precipitation_mm,
               cloud_cover_percent, weather_code, pressure_msl_hpa,
               visibility_m, wave_height_m, wave_direction_deg,
               wave_period_s, ocean_current_velocity_ms,
               ocean_current_direction_deg, sea_surface_temperature_c
        FROM weather_hourly WHERE date = ?
        ORDER BY time
        """,
        [date_str],
    ).fetchall()
    weather: dict[int, dict] = {}
    for r in rows:
        # time column is ISO string like "2026-03-02T10:00"
        hour = int(r[0].split("T")[1].split(":")[0])
        weather[hour] = {
            "temperature_c": r[1] or 28.0,
            "relative_humidity": r[2] or 75.0,
            "wind_speed_kn": r[3] or 5.0,
            "wind_direction_deg": r[4] or 180.0,
            "wind_gusts_kn": r[5] or 0.0,
            "precipitation_mm": r[6] or 0.0,
            "cloud_cover_percent": r[7] or 50.0,
            "weather_code": r[8] or 0,
            "pressure_msl_hpa": r[9] or 1013.0,
            "visibility_m": r[10],
            "wave_height_m": r[11] or 0.1,
            "wave_direction_deg": r[12] or 0.0,
            "wave_period_s": r[13] or 0.0,
            "ocean_current_velocity_ms": r[14] or 0.0,
            "ocean_current_direction_deg": r[15] or 0.0,
            "sea_surface_temperature_c": r[16] or 28.0,
        }
    return weather


def load_parquet(segment_id: str) -> pl.DataFrame | None:
    """Load trip parquet for a segment. Returns None if file missing."""
    date_part = segment_id[:10]  # e.g. "2026-03-02"
    fname = f"{segment_id}.parquet"
    path = PARQUET_DIR / fname
    if not path.exists():
        log.warning("Parquet not found: %s", path)
        return None
    return pl.read_parquet(path)


def get_weather_for_hour(weather: dict[int, dict], hour: int) -> dict:
    """Return weather dict for a given hour, falling back to nearest hour."""
    if hour in weather:
        return weather[hour]
    # Find nearest available hour
    available = sorted(weather.keys())
    if not available:
        return {
            "temperature_c": 28.0, "relative_humidity": 75.0,
            "wind_speed_kn": 5.0, "wind_direction_deg": 180.0,
            "wind_gusts_kn": 0.0, "precipitation_mm": 0.0,
            "cloud_cover_percent": 50.0, "weather_code": 0,
            "pressure_msl_hpa": 1013.0, "visibility_m": None,
            "wave_height_m": 0.1, "wave_direction_deg": 0.0,
            "wave_period_s": 0.0, "ocean_current_velocity_ms": 0.0,
            "ocean_current_direction_deg": 0.0,
            "sea_surface_temperature_c": 28.0,
        }
    nearest = min(available, key=lambda h: abs(h - hour))
    return weather[nearest]


def weather_description(code: int | None) -> str:
    """Map WMO weather code to description string."""
    if code is None:
        return "Unknown"
    return WMO_DESCRIPTIONS.get(code, "Unknown")


def safety_status(arrival_soc: float) -> str:
    """Determine safety status from predicted arrival SOC."""
    if arrival_soc > 50:
        return "RECOMMENDED"
    elif arrival_soc > 20:
        return "CAUTION"
    else:
        return "CRITICAL"


# ===================================================================
# Auto-prediction: Model 1A predictions for all reachable destinations
# ===================================================================

def compute_auto_predictions(
    trip_predictor: SOCTripPredictor,
    departure_station: str,
    current_soc: float,
    passengers: int,
    weather_now: dict,
    departure_time: datetime,
) -> dict:
    """Run Model 1A for every reachable destination from the current station."""
    if departure_station not in STATION_BY_NAME:
        return {"mode": "docked", "predictions": []}

    dep_order = STATION_BY_NAME[departure_station]["order"]
    predictions = []

    # Downstream destinations (higher order)
    for stn in STATIONS:
        if stn["order"] <= dep_order:
            continue
        try:
            soc_consumed = trip_predictor.predict(
                departure_station=departure_station,
                arrival_station=stn["name"],
                current_soc=current_soc,
                hv_capacity=NOMINAL_HV_CAPACITY,
                target_speed_kn=max(5.0, 7.0),  # default cruising speed
                passengers=passengers,
                temperature_c=weather_now["temperature_c"],
                humidity=weather_now["relative_humidity"],
                wind_speed_kn=weather_now["wind_speed_kn"],
                wind_direction_deg=weather_now["wind_direction_deg"],
                precipitation_mm=weather_now["precipitation_mm"],
                wave_height_m=weather_now["wave_height_m"],
                hour=departure_time.hour,
                departure_time=departure_time,
                ocean_current_velocity_ms=weather_now["ocean_current_velocity_ms"],
                ocean_current_direction_deg=weather_now["ocean_current_direction_deg"],
                wave_direction_deg=weather_now["wave_direction_deg"],
                wave_period_s=weather_now["wave_period_s"],
            )
            arrival_soc = current_soc - soc_consumed
            status = "SAFE" if arrival_soc > 50 else ("CAUTION" if arrival_soc > 20 else "CRITICAL")
            predictions.append({
                "departure": departure_station,
                "destination": stn["name"],
                "predicted_soc": f"{arrival_soc:.1f}",
                "soc_reduction": f"{soc_consumed:.1f}",
                "safety_status": status,
                "direction": "downstream",
            })
        except Exception as e:
            log.warning("Auto-prediction failed for %s -> %s: %s", departure_station, stn["name"], e)

    # Upstream destinations (lower order)
    for stn in reversed(STATIONS):
        if stn["order"] >= dep_order:
            continue
        try:
            soc_consumed = trip_predictor.predict(
                departure_station=departure_station,
                arrival_station=stn["name"],
                current_soc=current_soc,
                hv_capacity=NOMINAL_HV_CAPACITY,
                target_speed_kn=max(5.0, 7.0),
                passengers=passengers,
                temperature_c=weather_now["temperature_c"],
                humidity=weather_now["relative_humidity"],
                wind_speed_kn=weather_now["wind_speed_kn"],
                wind_direction_deg=weather_now["wind_direction_deg"],
                precipitation_mm=weather_now["precipitation_mm"],
                wave_height_m=weather_now["wave_height_m"],
                hour=departure_time.hour,
                departure_time=departure_time,
                ocean_current_velocity_ms=weather_now["ocean_current_velocity_ms"],
                ocean_current_direction_deg=weather_now["ocean_current_direction_deg"],
                wave_direction_deg=weather_now["wave_direction_deg"],
                wave_period_s=weather_now["wave_period_s"],
            )
            arrival_soc = current_soc - soc_consumed
            status = "SAFE" if arrival_soc > 50 else ("CAUTION" if arrival_soc > 20 else "CRITICAL")
            predictions.append({
                "departure": departure_station,
                "destination": stn["name"],
                "predicted_soc": f"{arrival_soc:.1f}",
                "soc_reduction": f"{soc_consumed:.1f}",
                "safety_status": status,
                "direction": "upstream",
            })
        except Exception as e:
            log.warning("Auto-prediction failed for %s -> %s: %s", departure_station, stn["name"], e)

    return {"mode": "docked", "predictions": predictions}


# ===================================================================
# Speed prediction handler
# ===================================================================

def compute_speed_predictions(
    trip_predictor: SOCTripPredictor,
    departure_station: str,
    arrival_station: str,
    current_soc: float,
    passengers: int,
    weather_now: dict,
    departure_time: datetime,
) -> dict:
    """Run Model 1A at multiple speeds for a given route."""
    speeds_kn = [5.0, 7.0, 10.0, 12.0, 15.0]
    result_speeds = []

    for spd in speeds_kn:
        try:
            soc_consumed = trip_predictor.predict(
                departure_station=departure_station,
                arrival_station=arrival_station,
                current_soc=current_soc,
                hv_capacity=NOMINAL_HV_CAPACITY,
                target_speed_kn=spd,
                passengers=passengers,
                temperature_c=weather_now["temperature_c"],
                humidity=weather_now["relative_humidity"],
                wind_speed_kn=weather_now["wind_speed_kn"],
                wind_direction_deg=weather_now["wind_direction_deg"],
                precipitation_mm=weather_now["precipitation_mm"],
                wave_height_m=weather_now["wave_height_m"],
                hour=departure_time.hour,
                departure_time=departure_time,
                ocean_current_velocity_ms=weather_now["ocean_current_velocity_ms"],
                ocean_current_direction_deg=weather_now["ocean_current_direction_deg"],
                wave_direction_deg=weather_now["wave_direction_deg"],
                wave_period_s=weather_now["wave_period_s"],
            )
            arrival_soc = current_soc - soc_consumed
            result_speeds.append({
                "speed_kn": spd,
                "predicted_soc": f"{arrival_soc:.1f}%",
                "soc_reduction": f"{soc_consumed:.1f}",
                "safety_status": safety_status(arrival_soc),
            })
        except Exception as e:
            log.warning("Speed prediction failed at %.1f kn: %s", spd, e)
            result_speeds.append({
                "speed_kn": spd,
                "predicted_soc": "N/A",
                "soc_reduction": "N/A",
                "safety_status": "UNKNOWN",
            })

    return {
        "departure": departure_station,
        "destination": arrival_station,
        "speeds": result_speeds,
    }


# ===================================================================
# Replay Server
# ===================================================================

class ReplayServer:
    """Manages the Socket.IO server and replay state."""

    def __init__(self, date_str: str, dock_time: float, test_mode: bool):
        self.date_str = date_str
        self.dock_time = dock_time
        self.test_mode = test_mode
        self._shutdown = False
        self._replay_speed: float = 1.0
        self._replay_status: str = "waiting"  # waiting, playing, completed

        # Socket.IO server (async mode with aiohttp)
        self.sio = socketio.AsyncServer(
            async_mode="aiohttp",
            cors_allowed_origins="*",
            logger=False,
            engineio_logger=False,
        )
        self.app = aiohttp.web.Application()
        self.sio.attach(self.app)

        # --- Load ML models ---
        log.info("Loading ML models...")
        models_str = str(MODELS_DIR.resolve())
        config_str = str(CONFIG_DIR.resolve())

        self.trip_predictor = SOCTripPredictor(models_str, config_str)
        log.info("  Model 1A (trip SOC): %d ensemble members", len(self.trip_predictor.models))

        self.rt_predictor = SOCRealtimePredictor(models_str, models_str, config_str)
        log.info("  Model 1B (realtime SOC): %d ensemble members", len(self.rt_predictor.rt_models))

        self.motor_detector = MotorAnomalyDetector(config_str, models_str)
        log.info("  Model 2 (motor anomaly): %d reconstruction models", len(self.motor_detector.models))

        # --- Scan available dates ---
        self._available_dates = self._scan_available_dates()
        log.info("Found %d dates with parquet data", len(self._available_dates))

        # --- Load data for the initial date ---
        if not self._load_data(date_str):
            log.error("No valid segments for date %s — exiting", date_str)
            sys.exit(1)

        # Register Socket.IO events
        self._register_events()

    def _scan_available_dates(self) -> list[dict]:
        """Scan the parquet directory for dates that have trip data."""
        from collections import Counter
        counts: Counter[str] = Counter()
        for f in PARQUET_DIR.glob("????-??-??_trip_*.parquet"):
            counts[f.name[:10]] += 1
        return [{"date": d, "trips": c} for d, c in sorted(counts.items())]

    def _load_data(self, date_str: str) -> bool:
        """Load segments, ridership, weather, and parquets for a date.

        Returns True if at least one valid segment is ready.
        """
        log.info("Loading data for %s...", date_str)
        con = duckdb.connect(str(DUCKDB_PATH.resolve()), read_only=True)
        try:
            self.segments = load_segments(con, date_str)
            if not self.segments:
                log.warning("No segments found for date %s", date_str)
                self.valid_segments = []
                self.parquets = {}
                self.ridership = {}
                self.weather = {}
                return False
            log.info("  %d segments found", len(self.segments))

            seg_ids = [s["segment_id"] for s in self.segments]
            self.ridership = load_ridership(con, seg_ids)
            log.info("  Ridership data for %d segments", len(self.ridership))

            self.weather = load_weather(con, date_str)
            log.info("  Weather data for %d hours", len(self.weather))
        finally:
            con.close()

        # Pre-load trip parquets
        self.parquets: dict[str, pl.DataFrame] = {}
        for seg in self.segments:
            sid = seg["segment_id"]
            df = load_parquet(sid)
            if df is not None:
                self.parquets[sid] = df
                log.info("  Loaded %s: %d rows", sid, len(df))
            else:
                log.warning("  Missing parquet for %s — segment will be skipped", sid)

        # Filter segments to those with valid stations and parquet data
        self.valid_segments = [
            s for s in self.segments
            if s["segment_id"] in self.parquets
            and s["departure_station"] in STATION_BY_NAME
            and s["arrival_station"] in STATION_BY_NAME
        ]
        log.info("  %d valid segments (of %d total) ready for replay",
                 len(self.valid_segments), len(self.segments))

        # Reset replay state
        self._current_soc: float = 0.0
        self._current_station: str = ""
        self._current_weather_hour: int = -1
        self._current_passengers: int = 23

        return len(self.valid_segments) > 0

    def _get_replay_config(self) -> dict:
        """Build the replay_config payload."""
        return {
            "speed": self._replay_speed,
            "date": self.date_str,
            "test_mode": self.test_mode,
            "total_segments": len(self.valid_segments),
            "status": self._replay_status,
        }

    def _register_events(self) -> None:
        """Register Socket.IO event handlers."""

        @self.sio.event
        async def connect(sid: str, environ: dict) -> None:
            log.info("Client connected: %s", sid)
            # Send current replay config and available dates
            await self.sio.emit("replay_config", self._get_replay_config(), to=sid)
            await self.sio.emit("available_dates", {"dates": self._available_dates}, to=sid)

        @self.sio.event
        async def disconnect(sid: str) -> None:
            log.info("Client disconnected: %s", sid)

        @self.sio.on("speed_prediction_request")
        async def handle_speed_request(sid: str, data: dict) -> None:
            log.info("Speed prediction request from %s: %s -> %s",
                     sid, data.get("departure"), data.get("destination"))

            departure = data.get("departure", "")
            destination = data.get("destination", "")

            if departure not in STATION_BY_NAME or destination not in STATION_BY_NAME:
                log.warning("Invalid stations in speed request: %s -> %s", departure, destination)
                return

            hour = datetime.now().hour
            weather_now = get_weather_for_hour(self.weather, hour)
            dep_time = datetime.strptime(self.date_str, "%Y-%m-%d").replace(hour=hour)

            result = compute_speed_predictions(
                self.trip_predictor,
                departure, destination,
                self._current_soc if self._current_soc > 0 else 95.0,
                self._current_passengers,
                weather_now, dep_time,
            )
            await self.sio.emit("speed_prediction_result", result, to=sid)
            log.info("  -> Sent speed_prediction_result to %s", sid)

        @self.sio.on("set_replay_speed")
        async def handle_set_speed(sid: str, data: dict) -> None:
            speed = data.get("speed", 1.0)
            if speed in (1, 5, 10, 20):
                self._replay_speed = float(speed)
                log.info("Replay speed set to %dx by %s", int(speed), sid)
                await self.sio.emit("replay_config", self._get_replay_config())

        @self.sio.on("start_replay")
        async def handle_start_replay(sid: str, data: dict) -> None:
            if self._replay_status == "playing":
                log.info("Replay already playing, ignoring start request from %s", sid)
                return
            log.info("Replay start requested by %s", sid)
            self._replay_status = "playing"
            self._shutdown = False
            await self.sio.emit("replay_config", self._get_replay_config())
            self._replay_task = asyncio.create_task(self._replay_loop())

        @self.sio.on("get_available_dates")
        async def handle_get_dates(sid: str, data: dict) -> None:
            await self.sio.emit("available_dates", {"dates": self._available_dates}, to=sid)

        @self.sio.on("load_date")
        async def handle_load_date(sid: str, data: dict) -> None:
            date_str = data.get("date", "")
            if not date_str:
                return
            log.info("Date change requested by %s: %s -> %s", sid, self.date_str, date_str)

            # Stop current replay
            self._shutdown = True
            if hasattr(self, "_replay_task") and not self._replay_task.done():
                self._replay_task.cancel()
                try:
                    await self._replay_task
                except asyncio.CancelledError:
                    pass

            # Reload data for new date
            self.date_str = date_str
            self._shutdown = False
            self._load_data(date_str)
            self._replay_status = "waiting"
            await self.sio.emit("replay_config", self._get_replay_config())
            log.info("Date loaded: %s (%d segments) — waiting for start",
                     date_str, len(self.valid_segments))

    async def _emit(self, event: str, data: Any) -> None:
        """Emit an event to all connected clients."""
        await self.sio.emit(event, data)

    async def _replay_loop(self) -> None:
        """Main replay loop: iterate through segments and replay telemetry."""
        if not self.valid_segments:
            log.error("No valid segments to replay!")
            return

        log.info("=" * 60)
        log.info("Starting replay for %s (%d segments)", self.date_str, len(self.valid_segments))
        log.info("=" * 60)

        for seg_idx, seg in enumerate(self.valid_segments):
            if self._shutdown:
                break

            sid = seg["segment_id"]
            dep = seg["departure_station"]
            arr = seg["arrival_station"]
            direction = seg["direction"]
            dep_time: datetime = seg["departure_time"]
            arr_time: datetime = seg["arrival_time"]
            actual_last_soc = seg["last_soc"]
            passengers = self.ridership.get(sid, 23)
            self._current_passengers = passengers

            df = self.parquets[sid]
            first_row = df.row(0, named=True)
            current_soc = first_row["soc_percent"]
            self._current_soc = current_soc

            log.info("")
            log.info("-" * 50)
            log.info("Segment %d/%d: %s", seg_idx + 1, len(self.valid_segments), sid)
            log.info("  Route: %s -> %s (%s)", dep, arr, direction)
            log.info("  SOC: %.1f%% -> %.1f%% (actual)", seg["first_soc"], seg["last_soc"])
            log.info("  %d telemetry rows, %d passengers", len(df), passengers)
            log.info("-" * 50)

            # --- a) DOCKED phase ---
            self._current_station = dep
            weather_hour = dep_time.hour
            weather_now = get_weather_for_hour(self.weather, weather_hour)

            await self._emit("station_status", {
                "state": "DOCKED",
                "current_station": dep,
                "departure_station": dep,
                "next_station": arr,
                "direction": direction,
                "stations": STATIONS,
            })
            log.info("  [DOCKED] at %s", dep)

            # Auto-predictions (Model 1A) for all reachable destinations
            auto_preds = compute_auto_predictions(
                self.trip_predictor, dep, current_soc,
                passengers, weather_now, dep_time,
            )
            await self._emit("auto_prediction", auto_preds)
            log.info("  [AUTO_PREDICTION] %d destinations", len(auto_preds["predictions"]))

            # Passenger count
            await self._emit("passenger_count", {"count": passengers})

            # Weather + tide (tide is computed from harmonic model, no internet needed)
            tide = compute_tide_features(dep_time)
            await self._emit("weather_data", {
                "temperature_c": weather_now["temperature_c"],
                "wind_speed_kn": weather_now["wind_speed_kn"],
                "wind_direction_deg": weather_now["wind_direction_deg"],
                "humidity": weather_now["relative_humidity"],
                "precipitation_mm": weather_now["precipitation_mm"],
                "wave_height_m": weather_now["wave_height_m"],
                "weather_description": weather_description(weather_now["weather_code"]),
                "tide_height_m": round(tide["tide_height_m"], 2),
                "hours_since_high_tide": round(tide["hours_since_high_tide"], 1),
                "tide_phase": tide["tide_phase"],
            })
            self._current_weather_hour = weather_hour

            if self.dock_time > 0:
                await asyncio.sleep(self.dock_time / self._replay_speed)

            if self._shutdown:
                break

            # --- b) DEPARTING ---
            await self._emit("station_status", {
                "state": "DEPARTING",
                "current_station": dep,
                "departure_station": dep,
                "next_station": arr,
                "direction": direction,
                "stations": STATIONS,
            })
            log.info("  [DEPARTING] %s -> %s", dep, arr)

            # Initialize Model 1B
            self.rt_predictor.start_trip(
                departure_station=dep,
                arrival_station=arr,
                passengers=passengers,
                temperature_c=weather_now["temperature_c"],
                wind_speed_kn=weather_now["wind_speed_kn"],
                wind_direction_deg=weather_now["wind_direction_deg"],
                wave_height_m=weather_now["wave_height_m"],
                ocean_current_velocity_ms=weather_now["ocean_current_velocity_ms"],
                ocean_current_direction_deg=weather_now["ocean_current_direction_deg"],
                wave_direction_deg=weather_now["wave_direction_deg"],
                wave_period_s=weather_now["wave_period_s"],
            )

            # --- c) IN_TRANSIT (1Hz telemetry loop) ---
            num_rows = len(df)
            for row_idx in range(num_rows):
                if self._shutdown:
                    break

                row = df.row(row_idx, named=True)

                lat = row["latitude"]
                lon = row["longitude"]
                speed = row["speed_over_ground"]
                heading = row["heading"]
                soc = row["soc_percent"]
                motor_power = row["motor_power_combined"]
                port_power = row["port_motor_power"]
                stbd_power = row["stbd_motor_power"]
                battery_power = row["battery_power"]
                port_rpm = row["port_rpm"]
                stbd_rpm = row["stbd_rpm"]
                trip_nm = row["trip_nm"]
                ts = row["timestamp"]

                self._current_soc = soc

                # Ferry position
                await self._emit("ferry_position", {
                    "lat": round(lat, 6),
                    "lon": round(lon, 6),
                    "heading": round(heading, 1),
                    "speed": round(speed, 1),
                })

                # Vessel data
                await self._emit("vessel_data", {
                    "soc": round(soc),
                    "speed": round(speed, 1),
                    "vessel_state": "IN_TRANSIT",
                })

                # Motor anomaly detection (Model 2)
                motor_result = self.motor_detector.check({
                    "port_motor_power": port_power or 0.0,
                    "stbd_motor_power": stbd_power or 0.0,
                    "motor_power_combined": motor_power or 0.0,
                    "port_rpm": port_rpm or 0.0,
                    "stbd_rpm": stbd_rpm or 0.0,
                    "speed_over_ground": speed or 0.0,
                    "battery_power": battery_power or 0.0,
                })
                motor_health = "ANOMALY" if motor_result.get("level") == "anomalous" else "OK"
                await self._emit("anomaly_status", {
                    "motor_health": motor_health,
                    "battery_health": "OK",
                })

                # Realtime SOC prediction (Model 1B)
                telemetry_dict = {
                    "soc_percent": soc or 0.0,
                    "speed_over_ground": speed or 0.0,
                    "motor_power_combined": motor_power or 0.0,
                    "battery_power": battery_power or 0.0,
                    "heading": heading or 0.0,
                    "port_rpm": port_rpm or 0.0,
                    "stbd_rpm": stbd_rpm or 0.0,
                    "trip_nm": trip_nm or 0.0,
                }

                # Determine timestamp for tide computation
                tick_time = ts if isinstance(ts, datetime) else None

                rt_result = self.rt_predictor.update(telemetry_dict, current_time=tick_time)
                if rt_result is not None:
                    payload = {
                        "predicted_arrival_soc": rt_result["predicted_arrival_soc"],
                        "soc_remaining_delta": rt_result["soc_remaining_delta"],
                        "reachable_stations": rt_result["reachable_stations"],
                    }
                    if self.test_mode:
                        payload["actual_arrival_soc"] = actual_last_soc
                    await self._emit("realtime_prediction", payload)

                # Weather update on hour change
                if tick_time is not None:
                    tick_hour = tick_time.hour if isinstance(tick_time, datetime) else weather_hour
                else:
                    tick_hour = weather_hour

                if tick_hour != self._current_weather_hour:
                    weather_now = get_weather_for_hour(self.weather, tick_hour)
                    tide = compute_tide_features(tick_time)
                    await self._emit("weather_data", {
                        "temperature_c": weather_now["temperature_c"],
                        "wind_speed_kn": weather_now["wind_speed_kn"],
                        "wind_direction_deg": weather_now["wind_direction_deg"],
                        "humidity": weather_now["relative_humidity"],
                        "precipitation_mm": weather_now["precipitation_mm"],
                        "wave_height_m": weather_now["wave_height_m"],
                        "weather_description": weather_description(weather_now["weather_code"]),
                        "tide_height_m": round(tide["tide_height_m"], 2),
                        "hours_since_high_tide": round(tide["hours_since_high_tide"], 1),
                        "tide_phase": tide["tide_phase"],
                    })
                    self._current_weather_hour = tick_hour
                    log.info("  [WEATHER] Updated for hour %d (tide: %.2fm)", tick_hour, tide["tide_height_m"])

                # Log progress every 60 ticks
                if row_idx > 0 and row_idx % 60 == 0:
                    rt_info = ""
                    if rt_result is not None:
                        rt_info = f" | 1B pred: {rt_result['predicted_arrival_soc']:.1f}%"
                    log.info("  [TICK %d/%d] SOC=%.1f%% speed=%.1f kn motor=%s%s",
                             row_idx, num_rows, soc, speed, motor_health, rt_info)

                # 1Hz pacing (adjusted by replay speed)
                await asyncio.sleep(1.0 / self._replay_speed)

            # --- d) ARRIVING ---
            if not self._shutdown:
                await self._emit("station_status", {
                    "state": "ARRIVING",
                    "current_station": arr,
                    "departure_station": dep,
                    "next_station": arr,
                    "direction": direction,
                    "stations": STATIONS,
                })
                self._current_station = arr
                log.info("  [ARRIVING] at %s (SOC: %.1f%%)", arr, self._current_soc)

        # --- After last segment: stay DOCKED ---
        if not self._shutdown and self.valid_segments:
            final_station = self.valid_segments[-1]["arrival_station"]
            await self._emit("station_status", {
                "state": "DOCKED",
                "current_station": final_station,
                "departure_station": final_station,
                "next_station": final_station,
                "direction": self.valid_segments[-1]["direction"],
                "stations": STATIONS,
            })
            log.info("")
            log.info("=" * 60)
            log.info("Replay complete. Docked at %s (SOC: %.1f%%)",
                     final_station, self._current_soc)
            log.info("=" * 60)
            self._replay_status = "completed"
            await self.sio.emit("replay_config", self._get_replay_config())

    async def _on_startup(self, app: aiohttp.web.Application) -> None:
        """Server ready — waits for client to send start_replay."""
        log.info("Server ready — waiting for client to start replay...")

    async def _on_shutdown(self, app: aiohttp.web.Application) -> None:
        """Signal the replay loop to stop."""
        self._shutdown = True
        if hasattr(self, "_replay_task") and not self._replay_task.done():
            self._replay_task.cancel()
            try:
                await self._replay_task
            except asyncio.CancelledError:
                pass
        log.info("Server shut down.")

    def run(self, port: int = 5000) -> None:
        """Start the aiohttp+Socket.IO server."""
        self.app.on_startup.append(self._on_startup)
        self.app.on_shutdown.append(self._on_shutdown)

        log.info("Starting replay server on http://0.0.0.0:%d", port)
        log.info("  Date: %s", self.date_str)
        log.info("  Dock time: %.1fs", self.dock_time)
        log.info("  Test mode: %s", self.test_mode)

        aiohttp.web.run_app(
            self.app,
            host="0.0.0.0",
            port=port,
            print=None,  # suppress aiohttp's default print
        )


# ===================================================================
# CLI entry point
# ===================================================================

def main() -> None:
    parser = argparse.ArgumentParser(
        description="M/B Dalaray Dashboard replay server — streams historical trip data via Socket.IO",
    )
    parser.add_argument(
        "--date", required=True,
        help="Date to replay (YYYY-MM-DD), e.g. 2026-03-02",
    )
    parser.add_argument(
        "--dock-time", type=float, default=5.0,
        help="Seconds to pause at each station in DOCKED state (default: 5)",
    )
    parser.add_argument(
        "--test-mode", action="store_true",
        help="Enable test mode: include actual_arrival_soc in realtime_prediction events",
    )
    parser.add_argument(
        "--port", type=int, default=5000,
        help="Port to run the server on (default: 5000)",
    )

    args = parser.parse_args()

    # Validate date format
    try:
        datetime.strptime(args.date, "%Y-%m-%d")
    except ValueError:
        parser.error(f"Invalid date format: {args.date}. Use YYYY-MM-DD.")

    # Validate paths
    if not DUCKDB_PATH.exists():
        log.error("DuckDB not found at %s", DUCKDB_PATH.resolve())
        sys.exit(1)
    if not MODELS_DIR.exists():
        log.error("Models directory not found at %s", MODELS_DIR.resolve())
        sys.exit(1)
    if not CONFIG_DIR.exists():
        log.error("Config directory not found at %s", CONFIG_DIR.resolve())
        sys.exit(1)

    server = ReplayServer(
        date_str=args.date,
        dock_time=args.dock_time,
        test_mode=args.test_mode,
    )
    server.run(port=args.port)


if __name__ == "__main__":
    main()
