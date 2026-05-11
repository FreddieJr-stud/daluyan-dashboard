"""Unit tests for dashboard_backend.py.

Run:  pytest test_dashboard_backend.py -v
"""
from __future__ import annotations

import math
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from dashboard_backend import (
    GEOFENCE_RADIUS_M,
    STATIONS,
    STATION_ALIAS,
    STATION_BY_NAME,
    Config,
    DashboardServer,
    _bearing,
    _haversine_m,
    _heading_diff,
    _in_geofence,
    _nearest_station,
    _determine_direction,
    _resolve_station,
)


# ===================================================================
# Fixtures
# ===================================================================


@pytest.fixture
def server():
    """Create a DashboardServer without loading ML models."""
    with patch.object(DashboardServer, "_load_models"):
        srv = DashboardServer(Config())
    srv.trip_predictor = None
    srv.rt_predictor = None
    srv.motor_detector = None
    srv.battery_detector = None
    srv._tide_fn = None
    srv._emit = AsyncMock()
    srv._emit_station_status = AsyncMock()
    srv._run_auto_predictions = AsyncMock()
    return srv


# ===================================================================
# Section A: Geo Helpers (~15 tests, pure functions)
# ===================================================================


class TestHaversine:
    """Tests for _haversine_m."""

    def test_known_distance_napindan_guadalupe(self):
        """Napindan to Guadalupe should be ~2400m."""
        n = STATION_BY_NAME["Napindan"]
        g = STATION_BY_NAME["Guadalupe"]
        d = _haversine_m(n["lat"], n["lon"], g["lat"], g["lon"])
        assert 2000 < d < 3000, f"Expected ~2400m, got {d:.0f}m"

    def test_known_distance_quinta_escolta(self):
        """Quinta to Escolta should be ~430m."""
        q = STATION_BY_NAME["Quinta"]
        e = STATION_BY_NAME["Escolta"]
        d = _haversine_m(q["lat"], q["lon"], e["lat"], e["lon"])
        assert 300 < d < 600, f"Expected ~430m, got {d:.0f}m"

    def test_zero_distance(self):
        """Same point should give 0."""
        d = _haversine_m(14.55713, 121.06836, 14.55713, 121.06836)
        assert d == pytest.approx(0, abs=0.01)

    def test_symmetry(self):
        """d(A,B) == d(B,A)."""
        n = STATION_BY_NAME["Napindan"]
        g = STATION_BY_NAME["Guadalupe"]
        d1 = _haversine_m(n["lat"], n["lon"], g["lat"], g["lon"])
        d2 = _haversine_m(g["lat"], g["lon"], n["lat"], n["lon"])
        assert d1 == pytest.approx(d2, abs=0.01)


class TestNearestStation:
    """Tests for _nearest_station."""

    @pytest.mark.parametrize("stn", STATIONS)
    def test_exact_coords_returns_itself(self, stn):
        """Each station's coords should return itself, dist < 1m."""
        found, dist = _nearest_station(stn["lat"], stn["lon"])
        assert found["name"] == stn["name"]
        assert dist < 1.0

    def test_midpoint_returns_one_of_neighbours(self):
        """Midpoint between Napindan and Guadalupe returns one of them."""
        n = STATION_BY_NAME["Napindan"]
        g = STATION_BY_NAME["Guadalupe"]
        mid_lat = (n["lat"] + g["lat"]) / 2
        mid_lon = (n["lon"] + g["lon"]) / 2
        found, _ = _nearest_station(mid_lat, mid_lon)
        assert found["name"] in ("Napindan", "Guadalupe")


