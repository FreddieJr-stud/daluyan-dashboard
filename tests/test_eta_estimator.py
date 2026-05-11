"""Unit tests for ETAEstimator.

Self-contained: copies minimal globals and the ETAEstimator class from
dashboard_backend.py so we avoid importing the full backend (which pulls
in aiohttp, socketio, etc.).
"""

from __future__ import annotations

import json
import math
import logging
from pathlib import Path
from datetime import datetime
from typing import Any

import pytest

# ---------------------------------------------------------------------------
# Minimal globals copied from dashboard_backend.py
# ---------------------------------------------------------------------------

log = logging.getLogger(__name__)

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

OPEN_STATIONS: set[str] = {
    "Guadalupe", "Hulo", "Lambingan", "PUP", "Quinta", "Escolta",
}


def _haversine_m(lat1, lon1, lat2, lon2):
    R = 6_371_000
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlam = math.radians(lon2 - lon1)
    a = (math.sin(dphi / 2) ** 2
         + math.cos(phi1) * math.cos(phi2) * math.sin(dlam / 2) ** 2)
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


# ---------------------------------------------------------------------------
# ETAEstimator class — copied from dashboard_backend.py (lines 314-503)
# ---------------------------------------------------------------------------


class ETAEstimator:
    """Estimates arrival times using historical baselines adjusted by real-time conditions."""

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
            log.warning("ETA baselines not found at %s -- using fallbacks", path)
            return
        try:
            data = json.loads(path.read_text())
            self._segment_baselines = data.get("segment_baselines", {})
            self._dwell_baselines = data.get("dwell_baselines", {})
            log.info(
                "ETA baselines loaded: %d segments, %d dwell entries",
                len(self._segment_baselines),
                len(self._dwell_baselines),
            )
        except Exception as e:
            log.warning("Failed to load ETA baselines: %s", e)

    def _segment_time(self, dep: str, arr: str, direction: str) -> tuple[float, float]:
        baseline = self._segment_baselines.get(f"{dep}|{arr}|{direction}")
        if baseline:
            return baseline["time_s"], baseline["avg_speed_kn"]
        km_dep = STATION_BY_NAME.get(dep, {}).get("km", 0)
        km_arr = STATION_BY_NAME.get(arr, {}).get("km", 0)
        dist_km = abs(km_arr - km_dep) or 1.0
        dist_nm = dist_km / 1.852
        time_s = (dist_nm / self._DEFAULT_SPEED_KN) * 3600
        return time_s, self._DEFAULT_SPEED_KN

    def _dwell_time(self, station: str, direction: str) -> float:
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

        remaining_m = _haversine_m(lat, lon, next_stn["lat"], next_stn["lon"])
        remaining_km = remaining_m / 1000.0

        dep_stn = STATION_BY_NAME.get(departure_station or "")
        total_km = abs(next_stn["km"] - dep_stn["km"]) if dep_stn else remaining_km
        total_km = max(total_km, 0.01)

        baseline_s, baseline_speed = self._segment_time(
            departure_station or "", next_station, direction,
        )

        if speed > 0.5:
            ratio = speed / baseline_speed
            ratio = max(self._SPEED_RATIO_MIN, min(ratio, self._SPEED_RATIO_MAX))
        else:
            ratio = 1.0

        remaining_frac = min(remaining_km / total_km, 1.0)
        tide = self._tide_factor(tide_phase, direction)

        current_seg_s = baseline_s * remaining_frac * (1.0 / ratio) * tide

        all_etas: dict[str, float] = {}
        cumulative = current_seg_s
        all_etas[next_station] = cumulative

        if direction == "downstream":
            beyond = [
                s for s in self._ROUTE_STATIONS
                if STATION_BY_NAME.get(s, {}).get("order", -1) > next_stn["order"]
            ]
        else:
            beyond = [
                s for s in reversed(self._ROUTE_STATIONS)
                if STATION_BY_NAME.get(s, {}).get("order", 99) < next_stn["order"]
            ]

        prev = next_station
        for stn_name in beyond:
            cumulative += self._dwell_time(prev, direction)
            seg_s, _ = self._segment_time(prev, stn_name, direction)
            cumulative += seg_s * (1.0 / ratio) * tide
            all_etas[stn_name] = cumulative
            prev = stn_name

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
        if not self._last_payload or not self._last_payload.get("next_station"):
            return []
        lines = ["ETA estimates:"]
        for stn, info in self._last_payload["all_stations"].items():
            lines.append(f"  ETA to {stn}: ~{info['eta_min']} minutes")
        return lines

    def get_payload(self) -> dict[str, Any] | None:
        return self._last_payload


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

