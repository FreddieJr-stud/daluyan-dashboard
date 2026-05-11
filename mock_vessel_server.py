"""Mock vessel HTTP server for desktop end-to-end testing.

Simulates the vessel's telemetry API so dashboard_backend.py can run
without a real RPi5 connection.

Usage:
    python mock_vessel_server.py --mode docked
    python mock_vessel_server.py --mode trip --speed 8.0
    python mock_vessel_server.py --mode patrol --port 8481
"""
from __future__ import annotations

import argparse
import asyncio
import math
import time
from dataclasses import dataclass, field
from typing import Any

from aiohttp import web


# ---------------------------------------------------------------------------
# River waypoints (from Flutter main.dart OpenStreetMap relation)
# ---------------------------------------------------------------------------
RIVER_PATH: list[dict[str, Any]] = [
    {"lat": 14.5359379, "lon": 121.1021445, "station": "Napindan"},
    {"lat": 14.5358599, "lon": 121.1017740, "station": None},
    {"lat": 14.5372697, "lon": 121.0988241, "station": None},
    {"lat": 14.5391390, "lon": 121.0980034, "station": None},
    {"lat": 14.5407280, "lon": 121.0961446, "station": None},
    {"lat": 14.5427219, "lon": 121.0965443, "station": None},
    {"lat": 14.5451001, "lon": 121.0948062, "station": None},
    {"lat": 14.5526914, "lon": 121.0928535, "station": None},
    {"lat": 14.5529510, "lon": 121.0920489, "station": None},
    {"lat": 14.5520060, "lon": 121.0893130, "station": None},
    {"lat": 14.5532106, "lon": 121.0874918, "station": None},
    {"lat": 14.5532028, "lon": 121.0821411, "station": None},
    {"lat": 14.5538460, "lon": 121.0808408, "station": None},
    {"lat": 14.5534365, "lon": 121.0765940, "station": None},
    {"lat": 14.5546620, "lon": 121.0739286, "station": None},
    {"lat": 14.5550764, "lon": 121.0736239, "station": None},
    {"lat": 14.5573332, "lon": 121.0672545, "station": None},
    {"lat": 14.5603395, "lon": 121.0662997, "station": None},
    {"lat": 14.5612524, "lon": 121.0638741, "station": None},
    {"lat": 14.5626448, "lon": 121.0611713, "station": None},
    {"lat": 14.5642284, "lon": 121.0595030, "station": None},
    {"lat": 14.5667257, "lon": 121.0530710, "station": None},
    {"lat": 14.5683560, "lon": 121.0502064, "station": None},
    {"lat": 14.5684062, "lon": 121.0486719, "station": None},
    {"lat": 14.5681100, "lon": 121.0478946, "station": "Guadalupe"},
    {"lat": 14.5689783, "lon": 121.0430773, "station": None},
    {"lat": 14.5670395, "lon": 121.0364722, "station": None},
    {"lat": 14.5673488, "lon": 121.0339603, "station": None},
    {"lat": 14.5679545, "lon": 121.0336782, "station": "Hulo"},
    {"lat": 14.5679866, "lon": 121.0336158, "station": None},
    {"lat": 14.5730310, "lon": 121.0274336, "station": None},
    {"lat": 14.5739778, "lon": 121.0257656, "station": "Valenzuela"},
    {"lat": 14.5744081, "lon": 121.0253843, "station": None},
    {"lat": 14.5749968, "lon": 121.0247592, "station": None},
    {"lat": 14.5760368, "lon": 121.0231134, "station": None},
    {"lat": 14.5794938, "lon": 121.0178348, "station": None},
    {"lat": 14.5797947, "lon": 121.0174394, "station": None},
    {"lat": 14.5800531, "lon": 121.0172198, "station": None},
    {"lat": 14.5804296, "lon": 121.0171431, "station": None},
    {"lat": 14.5808805, "lon": 121.0171961, "station": None},
    {"lat": 14.5811553, "lon": 121.0172874, "station": None},
    {"lat": 14.5814038, "lon": 121.0174699, "station": None},
    {"lat": 14.5824962, "lon": 121.0185242, "station": None},
    {"lat": 14.5836962, "lon": 121.0195418, "station": None},
    {"lat": 14.5847201, "lon": 121.0201531, "station": None},
    {"lat": 14.5850930, "lon": 121.0202545, "station": None},
    {"lat": 14.5855947, "lon": 121.0202579, "station": None},
    {"lat": 14.5859956, "lon": 121.0201903, "station": None},
    {"lat": 14.5863259, "lon": 121.0200111, "station": None},
    {"lat": 14.5868590, "lon": 121.0195042, "station": None},
    {"lat": 14.5870520, "lon": 121.0190582, "station": None},
    {"lat": 14.5872813, "lon": 121.0184560, "station": "Lambingan"},
    {"lat": 14.5870618, "lon": 121.0183654, "station": None},
    {"lat": 14.5867589, "lon": 121.0180509, "station": None},
    {"lat": 14.5866530, "lon": 121.0177301, "station": None},
    {"lat": 14.5865581, "lon": 121.0173279, "station": None},
    {"lat": 14.5864044, "lon": 121.0165946, "station": None},
    {"lat": 14.5862278, "lon": 121.0157937, "station": None},
    {"lat": 14.5857792, "lon": 121.0144361, "station": None},
    {"lat": 14.5854298, "lon": 121.0138269, "station": None},
    {"lat": 14.5850449, "lon": 121.0133851, "station": None},
    {"lat": 14.5845076, "lon": 121.0129908, "station": None},
    {"lat": 14.5836094, "lon": 121.0123068, "station": None},
    {"lat": 14.5832226, "lon": 121.0120869, "station": None},
    {"lat": 14.5829319, "lon": 121.0119554, "station": None},
    {"lat": 14.5827238, "lon": 121.0119451, "station": "Sta Ana"},
    {"lat": 14.5827009, "lon": 121.0117194, "station": None},
    {"lat": 14.5826386, "lon": 121.0114914, "station": None},
    {"lat": 14.5823427, "lon": 121.0109496, "station": None},
    {"lat": 14.5821363, "lon": 121.0103770, "station": None},
    {"lat": 14.5820844, "lon": 121.0100162, "station": None},
    {"lat": 14.5820850, "lon": 121.0096693, "station": None},
    {"lat": 14.5821661, "lon": 121.0091016, "station": None},
    {"lat": 14.5823647, "lon": 121.0085839, "station": None},
    {"lat": 14.5828141, "lon": 121.0080478, "station": None},
    {"lat": 14.5832655, "lon": 121.0077593, "station": None},
    {"lat": 14.5837825, "lon": 121.0074774, "station": None},
    {"lat": 14.5845401, "lon": 121.0072023, "station": None},
    {"lat": 14.5850616, "lon": 121.0070779, "station": None},
    {"lat": 14.5854322, "lon": 121.0070675, "station": None},
    {"lat": 14.5859946, "lon": 121.0071307, "station": None},
    {"lat": 14.5864162, "lon": 121.0072377, "station": None},
    {"lat": 14.5869669, "lon": 121.0075987, "station": None},
    {"lat": 14.5874215, "lon": 121.0081191, "station": None},
    {"lat": 14.5876744, "lon": 121.0086966, "station": None},
    {"lat": 14.5877486, "lon": 121.0090417, "station": None},
    {"lat": 14.5879709, "lon": 121.0101468, "station": None},
    {"lat": 14.5881018, "lon": 121.0105624, "station": None},
    {"lat": 14.5883634, "lon": 121.0112755, "station": None},
    {"lat": 14.5889021, "lon": 121.0123242, "station": None},
    {"lat": 14.5893347, "lon": 121.0130767, "station": None},
    {"lat": 14.5899076, "lon": 121.0138971, "station": None},
    {"lat": 14.5900024, "lon": 121.0140105, "station": None},
    {"lat": 14.5909293, "lon": 121.0154007, "station": None},
    {"lat": 14.5913994, "lon": 121.0159120, "station": None},
    {"lat": 14.5917221, "lon": 121.0160505, "station": None},
    {"lat": 14.5920852, "lon": 121.0160768, "station": None},
    {"lat": 14.5923830, "lon": 121.0160056, "station": None},
    {"lat": 14.5926934, "lon": 121.0158038, "station": None},
    {"lat": 14.5928554, "lon": 121.0156006, "station": None},
    {"lat": 14.5933486, "lon": 121.0147584, "station": None},
    {"lat": 14.5939300, "lon": 121.0132295, "station": None},
    {"lat": 14.5946724, "lon": 121.0117971, "station": None},
    {"lat": 14.5952125, "lon": 121.0111276, "station": None},
    {"lat": 14.5956302, "lon": 121.0108497, "station": None},
    {"lat": 14.5960355, "lon": 121.0107013, "station": "PUP"},
    {"lat": 14.5960455, "lon": 121.0100521, "station": None},
    {"lat": 14.5961436, "lon": 121.0093864, "station": None},
    {"lat": 14.5965003, "lon": 121.0080680, "station": None},
    {"lat": 14.5971576, "lon": 121.0060760, "station": None},
    {"lat": 14.5972317, "lon": 121.0054457, "station": None},
    {"lat": 14.5971202, "lon": 121.0046192, "station": None},
    {"lat": 14.5969115, "lon": 121.0039119, "station": None},
    {"lat": 14.5965958, "lon": 121.0032329, "station": None},
    {"lat": 14.5959877, "lon": 121.0022691, "station": None},
    {"lat": 14.5958586, "lon": 121.0019401, "station": None},
    {"lat": 14.5958411, "lon": 121.0016260, "station": None},
    {"lat": 14.5958903, "lon": 121.0010451, "station": None},
    {"lat": 14.5961213, "lon": 121.0003572, "station": None},
    {"lat": 14.5964385, "lon": 120.9996164, "station": None},
    {"lat": 14.5965576, "lon": 120.9993010, "station": None},
    {"lat": 14.5966309, "lon": 120.9988259, "station": None},
    {"lat": 14.5966381, "lon": 120.9986337, "station": None},
    {"lat": 14.5965727, "lon": 120.9982134, "station": None},
    {"lat": 14.5964412, "lon": 120.9979303, "station": None},
    {"lat": 14.5962782, "lon": 120.9976409, "station": None},
    {"lat": 14.5951241, "lon": 120.9962527, "station": None},
    {"lat": 14.5947245, "lon": 120.9958781, "station": None},
    {"lat": 14.5935381, "lon": 120.9951407, "station": None},
    {"lat": 14.5927475, "lon": 120.9946203, "station": None},
    {"lat": 14.5922974, "lon": 120.9942234, "station": None},
    {"lat": 14.5919592, "lon": 120.9938664, "station": None},
    {"lat": 14.5915576, "lon": 120.9932739, "station": None},
    {"lat": 14.5913396, "lon": 120.9926677, "station": None},
    {"lat": 14.5912357, "lon": 120.9921446, "station": None},
    {"lat": 14.5912150, "lon": 120.9916458, "station": None},
    {"lat": 14.5912917, "lon": 120.9905392, "station": None},
    {"lat": 14.5913581, "lon": 120.9896298, "station": None},
    {"lat": 14.5913896, "lon": 120.9887017, "station": None},
    {"lat": 14.5913891, "lon": 120.9876640, "station": None},
    {"lat": 14.5914236, "lon": 120.9870050, "station": None},
    {"lat": 14.5915954, "lon": 120.9862286, "station": None},
    {"lat": 14.5918431, "lon": 120.9855545, "station": None},
    {"lat": 14.5924012, "lon": 120.9847069, "station": None},
    {"lat": 14.5931649, "lon": 120.9838223, "station": None},
    {"lat": 14.5937273, "lon": 120.9833497, "station": None},
    {"lat": 14.5945288, "lon": 120.9827962, "station": None},
    {"lat": 14.5952189, "lon": 120.9822895, "station": None},
    {"lat": 14.5952869, "lon": 120.9822490, "station": None},
    {"lat": 14.5954166, "lon": 120.9822001, "station": None},
    {"lat": 14.5959362, "lon": 120.9822120, "station": None},
    {"lat": 14.5957803, "lon": 120.9814485, "station": "Quinta"},
    {"lat": 14.5959182, "lon": 120.9815919, "station": None},
    {"lat": 14.5960520, "lon": 120.9816156, "station": None},
    {"lat": 14.5961707, "lon": 120.9815969, "station": None},
    {"lat": 14.5962570, "lon": 120.9815352, "station": None},
    {"lat": 14.5963157, "lon": 120.9814643, "station": None},
    {"lat": 14.5968008, "lon": 120.9806299, "station": None},
    {"lat": 14.5969237, "lon": 120.9802064, "station": None},
    {"lat": 14.5969391, "lon": 120.9798966, "station": None},
    {"lat": 14.5969000, "lon": 120.9795901, "station": None},
    {"lat": 14.5967929, "lon": 120.9792729, "station": None},
    {"lat": 14.5964359, "lon": 120.9783990, "station": None},
    {"lat": 14.5963561, "lon": 120.9781467, "station": None},
    {"lat": 14.5963212, "lon": 120.9779113, "station": None},
    {"lat": 14.5963832, "lon": 120.9775262, "station": "Escolta"},
]