class TestInGeofence:
    """Tests for _in_geofence."""

    def test_inside_exact_coords(self):
        """Station exact coords => name returned, dist < 1m."""
        stn = STATION_BY_NAME["Hulo"]
        name, dist = _in_geofence(stn["lat"], stn["lon"])
        assert name == "Hulo"
        assert dist < 1.0

    def test_inside_150m_offset(self):
        """150m offset (~0.00135° lat) => still inside geofence."""
        stn = STATION_BY_NAME["Guadalupe"]
        # Offset ~150m north (0.00135° ≈ 150m at this latitude)
        name, dist = _in_geofence(stn["lat"] + 0.00135, stn["lon"])
        assert name == "Guadalupe"
        assert dist < GEOFENCE_RADIUS_M

    def test_outside_300m(self):
        """300m offset (~0.0027° lat) => outside geofence."""
        stn = STATION_BY_NAME["Guadalupe"]
        name, dist = _in_geofence(stn["lat"] + 0.0027, stn["lon"])
        assert name == ""
        assert dist > GEOFENCE_RADIUS_M


class TestBearing:
    """Tests for _bearing."""

    def test_napindan_to_guadalupe(self):
        """Guadalupe is NW of Napindan => bearing ~300-320°."""
        n = STATION_BY_NAME["Napindan"]
        g = STATION_BY_NAME["Guadalupe"]
        b = _bearing(n["lat"], n["lon"], g["lat"], g["lon"])
        assert 290 <= b <= 330, f"Expected ~300-320°, got {b:.1f}°"

    def test_escolta_to_napindan(self):
        """Napindan is SE of Escolta => bearing ~110-140°."""
        e = STATION_BY_NAME["Escolta"]
        n = STATION_BY_NAME["Napindan"]
        b = _bearing(e["lat"], e["lon"], n["lat"], n["lon"])
        assert 100 <= b <= 150, f"Expected ~110-140°, got {b:.1f}°"


class TestHeadingDiff:
    """Tests for _heading_diff."""

    def test_basic_cases(self):
        assert _heading_diff(0, 0) == pytest.approx(0)
        assert _heading_diff(0, 180) == pytest.approx(180)
        assert _heading_diff(170, 190) == pytest.approx(20)

    def test_wraparound(self):
        assert _heading_diff(350, 10) == pytest.approx(20)
        assert _heading_diff(0, 360) == pytest.approx(0)

    def test_symmetry(self):
        assert _heading_diff(30, 90) == pytest.approx(_heading_diff(90, 30))


class TestDetermineDirection:
    """Tests for _determine_direction."""

    def test_downstream_at_guadalupe(self):
        """At Guadalupe, heading toward Hulo => downstream."""
        g = STATION_BY_NAME["Guadalupe"]
        h = STATION_BY_NAME["Hulo"]
        heading = _bearing(g["lat"], g["lon"], h["lat"], h["lon"])
        direction, next_stn = _determine_direction(heading, g["lat"], g["lon"])
        assert direction == "downstream"
        assert next_stn == "Hulo"

    def test_upstream_at_guadalupe(self):
        """At Guadalupe, heading toward Napindan => upstream."""
        g = STATION_BY_NAME["Guadalupe"]
        n = STATION_BY_NAME["Napindan"]
        heading = _bearing(g["lat"], g["lon"], n["lat"], n["lon"])
        direction, next_stn = _determine_direction(heading, g["lat"], g["lon"])
        assert direction == "upstream"
        assert next_stn == "Napindan"

    def test_endpoint_napindan(self):
        """At Napindan, any heading => downstream (only downstream neighbor)."""
        n = STATION_BY_NAME["Napindan"]
        direction, next_stn = _determine_direction(0, n["lat"], n["lon"])
        assert direction == "downstream"
        assert next_stn == "Guadalupe"

    def test_endpoint_escolta(self):
        """At Escolta, any heading => upstream (only upstream neighbor)."""
        e = STATION_BY_NAME["Escolta"]
        direction, next_stn = _determine_direction(0, e["lat"], e["lon"])
        assert direction == "upstream"
        assert next_stn == "Quinta"


