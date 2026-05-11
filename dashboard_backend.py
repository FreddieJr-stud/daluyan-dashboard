"""Production Socket.IO backend for the M/B Dalaray Flutter Dashboard.

Runs on the RPi5 aboard the ferry, connecting to live vessel telemetry,
BMS data, MQTT passenger sensors, and weather APIs.  Runs 5 ML models
in real-time and serves the Flutter web dashboard via Socket.IO.

Usage (on RPi5):
    python dashboard_backend.py --auto-discover
    python dashboard_backend.py --vessel-host CONFIGURE_MINIPC_HOST --port 5000

Desktop testing:
    python dashboard_backend.py --vessel-host localhost --vessel-port 8481
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import math
import os
import sys
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import socket
import struct

import aiohttp
import aiohttp.web
import socketio

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------


@dataclass
class Config:
    vessel_host: str = "CONFIGURE_VESSEL_HOST"
    vessel_port: int = 8481
    mqtt_host: str = "localhost"
    mqtt_port: int = 1883
    server_port: int = 5000
    bundle_dir: str = str(Path(__file__).resolve().parent.parent / "Ferry_Digital_Shadow" / "Models" / "rpi5_bundle")
    auto_discover: bool = False


# ---------------------------------------------------------------------------
# Vessel API auto-discovery
# ---------------------------------------------------------------------------

def _get_local_subnets() -> list[tuple[str, str]]:
    """Return list of (network_prefix, local_ip) for all active IPv4 interfaces."""
    subnets = []
    try:
        # Use UDP socket trick to find interfaces with routes
        for iface_ip in _get_interface_ips():
            # Assume /24 for discovery (covers typical ferry router setups)
            parts = iface_ip.rsplit(".", 1)
            if len(parts) == 2:
                subnets.append((parts[0], iface_ip))
    except Exception as e:
        log.warning("Subnet detection failed: %s", e)
    return subnets


def _get_interface_ips() -> list[str]:
    """Get all local IPv4 addresses (non-loopback)."""
    ips = []
    try:
        import netifaces
        for iface in netifaces.interfaces():
            addrs = netifaces.ifaddresses(iface).get(netifaces.AF_INET, [])
            for addr in addrs:
                ip = addr.get("addr", "")
                if ip and not ip.startswith("127."):
                    ips.append(ip)
    except ImportError:
        # Fallback: connect UDP sockets to known subnets to discover local IPs
        for test_target in ["10.0.161.1", "192.168.0.1", "192.168.1.1"]:
            try:
                s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                try:
                    s.settimeout(0.1)
                    s.connect((test_target, 80))
                    ip = s.getsockname()[0]
                    if ip not in ips and not ip.startswith("127."):
                        ips.append(ip)
                finally:
                    s.close()
            except Exception:
                pass
    return ips


def discover_vessel_api(port: int = 8481, timeout: float = 0.3,
                        known_hosts: list[str] | None = None) -> str | None:
    """Scan local subnets for a host with `port` open. Returns IP or None.

    Checks known_hosts first (fast path), then scans all /24 subnets.
    """
    # Fast path: try known/likely hosts first
    candidates = list(known_hosts or [])
    # Add known IPs from ferry network topology
    # CONFIGURE_MINIPC_HOST  = Mini PC on TP-Link / UPD Ferry router (Ethernet)
    # CONFIGURE_HOTSPOT_GATEWAY  = Mini PC mobile hotspot gateway
    # CONFIGURE_VESSEL_HOST    = e-boat controller (direct, requires port proxy)
    for ip in ["CONFIGURE_MINIPC_HOST", "CONFIGURE_HOTSPOT_GATEWAY", "CONFIGURE_VESSEL_HOST"]:
        if ip not in candidates:
            candidates.append(ip)

    for ip in candidates:
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            try:
                s.settimeout(timeout)
                if s.connect_ex((ip, port)) == 0:
                    log.info("Auto-discovery: found vessel API at %s:%d (fast path)", ip, port)
                    return ip
            finally:
                s.close()
        except Exception:
            pass

    # Slow path: scan all local subnets
    subnets = _get_local_subnets()
    log.info("Auto-discovery: scanning %d subnet(s) for port %d...", len(subnets), port)

    for prefix, local_ip in subnets:
        for i in range(1, 255):
            ip = f"{prefix}.{i}"
            if ip == local_ip:
                continue
            try:
                s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                try:
                    s.settimeout(timeout)
                    if s.connect_ex((ip, port)) == 0:
                        log.info("Auto-discovery: found vessel API at %s:%d", ip, port)
                        return ip
                finally:
                    s.close()
            except Exception:
                pass

    log.warning("Auto-discovery: no vessel API found on port %d", port)
    return None


# ---------------------------------------------------------------------------
# Station registry (canonical order, GPS, cumulative km)
# ---------------------------------------------------------------------------
STATIONS = [
    {"name": "Napindan",   "order": 0, "lat": 14.55713,   "lon": 121.06836,   "km": 0.0},
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
# Flutter UI sometimes sends "Sta. Ana" with period
STATION_ALIAS = {"Sta. Ana": "Sta Ana"}

# Stations where passengers board/alight — sensors wake only at these.
# Closed/broken stations (Valenzuela, Sta Ana) and the docking terminal
# (Napindan) are excluded so sensors stay asleep there.
OPEN_STATIONS: set[str] = {
    "Guadalupe", "Hulo", "Lambingan", "PUP", "Quinta", "Escolta",
}

# WMO weather code descriptions
WMO_DESCRIPTIONS = {
    0: "Clear Sky", 1: "Mainly Clear", 2: "Partly Cloudy", 3: "Overcast",
    45: "Foggy", 48: "Foggy",
    51: "Drizzle", 53: "Drizzle", 55: "Drizzle",
    61: "Rain", 63: "Rain", 65: "Rain",
    80: "Showers", 81: "Showers", 82: "Showers",
    95: "Thunderstorm", 96: "Thunderstorm", 99: "Thunderstorm",
}

# Constants
NOMINAL_HV_CAPACITY = 160.0
GEOFENCE_RADIUS_M = 200
SPEED_MOVING_KN = 2.0
SPEED_STOPPED_KN = 1.0
STOPPED_DWELL_S = 3.0
SENSOR_WAKE_DISTANCE_M = 100  # wake passenger-counter sensors within 100 m of station

# Pasig River midpoint for weather API queries
WEATHER_LAT = 14.58
WEATHER_LON = 121.02

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("dashboard")

# Separate file logger for passenger events (timeline for debugging)
_pax_logger = logging.getLogger("passenger_events")
_pax_logger.setLevel(logging.INFO)
_pax_logger.propagate = False  # don't duplicate into main log
_pax_fh = logging.FileHandler("passenger_events.log")
_pax_fh.setFormatter(logging.Formatter(
    "%(asctime)s  %(message)s", datefmt="%Y-%m-%d %H:%M:%S"))
_pax_logger.addHandler(_pax_fh)


# ===================================================================
# Geo helpers
# ===================================================================


def _haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Haversine distance in metres."""
    R = 6_371_000
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlam = math.radians(lon2 - lon1)
    a = (math.sin(dphi / 2) ** 2
         + math.cos(phi1) * math.cos(phi2) * math.sin(dlam / 2) ** 2)
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def _nearest_station(lat: float, lon: float) -> tuple[dict, float]:
    """Return (station_dict, distance_m) for the closest station."""
    best, best_d = STATIONS[0], float("inf")
    for s in STATIONS:
        d = _haversine_m(lat, lon, s["lat"], s["lon"])
        if d < best_d:
            best, best_d = s, d
    return best, best_d


def _in_geofence(lat: float, lon: float) -> tuple[str, float]:
    """Return (station_name, distance_m) if within geofence, else ("", dist)."""
    stn, dist = _nearest_station(lat, lon)
    if dist <= GEOFENCE_RADIUS_M:
        return stn["name"], dist
    return "", dist