# Pre-compute cumulative segment distances for interpolation
_SEGMENT_DISTS: list[float] = [0.0]
for i in range(1, len(RIVER_PATH)):
    p0, p1 = RIVER_PATH[i - 1], RIVER_PATH[i]
    R = 6_371_000
    phi1, phi2 = math.radians(p0["lat"]), math.radians(p1["lat"])
    dphi = math.radians(p1["lat"] - p0["lat"])
    dlam = math.radians(p1["lon"] - p0["lon"])
    a = (math.sin(dphi / 2) ** 2
         + math.cos(phi1) * math.cos(phi2) * math.sin(dlam / 2) ** 2)
    d = R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    _SEGMENT_DISTS.append(_SEGMENT_DISTS[-1] + d)

TOTAL_ROUTE_M = _SEGMENT_DISTS[-1]

# Station indices in RIVER_PATH
STATION_INDICES = {
    wp["station"]: i for i, wp in enumerate(RIVER_PATH) if wp["station"]
}


def _interpolate_position(dist_m: float) -> tuple[float, float, float]:
    """Interpolate (lat, lon, bearing) along the river path at a given distance."""
    dist_m = max(0.0, min(dist_m, TOTAL_ROUTE_M))
    for i in range(1, len(_SEGMENT_DISTS)):
        if _SEGMENT_DISTS[i] >= dist_m:
            seg_start = _SEGMENT_DISTS[i - 1]
            seg_len = _SEGMENT_DISTS[i] - seg_start
            t = (dist_m - seg_start) / seg_len if seg_len > 0 else 0.0
            p0, p1 = RIVER_PATH[i - 1], RIVER_PATH[i]
            lat = p0["lat"] + t * (p1["lat"] - p0["lat"])
            lon = p0["lon"] + t * (p1["lon"] - p0["lon"])
            # Bearing
            phi1, phi2 = math.radians(p0["lat"]), math.radians(p1["lat"])
            dlam = math.radians(p1["lon"] - p0["lon"])
            x = math.sin(dlam) * math.cos(phi2)
            y = (math.cos(phi1) * math.sin(phi2)
                 - math.sin(phi1) * math.cos(phi2) * math.cos(dlam))
            bearing = (math.degrees(math.atan2(x, y)) + 360) % 360
            return lat, lon, bearing
    # Fallback: last point
    p = RIVER_PATH[-1]
    return p["lat"], p["lon"], 0.0