class TestResolveStation:
    """Tests for _resolve_station."""

    def test_alias(self):
        assert _resolve_station("Sta. Ana") == "Sta Ana"

    def test_passthrough(self):
        assert _resolve_station("Napindan") == "Napindan"
        assert _resolve_station("UnknownStation") == "UnknownStation"


# ===================================================================
# Section B: Navigation State Machine (~11 tests, async)
# ===================================================================


class TestNavStateMachine:
    """Tests for _update_nav_state transitions."""

    @pytest.mark.asyncio
    async def test_b1_boot_at_station(self, server):
        """UNKNOWN -> DOCKED when booting inside a station geofence."""
        n = STATION_BY_NAME["Napindan"]
        await server._update_nav_state(n["lat"], n["lon"], 0.0, 0.0)
        assert server._nav["state"] == "DOCKED"
        assert server._nav["current_station"] == "Napindan"

    @pytest.mark.asyncio
    async def test_b2_boot_outside_stopped(self, server):
        """UNKNOWN -> DOCKED when outside geofence but stopped."""
        # Midpoint between Napindan and Guadalupe, speed=0
        n = STATION_BY_NAME["Napindan"]
        g = STATION_BY_NAME["Guadalupe"]
        mid_lat = (n["lat"] + g["lat"]) / 2
        mid_lon = (n["lon"] + g["lon"]) / 2
        await server._update_nav_state(mid_lat, mid_lon, 0.0, 0.0)
        assert server._nav["state"] == "DOCKED"
        assert server._nav["current_station"] is not None

    @pytest.mark.asyncio
    async def test_b3_boot_outside_moving(self, server):
        """UNKNOWN -> IN_TRANSIT when outside geofence and moving."""
        n = STATION_BY_NAME["Napindan"]
        g = STATION_BY_NAME["Guadalupe"]
        mid_lat = (n["lat"] + g["lat"]) / 2
        mid_lon = (n["lon"] + g["lon"]) / 2
        heading = _bearing(mid_lat, mid_lon, g["lat"], g["lon"])
        await server._update_nav_state(mid_lat, mid_lon, 5.0, heading)
        assert server._nav["state"] == "IN_TRANSIT"
        assert server._nav["direction"] is not None

    @pytest.mark.asyncio
    async def test_b4_depart(self, server):
        """DOCKED -> DEPARTING when speed exceeds threshold."""
        n = STATION_BY_NAME["Napindan"]
        # First, dock at Napindan
        await server._update_nav_state(n["lat"], n["lon"], 0.0, 0.0)
        assert server._nav["state"] == "DOCKED"

        # Now move — heading toward Guadalupe
        g = STATION_BY_NAME["Guadalupe"]
        heading = _bearing(n["lat"], n["lon"], g["lat"], g["lon"])
        await server._update_nav_state(n["lat"], n["lon"], 3.0, heading)
        assert server._nav["state"] == "DEPARTING"
        assert server._nav["departure_station"] == "Napindan"
        assert server._nav["direction"] is not None
        assert server._nav["visited_other"] is False
        assert server._trip_active is True

    @pytest.mark.asyncio
    async def test_b5_leave_geofence(self, server):
        """DEPARTING -> IN_TRANSIT when leaving the geofence."""
        n = STATION_BY_NAME["Napindan"]
        g = STATION_BY_NAME["Guadalupe"]
        heading = _bearing(n["lat"], n["lon"], g["lat"], g["lon"])

        # Dock, then depart
        await server._update_nav_state(n["lat"], n["lon"], 0.0, 0.0)
        await server._update_nav_state(n["lat"], n["lon"], 3.0, heading)
        assert server._nav["state"] == "DEPARTING"

        # Move outside geofence (midpoint is >200m from any station)
        mid_lat = (n["lat"] + g["lat"]) / 2
        mid_lon = (n["lon"] + g["lon"]) / 2
        await server._update_nav_state(mid_lat, mid_lon, 5.0, heading)
        assert server._nav["state"] == "IN_TRANSIT"

    @pytest.mark.asyncio
    async def test_b6_enter_new_geofence(self, server):
        """IN_TRANSIT -> ARRIVING when entering a new station's geofence."""
        n = STATION_BY_NAME["Napindan"]
        g = STATION_BY_NAME["Guadalupe"]
        heading = _bearing(n["lat"], n["lon"], g["lat"], g["lon"])

        # Dock -> Depart -> Transit
        await server._update_nav_state(n["lat"], n["lon"], 0.0, 0.0)
        await server._update_nav_state(n["lat"], n["lon"], 3.0, heading)
        mid_lat = (n["lat"] + g["lat"]) / 2
        mid_lon = (n["lon"] + g["lon"]) / 2
        await server._update_nav_state(mid_lat, mid_lon, 5.0, heading)
        assert server._nav["state"] == "IN_TRANSIT"

        # Enter Guadalupe geofence
        await server._update_nav_state(g["lat"], g["lon"], 3.0, heading)
        assert server._nav["state"] == "ARRIVING"
        assert server._nav["current_station"] == "Guadalupe"
        assert server._nav["visited_other"] is True

    @pytest.mark.asyncio
    async def test_b7_dwell_at_station(self, server):
        """ARRIVING -> DOCKED after stopping 3s at station."""
        n = STATION_BY_NAME["Napindan"]
        g = STATION_BY_NAME["Guadalupe"]
        heading = _bearing(n["lat"], n["lon"], g["lat"], g["lon"])

        # Drive to Guadalupe: Dock -> Depart -> Transit -> Arriving
        await server._update_nav_state(n["lat"], n["lon"], 0.0, 0.0)
        await server._update_nav_state(n["lat"], n["lon"], 3.0, heading)
        mid_lat = (n["lat"] + g["lat"]) / 2
        mid_lon = (n["lon"] + g["lon"]) / 2
        await server._update_nav_state(mid_lat, mid_lon, 5.0, heading)
        await server._update_nav_state(g["lat"], g["lon"], 3.0, heading)
        assert server._nav["state"] == "ARRIVING"

        # Stop at Guadalupe — first tick sets stopped_since
        t0 = 1000.0
        with patch("dashboard_backend.time") as mock_time:
            mock_time.monotonic.return_value = t0
            await server._update_nav_state(g["lat"], g["lon"], 0.5, heading)
        assert server._nav["state"] == "ARRIVING"  # Not yet docked

        # Second tick: 4 seconds later => dwell exceeded
        with patch("dashboard_backend.time") as mock_time:
            mock_time.monotonic.return_value = t0 + 4.0
            await server._update_nav_state(g["lat"], g["lon"], 0.5, heading)
        assert server._nav["state"] == "DOCKED"
        assert server._trip_active is False

    @pytest.mark.asyncio
    async def test_b8_pass_through(self, server):
        """ARRIVING -> IN_TRANSIT when leaving geofence without stopping."""
        n = STATION_BY_NAME["Napindan"]
        g = STATION_BY_NAME["Guadalupe"]
        h = STATION_BY_NAME["Hulo"]
        heading_ng = _bearing(n["lat"], n["lon"], g["lat"], g["lon"])
        heading_gh = _bearing(g["lat"], g["lon"], h["lat"], h["lon"])

        # Drive to Guadalupe: Dock -> Depart -> Transit -> Arriving
        await server._update_nav_state(n["lat"], n["lon"], 0.0, 0.0)
        await server._update_nav_state(n["lat"], n["lon"], 3.0, heading_ng)
        mid_lat = (n["lat"] + g["lat"]) / 2
        mid_lon = (n["lon"] + g["lon"]) / 2
        await server._update_nav_state(mid_lat, mid_lon, 5.0, heading_ng)
        await server._update_nav_state(g["lat"], g["lon"], 3.0, heading_ng)
        assert server._nav["state"] == "ARRIVING"

        # Leave geofence toward Hulo without stopping
        mid2_lat = (g["lat"] + h["lat"]) / 2
        mid2_lon = (g["lon"] + h["lon"]) / 2
        await server._update_nav_state(mid2_lat, mid2_lon, 5.0, heading_gh)
        assert server._nav["state"] == "IN_TRANSIT"

    @pytest.mark.asyncio
    async def test_b9_cancel_departure(self, server):
        """DEPARTING -> DOCKED when speed drops in geofence."""
        n = STATION_BY_NAME["Napindan"]
        g = STATION_BY_NAME["Guadalupe"]
        heading = _bearing(n["lat"], n["lon"], g["lat"], g["lon"])

        # Dock, then depart
        await server._update_nav_state(n["lat"], n["lon"], 0.0, 0.0)
        await server._update_nav_state(n["lat"], n["lon"], 3.0, heading)
        assert server._nav["state"] == "DEPARTING"

        # Stop again inside geofence
        await server._update_nav_state(n["lat"], n["lon"], 0.5, heading)
        assert server._nav["state"] == "DOCKED"
        assert server._trip_active is False

    @pytest.mark.asyncio
    async def test_b10_return_no_visit(self, server):
        """IN_TRANSIT stays when returning to departure without visiting another."""
        n = STATION_BY_NAME["Napindan"]
        g = STATION_BY_NAME["Guadalupe"]
        heading_out = _bearing(n["lat"], n["lon"], g["lat"], g["lon"])
        heading_back = _bearing(g["lat"], g["lon"], n["lat"], n["lon"])

        # Dock -> Depart -> Transit
        await server._update_nav_state(n["lat"], n["lon"], 0.0, 0.0)
        await server._update_nav_state(n["lat"], n["lon"], 3.0, heading_out)
        mid_lat = (n["lat"] + g["lat"]) / 2
        mid_lon = (n["lon"] + g["lon"]) / 2
        await server._update_nav_state(mid_lat, mid_lon, 5.0, heading_out)
        assert server._nav["state"] == "IN_TRANSIT"
        assert server._nav["visited_other"] is False

        # Return to Napindan geofence without visiting another station
        await server._update_nav_state(n["lat"], n["lon"], 3.0, heading_back)
        # Should stay IN_TRANSIT because visited_other is False and
        # gf_name == departure_station
        assert server._nav["state"] == "IN_TRANSIT"

    @pytest.mark.asyncio
    async def test_b11_model_1b_started(self, server):
        """When departing, rt_predictor.start_trip should be called."""
        mock_rt = MagicMock()
        server.rt_predictor = mock_rt

        n = STATION_BY_NAME["Napindan"]
        g = STATION_BY_NAME["Guadalupe"]
        heading = _bearing(n["lat"], n["lon"], g["lat"], g["lon"])

        # Dock, then depart
        await server._update_nav_state(n["lat"], n["lon"], 0.0, 0.0)
        await server._update_nav_state(n["lat"], n["lon"], 3.0, heading)
        assert server._nav["state"] == "DEPARTING"
        mock_rt.start_trip.assert_called_once()


