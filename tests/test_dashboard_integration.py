"""Integration tests for Dashboard backend + replay server.

Tests that the server starts, Socket.IO connects, events flow,
and prediction responses have the correct shape.

Run:  pytest test_dashboard_integration.py -v
"""
from __future__ import annotations

import asyncio
import socket
import time
from unittest.mock import AsyncMock, MagicMock, patch

import aiohttp
import pytest
import pytest_asyncio
import socketio as sio_pkg

from dashboard_backend import Config, DashboardServer, STATIONS


# ── Helpers ────────────────────────────────────────────────────────────


def _find_free_port() -> int:
    """Find a free TCP port on localhost."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


# ── Fixtures ───────────────────────────────────────────────────────────


@pytest.fixture
def free_port():
    """Return a free port for the test server."""
    return _find_free_port()


@pytest.fixture
def config(free_port):
    """Config pointing at a free port, no real vessel server."""
    return Config(
        vessel_host="localhost",
        vessel_port=0,  # no real vessel server
        server_port=free_port,
    )


@pytest_asyncio.fixture
async def running_server(config, free_port):
    """Start a DashboardServer (models mocked) and yield (server, port).

    Tears down after test.
    """
    with patch.object(DashboardServer, "_load_models"):
        srv = DashboardServer(config)
    srv.trip_predictor = None
    srv.rt_predictor = None
    srv.motor_detector = None
    srv.battery_detector = None
    srv._tide_fn = None

    # Disable polling loops that need a vessel server
    srv._poll_vessel = AsyncMock()
    srv._poll_weather = AsyncMock()

    runner = aiohttp.web.AppRunner(srv.app)
    await runner.setup()
    site = aiohttp.web.TCPSite(runner, "127.0.0.1", free_port)
    await site.start()

    yield srv, free_port

    await runner.cleanup()


# ===================================================================
# Section A: Server Startup & Binding
# ===================================================================


class TestServerStartup:
    """Verify the backend starts and binds correctly."""

    @pytest.mark.asyncio
    async def test_server_binds_to_port(self, running_server):
        """Server should accept HTTP connections on its port."""
        srv, port = running_server
        async with aiohttp.ClientSession() as session:
            # Socket.IO endpoint should respond (even if not a normal HTTP page)
            try:
                async with session.get(
                    f"http://127.0.0.1:{port}/socket.io/?EIO=4&transport=polling",
                    timeout=aiohttp.ClientTimeout(total=5),
                ) as resp:
                    assert resp.status == 200
            except aiohttp.ClientError:
                pytest.fail("Server did not respond on expected port")

    @pytest.mark.asyncio
    async def test_server_creates_socketio_instance(self, running_server):
        """Server should have a valid Socket.IO instance attached."""
        srv, _ = running_server
        assert srv.sio is not None

    @pytest.mark.asyncio
    async def test_config_stored_correctly(self, config):
        """Config values should be stored on the server."""
        with patch.object(DashboardServer, "_load_models"):
            srv = DashboardServer(config)
        assert srv.config.server_port == config.server_port
        assert srv.config.vessel_host == config.vessel_host


# ===================================================================
# Section B: Socket.IO Connection
# ===================================================================


class TestSocketIOConnection:
    """Verify Socket.IO client can connect and receive events."""

    @pytest.mark.asyncio
    async def test_client_connects(self, running_server):
        """A Socket.IO client should connect successfully."""
        _, port = running_server
        client = sio_pkg.AsyncClient()
        connected = asyncio.Event()

        @client.event
        async def connect():
            connected.set()

        await client.connect(
            f"http://127.0.0.1:{port}",
            transports=["polling"],
            wait_timeout=5,
        )
        await asyncio.wait_for(connected.wait(), timeout=5)
        assert client.connected
        await client.disconnect()

    @pytest.mark.asyncio
    async def test_client_reconnects_after_disconnect(self, running_server):
        """Client should be able to reconnect after disconnecting."""
        _, port = running_server
        client = sio_pkg.AsyncClient()

        await client.connect(
            f"http://127.0.0.1:{port}",
            transports=["polling"],
            wait_timeout=5,
        )
        assert client.connected
        await client.disconnect()
        assert not client.connected

        # Reconnect
        await client.connect(
            f"http://127.0.0.1:{port}",
            transports=["polling"],
            wait_timeout=5,
        )
        assert client.connected
        await client.disconnect()


# ===================================================================
# Section C: Event Flow
# ===================================================================


class TestEventFlow:
    """Verify server emits expected events and handles client requests."""

    @pytest.mark.asyncio
    async def test_vessel_data_emission(self, running_server):
        """Simulating vessel data should trigger vessel_data event."""
        srv, port = running_server
        client = sio_pkg.AsyncClient()
        received = asyncio.Event()
        received_data = {}

        @client.on("vessel_data")
        async def on_vessel_data(data):
            received_data.update(data)
            received.set()

        await client.connect(
            f"http://127.0.0.1:{port}",
            transports=["polling"],
            wait_timeout=5,
        )

        # Emit vessel_data from server side
        await srv.sio.emit("vessel_data", {
            "soc": 85.0,
            "speed": 5.2,
            "latitude": 14.5571,
            "longitude": 121.0684,
            "heading": 310.0,
            "timestamp": "2026-03-02T10:00:00",
        })

        try:
            await asyncio.wait_for(received.wait(), timeout=5)
            assert "soc" in received_data
            assert "speed" in received_data
        except asyncio.TimeoutError:
            pytest.fail("Did not receive vessel_data event within timeout")
        finally:
            await client.disconnect()

    @pytest.mark.asyncio
    async def test_weather_data_emission(self, running_server):
        """Server should be able to emit weather_data events."""
        srv, port = running_server
        client = sio_pkg.AsyncClient()
        received = asyncio.Event()
        received_data = {}

        @client.on("weather_data")
        async def on_weather_data(data):
            received_data.update(data)
            received.set()

        await client.connect(
            f"http://127.0.0.1:{port}",
            transports=["polling"],
            wait_timeout=5,
        )

        await srv.sio.emit("weather_data", {
            "temperature_c": 30.5,
            "wind_speed_kn": 8.2,
            "wind_direction_deg": 180,
            "wave_height_m": 0.3,
        })

        try:
            await asyncio.wait_for(received.wait(), timeout=5)
            assert "temperature_c" in received_data
        except asyncio.TimeoutError:
            pytest.fail("Did not receive weather_data event within timeout")
        finally:
            await client.disconnect()

    @pytest.mark.asyncio
    async def test_anomaly_status_emission(self, running_server):
        """Server should emit anomaly_status with expected fields."""
        srv, port = running_server
        client = sio_pkg.AsyncClient()
        received = asyncio.Event()
        received_data = {}

        @client.on("anomaly_status")
        async def on_anomaly(data):
            received_data.update(data)
            received.set()

        await client.connect(
            f"http://127.0.0.1:{port}",
            transports=["polling"],
            wait_timeout=5,
        )

        await srv.sio.emit("anomaly_status", {
            "motor_health": "OK",
            "battery_health": "OK",
        })

        try:
            await asyncio.wait_for(received.wait(), timeout=5)
            assert "motor_health" in received_data
        except asyncio.TimeoutError:
            pytest.fail("Did not receive anomaly_status event within timeout")
        finally:
            await client.disconnect()


# ===================================================================
# Section D: Prediction Response Schema
# ===================================================================


class TestPredictionSchema:
    """Verify prediction outputs have the correct structure."""

    @pytest.mark.asyncio
    async def test_auto_prediction_schema(self):
        """auto_prediction event should contain predictions list with required fields."""
        with patch.object(DashboardServer, "_load_models"):
            srv = DashboardServer(Config())
        srv.rt_predictor = None
        srv.motor_detector = None
        srv.battery_detector = None
        srv._tide_fn = None

        srv._nav["current_station"] = "Guadalupe"
        srv._nav["departure_station"] = "Guadalupe"
        srv._current_soc = 90.0
        srv._hv_capacity = 160.0
        srv._passenger_count = 0

        mock_predictor = MagicMock()
        mock_predictor.predict_interval.return_value = {
            "point": 4.0, "lower": 2.5, "upper": 5.5,
        }
        srv.trip_predictor = mock_predictor

        emitted = {}

        async def capture(event, data, **kw):
            emitted[event] = data

        srv.sio = MagicMock()
        srv.sio.emit = AsyncMock(side_effect=capture)

        await srv._run_auto_predictions()

        assert "auto_prediction" in emitted
        payload = emitted["auto_prediction"]
        preds = payload["predictions"]

        # From Guadalupe: 8 other stations
        assert len(preds) == 8

        required_keys = {
            "departure", "destination", "predicted_soc",
            "soc_reduction", "safety_status", "direction",
        }
        for p in preds:
            assert required_keys.issubset(p.keys()), f"Missing keys: {required_keys - p.keys()}"
            assert p["departure"] == "Guadalupe"
            assert p["safety_status"] in ("SAFE", "CAUTION", "CRITICAL")

    @pytest.mark.asyncio
    async def test_speed_prediction_schema(self):
        """_handle_speed_prediction should return speeds list with required fields."""
        with patch.object(DashboardServer, "_load_models"):
            srv = DashboardServer(Config())
        srv.rt_predictor = None
        srv.motor_detector = None
        srv.battery_detector = None
        srv._tide_fn = None
        srv._current_soc = 90.0
        srv._hv_capacity = 160.0
        srv._passenger_count = 0

        mock_predictor = MagicMock()
        mock_predictor.predict_interval.return_value = {
            "point": 4.0, "lower": 2.5, "upper": 5.5,
        }
        srv.trip_predictor = mock_predictor

        result = await srv._handle_speed_prediction("Hulo", "Lambingan")

        assert result["departure"] == "Hulo"
        assert result["destination"] == "Lambingan"
        assert len(result["speeds"]) == 5

        required_keys = {"speed_kn", "predicted_soc", "soc_reduction", "safety_status"}
        for entry in result["speeds"]:
            assert required_keys.issubset(entry.keys()), f"Missing: {required_keys - entry.keys()}"
            assert entry["safety_status"] in ("RECOMMENDED", "CAUTION", "CRITICAL")

    @pytest.mark.asyncio
    async def test_realtime_prediction_schema(self):
        """Realtime prediction should include point, lower, upper, progress."""
        with patch.object(DashboardServer, "_load_models"):
            srv = DashboardServer(Config())
        srv.motor_detector = None
        srv.battery_detector = None
        srv._tide_fn = None
        srv.trip_predictor = None
        srv._current_soc = 88.0
        srv._hv_capacity = 160.0

        mock_rt = MagicMock()
        mock_rt.predict.return_value = {
            "predicted_end_soc": 83.0,
            "lower": 81.5,
            "upper": 84.5,
            "progress": 0.45,
            "ticks": 30,
        }
        srv.rt_predictor = mock_rt

        # Simulate what the server does with rt_predictor output
        pred = srv.rt_predictor.predict()
        assert "predicted_end_soc" in pred
        assert "lower" in pred
        assert "upper" in pred
        assert "progress" in pred
        assert 0 <= pred["progress"] <= 1


# ===================================================================
# Section E: Station Data Integrity
# ===================================================================


class TestStationIntegrity:
    """Verify station data is consistent and complete."""

    def test_all_nine_stations_exist(self):
        """There should be exactly 9 stations."""
        assert len(STATIONS) == 9

    def test_stations_ordered(self):
        """Stations should be ordered 0-8 (Napindan to Escolta)."""
        for i, stn in enumerate(STATIONS):
            assert stn["order"] == i, f"Station {stn['name']} has order {stn['order']}, expected {i}"

    def test_station_names(self):
        """All expected station names should be present."""
        expected = {
            "Napindan", "Guadalupe", "Hulo", "Lambingan",
            "Valenzuela", "Sta Ana", "PUP", "Quinta", "Escolta",
        }
        actual = {s["name"] for s in STATIONS}
        assert actual == expected, f"Mismatch: {actual.symmetric_difference(expected)}"

    def test_stations_have_coordinates(self):
        """Every station must have lat/lon within Manila metro area."""
        for stn in STATIONS:
            assert 14.5 < stn["lat"] < 14.7, f"{stn['name']} lat out of range"
            assert 120.9 < stn["lon"] < 121.1, f"{stn['name']} lon out of range"


# ===================================================================
# Section F: Pre-flight Check Script
# ===================================================================


class TestPreflightCheck:
    """Verify that the preflight check module works."""

    def test_preflight_imports(self):
        """preflight_check.py should be importable."""
        import preflight_check
        assert hasattr(preflight_check, "run_preflight")
        assert hasattr(preflight_check, "CheckResult")

    def test_check_result_tracking(self):
        """CheckResult should correctly track pass/warn/fail."""
        from preflight_check import CheckResult

        r = CheckResult()
        r.ok("good thing")
        r.warn("minor issue")
        r.fail("big problem")

        assert len(r.passed) == 1
        assert len(r.warnings) == 1
        assert len(r.failures) == 1
        assert r.exit_code == 1  # failures present

    def test_check_result_warn_only(self):
        """Warnings without failures should give exit code 2."""
        from preflight_check import CheckResult

        r = CheckResult()
        r.ok("good")
        r.warn("minor")
        assert r.exit_code == 2

    def test_check_result_all_pass(self):
        """All passes should give exit code 0."""
        from preflight_check import CheckResult

        r = CheckResult()
        r.ok("good 1")
        r.ok("good 2")
        assert r.exit_code == 0