# ---------------------------------------------------------------------------
# Vessel State
# ---------------------------------------------------------------------------

@dataclass
class VesselState:
    lat: float = 14.5359379
    lon: float = 121.1021445
    heading: float = 0.0
    speed_kn: float = 0.0
    soc: float = 95.0
    port_power: float = 0.0
    stbd_power: float = 0.0
    port_rpm: float = 0.0
    stbd_rpm: float = 0.0
    battery_power: float = 0.0
    trip_nm: float = 0.0
    hv_capacity: float = 160.0
    # BMS fields
    port_cell_balance: float = 0.015
    port_max_cell_temp: float = 28.0
    port_min_cell_temp: float = 27.0
    port_pack_voltage: float = 614.0
    port_pack_current: float = 0.0
    port_soc: float = 95.0
    port_power_bms: float = 0.0
    port_avg_temp: float = 27.5
    stbd_cell_balance: float = 0.014
    stbd_max_cell_temp: float = 28.5
    stbd_min_cell_temp: float = 27.0
    stbd_pack_voltage: float = 612.0
    stbd_pack_current: float = 0.0
    stbd_soc: float = 95.0
    stbd_power_bms: float = 0.0
    stbd_avg_temp: float = 27.8

    def vessel_json(self) -> dict[str, Any]:
        return {
            "batteryStateOfChargePercent": round(self.soc, 1),
            "speedOverGround": round(self.speed_kn, 2),
            "currentPositionLatitude": round(self.lat, 7),
            "currentPositionLongitude": round(self.lon, 7),
            "currentHeading": round(self.heading, 1),
            "portMotorPower": round(self.port_power, 1),
            "stbdMotorPower": round(self.stbd_power, 1),
            "motorPowerCombined": round(self.port_power + self.stbd_power, 1),
            "portRpmShaft": round(self.port_rpm, 0),
            "stbdRpmShaft": round(self.stbd_rpm, 0),
            "currentBatteryPower": round(self.battery_power, 1),
            "trip": round(self.trip_nm, 3),
            "hvBatteryCapacity": self.hv_capacity,
        }

    def bms_json(self, side: str) -> dict[str, Any]:
        if side == "port":
            return {
                "gCellBalance": self.port_cell_balance,
                "gMaxCellTemperature": self.port_max_cell_temp,
                "gMinCellTemperature": self.port_min_cell_temp,
                "gPackVoltage": self.port_pack_voltage,
                "gCurrent": self.port_pack_current,
                "gStateOfCharge": self.port_soc,
                "gPower": self.port_power_bms,
                "gAverageTemperature": self.port_avg_temp,
            }
        return {
            "gCellBalance": self.stbd_cell_balance,
            "gMaxCellTemperature": self.stbd_max_cell_temp,
            "gMinCellTemperature": self.stbd_min_cell_temp,
            "gPackVoltage": self.stbd_pack_voltage,
            "gCurrent": self.stbd_pack_current,
            "gStateOfCharge": self.stbd_soc,
            "gPower": self.stbd_power_bms,
            "gAverageTemperature": self.stbd_avg_temp,
        }