def _bearing(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Initial bearing from point 1 to point 2 in degrees [0, 360)."""
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dlam = math.radians(lon2 - lon1)
    x = math.sin(dlam) * math.cos(phi2)
    y = (math.cos(phi1) * math.sin(phi2)
         - math.sin(phi1) * math.cos(phi2) * math.cos(dlam))
    return (math.degrees(math.atan2(x, y)) + 360) % 360


def _heading_diff(h1: float, h2: float) -> float:
    """Absolute angular difference in [0, 180]."""
    d = abs(h1 - h2) % 360
    return d if d <= 180 else 360 - d


def _determine_direction(
    heading: float, lat: float, lon: float,
) -> tuple[str, str | None]:
    """Determine travel direction and next station from heading."""
    stn, _ = _nearest_station(lat, lon)
    order = stn["order"]

    candidates: list[tuple[str, str, float]] = []
    # Upstream candidate (lower order — toward Napindan), skip closed stations
    i = order - 1
    while i >= 0 and STATIONS[i]["name"] not in OPEN_STATIONS:
        i -= 1
    if i >= 0:
        up = STATIONS[i]
        brg = _bearing(lat, lon, up["lat"], up["lon"])
        candidates.append(("upstream", up["name"], _heading_diff(heading, brg)))
    # Downstream candidate (higher order — toward Escolta), skip closed stations
    j = order + 1
    while j < len(STATIONS) and STATIONS[j]["name"] not in OPEN_STATIONS:
        j += 1
    if j < len(STATIONS):
        down = STATIONS[j]
        brg = _bearing(lat, lon, down["lat"], down["lon"])
        candidates.append(("downstream", down["name"], _heading_diff(heading, brg)))

    if not candidates:
        return "downstream", None

    best = min(candidates, key=lambda c: c[2])
    return best[0], best[1]


def _resolve_station(name: str) -> str:
    """Resolve station aliases (e.g. 'Sta. Ana' -> 'Sta Ana')."""
    return STATION_ALIAS.get(name, name)


# ===================================================================
# ETA Estimator
# ===================================================================


class ETAEstimator:
    """Estimates arrival times using historical baselines adjusted by real-time conditions.

    On each telemetry tick during IN_TRANSIT, computes ETA to every reachable
    station by adjusting historical segment travel times with a speed ratio
    (current vs. historical) and tide factor.  Output is smoothed to avoid
    flickering — only emitted when any station's ETA changes by > 30 s.
    """

    # Tide adjustment multipliers: (phase, direction) -> multiplier
    _TIDE_FACTORS: dict[tuple[str, str], float] = {
        ("rising", "upstream"): 0.9,
        ("rising", "downstream"): 1.1,
        ("falling", "upstream"): 1.1,
        ("falling", "downstream"): 0.9,
    }

    _DEFAULT_SPEED_KN = 6.0
    _DEFAULT_DWELL_S = 120.0
    _SPEED_RATIO_MIN = 0.3
    _SPEED_RATIO_MAX = 3.0
    _SMOOTHING_THRESHOLD_S = 30

    # Open stations + Napindan terminal, in downstream order
    _ROUTE_STATIONS = [
        "Napindan", "Guadalupe", "Hulo", "Lambingan",
        "PUP", "Quinta", "Escolta",
    ]

    def __init__(self, config_dir: str) -> None:
        self._segment_baselines: dict[str, dict] = {}
        self._dwell_baselines: dict[str, dict] = {}
        self._last_emitted: dict[str, float] = {}
        self._last_payload: dict[str, Any] | None = None
        self._load_baselines(config_dir)

    def _load_baselines(self, config_dir: str) -> None:
        path = Path(config_dir) / "eta_baselines.json"
        if not path.exists():
            log.warning("ETA baselines not found at %s — using fallbacks", path)
            return
        try:
            data = json.loads(path.read_text())
            self._segment_baselines = data.get("segment_baselines", {})
            self._dwell_baselines = data.get("dwell_baselines", {})
            log.info("ETA baselines loaded: %d segments, %d dwell entries",
                     len(self._segment_baselines), len(self._dwell_baselines))
        except Exception as e:
            log.warning("Failed to load ETA baselines: %s", e)

    def _segment_time(self, dep: str, arr: str, direction: str) -> tuple[float, float]:
        """Return (baseline_time_s, avg_speed_kn) for a segment pair."""
        baseline = self._segment_baselines.get(f"{dep}|{arr}|{direction}")
        if baseline:
            return baseline["time_s"], baseline["avg_speed_kn"]
        # Fallback: distance / default speed
        km_dep = STATION_BY_NAME.get(dep, {}).get("km", 0)
        km_arr = STATION_BY_NAME.get(arr, {}).get("km", 0)
        dist_km = abs(km_arr - km_dep) or 1.0
        dist_nm = dist_km / 1.852
        time_s = (dist_nm / self._DEFAULT_SPEED_KN) * 3600
        return time_s, self._DEFAULT_SPEED_KN

    def _dwell_time(self, station: str, direction: str) -> float:
        """Return expected dwell time in seconds at a station."""
        if station not in OPEN_STATIONS:
            return 0.0
        baseline = self._dwell_baselines.get(f"{station}|{direction}")
        return baseline["dwell_s"] if baseline else self._DEFAULT_DWELL_S

    def _tide_factor(self, tide_phase: str, direction: str) -> float:
        return self._TIDE_FACTORS.get((tide_phase, direction), 1.0)

    def update(
        self,
        lat: float,
        lon: float,
        speed: float,
        nav_state: str,
        direction: str | None,
        next_station: str | None,
        departure_station: str | None,
        tide_phase: str,
    ) -> dict[str, Any] | None:
        """Compute ETAs. Returns payload dict if changed, else None."""
        # --- Not in transit: reset if needed ---
        if nav_state != "IN_TRANSIT" or not next_station or not direction:
            if self._last_payload is not None:
                self._last_emitted.clear()
                self._last_payload = None
                return {
                    "next_station": None,
                    "next_station_eta_s": None,
                    "next_station_eta_min": None,
                    "all_stations": {},
                    "direction": direction or "",
                    "timestamp": datetime.now().isoformat(),
                }
            return None

        next_stn = STATION_BY_NAME.get(next_station)
        if not next_stn:
            return None

        # --- Current segment: remaining distance & time ---
        remaining_m = _haversine_m(lat, lon, next_stn["lat"], next_stn["lon"])
        remaining_km = remaining_m / 1000.0

        dep_stn = STATION_BY_NAME.get(departure_station or "")
        total_km = abs(next_stn["km"] - dep_stn["km"]) if dep_stn else remaining_km
        total_km = max(total_km, 0.01)  # avoid division by zero

        baseline_s, baseline_speed = self._segment_time(
            departure_station or "", next_station, direction,
        )

        # Speed ratio: current speed vs historical average
        if speed > 0.5:
            ratio = speed / baseline_speed
            ratio = max(self._SPEED_RATIO_MIN, min(ratio, self._SPEED_RATIO_MAX))
        else:
            ratio = 1.0  # stopped — use baseline as-is

        remaining_frac = min(remaining_km / total_km, 1.0)
        tide = self._tide_factor(tide_phase, direction)

        current_seg_s = baseline_s * remaining_frac * (1.0 / ratio) * tide

        # --- Multi-hop ETAs ---
        all_etas: dict[str, float] = {}
        cumulative = current_seg_s
        all_etas[next_station] = cumulative

        # Stations beyond next_station in travel direction
        if direction == "downstream":
            beyond = [s for s in self._ROUTE_STATIONS
                      if STATION_BY_NAME.get(s, {}).get("order", -1) > next_stn["order"]]
        else:
            beyond = [s for s in reversed(self._ROUTE_STATIONS)
                      if STATION_BY_NAME.get(s, {}).get("order", 99) < next_stn["order"]]

        prev = next_station
        for stn_name in beyond:
            cumulative += self._dwell_time(prev, direction)
            seg_s, _ = self._segment_time(prev, stn_name, direction)
            cumulative += seg_s * (1.0 / ratio) * tide
            all_etas[stn_name] = cumulative
            prev = stn_name

        # --- Smoothing ---
        changed = set(all_etas.keys()) != set(self._last_emitted.keys())
        if not changed:
            for stn, eta_s in all_etas.items():
                if abs(eta_s - self._last_emitted.get(stn, 0)) > self._SMOOTHING_THRESHOLD_S:
                    changed = True
                    break

        if not changed:
            return None

        self._last_emitted = dict(all_etas)

        payload: dict[str, Any] = {
            "next_station": next_station,
            "next_station_eta_s": round(all_etas[next_station]),
            "next_station_eta_min": round(all_etas[next_station] / 60, 1),
            "all_stations": {
                stn: {"eta_s": round(s), "eta_min": round(s / 60, 1)}
                for stn, s in all_etas.items()
            },
            "direction": direction,
            "timestamp": datetime.now().isoformat(),
        }
        self._last_payload = payload
        return payload

    def get_context_lines(self) -> list[str]:
        """Return lines for _build_dashboard_context LLM injection."""
        if not self._last_payload or not self._last_payload.get("next_station"):
            return []
        lines = ["ETA estimates:"]
        for stn, info in self._last_payload["all_stations"].items():
            lines.append(f"  ETA to {stn}: ~{info['eta_min']} minutes")
        return lines

    def get_payload(self) -> dict[str, Any] | None:
        """Return latest payload for Socket.IO emission / connect snapshot."""
        return self._last_payload


# ===================================================================
# Default weather dicts
# ===================================================================

WEATHER_CACHE_FILE = Path(__file__).resolve().parent / "weather_cache.json"


def _default_weather_raw() -> dict[str, Any]:
    return {
        "temperature_c": 28.0, "relative_humidity": 75.0,
        "wind_speed_kn": 5.0, "wind_direction_deg": 180.0,
        "precipitation_mm": 0.0, "wave_height_m": 0.1,
        "wave_direction_deg": 0.0, "wave_period_s": 0.0,
        "ocean_current_velocity_ms": 0.0, "ocean_current_direction_deg": 0.0,
        "weather_code": 0,
    }


def _default_weather_display() -> dict[str, Any]:
    return {
        "temperature_c": 28.0, "wind_speed_kn": 5.0,
        "wind_direction_deg": 180.0, "humidity": 75.0,
        "precipitation_mm": 0.0, "wave_height_m": 0.1,
        "weather_description": "Unknown",
        "tide_height_m": 0.0, "hours_since_high_tide": 0.0,
        "tide_phase": "unknown",
    }


# ===================================================================
# Dashboard Server
# ===================================================================


@aiohttp.web.middleware
async def _cors_middleware(request, handler):
    """Add CORS headers to ALL responses, including errors."""
    if request.method == "OPTIONS":
        return aiohttp.web.Response(headers={
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
            "Access-Control-Allow-Headers": "Content-Type",
        })
    try:
        response = await handler(request)
    except aiohttp.web.HTTPException as ex:
        ex.headers["Access-Control-Allow-Origin"] = "*"
        raise
    except Exception as e:
        import traceback
        log.warning("Unhandled error in %s %s: %s\n%s",
                     request.method, request.path, e, traceback.format_exc())
        return aiohttp.web.json_response(
            {"error": str(e)},
            status=500,
            headers={"Access-Control-Allow-Origin": "*"},
        )
    response.headers["Access-Control-Allow-Origin"] = "*"
    return response


class DashboardServer:
    """Production dashboard: live telemetry -> ML models -> Socket.IO."""

    def __init__(self, config: Config) -> None:
        self.config = config

        # Socket.IO + aiohttp
        self.sio = socketio.AsyncServer(
            async_mode="aiohttp",
            cors_allowed_origins="*",
            logger=False,
            engineio_logger=False,
        )
        self.app = aiohttp.web.Application(middlewares=[_cors_middleware])
        self.sio.attach(self.app)

        # --- HTTP routes (with CORS for web/Chrome browser) ---
        self.app.router.add_get('/health', self._handle_health)
        self.app.router.add_post('/tts', self._handle_tts)
        self.app.router.add_post('/chat', self._handle_chat)
        self.app.router.add_route('OPTIONS', '/tts', self._handle_cors_preflight)
        self.app.router.add_route('OPTIONS', '/chat', self._handle_cors_preflight)

        # --- Gemini LLM client (lazy init) ---
        self._gemini_client = None
        self._gemini_model = "gemini-3.1-flash-lite-preview"

        # --- Load ML models (graceful fallback) ---
        self._load_models()

        # --- ETA estimator ---
        _config_dir = str(Path(self.config.bundle_dir).resolve() / "config")
        self._eta = ETAEstimator(_config_dir)

        # --- Instance state ---
        self._vessel_data: dict[str, Any] = {}
        self._bms_telemetry: dict[str, float] = {}
        self._weather_raw: dict[str, Any] = _default_weather_raw()
        self._weather_state: dict[str, Any] = _default_weather_display()
        self._anomaly_state: dict[str, Any] = {
            "motor_health": "OK",
            "battery_health": "OK",
            "motor_score": None,
            "motor_threshold": None,
            "battery_score": None,
            "battery_threshold": None,
        }
        self._passenger_count: int = 0
        self._trip_active: bool = False
        self._trip_primed: bool = False  # True after start_trip() called from segment metadata
        self._current_soc: float = 0.0
        self._last_auto_pred_soc: float = 0.0  # SOC when auto-predictions were last computed
        self._current_speed: float = 0.0
        self._hv_capacity: float = NOMINAL_HV_CAPACITY

        # Navigation state machine
        self._nav: dict[str, Any] = {
            "state": "UNKNOWN",
            "current_station": None,
            "departure_station": None,
            "next_station": None,
            "direction": None,
            "visited_other": False,
            "stopped_since": None,
        }

        # Sensor sleep/wake control
        self._sensors_sleeping: bool = False
        self._mqtt_client = None  # set in _mqtt_loop for publishing commands

        # Sensor health tracking — last heard timestamp per door
        self._sensor_last_seen: dict[str, float] = {
            "left": 0.0, "right": 0.0, "back": 0.0,
        }
        self._sensor_health_interval = 30.0  # check every 30s
        self._sensor_timeout = 60.0  # consider offline after 60s of silence

        # Async resources (set on startup)
        self._session: aiohttp.ClientSession | None = None
        self._tasks: list[asyncio.Task] = []

        # Register Socket.IO event handlers
        self._register_events()

    # ---------------------------------------------------------------
    # Model loading
    # ---------------------------------------------------------------

    def _load_models(self) -> None:
        bundle = Path(self.config.bundle_dir).resolve()
        models_dir = str(bundle / "models")
        config_dir = str(bundle / "config")

        bundle_str = str(bundle)
        if bundle_str not in sys.path:
            sys.path.insert(0, bundle_str)

        log.info("Loading ML models from %s ...", bundle)

        self.trip_predictor = None
        self.rt_predictor = None
        self.motor_detector = None
        self.battery_detector = None
        self._tide_fn = None

        try:
            from inference.inference_soc_trip import SOCTripPredictor
            self.trip_predictor = SOCTripPredictor(models_dir, config_dir)
            log.info("  Model 1A (trip SOC): %d ensemble members",
                     len(self.trip_predictor.models))
        except Exception as e:
            log.warning("  Model 1A failed to load: %s", e)

        try:
            from inference.inference_soc_realtime import SOCRealtimePredictor
            self.rt_predictor = SOCRealtimePredictor(
                models_dir, models_dir, config_dir,
            )
            log.info("  Model 1B (realtime SOC): %d ensemble members",
                     len(self.rt_predictor.rt_models))
        except Exception as e:
            log.warning("  Model 1B failed to load: %s", e)

        try:
            from inference.inference_anomaly import MotorAnomalyDetector
            self.motor_detector = MotorAnomalyDetector(config_dir, models_dir)
            log.info("  Model 2 (motor anomaly): %d reconstruction models",
                     len(self.motor_detector.models))
        except Exception as e:
            log.warning("  Model 2 failed to load: %s", e)

        try:
            from inference.inference_battery import BatteryAnomalyDetector
            self.battery_detector = BatteryAnomalyDetector(config_dir, models_dir)
            log.info("  Models 3a/3b (battery): modes=%s",
                     self.battery_detector.available_modes)
        except Exception as e:
            log.warning("  Models 3a/3b failed to load: %s", e)

        # Charging estimator
        try:
            from inference.charging_estimator import ChargingEstimator
            curve_path = Path(self.config.bundle_dir).resolve() / "charging_curve.json"
            if curve_path.exists():
                self._charging_estimator = ChargingEstimator(str(curve_path))
                log.info("  Charging estimator: loaded (%d bins)",
                         len(self._charging_estimator._bins))
            else:
                self._charging_estimator = None
                log.warning("  charging_curve.json not found — charging estimates disabled")
        except Exception as e:
            self._charging_estimator = None
            log.warning("  Charging estimator failed to load: %s", e)
        self._charging_target_soc: float = 80.0

        try:
            from inference.features.tide import compute_tide_features
            self._tide_fn = compute_tide_features
            log.info("  Tide harmonic model: loaded")
        except Exception as e:
            log.warning("  Tide model failed to load: %s", e)

    # ---------------------------------------------------------------
    # Emit helper
    # ---------------------------------------------------------------

    async def _emit(self, event: str, data: Any) -> None:
        await self.sio.emit(event, data)

    async def _emit_charging_status(self) -> None:
        """Detect charging state and emit charging_status event."""
        bms = self._bms_telemetry
        if not bms or self._charging_estimator is None:
            return

        # Use combined power from both sides
        port_power = abs(bms.get("port_power", 0.0))
        stbd_power = abs(bms.get("stbd_power", 0.0))
        charger_power = port_power + stbd_power
        soc = (bms.get("port_soc", 0.0) + bms.get("stbd_soc", 0.0)) / 2.0
        is_charging = (charger_power > 10.0
                       and self._nav["state"] == "DOCKED")

        if not is_charging:
            await self._emit("charging_status", {"is_charging": False})
            return

        est_to_full = self._charging_estimator.estimate_to_full(soc)
        est_to_target = self._charging_estimator.estimate_to_target(
            soc, self._charging_target_soc)

        await self._emit("charging_status", {
            "is_charging": True,
            "charging_power_kw": round(charger_power, 1),
            "soc_percent": round(soc, 1),
            "est_minutes_to_full": est_to_full,
            "est_minutes_to_target": est_to_target,
            "charging_target_soc": self._charging_target_soc,
        })

    # ---------------------------------------------------------------
    # HTTP Endpoints
    # ---------------------------------------------------------------

    _CORS_HEADERS = {
        "Access-Control-Allow-Origin": "*",
        "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
        "Access-Control-Allow-Headers": "Content-Type",
    }

    async def _handle_health(self, request: aiohttp.web.Request) -> aiohttp.web.Response:
        """Simple health check for Flutter connectivity probes."""
        return aiohttp.web.json_response(
            {"status": "ok"},
            headers=self._CORS_HEADERS,
        )

    async def _handle_cors_preflight(self, request: aiohttp.web.Request) -> aiohttp.web.Response:
        """Handle CORS preflight OPTIONS request."""
        return aiohttp.web.Response(headers=self._CORS_HEADERS)

    @staticmethod
    def _numbers_to_english(text: str) -> str:
        """Replace numeric digits with English words so Filipino voices
        pronounce them in English (natural Taglish code-switching).

        Edge-tts XML-escapes all input and wraps it in its own SSML, so we
        cannot inject <lang> or <say-as> tags.  fil-PH-BlessicaNeural is not
        a multilingual voice, so <lang xml:lang="en-US"> would be ignored even
        if we could inject it.  The only reliable approach is to spell out
        numbers as English words -- Blessica pronounces English words naturally.
        """
        import re

        # --- Lightweight number-to-words (English, 0-9999 + decimals) ---
        _ones = [
            '', 'one', 'two', 'three', 'four', 'five', 'six', 'seven',
            'eight', 'nine', 'ten', 'eleven', 'twelve', 'thirteen',
            'fourteen', 'fifteen', 'sixteen', 'seventeen', 'eighteen', 'nineteen',
        ]
        _tens = [
            '', '', 'twenty', 'thirty', 'forty', 'fifty',
            'sixty', 'seventy', 'eighty', 'ninety',
        ]

        def _int_to_words(n: int) -> str:
            if n < 0:
                return 'negative ' + _int_to_words(-n)
            if n == 0:
                return 'zero'
            if n < 20:
                return _ones[n]
            if n < 100:
                w = _tens[n // 10]
                r = n % 10
                return f'{w}-{_ones[r]}' if r else w
            if n < 1000:
                w = _ones[n // 100] + ' hundred'
                r = n % 100
                return f'{w} {_int_to_words(r)}' if r else w
            if n < 10000:
                w = _int_to_words(n // 1000) + ' thousand'
                r = n % 1000
                return f'{w} {_int_to_words(r)}' if r else w
            # For very large numbers, fall back to digit-by-digit
            return ' '.join(_ones[int(d)] if d != '0' else 'zero' for d in str(n))

        def _number_to_words(m: re.Match) -> str:
            token = m.group(0)
            has_percent = token.endswith('%')
            num_str = token.rstrip('%')

            # Time-like pattern (e.g. 10:30) -- leave as-is
            if ':' in num_str:
                return token

            try:
                if '.' in num_str:
                    int_part, dec_part = num_str.split('.', 1)
                    int_w = _int_to_words(int(int_part)) if int_part else 'zero'
                    dec_w = ' '.join(
                        _ones[int(d)] if d != '0' else 'zero' for d in dec_part
                    )
                    words = f'{int_w} point {dec_w}'
                else:
                    words = _int_to_words(int(num_str))
            except (ValueError, IndexError):
                return token  # leave unparseable numbers alone

            if has_percent:
                words += ' percent'
            return words

        # Match integers, decimals, percentages (e.g. 97, 3.5, 80%, 1000)
        return re.sub(r'\d+\.?\d*%?', _number_to_words, text)

    # Phonetic respellings so Blessica pronounces words the Filipino way
    _PRONUNCIATION_MAP: dict[str, str] = {
        "Guadalupe": "Guadalupeh",
    }

    @classmethod
    def _fix_pronunciation(cls, text: str) -> str:
        """Apply phonetic respellings for words Blessica mispronounces."""
        import re
        for word, phonetic in cls._PRONUNCIATION_MAP.items():
            text = re.sub(re.escape(word), phonetic, text, flags=re.IGNORECASE)
        return text

    async def _handle_tts(self, request: aiohttp.web.Request) -> aiohttp.web.Response:
        """Text-to-speech via Microsoft Edge TTS (natural neural voices)."""
        try:
            data = await request.json()
        except Exception:
            return aiohttp.web.json_response(
                {"error": "Invalid JSON"}, status=400, headers=self._CORS_HEADERS,
            )

        text = data.get("text", "")
        voice = data.get("voice", "fil-PH-BlessicaNeural")

        if not text:
            return aiohttp.web.json_response(
                {"error": "No text"}, status=400, headers=self._CORS_HEADERS,
            )

        try:
            import edge_tts
            processed_text = self._fix_pronunciation(self._numbers_to_english(text))
            communicate = edge_tts.Communicate(processed_text, voice)
            audio_chunks: list[bytes] = []
            async for chunk in communicate.stream():
                if chunk["type"] == "audio":
                    audio_chunks.append(chunk["data"])

            audio_bytes = b"".join(audio_chunks)
            return aiohttp.web.Response(
                body=audio_bytes,
                content_type="audio/mpeg",
                headers={
                    "Content-Length": str(len(audio_bytes)),
                    **self._CORS_HEADERS,
                },
            )
        except ImportError:
            return aiohttp.web.json_response(
                {"error": "edge-tts not installed. Run: pip install edge-tts"},
                status=503,
                headers=self._CORS_HEADERS,
            )
        except Exception as e:
            log.warning("Edge TTS failed: %s", e)
            return aiohttp.web.json_response(
                {"error": str(e)}, status=500, headers=self._CORS_HEADERS,
            )

    def _get_gemini_client(self):
        """Lazy-init Gemini client. Loads key from env or local_keys.env."""
        if self._gemini_client is None:
            api_key = os.environ.get("GEMINI_API_KEY", "")

            # Fall back to local_keys.env if not in environment
            if not api_key:
                env_file = Path(__file__).resolve().parent / "flutter_application_1" / "local_keys.env"
                if env_file.exists():
                    for line in env_file.read_text().splitlines():
                        if line.startswith("GEMINI_API_KEY="):
                            api_key = line.split("=", 1)[1].strip()
                            break

            if not api_key:
                log.warning("No GEMINI_API_KEY found in env or local_keys.env")
                return None
            try:
                from google import genai
                self._gemini_client = genai.Client(api_key=api_key)
                log.info("Gemini client initialized (model: %s)", self._gemini_model)
            except ImportError:
                log.warning("google-genai not installed. Run: pip install google-genai")
                return None
        return self._gemini_client

    def _build_dashboard_context(self) -> str:
        """Build a text summary of current dashboard state for the LLM."""
        nav = self._nav
        weather = self._weather_state
        anomaly = self._anomaly_state
        soc = self._current_soc
        speed = self._current_speed
        passengers = self._passenger_count

        lines = [
            f"Battery SOC: {soc:.1f}%",
            f"Speed: {speed:.1f} knots",
            f"Passengers on board: {passengers}",
            f"Navigation state: {nav.get('state', 'UNKNOWN')}",
            f"Current station: {nav.get('current_station', 'unknown')}",
            f"Departure: {nav.get('departure_station', 'unknown')}",
            f"Next station: {nav.get('next_station', 'unknown')}",
            f"Direction: {nav.get('direction', 'unknown')}",
            f"Motor health: {anomaly.get('motor_health', 'OK')}",
            f"Battery health: {anomaly.get('battery_health', 'OK')}",
        ]
        if anomaly.get("motor_score") is not None:
            lines.append(f"Motor anomaly score: {anomaly['motor_score']:.3f} (threshold: {anomaly.get('motor_threshold', 'N/A')})")
        if anomaly.get("battery_score") is not None:
            lines.append(f"Battery anomaly score: {anomaly['battery_score']:.3f}")

        # Charging status
        if self._charging_estimator and nav.get("state") == "DOCKED":
            bms = self._bms_telemetry
            port_power = abs(bms.get("port_power", 0.0))
            stbd_power = abs(bms.get("stbd_power", 0.0))
            charger_power = port_power + stbd_power
            avg_soc = (bms.get("port_soc", 0.0) + bms.get("stbd_soc", 0.0)) / 2.0
            if charger_power > 10.0:
                est_full = self._charging_estimator.estimate_to_full(avg_soc)
                est_target = self._charging_estimator.estimate_to_target(
                    avg_soc, self._charging_target_soc)
                lines.append(f"Charging: YES at {charger_power:.0f} kW")
                lines.append(f"Charging SOC: {avg_soc:.1f}%")
                lines.append(f"Est. time to {self._charging_target_soc:.0f}%: {est_target:.0f} min")
                lines.append(f"Est. time to 100%: {est_full:.0f} min")
            else:
                lines.append("Charging: NO (docked but not plugged in)")

        lines.append(f"Temperature: {weather.get('temperature_c', 'N/A')} C")
        lines.append(f"Wind: {weather.get('wind_speed_kn', 'N/A')} kn from {weather.get('wind_direction_deg', 'N/A')} deg")
        lines.append(f"Tide: {weather.get('tide_height_m', 'N/A')} m ({weather.get('tide_phase', 'N/A')})")

        # Station predictions from Model 1A (per-station SOC forecast)
        try:
            preds = getattr(self, '_auto_predictions', None) or []
            if preds:
                lines.append("Station predictions (from current location):")
                for p in preds:
                    lines.append(
                        f"  {p['destination']} ({p['direction']}): "
                        f"arrival SOC {p['predicted_soc']}%, "
                        f"uses ~{p['soc_reduction']}%, "
                        f"status: {p['safety_status']}"
                    )
        except Exception:
            pass

        # ETA estimates
        try:
            eta_lines = self._eta.get_context_lines()
            lines.extend(eta_lines)
        except Exception:
            pass

        return "\n".join(lines)

    _DALARAY_SYSTEM_PROMPT = """You are Dalaray, the AI voice assistant for the M/B Dalaray electric ferry operating on the Pasig River in Metro Manila, Philippines.

Your role:
- Help the ferry crew with real-time information about the vessel
- Answer questions about battery status, weather, position, passengers, anomalies, and reachable stations
- Be concise — your responses will be spoken aloud via TTS, so keep them short (2-3 sentences)
- Match the user's language: respond in Filipino if they speak Filipino, English if they speak English
- Be extra polite, warm, and respectful (use "po" in Filipino responses)
- Always end your response by offering further help (e.g., "Is there anything else I can help with po?" or "May iba pa po ba akong maitutulong?")
- If asked about something not in the dashboard data, say you don't have that information

Current dashboard state:
{context}

IMPORTANT:
- If the user wants to SET, ADD, or REMOVE passengers, include an action in your response.
  Format the action on a NEW line at the end, starting with ACTION: followed by JSON.
  Examples:
    ACTION: {{"type": "set_passengers", "count": 25}}
    ACTION: {{"type": "add_passengers", "count": 5}}
    ACTION: {{"type": "remove_passengers", "count": 3}}
- For station predictions, use:
    ACTION: {{"type": "predict_station", "station": "Escolta"}}
- Only include an ACTION line if the user explicitly requests one of these operations.
- The 9 ferry stations in order: Napindan, Kalawaan, Bambang, Lambingan, Valenzuela, Guadalupe, Hulo, Quinta, Escolta.
- Charging stations: Guadalupe and Napindan. When asked about charging, use the station predictions to recommend the closer reachable charging station first.
- When the ferry is actively charging (Charging: YES), you can tell the user the current charging power, SOC, and estimated time to reach their target or full charge. If they ask "how long until fully charged?" use the time-to-100% estimate.
"""

    async def _handle_chat(self, request: aiohttp.web.Request) -> aiohttp.web.Response:
        """LLM-powered chat via Gemini."""
        try:
            data = await request.json()
        except Exception:
            return aiohttp.web.json_response(
                {"error": "Invalid JSON"}, status=400, headers=self._CORS_HEADERS,
            )

        text = data.get("text", "").strip()
        if not text:
            return aiohttp.web.json_response(
                {"error": "No text"}, status=400, headers=self._CORS_HEADERS,
            )

        client = self._get_gemini_client()
        if client is None:
            return aiohttp.web.json_response(
                {"error": "Gemini not configured"}, status=503, headers=self._CORS_HEADERS,
            )

        try:
            context = self._build_dashboard_context()
            system_prompt = self._DALARAY_SYSTEM_PROMPT.format(context=context)

            from google.genai import types
            response = await asyncio.get_event_loop().run_in_executor(
                None,
                lambda: client.models.generate_content(
                    model=self._gemini_model,
                    contents=[text],
                    config=types.GenerateContentConfig(
                        system_instruction=system_prompt,
                        max_output_tokens=200,
                        temperature=0.7,
                    ),
                ),
            )

            response_text = response.text.strip()

            # Parse action if present
            action = None
            if "ACTION:" in response_text:
                parts = response_text.split("ACTION:", 1)
                response_text = parts[0].strip()
                try:
                    action = json.loads(parts[1].strip())
                except Exception:
                    pass

            # Execute action on the backend
            if action:
                action_type = action.get("type", "")
                if action_type == "set_passengers":
                    self._passenger_count = int(action["count"])
                    await self._emit("passenger_correction", {"count": self._passenger_count})
                elif action_type == "add_passengers":
                    self._passenger_count += int(action["count"])
                    await self._emit("passenger_correction", {"count": self._passenger_count})
                elif action_type == "remove_passengers":
                    self._passenger_count = max(0, self._passenger_count - int(action["count"]))
                    await self._emit("passenger_correction", {"count": self._passenger_count})

            # Detect response language for TTS voice selection
            fil_markers = {"ang", "mga", "na", "sa", "ng", "ko", "mo", "po",
                           "ito", "ay", "para", "namin", "atin", "tayo", "natin",
                           "hindi", "oo", "mga", "meron", "wala", "dito", "doon"}
            words = set(response_text.lower().split())
            fil_count = len(words & fil_markers)
            detected_lang = "fil" if fil_count >= 3 else "en"

            return aiohttp.web.json_response(
                {"response": response_text, "action": action, "language": detected_lang},
                headers=self._CORS_HEADERS,
            )

        except Exception as e:
            import traceback
            log.warning("Gemini chat failed: %s\n%s", e, traceback.format_exc())
            return aiohttp.web.json_response(
                {"error": str(e)}, status=500, headers=self._CORS_HEADERS,
            )

    # ---------------------------------------------------------------
    # Lifecycle
    # ---------------------------------------------------------------

    async def _on_startup(self, app: aiohttp.web.Application) -> None:
        self._session = aiohttp.ClientSession()

        # Auto-discover vessel API if enabled
        if self.config.auto_discover:
            discovered = await asyncio.get_event_loop().run_in_executor(
                None, lambda: discover_vessel_api(
                    port=self.config.vessel_port,
                    known_hosts=[self.config.vessel_host],
                ),
            )
            if discovered:
                self.config.vessel_host = discovered
            else:
                log.warning(
                    "Auto-discovery failed — falling back to %s",
                    self.config.vessel_host,
                )

        self._consecutive_failures = 0
        self._tasks = [
            asyncio.create_task(self._poll_vessel_loop()),
            asyncio.create_task(self._poll_bms_loop()),
            asyncio.create_task(self._poll_weather_loop()),
            asyncio.create_task(self._mqtt_loop()),
        ]
        log.info("All 4 polling loops started (vessel API: %s:%d)",
                 self.config.vessel_host, self.config.vessel_port)

    async def _on_shutdown(self, app: aiohttp.web.Application) -> None:
        for t in self._tasks:
            t.cancel()
        await asyncio.gather(*self._tasks, return_exceptions=True)
        if self._session:
            await self._session.close()
        log.info("Server shut down")

    def run(self, port: int | None = None) -> None:
        port = port or self.config.server_port
        self.app.on_startup.append(self._on_startup)
        self.app.on_shutdown.append(self._on_shutdown)
        log.info("Starting production dashboard on http://0.0.0.0:%d", port)
        aiohttp.web.run_app(self.app, host="0.0.0.0", port=port, print=None)

    # ===================================================================
    # Navigation State Machine
    # ===================================================================

    async def _update_nav_state(
        self, lat: float, lon: float, speed: float, heading: float,
    ) -> None:
        state = self._nav["state"]
        gf_name, gf_dist = _in_geofence(lat, lon)
        in_gf = bool(gf_name)
        new_state = state

        # --- UNKNOWN ---
        if state == "UNKNOWN":
            if in_gf:
                self._nav["current_station"] = gf_name
                self._nav["departure_station"] = gf_name
                new_state = "DOCKED"
            elif speed >= SPEED_MOVING_KN:
                direction, next_stn = _determine_direction(heading, lat, lon)
                self._nav["direction"] = direction
                self._nav["next_station"] = next_stn
                # Infer departure from nearest station
                nearest, _ = _nearest_station(lat, lon)
                self._nav["departure_station"] = nearest["name"]
                new_state = "IN_TRANSIT"

                # Start Model 1B (skip start_trip if already primed)
                self._trip_active = True
                if self._trip_primed:
                    log.info("Model 1B activated from UNKNOWN (primed, buffers pre-filled)")
                    self._trip_primed = False
                else:
                    dep = nearest["name"]
                    if self.rt_predictor and dep and next_stn:
                        try:
                            w = self._weather_raw
                            self.rt_predictor.start_trip(
                                departure_station=dep,
                                arrival_station=next_stn,
                                passengers=self._passenger_count,
                                temperature_c=w.get("temperature_c", 28.0),
                                wind_speed_kn=w.get("wind_speed_kn", 5.0),
                                wind_direction_deg=w.get("wind_direction_deg", 180.0),
                                wave_height_m=w.get("wave_height_m", 0.1),
                                ocean_current_velocity_ms=w.get(
                                    "ocean_current_velocity_ms", 0.0),
                                ocean_current_direction_deg=w.get(
                                    "ocean_current_direction_deg", 0.0),
                                wave_direction_deg=w.get("wave_direction_deg", 0.0),
                                wave_period_s=w.get("wave_period_s", 0.0),
                            )
                            log.info("Model 1B trip started (from UNKNOWN): %s -> %s",
                                     dep, next_stn)
                        except Exception as e:
                            log.warning("Failed to start Model 1B (from UNKNOWN): %s", e)
            else:
                stn, _ = _nearest_station(lat, lon)
                self._nav["current_station"] = stn["name"]
                self._nav["departure_station"] = stn["name"]
                new_state = "DOCKED"

        # --- DOCKED ---
        elif state == "DOCKED":
            # Detect station or SOC change while already docked (e.g., new replay segment)
            if in_gf and gf_name != self._nav["current_station"]:
                self._nav["current_station"] = gf_name
                self._nav["departure_station"] = gf_name
                log.info("Station changed while docked: %s", gf_name)
                await self._run_auto_predictions()
                await self._emit_station_status()
            elif (self._last_auto_pred_soc > 0
                  and abs(self._current_soc - self._last_auto_pred_soc) > 2.0):
                log.info("SOC drift while docked: %.1f%% -> %.1f%%, refreshing predictions",
                         self._last_auto_pred_soc, self._current_soc)
                await self._run_auto_predictions()
            if speed >= SPEED_MOVING_KN:
                direction, next_stn = _determine_direction(heading, lat, lon)
                self._nav["direction"] = direction
                self._nav["next_station"] = next_stn
                self._nav["departure_station"] = self._nav["current_station"]
                self._nav["visited_other"] = False
                self._nav["stopped_since"] = None
                new_state = "DEPARTING"

                # Start Model 1B (skip start_trip if already primed from segment metadata)
                self._trip_active = True
                if self._trip_primed:
                    log.info("Model 1B activated (primed, buffers pre-filled)")
                    self._trip_primed = False
                else:
                    dep = self._nav["departure_station"]
                    if self.rt_predictor and dep and next_stn:
                        try:
                            w = self._weather_raw
                            self.rt_predictor.start_trip(
                                departure_station=dep,
                                arrival_station=next_stn,
                                passengers=self._passenger_count,
                                temperature_c=w.get("temperature_c", 28.0),
                                wind_speed_kn=w.get("wind_speed_kn", 5.0),
                                wind_direction_deg=w.get("wind_direction_deg", 180.0),
                                wave_height_m=w.get("wave_height_m", 0.1),
                                ocean_current_velocity_ms=w.get(
                                    "ocean_current_velocity_ms", 0.0),
                                ocean_current_direction_deg=w.get(
                                    "ocean_current_direction_deg", 0.0),
                                wave_direction_deg=w.get("wave_direction_deg", 0.0),
                                wave_period_s=w.get("wave_period_s", 0.0),
                            )
                            log.info("Model 1B trip started: %s -> %s", dep, next_stn)
                        except Exception as e:
                            log.warning("Failed to start Model 1B: %s", e)

        # --- DEPARTING ---
        elif state == "DEPARTING":
            if not in_gf:
                new_state = "IN_TRANSIT"
            elif speed < SPEED_STOPPED_KN:
                self._trip_active = False
                new_state = "DOCKED"
                log.info("Departure cancelled — stopped in geofence")

        # --- IN_TRANSIT ---
        elif state == "IN_TRANSIT":
            direction, next_stn = _determine_direction(heading, lat, lon)
            self._nav["direction"] = direction
            self._nav["next_station"] = next_stn

            # Wake sensors when approaching next open station within 100 m
            if (self._sensors_sleeping and next_stn
                    and next_stn in OPEN_STATIONS
                    and next_stn in STATION_BY_NAME):
                ns = STATION_BY_NAME[next_stn]
                dist_to_next = _haversine_m(lat, lon, ns["lat"], ns["lon"])
                if dist_to_next <= SENSOR_WAKE_DISTANCE_M:
                    log.info("Approaching %s (%.0f m) — waking sensors",
                             next_stn, dist_to_next)
                    await self._send_sensor_wake()

            if in_gf:
                if gf_name != self._nav["departure_station"]:
                    # Arrived at a different station
                    self._nav["current_station"] = gf_name
                    self._nav["visited_other"] = True
                    self._nav["stopped_since"] = None
                    new_state = "ARRIVING"
                elif self._nav["visited_other"]:
                    # Returned to departure after visiting another station
                    self._nav["current_station"] = gf_name
                    self._nav["stopped_since"] = None
                    new_state = "ARRIVING"

        # --- ARRIVING ---
        elif state == "ARRIVING":
            if not in_gf:
                # Passed through without stopping
                self._nav["visited_other"] = True
                new_state = "IN_TRANSIT"
                log.info("Pass-through at %s — continuing transit",
                         self._nav["current_station"])
            elif speed < SPEED_STOPPED_KN:
                now = time.monotonic()
                if self._nav["stopped_since"] is None:
                    self._nav["stopped_since"] = now
                elif now - self._nav["stopped_since"] >= STOPPED_DWELL_S:
                    self._trip_active = False
                    self._nav["departure_station"] = self._nav["current_station"]
                    self._nav["stopped_since"] = None
                    new_state = "DOCKED"
                    log.info("Arrived and docked at %s",
                             self._nav["current_station"])
            else:
                # Still moving in geofence — reset dwell timer
                self._nav["stopped_since"] = None

        # --- State transition side-effects ---
        if new_state != state:
            self._nav["state"] = new_state
            await self._emit_station_status()

            # Sensor sleep/wake control — only wake at open boarding stations
            current = self._nav.get("current_station")
            if new_state == "IN_TRANSIT":
                await self._send_sensor_sleep()
            elif new_state in ("DOCKED", "ARRIVING"):
                if current in OPEN_STATIONS:
                    await self._send_sensor_wake()
                else:
                    # Closed station or Napindan — keep sensors asleep
                    log.info("Docked at %s (not an open station) — sensors stay asleep",
                             current)
                    await self._send_sensor_sleep()

            if new_state == "DOCKED":
                await self._run_auto_predictions()
                await self._emit("weather_data", self._weather_state)

    async def _emit_station_status(self) -> None:
        await self._emit("station_status", {
            "state": self._nav["state"],
            "current_station": self._nav["current_station"] or "",
            "departure_station": self._nav["departure_station"] or "",
            "next_station": self._nav["next_station"] or "",
            "direction": self._nav["direction"] or "",
            "stations": STATIONS,
        })

    async def _reset_and_prime_trip(self, segment_info: dict | None) -> None:
        """Reset nav state and pre-load Model 1B from segment metadata."""
        # 1) Stop any active trip
        self._trip_active = False
        self._trip_primed = False

        # 2) Reset nav state to UNKNOWN
        self._nav = {
            "state": "UNKNOWN",
            "current_station": None,
            "departure_station": None,
            "next_station": None,
            "direction": None,
            "visited_other": False,
            "stopped_since": None,
        }

        # 3) Emit clears to Flutter
        await self._emit("realtime_prediction", {
            "predicted_arrival_soc": None,
            "soc_remaining_delta": None,
            "arrival_soc_lower": None,
            "arrival_soc_upper": None,
            "reachable_stations": None,
        })
        await self._emit_station_status()

        # 4) Prime Model 1B from segment metadata (if available)
        if segment_info and self.rt_predictor:
            dep = segment_info.get("departure_station")
            dest = segment_info.get("arrival_station")
            if dep and dest:
                try:
                    w = self._weather_raw
                    self.rt_predictor.start_trip(
                        departure_station=dep,
                        arrival_station=dest,
                        passengers=self._passenger_count,
                        temperature_c=w.get("temperature_c", 28.0),
                        wind_speed_kn=w.get("wind_speed_kn", 5.0),
                        wind_direction_deg=w.get("wind_direction_deg", 180.0),
                        wave_height_m=w.get("wave_height_m", 0.1),
                        ocean_current_velocity_ms=w.get(
                            "ocean_current_velocity_ms", 0.0),
                        ocean_current_direction_deg=w.get(
                            "ocean_current_direction_deg", 0.0),
                        wave_direction_deg=w.get("wave_direction_deg", 0.0),
                        wave_period_s=w.get("wave_period_s", 0.0),
                    )
                    self._trip_primed = True
                    log.info("Model 1B primed from segment: %s -> %s", dep, dest)
                except Exception as e:
                    log.warning("Failed to prime Model 1B: %s", e)

    # ===================================================================
    # Vessel Polling Loop (1 Hz)
    # ===================================================================

    def _rebuild_vessel_urls(self) -> tuple[str, str]:
        """Rebuild base/vessel URLs from current config (after rediscovery)."""
        base = f"http://{self.config.vessel_host}:{self.config.vessel_port}"
        return base, f"{base}/vessel"

    async def _try_rediscover(self) -> None:
        """Run auto-discovery in a thread and update config if found."""
        if not self.config.auto_discover:
            return
        log.info("Attempting vessel API re-discovery...")
        discovered = await asyncio.get_event_loop().run_in_executor(
            None, lambda: discover_vessel_api(
                port=self.config.vessel_port,
                known_hosts=[self.config.vessel_host],
            ),
        )
        if discovered and discovered != self.config.vessel_host:
            log.info("Re-discovery: vessel API moved to %s (was %s)",
                     discovered, self.config.vessel_host)
            self.config.vessel_host = discovered

    async def _poll_vessel_loop(self) -> None:
        base, vessel_url = self._rebuild_vessel_urls()
        log.info("Vessel polling: %s", vessel_url)
        tick = 0

        while True:
            try:
                timeout = aiohttp.ClientTimeout(total=5)
                async with self._session.get(vessel_url, timeout=timeout) as resp:
                    if resp.status != 200:
                        log.warning("Vessel API returned %d", resp.status)
                        await asyncio.sleep(1)
                        continue
                    data = await resp.json(content_type=None)
                self._consecutive_failures = 0  # reset on success

                # --- Extract fields ---
                lat = float(data.get("currentPositionLatitude", 0))
                lon = float(data.get("currentPositionLongitude", 0))
                speed = float(data.get("speedOverGround", 0))
                heading = float(data.get("currentHeading",
                                         data.get("heading", 0)))
                soc = float(data.get("batteryStateOfChargePercent", 0))
                port_power = float(data.get("portMotorPower", 0))
                stbd_power = float(data.get("stbdMotorPower", 0))
                motor_combined = float(data.get("motorPowerCombined", 0))
                port_rpm = float(data.get("portRpmShaft",
                                          data.get("portRpm", 0)))
                stbd_rpm = float(data.get("stbdRpmShaft",
                                          data.get("stbdRpm", 0)))
                battery_power = float(data.get("currentBatteryPower",
                                               data.get("batteryPower", 0)))
                trip_nm = float(data.get("trip", 0))
                hv_cap = float(data.get("hvBatteryCapacity",
                                        NOMINAL_HV_CAPACITY))

                self._current_soc = soc
                self._current_speed = speed
                self._hv_capacity = hv_cap
                self._vessel_data = {
                    "lat": lat, "lon": lon, "heading": heading,
                }

                # 1) Ferry position
                await self._emit("ferry_position", {
                    "lat": round(lat, 6),
                    "lon": round(lon, 6),
                    "heading": round(heading, 1),
                    "speed": round(speed, 1),
                })

                # 2) Vessel data
                await self._emit("vessel_data", {
                    "soc": round(soc),
                    "speed": round(speed, 1),
                    "vessel_state": self._nav["state"],
                })

                # 3) Safety status (based on current SOC)
                if soc > 50:
                    safety = "SAFE"
                elif soc > 20:
                    safety = "CAUTION"
                else:
                    safety = "CRITICAL"
                await self._emit("safety_status", {"status": safety})

                # 4) Motor anomaly detection (Model 2)
                if self.motor_detector:
                    try:
                        motor_result = self.motor_detector.check({
                            "port_motor_power": port_power,
                            "stbd_motor_power": stbd_power,
                            "motor_power_combined": motor_combined,
                            "port_rpm": port_rpm,
                            "stbd_rpm": stbd_rpm,
                            "speed_over_ground": speed,
                            "battery_power": battery_power,
                        })
                        self._anomaly_state["motor_health"] = (
                            "ANOMALY"
                            if motor_result.get("level") == "anomalous"
                            else "OK"
                        )
                        self._anomaly_state["motor_score"] = motor_result.get("score")
                        self._anomaly_state["motor_threshold"] = motor_result.get("threshold_value")
                    except Exception as e:
                        log.warning("Motor anomaly check failed: %s", e)

                await self._emit("anomaly_status", self._anomaly_state)

                # 5) Navigation state machine
                await self._update_nav_state(lat, lon, speed, heading)

                # ETA estimation (after nav state is current)
                eta_payload = self._eta.update(
                    lat=lat, lon=lon, speed=speed,
                    nav_state=self._nav["state"],
                    direction=self._nav.get("direction"),
                    next_station=self._nav.get("next_station"),
                    departure_station=self._nav.get("departure_station"),
                    tide_phase=self._weather_state.get("tide_phase", "unknown"),
                )
                if eta_payload is not None:
                    nxt = eta_payload.get("next_station", "?")
                    nxt_min = eta_payload.get("next_station_eta_min", "?")
                    logger.info("ETA ▸ next=%s  ~%.1f min  | stations=%s",
                                nxt, float(nxt_min),
                                ", ".join(f"{s}:{d['eta_min']:.0f}m"
                                          for s, d in eta_payload.get("all_stations", {}).items()))
                    await self._emit("eta_update", eta_payload)

                # 6) Realtime SOC prediction (Model 1B)
                # When primed (but not yet active), pre-fill buffers silently.
                # When active, run update and emit predictions.
                if (self._trip_active or self._trip_primed) and self.rt_predictor:
                    try:
                        rt_result = self.rt_predictor.update(
                            {
                                "soc_percent": soc,
                                "speed_over_ground": speed,
                                "motor_power_combined": motor_combined,
                                "battery_power": battery_power,
                                "heading": heading,
                                "port_rpm": port_rpm,
                                "stbd_rpm": stbd_rpm,
                                "trip_nm": trip_nm,
                            },
                            current_time=datetime.now(),
                        )
                        if self._trip_active and rt_result is not None:
                            await self._emit("realtime_prediction", {
                                "predicted_arrival_soc":
                                    rt_result["predicted_arrival_soc"],
                                "soc_remaining_delta":
                                    rt_result["soc_remaining_delta"],
                                "arrival_soc_lower":
                                    rt_result.get("arrival_soc_lower"),
                                "arrival_soc_upper":
                                    rt_result.get("arrival_soc_upper"),
                                "reachable_stations":
                                    rt_result["reachable_stations"],
                            })
                    except Exception as e:
                        log.warning("Realtime prediction failed: %s", e)

                # Progress log every 60 ticks
                tick += 1
                if tick % 60 == 0:
                    log.info("[TICK %d] SOC=%.1f%% speed=%.1fkn state=%s "
                             "motor=%s batt=%s",
                             tick, soc, speed, self._nav["state"],
                             self._anomaly_state["motor_health"],
                             self._anomaly_state["battery_health"])

            except asyncio.CancelledError:
                raise
            except Exception as e:
                self._consecutive_failures += 1
                log.warning("Vessel poll error (%d consecutive): %s",
                            self._consecutive_failures, e)

                # After 5 consecutive failures, attempt re-discovery
                if self._consecutive_failures >= 5 and self.config.auto_discover:
                    await self._try_rediscover()
                    base, vessel_url = self._rebuild_vessel_urls()
                    self._consecutive_failures = 0

            await asyncio.sleep(1)

    # ===================================================================
    # BMS Polling Loop (1 Hz, battery anomaly every 5s)
    # ===================================================================

    async def _poll_bms_loop(self) -> None:
        tick = 0
        _last_host = self.config.vessel_host
        base = f"http://{_last_host}:{self.config.vessel_port}"
        log.info("BMS polling: port=%s  stbd=%s",
                 f"{base}/device/OneAries_IP_3_ID_49",
                 f"{base}/device/OneAries_IP_4_ID_49")

        while True:
            try:
                # Rebuild URLs if vessel host changed (after rediscovery)
                if self.config.vessel_host != _last_host:
                    _last_host = self.config.vessel_host
                    base = f"http://{_last_host}:{self.config.vessel_port}"
                    log.info("BMS polling: host changed → %s", base)

                port_url = f"{base}/device/OneAries_IP_3_ID_49"
                stbd_url = f"{base}/device/OneAries_IP_4_ID_49"
                timeout = aiohttp.ClientTimeout(total=3)

                # Port BMS
                try:
                    async with self._session.get(
                        port_url, timeout=timeout,
                    ) as resp:
                        if resp.status == 200:
                            pd = await resp.json(content_type=None)
                            self._bms_telemetry.update({
                                "port_cell_v_spread":
                                    float(pd.get("gCellBalance", 0)),
                                "port_cell_t_max":
                                    float(pd.get("gMaxCellTemperature", 0)),
                                "port_cell_t_min":
                                    float(pd.get("gMinCellTemperature", 0)),
                                "port_pack_voltage":
                                    float(pd.get("gPackVoltage", 0)),
                                "port_pack_current":
                                    float(pd.get("gCurrent", 0)),
                                "port_soc":
                                    float(pd.get("gStateOfCharge", 0)),
                                "port_power":
                                    float(pd.get("gPower", 0)),
                                "port_avg_temperature":
                                    float(pd.get("gAverageTemperature", 0)),
                            })
                except Exception as e:
                    log.warning("Port BMS error: %s", e)

                # Starboard BMS
                try:
                    async with self._session.get(
                        stbd_url, timeout=timeout,
                    ) as resp:
                        if resp.status == 200:
                            sd = await resp.json(content_type=None)
                            self._bms_telemetry.update({
                                "stbd_cell_v_spread":
                                    float(sd.get("gCellBalance", 0)),
                                "stbd_cell_t_max":
                                    float(sd.get("gMaxCellTemperature", 0)),
                                "stbd_cell_t_min":
                                    float(sd.get("gMinCellTemperature", 0)),
                                "stbd_pack_voltage":
                                    float(sd.get("gPackVoltage", 0)),
                                "stbd_pack_current":
                                    float(sd.get("gCurrent", 0)),
                                "stbd_soc":
                                    float(sd.get("gStateOfCharge", 0)),
                                "stbd_power":
                                    float(sd.get("gPower", 0)),
                                "stbd_avg_temperature":
                                    float(sd.get("gAverageTemperature", 0)),
                            })
                except Exception as e:
                    log.warning("Stbd BMS error: %s", e)

                # Battery anomaly every 5 ticks
                tick += 1
                if (tick % 5 == 0
                        and self.battery_detector
                        and self._bms_telemetry):
                    try:
                        mode = ("charging"
                                if self._nav["state"] == "DOCKED"
                                else "operational")
                        if mode in self.battery_detector.available_modes:
                            batt_result = self.battery_detector.check(
                                self._bms_telemetry, mode=mode,
                            )
                            level = batt_result.get("level", "normal")
                            if level == "anomalous":
                                self._anomaly_state["battery_health"] = "FAULT"
                            elif level == "warning":
                                self._anomaly_state["battery_health"] = "WARNING"
                            else:
                                self._anomaly_state["battery_health"] = "OK"
                            self._anomaly_state["battery_score"] = batt_result.get("score")
                            self._anomaly_state["battery_threshold"] = batt_result.get("threshold_p99")
                            await self._emit("anomaly_status",
                                             self._anomaly_state)
                    except Exception as e:
                        log.warning("Battery anomaly check failed: %s", e)

                # Charging status every 5 ticks
                if tick % 5 == 0:
                    try:
                        await self._emit_charging_status()
                    except Exception as e:
                        log.warning("Charging status emit failed: %s", e)

            except asyncio.CancelledError:
                raise
            except Exception as e:
                log.warning("BMS poll error: %s", e)

            await asyncio.sleep(1)

    # ===================================================================
    # Weather Polling Loop (every 30 min)
    # ===================================================================

    def _save_weather_cache(self) -> None:
        """Persist current weather data to disk for offline startup."""
        try:
            cache = {
                "weather_raw": self._weather_raw,
                "weather_state": self._weather_state,
                "cached_at": datetime.now().isoformat(),
            }
            WEATHER_CACHE_FILE.write_text(json.dumps(cache, indent=2))
            log.debug("Weather cache saved to %s", WEATHER_CACHE_FILE)
        except Exception as e:
            log.warning("Failed to save weather cache: %s", e)

    def _load_weather_cache(self) -> bool:
        """Load cached weather from disk. Returns True if loaded."""
        try:
            if not WEATHER_CACHE_FILE.exists():
                return False
            cache = json.loads(WEATHER_CACHE_FILE.read_text())
            self._weather_raw = cache["weather_raw"]
            self._weather_state = cache["weather_state"]
            cached_at = cache.get("cached_at", "unknown")
            log.info("Weather loaded from CACHE (saved %s)", cached_at)
            return True
        except Exception as e:
            log.warning("Failed to load weather cache: %s", e)
            return False

    async def _poll_weather_loop(self) -> None:
        log.info("Weather polling: Open-Meteo (every 30 min) + harmonic tide")

        # Load cached weather before first poll so we have real data even offline
        if self._load_weather_cache():
            await self._emit("weather_data", self._weather_state)

        while True:
            try:
                forecast_url = (
                    f"https://api.open-meteo.com/v1/forecast"
                    f"?latitude={WEATHER_LAT}&longitude={WEATHER_LON}"
                    f"&current=temperature_2m,relative_humidity_2m,"
                    f"wind_speed_10m,wind_direction_10m,wind_gusts_10m,"
                    f"precipitation,weather_code"
                    f"&wind_speed_unit=kn"
                )
                marine_url = (
                    f"https://api.open-meteo.com/v1/marine"
                    f"?latitude={WEATHER_LAT}&longitude={WEATHER_LON}"
                    f"&current=wave_height,wave_direction,wave_period"
                    f"&hourly=ocean_current_velocity,ocean_current_direction"
                )

                timeout = aiohttp.ClientTimeout(total=10)

                # Fetch forecast
                forecast: dict[str, Any] = {}
                try:
                    async with self._session.get(
                        forecast_url, timeout=timeout,
                    ) as resp:
                        if resp.status == 200:
                            forecast = await resp.json()
                except Exception as e:
                    log.warning("Forecast API error: %s", e)

                # Fetch marine
                marine: dict[str, Any] = {}
                try:
                    async with self._session.get(
                        marine_url, timeout=timeout,
                    ) as resp:
                        if resp.status == 200:
                            marine = await resp.json()
                except Exception as e:
                    log.warning("Marine API error: %s", e)

                # Parse forecast current block
                fc = forecast.get("current", {})
                temp = fc.get("temperature_2m", 28.0)
                humidity = fc.get("relative_humidity_2m", 75.0)
                wind_speed = fc.get("wind_speed_10m", 5.0)
                wind_dir = fc.get("wind_direction_10m", 180.0)
                precip = fc.get("precipitation", 0.0)
                wmo_code = fc.get("weather_code", 0)

                # Parse marine current block
                mc = marine.get("current", {})
                wave_height = mc.get("wave_height", 0.1)
                wave_dir = mc.get("wave_direction", 0.0)
                wave_period = mc.get("wave_period", 0.0)

                # Ocean current from hourly array (find current hour)
                ocean_vel, ocean_dir = 0.0, 0.0
                hourly = marine.get("hourly", {})
                if hourly:
                    times = hourly.get("time", [])
                    now_hour = datetime.now().strftime("%Y-%m-%dT%H:00")
                    if now_hour in times:
                        idx = times.index(now_hour)
                        vels = hourly.get("ocean_current_velocity", [])
                        dirs = hourly.get("ocean_current_direction", [])
                        if idx < len(vels) and vels[idx] is not None:
                            ocean_vel = vels[idx]
                        if idx < len(dirs) and dirs[idx] is not None:
                            ocean_dir = dirs[idx]

                # Compute tide from harmonic model (no internet needed)
                tide = {
                    "tide_height_m": 0.0,
                    "hours_since_high_tide": 0.0,
                    "tide_phase": "unknown",
                }
                if self._tide_fn:
                    try:
                        tide = self._tide_fn(datetime.now())
                    except Exception as e:
                        log.warning("Tide computation failed: %s", e)

                # Store raw weather for model feature inputs
                self._weather_raw = {
                    "temperature_c": temp,
                    "relative_humidity": humidity,
                    "wind_speed_kn": wind_speed,
                    "wind_direction_deg": wind_dir,
                    "precipitation_mm": precip,
                    "wave_height_m": wave_height,
                    "wave_direction_deg": wave_dir,
                    "wave_period_s": wave_period,
                    "ocean_current_velocity_ms": ocean_vel,
                    "ocean_current_direction_deg": ocean_dir,
                    "weather_code": wmo_code,
                }

                # Build frontend display payload
                desc = WMO_DESCRIPTIONS.get(wmo_code, "Unknown")
                self._weather_state = {
                    "temperature_c": temp,
                    "wind_speed_kn": wind_speed,
                    "wind_direction_deg": wind_dir,
                    "humidity": humidity,
                    "precipitation_mm": precip,
                    "wave_height_m": wave_height,
                    "weather_description": desc,
                    "tide_height_m": round(tide["tide_height_m"], 2),
                    "hours_since_high_tide":
                        round(tide["hours_since_high_tide"], 1),
                    "tide_phase": tide["tide_phase"],
                }

                await self._emit("weather_data", self._weather_state)

                api_success = bool(forecast) or bool(marine)
                if api_success:
                    self._save_weather_cache()

                log.info("Weather updated: %.1f°C, wind %.1fkn, "
                         "wave %.1fm, tide %.2fm (%s)",
                         temp, wind_speed, wave_height,
                         tide["tide_height_m"], tide["tide_phase"])

            except asyncio.CancelledError:
                raise
            except Exception as e:
                log.warning("Weather poll error: %s — keeping stale data", e)

            await asyncio.sleep(30 * 60)

    # ===================================================================
    # MQTT Loop (passenger counting + sensor sleep/wake)
    # ===================================================================

    async def _send_sensor_command(self, cmd: str) -> None:
        """Publish a command ('sleep' or 'wake') to rpi/broadcast via MQTT."""
        if self._mqtt_client is None:
            log.warning("MQTT client not connected — cannot send '%s'", cmd)
            return
        try:
            await self._mqtt_client.publish("rpi/broadcast", cmd)
            log.info("MQTT published '%s' on rpi/broadcast", cmd)
        except Exception as e:
            log.warning("Failed to publish '%s' on rpi/broadcast: %s", cmd, e)

    async def _send_sensor_sleep(self) -> None:
        if not self._sensors_sleeping:
            self._sensors_sleeping = True
            station = self._nav.get("current_station") or "unknown"
            nav_state = self._nav.get("state", "UNKNOWN")
            log.info("SENSORS SLEEP — station=%s  state=%s  pax=%d",
                     station, nav_state, self._passenger_count)
            _pax_logger.info(
                "SLEEP     station=%-12s  state=%-10s  pax=%d",
                station, nav_state, self._passenger_count)
            await self._send_sensor_command("sleep")

    async def _send_sensor_wake(self) -> None:
        if self._sensors_sleeping:
            self._sensors_sleeping = False
            station = self._nav.get("current_station") or "unknown"
            nav_state = self._nav.get("state", "UNKNOWN")
            log.info("SENSORS WAKE  — station=%s  state=%s  pax=%d",
                     station, nav_state, self._passenger_count)
            _pax_logger.info(
                "WAKE      station=%-12s  state=%-10s  pax=%d",
                station, nav_state, self._passenger_count)
            await self._send_sensor_command("wake")

    async def _mqtt_loop(self) -> None:
        # ProactorEventLoop (Windows Python 3.10+) doesn't support add_reader/add_writer
        # which paho-mqtt requires. Detect and skip early to avoid noisy tracebacks.
        import sys
        loop = asyncio.get_running_loop()
        if sys.platform == "win32" and type(loop).__name__ == "ProactorEventLoop":
            log.info("MQTT: skipped (Windows ProactorEventLoop unsupported) — passenger counting disabled")
            return

        try:
            import aiomqtt
        except ImportError:
            log.warning("aiomqtt not installed — passenger counting disabled")
            return

        log.info("MQTT: connecting to %s:%d",
                 self.config.mqtt_host, self.config.mqtt_port)

        max_retries = 3
        retries = 0
        while retries < max_retries:
            try:
                async with aiomqtt.Client(
                    hostname=self.config.mqtt_host,
                    port=self.config.mqtt_port,
                ) as client:
                    self._mqtt_client = client
                    await client.subscribe("esp32/#")
                    log.info("MQTT connected, subscribed to esp32/#")
                    retries = 0  # reset on successful connection

                    # Start sensor health check background task
                    health_task = asyncio.create_task(self._sensor_health_check_loop())

                    async for msg in client.messages:
                        try:
                            topic = msg.topic.value
                            payload = msg.payload.decode().strip()

                            # Track last-seen time per sensor door
                            now = time.monotonic()
                            if "sensor1" in topic or "passengerCount" == topic.split("/")[-1] or topic == "esp32/heartbeat" or topic == "esp32/health":
                                self._sensor_last_seen["left"] = now
                            if "sensor2" in topic or "passengerCount2" in topic or topic == "esp32/heartbeat2" or topic == "esp32/health2":
                                self._sensor_last_seen["right"] = now
                            if "sensor3" in topic or "passengerCount3" in topic or topic == "esp32/heartbeat3" or topic == "esp32/health3":
                                self._sensor_last_seen["back"] = now

                            # VL53L0X sensor health reports from ESP32s
                            if topic in ("esp32/health", "esp32/health2", "esp32/health3"):
                                door = {"esp32/health": "left", "esp32/health2": "right", "esp32/health3": "back"}[topic]
                                has_fail = "FAIL" in payload
                                level = "WARNING" if has_fail else "INFO"
                                log.log(logging.WARNING if has_fail else logging.INFO,
                                        "VL53L0X HEALTH [%s door]: %s", door, payload)
                                _pax_logger.info(
                                    "VL53L0X   door=%-5s  %s", door, payload)
                                continue

                            # Heartbeat from sleeping sensors — just log
                            if topic in ("esp32/heartbeat", "esp32/heartbeat2", "esp32/heartbeat3"):
                                log.debug("Sensor heartbeat: %s → %s", topic, payload)
                                continue

                            # Passenger counting
                            if topic in ("esp32/sensor1", "esp32/passengerCount"):
                                door = "left"
                            elif topic in ("esp32/sensor3", "esp32/passengerCount3"):
                                door = "back"
                            else:
                                door = "right"
                            station = (self._nav.get("current_station") or "unknown")
                            nav_state = self._nav.get("state", "UNKNOWN")

                            if payload == "plus 1":
                                self._passenger_count += 1
                                event = "BOARD"
                            elif payload == "minus 1":
                                if self._passenger_count == 0:
                                    event = "ALIGHT (at 0 — captain/artifact)"
                                else:
                                    event = "ALIGHT"
                                self._passenger_count = max(
                                    0, self._passenger_count - 1)
                            else:
                                continue

                            await self._emit("passenger_count", {
                                "count": self._passenger_count,
                            })
                            log.info("Passenger count: %d (%s via %s door at %s)",
                                     self._passenger_count, payload, door, station)

                            # Timeline log for debugging
                            dep = self._nav.get("departure_station") or ""
                            nxt = self._nav.get("next_station") or ""
                            direction = self._nav.get("direction") or ""
                            sleeping = "sleeping" if self._sensors_sleeping else "awake"
                            _pax_logger.info(
                                "%-8s  door=%-5s  station=%-12s  state=%-10s  "
                                "dep=%-12s  next=%-12s  dir=%-10s  sensors=%-7s  pax=%d",
                                event, door, station, nav_state,
                                dep, nxt, direction, sleeping,
                                self._passenger_count)
                        except Exception as e:
                            log.warning("MQTT message error: %s", e)

            except asyncio.CancelledError:
                self._mqtt_client = None
                health_task.cancel()
                raise
            except NotImplementedError:
                self._mqtt_client = None
                health_task.cancel()
                log.warning("MQTT: event loop does not support add_reader/add_writer "
                            "(Windows ProactorEventLoop) — passenger counting disabled")
                return
            except Exception as e:
                self._mqtt_client = None
                if 'health_task' in locals():
                    health_task.cancel()
                retries += 1
                if retries >= max_retries:
                    log.warning("MQTT: failed after %d attempts — passenger counting disabled", max_retries)
                    return
                log.warning("MQTT connection lost: %s — reconnecting in 5s (%d/%d)", e, retries, max_retries)
                await asyncio.sleep(5)

    async def _sensor_health_check_loop(self) -> None:
        """Periodically log the online/offline status of each sensor door."""
        try:
            await asyncio.sleep(self._sensor_timeout)  # initial grace period
            while True:
                now = time.monotonic()
                status_parts = []
                for door in ("left", "right", "back"):
                    last = self._sensor_last_seen[door]
                    if last == 0.0:
                        status = "NEVER SEEN"
                        ago = ""
                    elif now - last > self._sensor_timeout:
                        status = "OFFLINE"
                        ago = f" (last seen {int(now - last)}s ago)"
                    else:
                        status = "OK"
                        ago = f" ({int(now - last)}s ago)"
                    status_parts.append(f"{door}={status}{ago}")

                station = self._nav.get("current_station") or "unknown"
                nav_state = self._nav.get("state", "UNKNOWN")
                sleeping = "sleeping" if self._sensors_sleeping else "awake"
                summary = "  |  ".join(status_parts)

                log.info("SENSOR HEALTH  %s  [station=%s  state=%s  sensors=%s  pax=%d]",
                         summary, station, nav_state, sleeping,
                         self._passenger_count)
                _pax_logger.info(
                    "HEALTH    %s  station=%-12s  state=%-10s  sensors=%-7s  pax=%d",
                    summary, station, nav_state, sleeping,
                    self._passenger_count)

                await asyncio.sleep(self._sensor_health_interval)
        except asyncio.CancelledError:
            return

    # ===================================================================
    # Prediction Helpers
    # ===================================================================

    async def _run_auto_predictions(self, to: str | None = None) -> None:
        """Run Model 1A predictions to all reachable stations from current."""
        if not self.trip_predictor:
            return

        dep = (self._nav.get("departure_station")
               or self._nav.get("current_station"))
        if not dep or dep not in STATION_BY_NAME:
            return

        self._last_auto_pred_soc = self._current_soc

        now = datetime.now()
        w = self._weather_raw
        dep_order = STATION_BY_NAME[dep]["order"]
        predictions: list[dict] = []

        for stn in STATIONS:
            if stn["order"] == dep_order:
                continue
            direction = ("downstream" if stn["order"] > dep_order
                         else "upstream")
            try:
                interval = self.trip_predictor.predict_interval(
                    method="conformal",
                    departure_station=dep,
                    arrival_station=stn["name"],
                    current_soc=self._current_soc,
                    hv_capacity=self._hv_capacity,
                    target_speed_kn=8.0,
                    passengers=self._passenger_count,
                    temperature_c=w.get("temperature_c", 28.0),
                    humidity=w.get("relative_humidity", 75.0),
                    wind_speed_kn=w.get("wind_speed_kn", 5.0),
                    wind_direction_deg=w.get("wind_direction_deg", 180.0),
                    precipitation_mm=w.get("precipitation_mm", 0.0),
                    wave_height_m=w.get("wave_height_m", 0.1),
                    hour=now.hour,
                    departure_time=now,
                    ocean_current_velocity_ms=w.get(
                        "ocean_current_velocity_ms", 0.0),
                    ocean_current_direction_deg=w.get(
                        "ocean_current_direction_deg", 0.0),
                    wave_direction_deg=w.get("wave_direction_deg", 0.0),
                    wave_period_s=w.get("wave_period_s", 0.0),
                )
                best_soc = self._current_soc - interval["lower"]
                worst_soc = self._current_soc - interval["upper"]
                avg_soc = self._current_soc - interval["point"]
                if avg_soc > 50:
                    status = "SAFE"
                elif avg_soc > 20:
                    status = "CAUTION"
                else:
                    status = "CRITICAL"
                predictions.append({
                    "departure": dep,
                    "destination": stn["name"],
                    "predicted_soc": f"{best_soc:.1f}-{worst_soc:.1f}",
                    "soc_reduction": f"{interval['point']:.1f}",
                    "safety_status": status,
                    "direction": direction,
                })
            except Exception as e:
                log.warning("Auto-prediction %s->%s failed: %s",
                            dep, stn["name"], e)

        self._auto_predictions = predictions
        payload = {"mode": "docked", "predictions": predictions}
        if to:
            await self.sio.emit("auto_prediction", payload, to=to)
        else:
            await self._emit("auto_prediction", payload)
        log.info("Auto-predictions: %d destinations from %s",
                 len(predictions), dep)

    async def _handle_speed_prediction(
        self, departure: str, destination: str,
    ) -> dict:
        """Run Model 1A at multiple speeds for a given route."""
        empty = {"departure": departure, "destination": destination,
                 "speeds": []}
        if not self.trip_predictor:
            return empty

        now = datetime.now()
        w = self._weather_raw
        current_soc = self._current_soc if self._current_soc > 0 else 95.0
        speeds_kn = [5.0, 7.0, 10.0, 12.0, 15.0]
        result_speeds: list[dict] = []

        for spd in speeds_kn:
            try:
                interval = self.trip_predictor.predict_interval(
                    method="conformal",
                    departure_station=departure,
                    arrival_station=destination,
                    current_soc=current_soc,
                    hv_capacity=self._hv_capacity,
                    target_speed_kn=spd,
                    passengers=self._passenger_count,
                    temperature_c=w.get("temperature_c", 28.0),
                    humidity=w.get("relative_humidity", 75.0),
                    wind_speed_kn=w.get("wind_speed_kn", 5.0),
                    wind_direction_deg=w.get("wind_direction_deg", 180.0),
                    precipitation_mm=w.get("precipitation_mm", 0.0),
                    wave_height_m=w.get("wave_height_m", 0.1),
                    hour=now.hour,
                    departure_time=now,
                    ocean_current_velocity_ms=w.get(
                        "ocean_current_velocity_ms", 0.0),
                    ocean_current_direction_deg=w.get(
                        "ocean_current_direction_deg", 0.0),
                    wave_direction_deg=w.get("wave_direction_deg", 0.0),
                    wave_period_s=w.get("wave_period_s", 0.0),
                )
                best_soc = current_soc - interval["lower"]
                worst_soc = current_soc - interval["upper"]
                avg_soc = current_soc - interval["point"]
                if avg_soc > 50:
                    status = "RECOMMENDED"
                elif avg_soc > 20:
                    status = "CAUTION"
                else:
                    status = "CRITICAL"
                result_speeds.append({
                    "speed_kn": spd,
                    "predicted_soc": f"{best_soc:.1f}-{worst_soc:.1f}%",
                    "soc_reduction": f"{interval['point']:.1f}",
                    "safety_status": status,
                })
            except Exception as e:
                log.warning("Speed prediction at %.1f kn failed: %s", spd, e)
                result_speeds.append({
                    "speed_kn": spd,
                    "predicted_soc": "N/A",
                    "soc_reduction": "N/A",
                    "safety_status": "UNKNOWN",
                })

        return {
            "departure": departure,
            "destination": destination,
            "speeds": result_speeds,
        }

    # ===================================================================
    # Socket.IO Event Handlers
    # ===================================================================

    def _register_events(self) -> None:

        @self.sio.event
        async def connect(sid: str, environ: dict) -> None:
            log.info("Client connected: %s", sid)
            # Send full state snapshot to the newly connected client
            await self.sio.emit("vessel_data", {
                "soc": round(self._current_soc),
                "speed": round(self._current_speed, 1),
                "vessel_state": self._nav["state"],
            }, to=sid)
            await self.sio.emit("ferry_position", {
                "lat": round(self._vessel_data.get("lat", 0), 6),
                "lon": round(self._vessel_data.get("lon", 0), 6),
                "heading": round(self._vessel_data.get("heading", 0), 1),
                "speed": round(self._current_speed, 1),
            }, to=sid)
            soc = self._current_soc
            safety = ("SAFE" if soc > 50
                      else "CAUTION" if soc > 20
                      else "CRITICAL")
            await self.sio.emit("safety_status",
                                {"status": safety}, to=sid)
            await self.sio.emit("weather_data",
                                self._weather_state, to=sid)
            await self.sio.emit("anomaly_status",
                                self._anomaly_state, to=sid)
            await self.sio.emit("station_status", {
                "state": self._nav["state"],
                "current_station": self._nav["current_station"] or "",
                "departure_station": self._nav["departure_station"] or "",
                "next_station": self._nav["next_station"] or "",
                "direction": self._nav["direction"] or "",
                "stations": STATIONS,
            }, to=sid)
            await self.sio.emit("passenger_count", {
                "count": self._passenger_count,
            }, to=sid)

            # If docked, send auto-predictions (targeted to this client)
            if self._nav["state"] == "DOCKED" and self.trip_predictor:
                await self._run_auto_predictions(to=sid)

            # Send current ETA snapshot
            eta_payload = self._eta.get_payload()
            if eta_payload:
                await self.sio.emit("eta_update", eta_payload, to=sid)

            # Send current charging status
            if self._charging_estimator:
                try:
                    await self._emit_charging_status()
                except Exception:
                    pass

        @self.sio.event
        async def disconnect(sid: str) -> None:
            log.info("Client disconnected: %s", sid)

        @self.sio.on("set_charging_target")
        async def handle_set_charging_target(sid: str, data: dict) -> None:
            target = data.get("target_soc", 80.0)
            self._charging_target_soc = max(50.0, min(100.0, float(target)))
            log.info("Charging target SOC set to %.0f%% by %s",
                     self._charging_target_soc, sid)

        @self.sio.on("speed_prediction_request")
        async def handle_speed_request(sid: str, data: dict) -> None:
            departure = _resolve_station(data.get("departure", ""))
            destination = _resolve_station(data.get("destination", ""))
            log.info("Speed prediction request: %s -> %s (from %s)",
                     departure, destination, sid)

            if (departure not in STATION_BY_NAME
                    or destination not in STATION_BY_NAME):
                log.warning("Invalid stations: %s -> %s",
                            departure, destination)
                await self.sio.emit("speed_prediction_result", {
                    "departure": departure,
                    "destination": destination, "speeds": [],
                }, to=sid)
                return

            try:
                result = await self._handle_speed_prediction(
                    departure, destination)
                log.info("Speed prediction result: %d speeds for %s->%s",
                         len(result.get("speeds", [])),
                         departure, destination)
                await self.sio.emit(
                    "speed_prediction_result", result, to=sid)
                log.info("Speed prediction emitted to %s", sid)
            except Exception as e:
                log.error("Speed prediction failed: %s", e,
                          exc_info=True)
                await self.sio.emit("speed_prediction_result", {
                    "departure": departure,
                    "destination": destination, "speeds": [],
                }, to=sid)

        @self.sio.on("end_trip")
        async def handle_end_trip(sid: str, data: dict) -> None:
            log.info("Manual trip end from %s", sid)
            self._trip_active = False

        @self.sio.on("replay_command")
        async def handle_replay(sid: str, data: dict) -> None:
            """Forward replay control commands to the vessel/replay server."""
            action = data.get("action", "")
            base = f"http://{self.config.vessel_host}:{self.config.vessel_port}"
            try:
                async with aiohttp.ClientSession() as sess:
                    if action == "get_segments":
                        resp = await sess.get(f"{base}/segments", timeout=aiohttp.ClientTimeout(total=5))
                        segments = await resp.json()
                        await self.sio.emit("replay_segments", segments, room=sid)
                    elif action == "start":
                        body = (
                            {"mode": "full_day"}
                            if data.get("mode") == "full_day"
                            else {"segment_id": data.get("segment_id", "")}
                        )
                        resp = await sess.post(f"{base}/replay/start", json=body, timeout=aiohttp.ClientTimeout(total=5))
                        result = await resp.json()
                        # Reset nav state and prime Model 1B from segment metadata
                        segment_info = (result.get("status") or {}).get("current_segment")
                        await self._reset_and_prime_trip(segment_info)
                        await self.sio.emit("replay_status", result, room=sid)
                    elif action == "stop":
                        resp = await sess.post(f"{base}/replay/stop", json={}, timeout=aiohttp.ClientTimeout(total=5))
                        result = await resp.json()
                        await self.sio.emit("replay_status", result, room=sid)
                    elif action == "speed":
                        resp = await sess.post(
                            f"{base}/replay/speed",
                            json={"multiplier": data.get("multiplier", 1)},
                            timeout=aiohttp.ClientTimeout(total=5),
                        )
                        result = await resp.json()
                        await self.sio.emit("replay_status", result, room=sid)
                    elif action == "status":
                        resp = await sess.get(f"{base}/replay/status", timeout=aiohttp.ClientTimeout(total=5))
                        result = await resp.json()
                        await self.sio.emit("replay_status", result, room=sid)
                    elif action == "get_dates":
                        resp = await sess.get(f"{base}/dates", timeout=aiohttp.ClientTimeout(total=5))
                        result = await resp.json()
                        await self.sio.emit("replay_dates", result, room=sid)
                    elif action == "change_date":
                        resp = await sess.post(
                            f"{base}/replay/change_date",
                            json={"date": data.get("date", "")},
                            timeout=aiohttp.ClientTimeout(total=10),
                        )
                        result = await resp.json()
                        # Send updated segments and status
                        await self.sio.emit("replay_segments",
                                            result.get("segments", []),
                                            room=sid)
                        await self.sio.emit("replay_status",
                                            result.get("status", {}),
                                            room=sid)
                        await self.sio.emit("replay_dates", {
                            "dates": [],
                            "current": result.get("date", ""),
                        }, room=sid)
            except Exception as e:
                log.warning("Replay command '%s' failed: %s", action, e)
                await self.sio.emit("replay_status", {"error": str(e)}, room=sid)


# ===================================================================
# CLI Entry Point
# ===================================================================


def main() -> None:
    parser = argparse.ArgumentParser(
        description="M/B Dalaray production dashboard — "
                    "live telemetry + ML models via Socket.IO",
    )
    parser.add_argument(
        "--vessel-host", default="CONFIGURE_VESSEL_HOST",
        help="Vessel API host (default: CONFIGURE_VESSEL_HOST)",
    )
    parser.add_argument(
        "--vessel-port", type=int, default=8481,
        help="Vessel API port (default: 8481)",
    )
    parser.add_argument(
        "--mqtt-host", default="localhost",
        help="MQTT broker host (default: localhost)",
    )
    parser.add_argument(
        "--mqtt-port", type=int, default=1883,
        help="MQTT broker port (default: 1883)",
    )
    parser.add_argument(
        "--port", type=int, default=5000,
        help="Socket.IO server port (default: 5000)",
    )
    parser.add_argument(
        "--bundle-dir",
        default=str(Path(__file__).resolve().parent.parent / "Ferry_Digital_Shadow" / "Models" / "rpi5_bundle"),
        help="Path to rpi5_bundle directory",
    )
    parser.add_argument(
        "--auto-discover", action="store_true", default=False,
        help="Auto-discover vessel API on local network at startup "
             "and on connection failure (scans for port 8481)",
    )

    args = parser.parse_args()

    config = Config(
        vessel_host=args.vessel_host,
        vessel_port=args.vessel_port,
        mqtt_host=args.mqtt_host,
        mqtt_port=args.mqtt_port,
        server_port=args.port,
        bundle_dir=args.bundle_dir,
        auto_discover=args.auto_discover,
    )

    server = DashboardServer(config)
    server.run()


if __name__ == "__main__":
    main()