# ===================================================================
# Section C: Safety & Prediction Format (~4 tests)
# ===================================================================


class TestSafetyThresholds:
    """Tests for SOC-based safety status logic."""

    @pytest.mark.parametrize("soc,expected", [
        (80, "SAFE"),
        (51, "SAFE"),
        (50, "CAUTION"),
        (21, "CAUTION"),
        (20, "CRITICAL"),
        (0, "CRITICAL"),
    ])
    def test_safety_status(self, soc, expected):
        """Verify SOC thresholds: >50 SAFE, >20 CAUTION, <=20 CRITICAL."""
        if soc > 50:
            status = "SAFE"
        elif soc > 20:
            status = "CAUTION"
        else:
            status = "CRITICAL"
        assert status == expected


class TestAutoPredictionStructure:
    """Tests for _run_auto_predictions output structure."""

    @pytest.mark.asyncio
    async def test_prediction_structure(self):
        """Mock trip_predictor, verify 8 predictions with required fields."""
        with patch.object(DashboardServer, "_load_models"):
            srv = DashboardServer(Config())
        srv.rt_predictor = None
        srv.motor_detector = None
        srv.battery_detector = None
        srv._tide_fn = None

        # Set up state for predictions
        srv._nav["current_station"] = "Napindan"
        srv._nav["departure_station"] = "Napindan"
        srv._current_soc = 95.0
        srv._hv_capacity = 160.0
        srv._passenger_count = 0

        mock_predictor = MagicMock()
        mock_predictor.predict_interval.return_value = {
            "point": 5.0, "lower": 3.0, "upper": 7.0,
        }
        srv.trip_predictor = mock_predictor

        # Capture emitted data
        emitted = {}

        async def capture_emit(event, data, **kwargs):
            emitted[event] = data

        srv.sio = MagicMock()
        srv.sio.emit = AsyncMock(side_effect=capture_emit)

        await srv._run_auto_predictions()

        assert "auto_prediction" in emitted
        payload = emitted["auto_prediction"]
        assert payload["mode"] == "docked"
        preds = payload["predictions"]
        # 8 other stations from Napindan
        assert len(preds) == 8

        for p in preds:
            assert "departure" in p
            assert "destination" in p
            assert "predicted_soc" in p
            assert "soc_reduction" in p
            assert "safety_status" in p
            assert "direction" in p
            assert p["departure"] == "Napindan"
            assert p["safety_status"] in ("SAFE", "CAUTION", "CRITICAL")