# ---------------------------------------------------------------------------
# Trip Simulator
# ---------------------------------------------------------------------------

class TripSimulator:
    """Simulates a trip along the river path with realistic physics."""

    def __init__(
        self,
        cruise_speed_kn: float = 8.0,
        dwell_s: float = 30.0,
        loop: bool = False,
    ) -> None:
        self.cruise_speed_kn = cruise_speed_kn
        self.dwell_s = dwell_s
        self.loop = loop

        self.state = VesselState()
        self._dist_m = 0.0  # distance along river path
        self._direction = 1  # 1 = downstream, -1 = upstream
        self._phase = "docked"  # docked, ramp_up, cruise, ramp_down, dwell
        self._phase_timer = 0.0
        self._ramp_duration = 10.0  # seconds to ramp up/down
        self._current_speed_ms = 0.0
        self._trip_start_dist = 0.0
        self._dwell_at_idx = 0  # Index in station list for next stop

        # Build ordered station distances (downstream)
        self._station_dists: list[tuple[str, float]] = []
        for wp_i, wp in enumerate(RIVER_PATH):
            if wp["station"]:
                self._station_dists.append((wp["station"], _SEGMENT_DISTS[wp_i]))

        # Find next station to target (Guadalupe for downstream start)
        self._target_station_idx = 1 if self._direction == 1 else len(self._station_dists) - 2
        self._target_dist = self._station_dists[self._target_station_idx][1]

    def tick(self) -> VesselState:
        """Advance simulation by 1 second. Returns updated state."""
        cruise_ms = self.cruise_speed_kn * 0.5144  # kn to m/s

        if self._phase == "docked":
            self._phase_timer += 1.0
            self.state.speed_kn = 0.0
            self._current_speed_ms = 0.0
            self._update_motor_off()

            if self._phase_timer >= self.dwell_s:
                self._phase = "ramp_up"
                self._phase_timer = 0.0
                self._trip_start_dist = self._dist_m

        elif self._phase == "ramp_up":
            self._phase_timer += 1.0
            frac = min(self._phase_timer / self._ramp_duration, 1.0)
            self._current_speed_ms = frac * cruise_ms
            self.state.speed_kn = self._current_speed_ms / 0.5144

            if frac >= 1.0:
                self._phase = "cruise"
                self._phase_timer = 0.0

        elif self._phase == "cruise":
            self._current_speed_ms = cruise_ms
            self.state.speed_kn = self.cruise_speed_kn

            # Check if approaching target station
            remaining = abs(self._target_dist - self._dist_m)
            ramp_dist = cruise_ms * self._ramp_duration / 2  # distance to decelerate
            if remaining <= ramp_dist:
                self._phase = "ramp_down"
                self._phase_timer = 0.0

        elif self._phase == "ramp_down":
            self._phase_timer += 1.0
            frac = max(1.0 - self._phase_timer / self._ramp_duration, 0.0)
            self._current_speed_ms = frac * cruise_ms
            self.state.speed_kn = self._current_speed_ms / 0.5144

            if frac <= 0.0:
                self._phase = "dwell"
                self._phase_timer = 0.0
                self._current_speed_ms = 0.0
                self.state.speed_kn = 0.0

        elif self._phase == "dwell":
            self._phase_timer += 1.0
            self.state.speed_kn = 0.0
            self._current_speed_ms = 0.0
            self._update_motor_off()

            if self._phase_timer >= self.dwell_s:
                self._advance_target()
                self._phase = "ramp_up"
                self._phase_timer = 0.0
                self._trip_start_dist = self._dist_m

        # Move along path
        if self._current_speed_ms > 0:
            self._dist_m += self._direction * self._current_speed_ms
            self._dist_m = max(0.0, min(self._dist_m, TOTAL_ROUTE_M))
            self._update_motor_running()

        # Update position from path
        lat, lon, bearing = _interpolate_position(self._dist_m)
        if self._direction == -1:
            bearing = (bearing + 180) % 360
        self.state.lat = lat
        self.state.lon = lon
        self.state.heading = bearing

        # Trip distance
        trip_m = abs(self._dist_m - self._trip_start_dist)
        self.state.trip_nm = trip_m / 1852.0

        # SOC drain: ~2.5%/hop downstream, ~3.5%/hop upstream
        # Average hop ~2000m, so rate = 2.5%/2000m downstream
        if self._current_speed_ms > 0:
            drain_rate = 3.5 / 2000.0 if self._direction == -1 else 2.5 / 2000.0
            self.state.soc -= drain_rate * self._current_speed_ms
            self.state.soc = max(0.0, self.state.soc)

        # BMS tracking
        self._update_bms()

        # SOC reset for patrol mode
        if self.loop and self.state.soc < 30.0:
            self.state.soc = 95.0
            self.state.port_soc = 95.0
            self.state.stbd_soc = 95.0

        return self.state

    def _advance_target(self) -> None:
        """Move to the next station target, reversing at endpoints."""
        if self._direction == 1:
            self._target_station_idx += 1
            if self._target_station_idx >= len(self._station_dists):
                if self.loop:
                    self._direction = -1
                    self._target_station_idx = len(self._station_dists) - 2
                else:
                    # Reverse for trip mode
                    self._direction = -1
                    self._target_station_idx = len(self._station_dists) - 2
        else:
            self._target_station_idx -= 1
            if self._target_station_idx < 0:
                if self.loop:
                    self._direction = 1
                    self._target_station_idx = 1
                else:
                    self._direction = 1
                    self._target_station_idx = 1

        self._target_dist = self._station_dists[self._target_station_idx][1]

    def _update_motor_running(self) -> None:
        power_per_side = 5.0 * self.state.speed_kn  # ~5kW per kn per side
        self.state.port_power = power_per_side
        self.state.stbd_power = power_per_side
        self.state.port_rpm = self.state.speed_kn * 120  # RPM ∝ speed
        self.state.stbd_rpm = self.state.speed_kn * 120
        self.state.battery_power = -(self.state.port_power + self.state.stbd_power)

    def _update_motor_off(self) -> None:
        self.state.port_power = 0.0
        self.state.stbd_power = 0.0
        self.state.port_rpm = 0.0
        self.state.stbd_rpm = 0.0
        self.state.battery_power = 0.0

    def _update_bms(self) -> None:
        """Update BMS fields with realistic values."""
        t = time.time()
        load = self.state.port_power + self.state.stbd_power

        # Voltage sags under load
        v_base = 614.0
        v_sag = load * 0.02  # ~0.02V per kW
        self.state.port_pack_voltage = v_base - v_sag + 0.5 * math.sin(t * 0.1)
        self.state.stbd_pack_voltage = v_base - v_sag - 0.3 * math.sin(t * 0.1)

        # Current = power / voltage
        if self.state.port_pack_voltage > 0:
            self.state.port_pack_current = (
                self.state.port_power * 1000 / self.state.port_pack_voltage
            )
        if self.state.stbd_pack_voltage > 0:
            self.state.stbd_pack_current = (
                self.state.stbd_power * 1000 / self.state.stbd_pack_voltage
            )

        # BMS power
        self.state.port_power_bms = self.state.port_power
        self.state.stbd_power_bms = self.state.stbd_power

        # Cell balance: slight drift
        self.state.port_cell_balance = 0.015 + 0.003 * math.sin(t * 0.05)
        self.state.stbd_cell_balance = 0.014 + 0.002 * math.sin(t * 0.07)

        # Temperature rises under load
        temp_rise = load * 0.05  # ~0.05°C per kW
        base_temp = 27.0 + 2.0 * math.sin(t * 0.01)
        self.state.port_max_cell_temp = base_temp + temp_rise + 1.0
        self.state.port_min_cell_temp = base_temp + temp_rise - 0.5
        self.state.port_avg_temp = base_temp + temp_rise + 0.25
        self.state.stbd_max_cell_temp = base_temp + temp_rise + 1.2
        self.state.stbd_min_cell_temp = base_temp + temp_rise - 0.3
        self.state.stbd_avg_temp = base_temp + temp_rise + 0.45

        # SOC tracking
        self.state.port_soc = self.state.soc
        self.state.stbd_soc = self.state.soc