# Resolve path to the real baselines config directory
_REPO_ROOT = Path(__file__).resolve().parent.parent.parent  # Dashboard/../..
_CONFIG_DIR = (
    _REPO_ROOT
    / "Ferry_Digital_Shadow"
    / "Models"
    / "rpi5_bundle"
    / "config"
)


@pytest.fixture
def estimator() -> ETAEstimator:
    """ETAEstimator loaded with real baselines."""
    return ETAEstimator(str(_CONFIG_DIR))


@pytest.fixture
def estimator_no_baselines(tmp_path) -> ETAEstimator:
    """ETAEstimator with no baselines (fallback mode)."""
    return ETAEstimator(str(tmp_path))


# Midway between Guadalupe and Hulo
_MID_GUAD_HULO_LAT = 14.568
_MID_GUAD_HULO_LON = 121.041


def _make_transit_call(
    est: ETAEstimator,
    *,
    lat: float = _MID_GUAD_HULO_LAT,
    lon: float = _MID_GUAD_HULO_LON,
    speed: float = 7.0,
    direction: str = "downstream",
    next_station: str = "Hulo",
    departure_station: str = "Guadalupe",
    tide_phase: str = "high",
) -> dict[str, Any] | None:
    """Helper to call update() with sensible defaults for a downstream transit."""
    return est.update(
        lat=lat,
        lon=lon,
        speed=speed,
        nav_state="IN_TRANSIT",
        direction=direction,
        next_station=next_station,
        departure_station=departure_station,
        tide_phase=tide_phase,
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_baselines_loaded(estimator: ETAEstimator):
    """ETAEstimator loads baselines from the real JSON file."""
    assert len(estimator._segment_baselines) > 0, "No segment baselines loaded"
    assert len(estimator._dwell_baselines) > 0, "No dwell baselines loaded"


def test_eta_not_in_transit_returns_none(estimator: ETAEstimator):
    """When nav_state is DOCKED, update() returns None (no prior payload)."""
    result = estimator.update(
        lat=14.568, lon=121.048, speed=0.0,
        nav_state="DOCKED", direction=None,
        next_station=None, departure_station=None,
        tide_phase="high",
    )
    assert result is None


def test_eta_not_in_transit_reset(estimator: ETAEstimator):
    """After being in transit, switching to DOCKED returns a reset payload, then None."""
    # First: put it in transit so _last_payload is set
    payload = _make_transit_call(estimator)
    assert payload is not None, "First transit call should produce a payload"

    # Now dock -- should get a reset payload
    reset = estimator.update(
        lat=14.568, lon=121.048, speed=0.0,
        nav_state="DOCKED", direction=None,
        next_station=None, departure_station=None,
        tide_phase="high",
    )
    assert reset is not None, "First DOCKED call after transit should return reset"
    assert reset["next_station"] is None
    assert reset["all_stations"] == {}

    # Second DOCKED call -- should be None
    second = estimator.update(
        lat=14.568, lon=121.048, speed=0.0,
        nav_state="DOCKED", direction=None,
        next_station=None, departure_station=None,
        tide_phase="high",
    )
    assert second is None, "Subsequent DOCKED calls should return None"


def test_eta_next_station_downstream(estimator: ETAEstimator):
    """Ferry between Guadalupe and Hulo heading downstream gets reasonable ETA."""
    payload = _make_transit_call(estimator)
    assert payload is not None

    assert payload["next_station"] == "Hulo"
    eta_min = payload["next_station_eta_min"]
    assert 0.5 <= eta_min <= 15, f"ETA {eta_min} min is outside reasonable range [0.5, 15]"


def test_eta_multi_hop_ordering(estimator: ETAEstimator):
    """Multi-hop ETAs increase monotonically (further stations = higher ETA)."""
    payload = _make_transit_call(estimator)
    assert payload is not None

    all_stations = payload["all_stations"]
    # Downstream from Guadalupe -> should include Hulo, Lambingan, PUP, Quinta, Escolta
    expected_order = ["Hulo", "Lambingan", "PUP", "Quinta", "Escolta"]
    present = [s for s in expected_order if s in all_stations]
    assert len(present) >= 3, f"Expected at least 3 downstream stations, got {present}"

    etas = [all_stations[s]["eta_s"] for s in present]
    for i in range(len(etas) - 1):
        assert etas[i] < etas[i + 1], (
            f"ETA ordering violated: {present[i]}={etas[i]}s >= {present[i+1]}={etas[i+1]}s"
        )


def test_eta_speed_ratio_faster(estimator: ETAEstimator):
    """Higher speed produces lower ETA."""
    # Slow speed
    slow_payload = _make_transit_call(estimator, speed=5.0)
    assert slow_payload is not None
    slow_eta = slow_payload["next_station_eta_s"]

    # Reset smoothing by docking
    estimator.update(
        lat=14.568, lon=121.048, speed=0.0,
        nav_state="DOCKED", direction=None,
        next_station=None, departure_station=None,
        tide_phase="high",
    )

    # Fast speed
    fast_payload = _make_transit_call(estimator, speed=10.0)
    assert fast_payload is not None
    fast_eta = fast_payload["next_station_eta_s"]

    assert fast_eta < slow_eta, f"Fast ETA {fast_eta}s should be < slow ETA {slow_eta}s"


def test_eta_speed_ratio_clamped(estimator: ETAEstimator):
    """Extremely high speed doesn't produce absurd results (ratio clamped to 3.0)."""
    payload = _make_transit_call(estimator, speed=50.0)
    assert payload is not None

    eta_s = payload["next_station_eta_s"]
    assert eta_s > 0, "ETA should be positive even at extreme speed"
    # At 50 kn the ratio is clamped to 3.0, so ETA = baseline/3 -- still reasonable
    eta_min = payload["next_station_eta_min"]
    assert eta_min < 30, f"Clamped ETA {eta_min} min is unreasonably high"


def test_eta_tide_adjustment(estimator: ETAEstimator):
    """Rising tide + upstream should reduce ETA vs neutral tide (high)."""
    # Upstream ferry near PUP heading to Lambingan
    pup = STATION_BY_NAME["PUP"]
    lamb = STATION_BY_NAME["Lambingan"]
    mid_lat = (pup["lat"] + lamb["lat"]) / 2
    mid_lon = (pup["lon"] + lamb["lon"]) / 2

    # Neutral tide
    neutral = estimator.update(
        lat=mid_lat, lon=mid_lon, speed=7.0,
        nav_state="IN_TRANSIT", direction="upstream",
        next_station="Lambingan", departure_station="PUP",
        tide_phase="high",
    )
    assert neutral is not None
    neutral_eta = neutral["next_station_eta_s"]

    # Reset
    estimator.update(
        lat=mid_lat, lon=mid_lon, speed=0.0,
        nav_state="DOCKED", direction=None,
        next_station=None, departure_station=None,
        tide_phase="high",
    )

    # Rising tide + upstream -> factor 0.9 -> faster
    rising = estimator.update(
        lat=mid_lat, lon=mid_lon, speed=7.0,
        nav_state="IN_TRANSIT", direction="upstream",
        next_station="Lambingan", departure_station="PUP",
        tide_phase="rising",
    )
    assert rising is not None
    rising_eta = rising["next_station_eta_s"]

    assert rising_eta < neutral_eta, (
        f"Rising-upstream ETA {rising_eta}s should be < neutral ETA {neutral_eta}s"
    )


def test_smoothing_suppresses_unchanged(estimator: ETAEstimator):
    """Calling update() twice with same params returns None the second time."""
    first = _make_transit_call(estimator)
    assert first is not None, "First call should produce payload"

    second = _make_transit_call(estimator)
    assert second is None, "Identical second call should be suppressed by smoothing"


def test_smoothing_emits_on_large_change(estimator: ETAEstimator):
    """After a significant speed change, smoothing allows the update through."""
    first = _make_transit_call(estimator, speed=5.0)
    assert first is not None

    # Large speed change -> ETAs shift by much more than 30s threshold
    second = _make_transit_call(estimator, speed=15.0)
    assert second is not None, "Large speed change should pass smoothing threshold"


def test_eta_upstream(estimator: ETAEstimator):
    """Ferry heading upstream gets ETAs to lower-order stations."""
    pup = STATION_BY_NAME["PUP"]
    payload = estimator.update(
        lat=pup["lat"], lon=pup["lon"], speed=7.0,
        nav_state="IN_TRANSIT", direction="upstream",
        next_station="Lambingan", departure_station="PUP",
        tide_phase="high",
    )
    assert payload is not None

    all_stations = payload["all_stations"]
    # Upstream from PUP: should include Lambingan, and possibly Hulo, Guadalupe, Napindan
    assert "Lambingan" in all_stations, "Next station Lambingan should be in ETAs"

    # Check that some lower-order stations appear
    upstream_stations = {"Hulo", "Guadalupe", "Napindan"}
    found = upstream_stations & set(all_stations.keys())
    assert len(found) >= 2, f"Expected at least 2 upstream stations, got {found}"


def test_get_context_lines(estimator: ETAEstimator):
    """get_context_lines() returns formatted strings for LLM context."""
    # Before any update, should be empty
    assert estimator.get_context_lines() == []

    # After a transit update
    _make_transit_call(estimator)
    lines = estimator.get_context_lines()
    assert len(lines) > 0, "Should have context lines after update"
    assert lines[0] == "ETA estimates:"
    assert any("ETA to" in line for line in lines[1:])


def test_get_payload_after_update(estimator: ETAEstimator):
    """get_payload() returns the last emitted payload."""
    assert estimator.get_payload() is None, "No payload before any update"

    payload = _make_transit_call(estimator)
    assert payload is not None

    stored = estimator.get_payload()
    assert stored is not None
    assert stored == payload


def test_payload_format(estimator: ETAEstimator):
    """Payload has all required keys with correct types."""
    payload = _make_transit_call(estimator)
    assert payload is not None

    # Required keys
    assert "next_station" in payload
    assert "next_station_eta_s" in payload
    assert "next_station_eta_min" in payload
    assert "all_stations" in payload
    assert "direction" in payload
    assert "timestamp" in payload

    # Type checks
    assert isinstance(payload["next_station"], str)
    assert isinstance(payload["next_station_eta_s"], int)
    assert isinstance(payload["next_station_eta_min"], float)
    assert isinstance(payload["all_stations"], dict)
    assert isinstance(payload["direction"], str)
    assert isinstance(payload["timestamp"], str)

    # Verify timestamp is valid ISO format
    datetime.fromisoformat(payload["timestamp"])

    # Verify all_stations entries have eta_s and eta_min
    for stn, info in payload["all_stations"].items():
        assert isinstance(stn, str)
        assert "eta_s" in info
        assert "eta_min" in info
        assert isinstance(info["eta_s"], int)
        assert isinstance(info["eta_min"], float)