class TestSpeedPredictionStructure:
    """Tests for _handle_speed_prediction output structure."""

    @pytest.mark.asyncio
    async def test_speed_prediction_structure(self):
        """Mock predictor, verify 5 speed entries with required fields."""
        with patch.object(DashboardServer, "_load_models"):
            srv = DashboardServer(Config())
        srv.rt_predictor = None
        srv.motor_detector = None
        srv.battery_detector = None
        srv._tide_fn = None
        srv._current_soc = 95.0
        srv._hv_capacity = 160.0
        srv._passenger_count = 0

        mock_predictor = MagicMock()
        mock_predictor.predict_interval.return_value = {
            "point": 5.0, "lower": 3.0, "upper": 7.0,
        }
        srv.trip_predictor = mock_predictor

        result = await srv._handle_speed_prediction("Napindan", "Guadalupe")
        assert result["departure"] == "Napindan"
        assert result["destination"] == "Guadalupe"
        assert len(result["speeds"]) == 5

        for entry in result["speeds"]:
            assert "speed_kn" in entry
            assert "predicted_soc" in entry
            assert "soc_reduction" in entry
            assert "safety_status" in entry
            assert entry["safety_status"] in (
                "RECOMMENDED", "CAUTION", "CRITICAL")

    @pytest.mark.asyncio
    async def test_prediction_safety_mapping(self):
        """Verify best/worst SOC range format and correct status."""
        with patch.object(DashboardServer, "_load_models"):
            srv = DashboardServer(Config())
        srv.rt_predictor = None
        srv.motor_detector = None
        srv.battery_detector = None
        srv._tide_fn = None
        srv._current_soc = 95.0
        srv._hv_capacity = 160.0
        srv._passenger_count = 0

        mock_predictor = MagicMock()
        # Large reduction: 95 - 80 = 15 avg SOC => CRITICAL
        mock_predictor.predict_interval.return_value = {
            "point": 80.0, "lower": 75.0, "upper": 85.0,
        }
        srv.trip_predictor = mock_predictor

        result = await srv._handle_speed_prediction("Napindan", "Escolta")
        entry = result["speeds"][0]
        # best_soc = 95 - 75 = 20, worst_soc = 95 - 85 = 10
        assert "20.0" in entry["predicted_soc"]
        assert "10.0" in entry["predicted_soc"]
        assert entry["safety_status"] == "CRITICAL"