# ---------------------------------------------------------------------------
# Docked Simulator (static with BMS drift)
# ---------------------------------------------------------------------------

class DockedSimulator:
    """Static at Napindan with slow BMS drift."""

    def __init__(self) -> None:
        self.state = VesselState()

    def tick(self) -> VesselState:
        t = time.time()
        # Slow sinusoidal BMS drift
        self.state.port_cell_balance = 0.015 + 0.002 * math.sin(t * 0.02)
        self.state.stbd_cell_balance = 0.014 + 0.001 * math.sin(t * 0.03)
        self.state.port_max_cell_temp = 28.0 + 0.5 * math.sin(t * 0.01)
        self.state.port_min_cell_temp = 27.0 + 0.3 * math.sin(t * 0.01)
        self.state.port_avg_temp = 27.5 + 0.4 * math.sin(t * 0.01)
        self.state.stbd_max_cell_temp = 28.5 + 0.4 * math.sin(t * 0.015)
        self.state.stbd_min_cell_temp = 27.0 + 0.2 * math.sin(t * 0.015)
        self.state.stbd_avg_temp = 27.8 + 0.3 * math.sin(t * 0.015)
        return self.state


# ---------------------------------------------------------------------------
# HTTP Server
# ---------------------------------------------------------------------------

class MockVesselApp:
    """aiohttp application serving mock vessel telemetry."""

    def __init__(self, simulator: TripSimulator | DockedSimulator) -> None:
        self.simulator = simulator
        self.app = web.Application()
        self.app.router.add_get("/vessel", self._handle_vessel)
        self.app.router.add_get(
            "/device/OneAries_IP_3_ID_49", self._handle_bms_port)
        self.app.router.add_get(
            "/device/OneAries_IP_4_ID_49", self._handle_bms_stbd)
        self.app.on_startup.append(self._start_ticker)
        self.app.on_shutdown.append(self._stop_ticker)
        self._tick_task: asyncio.Task | None = None

    async def _start_ticker(self, app: web.Application) -> None:
        self._tick_task = asyncio.create_task(self._tick_loop())

    async def _stop_ticker(self, app: web.Application) -> None:
        if self._tick_task:
            self._tick_task.cancel()
            try:
                await self._tick_task
            except asyncio.CancelledError:
                pass

    async def _tick_loop(self) -> None:
        while True:
            self.simulator.tick()
            await asyncio.sleep(1)

    async def _handle_vessel(self, request: web.Request) -> web.Response:
        return web.json_response(self.simulator.state.vessel_json())

    async def _handle_bms_port(self, request: web.Request) -> web.Response:
        return web.json_response(self.simulator.state.bms_json("port"))

    async def _handle_bms_stbd(self, request: web.Request) -> web.Response:
        return web.json_response(self.simulator.state.bms_json("stbd"))


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Mock vessel server for dashboard testing",
    )
    parser.add_argument(
        "--mode", choices=["docked", "trip", "patrol"], default="docked",
        help="Simulation mode (default: docked)",
    )
    parser.add_argument(
        "--port", type=int, default=8481,
        help="HTTP port (default: 8481)",
    )
    parser.add_argument(
        "--dwell", type=float, default=30.0,
        help="Dwell time at stations in seconds (default: 30)",
    )
    parser.add_argument(
        "--speed", type=float, default=8.0,
        help="Cruise speed in knots (default: 8.0)",
    )
    args = parser.parse_args()

    if args.mode == "docked":
        sim = DockedSimulator()
        print(f"[mock] Docked mode — static at Napindan, SOC=95%")
    elif args.mode == "trip":
        sim = TripSimulator(
            cruise_speed_kn=args.speed, dwell_s=args.dwell, loop=False)
        print(f"[mock] Trip mode — {args.speed}kn, {args.dwell}s dwell")
    else:  # patrol
        sim = TripSimulator(
            cruise_speed_kn=args.speed, dwell_s=args.dwell, loop=True)
        print(f"[mock] Patrol mode — continuous loop, SOC resets at 30%")

    app = MockVesselApp(sim)
    print(f"[mock] Listening on http://0.0.0.0:{args.port}")
    print(f"[mock] Endpoints: /vessel, /device/OneAries_IP_3_ID_49, "
          f"/device/OneAries_IP_4_ID_49")
    web.run_app(app.app, host="0.0.0.0", port=args.port, print=None)


if __name__ == "__main__":
    main()
