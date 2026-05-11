# Charging Estimator Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add real-time charging speed display and time-to-full/target estimation to the dashboard, plus thesis-ready charging analysis artifacts.

**Architecture:** Empirical SOC-vs-power lookup curve built offline from 58 charging sessions (22K telemetry rows). Lightweight `ChargingEstimator` class loaded by `dashboard_backend.py` at startup. New `charging_status` Socket.IO event emitted during charging. Flutter UI shows a charging panel when ferry is plugged in. Separate analysis script generates thesis figures.

**Tech Stack:** Python (DuckDB, NumPy, matplotlib), Dart/Flutter, JSON artifacts

---

## File Map

| File | Action | Responsibility |
|---|---|---|
| `Models/evaluate/build_charging_curve.py` | Create | Query DuckDB, build SOC→power lookup, save JSON |
| `Models/artifacts/charging_curve.json` | Create (generated) | Lookup table: SOC bin → median/p25/p75 kW |
| `Models/rpi5_bundle/inference/charging_estimator.py` | Create | Lightweight estimator class for RPi5 |
| `Models/rpi5_bundle/charging_curve.json` | Create (copy) | RPi5 deployment copy |
| `Models/tests/test_charging_estimator.py` | Create | Unit tests for estimator |
| `Dashboard/dashboard_backend.py` | Modify | Add charging state detection + emit |
| `Dashboard/flutter_application_1/lib/services/socket_service.dart` | Modify | Add `onChargingStatus` callback |
| `Dashboard/flutter_application_1/lib/models/dashboard_data.dart` | Modify | Add charging fields |
| `Dashboard/flutter_application_1/lib/providers/dashboard_provider.dart` | Modify | Handle `charging_status` event |
| `Dashboard/flutter_application_1/lib/widgets/charging_panel.dart` | Create | Charging UI widget |
| `Dashboard/flutter_application_1/lib/main.dart` | Modify | Show charging panel when `isCharging` |
| `Models/evaluate/analyze_charging.py` | Create | Thesis plots + stats |

---

### Task 1: Build the Charging Curve from DuckDB

**Files:**
- Create: `Models/evaluate/build_charging_curve.py`
- Output: `Models/artifacts/charging_curve.json`

- [ ] **Step 1: Create the build script**

```python
"""Build empirical charging power-vs-SOC lookup curve from DuckDB telemetry.

Queries charging_telemetry, buckets by 1% SOC, computes median/p25/p75 power.
Output: artifacts/charging_curve.json

Usage:
    python -m evaluate.build_charging_curve
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import duckdb
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from config import ARTIFACTS_DIR, DUCKDB_PATH, BATTERY_CAPACITY_KWH

def build_curve() -> dict:
    """Build SOC-to-charging-power lookup from historical telemetry."""
    conn = duckdb.connect(DUCKDB_PATH, read_only=True)

    df = conn.execute("""
        SELECT
            CAST(FLOOR(soc_percent) AS INT) AS soc_bin,
            COUNT(*) AS n,
            MEDIAN(charger_power_kw) AS median_kw,
            PERCENTILE_CONT(0.25) WITHIN GROUP (ORDER BY charger_power_kw) AS p25_kw,
            PERCENTILE_CONT(0.75) WITHIN GROUP (ORDER BY charger_power_kw) AS p75_kw
        FROM charging_telemetry
        WHERE charger_power_kw > 10
          AND soc_percent IS NOT NULL
          AND soc_percent >= 20
          AND soc_percent < 100
        GROUP BY soc_bin
        ORDER BY soc_bin
    """).fetchdf()
    conn.close()

    curve = {
        "battery_capacity_kwh": BATTERY_CAPACITY_KWH,
        "bins": df["soc_bin"].tolist(),
        "median_kw": [round(v, 2) for v in df["median_kw"].tolist()],
        "p25_kw": [round(v, 2) for v in df["p25_kw"].tolist()],
        "p75_kw": [round(v, 2) for v in df["p75_kw"].tolist()],
        "sample_counts": df["n"].tolist(),
    }

    out_path = ARTIFACTS_DIR / "charging_curve.json"
    with open(out_path, "w") as f:
        json.dump(curve, f, indent=2)
    print(f"Saved charging curve ({len(curve['bins'])} bins) to {out_path}")

    # Also copy to rpi5_bundle
    rpi5_path = Path(__file__).resolve().parent.parent / "rpi5_bundle" / "charging_curve.json"
    with open(rpi5_path, "w") as f:
        json.dump(curve, f, indent=2)
    print(f"Copied to {rpi5_path}")

    return curve


if __name__ == "__main__":
    curve = build_curve()
    print(f"\nSOC range: {curve['bins'][0]}% – {curve['bins'][-1]}%")
    print(f"Peak median power: {max(curve['median_kw']):.1f} kW")
    print(f"Min median power: {min(curve['median_kw']):.1f} kW")
```

Note: We filter `charger_power_kw > 10` to exclude the taper rows at 98-100% SOC (2-5 kW) and the anomalous transition at 40% SOC (5.67 kW). The estimator handles the final taper with a fallback.

- [ ] **Step 2: Run the build script**

Run: `cd Models && python -m evaluate.build_charging_curve`

Expected: `Saved charging curve (N bins) to artifacts/charging_curve.json`

- [ ] **Step 3: Verify the output JSON**

Check `artifacts/charging_curve.json` has bins from ~22 to ~97, median_kw values, and no bins with anomalously low power.

- [ ] **Step 4: Commit**

```bash
git add Models/evaluate/build_charging_curve.py Models/artifacts/charging_curve.json Models/rpi5_bundle/charging_curve.json
git commit -m "feat(charging): build empirical SOC-vs-power lookup curve from 58 sessions"
```

---

### Task 2: Charging Estimator Class + Tests

**Files:**
- Create: `Models/rpi5_bundle/inference/charging_estimator.py`
- Create: `Models/tests/test_charging_estimator.py`

- [ ] **Step 1: Write the test file**

```python
"""Tests for ChargingEstimator."""
import json
import os
import tempfile
import pytest

# Add parent paths
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "rpi5_bundle"))

from inference.charging_estimator import ChargingEstimator


@pytest.fixture
def sample_curve(tmp_path):
    """Create a simple test charging curve."""
    curve = {
        "battery_capacity_kwh": 160.0,
        "bins": [20, 21, 22, 23, 24, 25, 50, 75, 95, 96, 97],
        "median_kw": [100.0, 100.0, 100.0, 100.0, 100.0, 100.0, 200.0, 300.0, 300.0, 300.0, 300.0],
        "p25_kw": [90.0, 90.0, 90.0, 90.0, 90.0, 90.0, 180.0, 280.0, 280.0, 280.0, 280.0],
        "p75_kw": [110.0, 110.0, 110.0, 110.0, 110.0, 110.0, 220.0, 320.0, 320.0, 320.0, 320.0],
        "sample_counts": [50, 50, 50, 50, 50, 50, 100, 150, 200, 200, 200],
    }
    path = tmp_path / "charging_curve.json"
    with open(path, "w") as f:
        json.dump(curve, f)
    return path


@pytest.fixture
def estimator(sample_curve):
    return ChargingEstimator(str(sample_curve))


def test_loads_curve(estimator):
    """Estimator loads the curve JSON and builds lookup."""
    assert estimator.capacity_kwh == 160.0
    assert len(estimator._power_at_soc) > 0


def test_estimate_minutes_basic(estimator):
    """Estimate from 20% to 25% at 100 kW = 5% * 1.6 kWh / 100 kW * 60 = 4.8 min."""
    mins = estimator.estimate_minutes(current_soc=20.0, target_soc=25.0)
    assert mins is not None
    assert abs(mins - 4.8) < 0.5  # Allow small interpolation error


def test_estimate_minutes_partial_first_bin(estimator):
    """Starting at 20.5% should give ~half of the first bin's time."""
    full = estimator.estimate_minutes(current_soc=20.0, target_soc=25.0)
    partial = estimator.estimate_minutes(current_soc=20.5, target_soc=25.0)
    assert partial < full


def test_estimate_to_full(estimator):
    """estimate_to_full always targets 100%."""
    result = estimator.estimate_to_full(current_soc=95.0)
    assert result is not None
    assert result > 0


def test_current_soc_equals_target_returns_zero(estimator):
    """If already at target, return 0."""
    mins = estimator.estimate_minutes(current_soc=50.0, target_soc=50.0)
    assert mins == 0.0


def test_current_soc_above_target_returns_zero(estimator):
    """If SOC is already above target, return 0."""
    mins = estimator.estimate_minutes(current_soc=80.0, target_soc=50.0)
    assert mins == 0.0


def test_charging_power_at_soc(estimator):
    """get_power_at_soc returns interpolated power."""
    power = estimator.get_power_at_soc(20.0)
    assert power > 0


def test_get_power_interpolates(estimator):
    """Power between known bins is linearly interpolated."""
    # Between bin 25 (100 kW) and bin 50 (200 kW)
    power = estimator.get_power_at_soc(37.5)
    assert 100 < power < 200
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd Models && python -m pytest tests/test_charging_estimator.py -v`

Expected: FAIL — `ModuleNotFoundError: No module named 'inference.charging_estimator'`

- [ ] **Step 3: Create the estimator class**

```python
"""Charging time estimator for RPi5 deployment.

Uses an empirical SOC-vs-charging-power lookup curve (built from historical
telemetry) to estimate time-to-target and time-to-full.

Dependencies: json, math only (no numpy/xgboost).
"""
from __future__ import annotations

import json
import math
from pathlib import Path


class ChargingEstimator:
    """Estimates charging time from an empirical power curve."""

    def __init__(self, curve_path: str):
        with open(curve_path) as f:
            curve = json.load(f)

        self.capacity_kwh: float = curve["battery_capacity_kwh"]
        self._bins: list[int] = curve["bins"]
        self._median_kw: list[float] = curve["median_kw"]

        # Build SOC → power lookup (integer keys)
        self._power_at_soc: dict[int, float] = dict(
            zip(self._bins, self._median_kw)
        )

        # Fallback power for SOC bins outside the curve (e.g., 98-100% taper)
        self._min_power: float = min(self._median_kw)
        self._max_soc_bin: int = max(self._bins)
        self._min_soc_bin: int = min(self._bins)

    def get_power_at_soc(self, soc: float) -> float:
        """Get estimated charging power (kW) at a given SOC%.

        Uses linear interpolation between known bins.
        """
        soc_int = int(math.floor(soc))

        # Direct lookup
        if soc_int in self._power_at_soc:
            return self._power_at_soc[soc_int]

        # Interpolate between nearest known bins
        lower = None
        upper = None
        for b in self._bins:
            if b <= soc_int:
                lower = b
            if b > soc_int and upper is None:
                upper = b

        if lower is not None and upper is not None:
            # Linear interpolation
            frac = (soc - lower) / (upper - lower)
            p_low = self._power_at_soc[lower]
            p_high = self._power_at_soc[upper]
            return p_low + frac * (p_high - p_low)

        if lower is not None:
            return self._power_at_soc[lower]
        if upper is not None:
            return self._power_at_soc[upper]

        return self._min_power

    def estimate_minutes(self, current_soc: float, target_soc: float) -> float:
        """Estimate minutes to charge from current_soc to target_soc.

        Walks 1% bins, using the empirical power at each bin.
        Handles partial first bin proportionally.
        """
        if current_soc >= target_soc:
            return 0.0

        energy_per_percent = self.capacity_kwh / 100.0  # 1.6 kWh per 1%
        total_minutes = 0.0

        # Partial first bin
        first_bin_ceil = math.ceil(current_soc)
        if first_bin_ceil > current_soc and first_bin_ceil <= target_soc:
            frac = first_bin_ceil - current_soc  # fraction of 1%
            power = self.get_power_at_soc(current_soc)
            if power > 0:
                total_minutes += (frac * energy_per_percent / power) * 60.0

        # Full bins
        start_bin = max(int(first_bin_ceil), int(math.ceil(current_soc)))
        end_bin = int(math.floor(target_soc))

        for soc_bin in range(start_bin, end_bin):
            power = self.get_power_at_soc(float(soc_bin))
            if power > 0:
                total_minutes += (energy_per_percent / power) * 60.0

        # Partial last bin
        last_frac = target_soc - end_bin
        if last_frac > 0 and end_bin < target_soc:
            power = self.get_power_at_soc(float(end_bin))
            if power > 0:
                total_minutes += (last_frac * energy_per_percent / power) * 60.0

        return round(total_minutes, 1)

    def estimate_to_full(self, current_soc: float) -> float:
        """Estimate minutes to 100% SOC."""
        return self.estimate_minutes(current_soc, 100.0)

    def estimate_to_target(self, current_soc: float, target_soc: float = 80.0) -> float:
        """Estimate minutes to a configurable target SOC."""
        return self.estimate_minutes(current_soc, target_soc)
```

- [ ] **Step 4: Run tests**

Run: `cd Models && python -m pytest tests/test_charging_estimator.py -v`

Expected: All 8 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add Models/rpi5_bundle/inference/charging_estimator.py Models/tests/test_charging_estimator.py
git commit -m "feat(charging): add ChargingEstimator class with time-to-target calculation"
```

---

### Task 3: Dashboard Backend — Charging Status Emission

**Files:**
- Modify: `Dashboard/dashboard_backend.py`

The backend already has `_bms_telemetry` dict and `_poll_bms_loop()`. We add charging detection and a new `charging_status` event.

- [ ] **Step 1: Add ChargingEstimator import and initialization**

Near the top of `dashboard_backend.py` where other inference modules are imported, add:

```python
# After existing inference imports
from rpi5_bundle.inference.charging_estimator import ChargingEstimator
```

In `DashboardServer.__init__()`, after existing model loading, add:

```python
# Charging estimator
charging_curve_path = Path(__file__).parent / "rpi5_bundle" / "charging_curve.json"
if charging_curve_path.exists():
    self._charging_estimator = ChargingEstimator(str(charging_curve_path))
    log.info("Loaded charging curve from %s", charging_curve_path)
else:
    self._charging_estimator = None
    log.warning("charging_curve.json not found — charging estimates disabled")
self._charging_target_soc: float = 80.0
```

- [ ] **Step 2: Add charging status emission in the BMS polling loop**

Find the BMS polling loop (`_poll_bms_loop`) and add charging detection after BMS data is read. Add a helper method to the `DashboardServer` class:

```python
async def _emit_charging_status(self) -> None:
    """Detect charging state and emit charging_status event."""
    bms = self._bms_telemetry
    if not bms or self._charging_estimator is None:
        return

    charger_power = bms.get("charger_power_kw", 0.0)
    soc = bms.get("soc_percent", 0.0)
    is_charging = charger_power > 10.0  # 10 kW threshold to filter noise

    if not is_charging:
        await self._emit("charging_status", {"is_charging": False})
        return

    est_to_full = self._charging_estimator.estimate_to_full(soc)
    est_to_target = self._charging_estimator.estimate_to_target(soc, self._charging_target_soc)

    await self._emit("charging_status", {
        "is_charging": True,
        "charging_power_kw": round(charger_power, 1),
        "soc_percent": round(soc, 1),
        "est_minutes_to_full": est_to_full,
        "est_minutes_to_target": est_to_target,
        "charging_target_soc": self._charging_target_soc,
    })
```

Call `await self._emit_charging_status()` at the end of each BMS poll iteration.

- [ ] **Step 3: Add Socket.IO handler for target SOC changes**

In the section where Socket.IO event handlers are registered (near `@sio.event` decorators), add:

```python
@self.sio.event
async def set_charging_target(sid, data):
    target = data.get("target_soc", 80.0)
    self._charging_target_soc = max(50.0, min(100.0, float(target)))
    log.info("Charging target SOC set to %.0f%% by %s", self._charging_target_soc, sid)
```

- [ ] **Step 4: Add charging_status to the initial state dump on client connect**

Find the section where initial state is emitted on client connect (look for the block that emits `vessel_data`, `anomaly_status`, etc. on connect — around line 2220). Add:

```python
# Emit current charging status
if self._charging_estimator:
    await self._emit_charging_status()
```

- [ ] **Step 5: Copy charging_curve.json to Dashboard/rpi5_bundle**

The dashboard backend loads from `Dashboard/rpi5_bundle/`. Ensure the curve JSON is there:

```bash
cp Models/artifacts/charging_curve.json Dashboard/rpi5_bundle/charging_curve.json
```

If the rpi5_bundle symlink or copy already exists in Dashboard, just ensure charging_curve.json is alongside the other model files.

- [ ] **Step 6: Commit**

```bash
git add Dashboard/dashboard_backend.py
git commit -m "feat(charging): add charging status detection and Socket.IO emission to backend"
```

---

### Task 4: Flutter — Socket Service + Data Model

**Files:**
- Modify: `Dashboard/flutter_application_1/lib/services/socket_service.dart`
- Modify: `Dashboard/flutter_application_1/lib/models/dashboard_data.dart`
- Modify: `Dashboard/flutter_application_1/lib/providers/dashboard_provider.dart`

- [ ] **Step 1: Add charging callback to SocketService**

In `socket_service.dart`, add to the callback declarations (after `onSpeedPredictionResult`):

```dart
// Charging events
Function(Map<String, dynamic>)? onChargingStatus;
```

In the `connect()` method, add the listener (after the `speed_prediction_result` listener):

```dart
socket.on('charging_status', (data) {
  onChargingStatus?.call(Map<String, dynamic>.from(data));
});
```

Add a method to send target SOC changes:

```dart
/// Set the charging target SOC on the server
void setChargingTarget(double targetSoc) {
  socket.emit('set_charging_target', {'target_soc': targetSoc});
}
```

- [ ] **Step 2: Add charging fields to DashboardData**

In `dashboard_data.dart`, add fields to the `DashboardData` class (after the battery anomaly fields):

```dart
// Charging status
bool isCharging;
double? chargingPowerKw;
double? chargingSocPercent;
double? estMinutesToFull;
double? estMinutesToTarget;
double chargingTargetSoc;
```

Add defaults in the constructor:

```dart
this.isCharging = false,
this.chargingPowerKw,
this.chargingSocPercent,
this.estMinutesToFull,
this.estMinutesToTarget,
this.chargingTargetSoc = 80.0,
```

- [ ] **Step 3: Handle charging_status in DashboardProvider**

In `dashboard_provider.dart`, add the handler (after the anomaly handler):

```dart
_socketService.onChargingStatus = (payload) {
  data.isCharging = payload['is_charging'] ?? false;
  if (data.isCharging) {
    data.chargingPowerKw = (payload['charging_power_kw'] as num?)?.toDouble();
    data.chargingSocPercent = (payload['soc_percent'] as num?)?.toDouble();
    data.estMinutesToFull = (payload['est_minutes_to_full'] as num?)?.toDouble();
    data.estMinutesToTarget = (payload['est_minutes_to_target'] as num?)?.toDouble();
    data.chargingTargetSoc = (payload['charging_target_soc'] as num?)?.toDouble() ?? 80.0;
  }
  notifyListeners();
};
```

Add a method to change the target:

```dart
void setChargingTarget(double targetSoc) {
  data.chargingTargetSoc = targetSoc;
  _socketService.setChargingTarget(targetSoc);
  notifyListeners();
}
```

- [ ] **Step 4: Commit**

```bash
git add Dashboard/flutter_application_1/lib/services/socket_service.dart \
      Dashboard/flutter_application_1/lib/models/dashboard_data.dart \
      Dashboard/flutter_application_1/lib/providers/dashboard_provider.dart
git commit -m "feat(charging): add charging status event to Flutter data layer"
```

---

### Task 5: Flutter — Charging Panel Widget

**Files:**
- Create: `Dashboard/flutter_application_1/lib/widgets/charging_panel.dart`
- Modify: `Dashboard/flutter_application_1/lib/main.dart`

- [ ] **Step 1: Create the ChargingPanel widget**

```dart
import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import '../providers/dashboard_provider.dart';

class ChargingPanel extends StatelessWidget {
  const ChargingPanel({super.key});

  String _formatTime(double? minutes) {
    if (minutes == null) return '--';
    if (minutes <= 0) return 'Ready';
    final h = minutes ~/ 60;
    final m = (minutes % 60).round();
    if (h > 0) return '${h}h ${m}m';
    return '${m}m';
  }

  @override
  Widget build(BuildContext context) {
    return Consumer<DashboardProvider>(
      builder: (context, provider, _) {
        final data = provider.data;
        if (!data.isCharging) return const SizedBox.shrink();

        return Container(
          margin: const EdgeInsets.all(12),
          padding: const EdgeInsets.all(16),
          decoration: BoxDecoration(
            color: Colors.green.shade900.withOpacity(0.85),
            borderRadius: BorderRadius.circular(12),
            border: Border.all(color: Colors.greenAccent, width: 1.5),
          ),
          child: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              // Header
              Row(
                children: [
                  Icon(Icons.bolt, color: Colors.greenAccent, size: 28),
                  const SizedBox(width: 8),
                  Text(
                    'CHARGING',
                    style: TextStyle(
                      color: Colors.greenAccent,
                      fontSize: 18,
                      fontWeight: FontWeight.bold,
                    ),
                  ),
                  const Spacer(),
                  Text(
                    '${data.chargingPowerKw?.toStringAsFixed(0) ?? "--"} kW',
                    style: const TextStyle(
                      color: Colors.white,
                      fontSize: 24,
                      fontWeight: FontWeight.bold,
                    ),
                  ),
                ],
              ),
              const SizedBox(height: 12),

              // SOC progress bar
              ClipRRect(
                borderRadius: BorderRadius.circular(8),
                child: LinearProgressIndicator(
                  value: (data.chargingSocPercent ?? 0) / 100.0,
                  minHeight: 20,
                  backgroundColor: Colors.grey.shade800,
                  valueColor: AlwaysStoppedAnimation<Color>(Colors.greenAccent),
                ),
              ),
              const SizedBox(height: 4),
              Text(
                '${data.chargingSocPercent?.toStringAsFixed(1) ?? "--"}%',
                style: const TextStyle(color: Colors.white70, fontSize: 14),
              ),
              const SizedBox(height: 12),

              // Time estimates
              Row(
                mainAxisAlignment: MainAxisAlignment.spaceAround,
                children: [
                  _TimeEstimate(
                    label: 'To ${data.chargingTargetSoc.round()}%',
                    time: _formatTime(data.estMinutesToTarget),
                  ),
                  _TimeEstimate(
                    label: 'To 100%',
                    time: _formatTime(data.estMinutesToFull),
                  ),
                ],
              ),
              const SizedBox(height: 12),

              // Target SOC selector
              Row(
                mainAxisAlignment: MainAxisAlignment.center,
                children: [
                  const Text('Target: ', style: TextStyle(color: Colors.white70)),
                  for (final target in [80.0, 90.0, 100.0])
                    Padding(
                      padding: const EdgeInsets.symmetric(horizontal: 4),
                      child: ChoiceChip(
                        label: Text('${target.round()}%'),
                        selected: data.chargingTargetSoc == target,
                        selectedColor: Colors.greenAccent,
                        onSelected: (_) => provider.setChargingTarget(target),
                      ),
                    ),
                ],
              ),
            ],
          ),
        );
      },
    );
  }
}

class _TimeEstimate extends StatelessWidget {
  final String label;
  final String time;

  const _TimeEstimate({required this.label, required this.time});

  @override
  Widget build(BuildContext context) {
    return Column(
      children: [
        Text(label, style: const TextStyle(color: Colors.white54, fontSize: 12)),
        const SizedBox(height: 4),
        Text(time, style: const TextStyle(color: Colors.white, fontSize: 20, fontWeight: FontWeight.bold)),
      ],
    );
  }
}
```

- [ ] **Step 2: Integrate ChargingPanel into main.dart**

In `main.dart`, import the widget:

```dart
import 'widgets/charging_panel.dart';
```

Find the main dashboard layout (where the map or trip view is built). Add the `ChargingPanel` as an overlay that appears when `data.isCharging` is true. Wrap it in a `Positioned` widget inside the existing `Stack`, or place it as a conditional widget above/below the map:

```dart
// Inside the main Stack or Column, add:
if (provider.data.isCharging) const ChargingPanel(),
```

The exact placement depends on the existing layout — position it where the trip prediction panel normally sits (since the ferry is docked while charging, the trip panel is inactive).

- [ ] **Step 3: Test the UI**

Run: `cd Dashboard/flutter_application_1 && flutter run -d chrome`

Verify: The app compiles. When not charging, no panel appears. (Full integration test requires the backend emitting `charging_status`.)

- [ ] **Step 4: Commit**

```bash
git add Dashboard/flutter_application_1/lib/widgets/charging_panel.dart \
      Dashboard/flutter_application_1/lib/main.dart
git commit -m "feat(charging): add charging panel widget to Flutter dashboard"
```

---

### Task 6: Thesis Analysis Script

**Files:**
- Create: `Models/evaluate/analyze_charging.py`
- Output: `Models/artifacts/progress_report/charging_analysis.png`
- Output: `Models/artifacts/progress_report/charging_summary_stats.csv`

- [ ] **Step 1: Create the analysis script**

```python
"""Charging analysis for thesis — profile characterization and operational patterns.

Generates:
  - artifacts/progress_report/charging_analysis.png (6-panel figure)
  - artifacts/progress_report/charging_summary_stats.csv

Usage:
    python -m evaluate.analyze_charging
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import duckdb
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from config import ARTIFACTS_DIR, DUCKDB_PATH

REPORT_DIR = ARTIFACTS_DIR / "progress_report"
REPORT_DIR.mkdir(parents=True, exist_ok=True)


def load_data() -> tuple[pd.DataFrame, pd.DataFrame]:
    """Load charging sessions and telemetry from DuckDB."""
    conn = duckdb.connect(DUCKDB_PATH, read_only=True)
    sessions = conn.execute(
        "SELECT * FROM charging_sessions WHERE energy_added_kwh > 0"
    ).fetchdf()
    telemetry = conn.execute(
        "SELECT * FROM charging_telemetry WHERE charger_power_kw > 0 AND soc_percent IS NOT NULL"
    ).fetchdf()
    conn.close()
    return sessions, telemetry


def plot_analysis(sessions: pd.DataFrame, telemetry: pd.DataFrame, curve_path: Path) -> None:
    """Generate 6-panel thesis figure."""
    with open(curve_path) as f:
        curve = json.load(f)

    fig, axes = plt.subplots(2, 3, figsize=(18, 10))
    fig.suptitle("M/B Dalaray Charging Analysis", fontsize=16, fontweight="bold")

    # Panel 1: Power vs SOC curve with confidence band
    ax = axes[0, 0]
    bins = curve["bins"]
    ax.fill_between(bins, curve["p25_kw"], curve["p75_kw"], alpha=0.3, color="green", label="P25–P75")
    ax.plot(bins, curve["median_kw"], color="green", linewidth=2, label="Median")
    ax.set_xlabel("SOC (%)")
    ax.set_ylabel("Charging Power (kW)")
    ax.set_title("Charging Power vs SOC")
    ax.legend()
    ax.grid(True, alpha=0.3)

    # Panel 2: Duration vs starting SOC
    ax = axes[0, 1]
    ax.scatter(sessions["soc_start"], sessions["duration_minutes"], c="steelblue", alpha=0.7, edgecolors="navy", s=50)
    ax.set_xlabel("Starting SOC (%)")
    ax.set_ylabel("Duration (minutes)")
    ax.set_title("Charge Duration vs Starting SOC")
    ax.grid(True, alpha=0.3)

    # Panel 3: Energy per session histogram
    ax = axes[0, 2]
    ax.hist(sessions["energy_added_kwh"], bins=15, color="teal", edgecolor="black", alpha=0.8)
    ax.set_xlabel("Energy Added (kWh)")
    ax.set_ylabel("Count")
    ax.set_title("Energy per Charging Session")
    ax.grid(True, alpha=0.3)

    # Panel 4: Time of day histogram
    ax = axes[1, 0]
    hours = pd.to_datetime(sessions["start_time"]).dt.hour
    ax.hist(hours, bins=range(0, 25), color="orange", edgecolor="black", alpha=0.8)
    ax.set_xlabel("Hour of Day")
    ax.set_ylabel("Count")
    ax.set_title("Charging Start Time Distribution")
    ax.set_xticks(range(0, 24, 2))
    ax.grid(True, alpha=0.3)

    # Panel 5: Discharge depth (SOC at plug-in)
    ax = axes[1, 1]
    ax.hist(sessions["soc_start"], bins=15, color="salmon", edgecolor="black", alpha=0.8)
    ax.set_xlabel("SOC at Plug-in (%)")
    ax.set_ylabel("Count")
    ax.set_title("Discharge Depth Before Charging")
    ax.grid(True, alpha=0.3)

    # Panel 6: Weekday vs weekend
    ax = axes[1, 2]
    sessions["date_parsed"] = pd.to_datetime(sessions["date"])
    sessions["is_weekend"] = sessions["date_parsed"].dt.dayofweek >= 5
    weekday = sessions[~sessions["is_weekend"]]
    weekend = sessions[sessions["is_weekend"]]
    labels = ["Weekday", "Weekend"]
    counts = [len(weekday), len(weekend)]
    avg_energy = [
        weekday["energy_added_kwh"].mean() if len(weekday) > 0 else 0,
        weekend["energy_added_kwh"].mean() if len(weekend) > 0 else 0,
    ]
    x = np.arange(len(labels))
    bars = ax.bar(x - 0.2, counts, 0.35, label="Sessions", color="steelblue")
    ax2 = ax.twinx()
    bars2 = ax2.bar(x + 0.2, avg_energy, 0.35, label="Avg Energy (kWh)", color="coral")
    ax.set_xticks(x)
    ax.set_xticklabels(labels)
    ax.set_ylabel("Session Count")
    ax2.set_ylabel("Avg Energy (kWh)")
    ax.set_title("Weekday vs Weekend Charging")
    ax.legend(loc="upper left")
    ax2.legend(loc="upper right")
    ax.grid(True, alpha=0.3)

    plt.tight_layout()
    out_path = REPORT_DIR / "charging_analysis.png"
    fig.savefig(out_path, dpi=150, bbox_inches="tight")
    plt.close()
    print(f"Saved figure to {out_path}")


def summary_stats(sessions: pd.DataFrame) -> pd.DataFrame:
    """Compute summary statistics table."""
    cols = ["duration_minutes", "energy_added_kwh", "avg_power_kw", "peak_power_kw", "soc_start", "soc_end"]
    stats = sessions[cols].describe().T[["count", "mean", "std", "min", "25%", "50%", "75%", "max"]]
    stats = stats.round(2)
    out_path = REPORT_DIR / "charging_summary_stats.csv"
    stats.to_csv(out_path)
    print(f"Saved stats to {out_path}")
    print(stats)
    return stats


if __name__ == "__main__":
    sessions, telemetry = load_data()
    print(f"Loaded {len(sessions)} sessions, {len(telemetry)} telemetry rows")

    curve_path = ARTIFACTS_DIR / "charging_curve.json"
    if not curve_path.exists():
        print("ERROR: Run build_charging_curve.py first")
        sys.exit(1)

    plot_analysis(sessions, telemetry, curve_path)
    summary_stats(sessions)
    print("\nDone!")
```

- [ ] **Step 2: Run the analysis**

Run: `cd Models && python -m evaluate.analyze_charging`

Expected: Two output files created, stats printed to console.

- [ ] **Step 3: Verify outputs**

Check that `artifacts/progress_report/charging_analysis.png` has 6 readable panels and `charging_summary_stats.csv` has the expected columns.

- [ ] **Step 4: Commit**

```bash
git add Models/evaluate/analyze_charging.py Models/artifacts/progress_report/charging_analysis.png Models/artifacts/progress_report/charging_summary_stats.csv
git commit -m "feat(charging): add thesis charging analysis script with 6-panel figure"
```

---

### Task 7: Integration Test — End to End

- [ ] **Step 1: Run build_charging_curve to ensure artifacts exist**

```bash
cd Models && python -m evaluate.build_charging_curve
```

- [ ] **Step 2: Run unit tests**

```bash
cd Models && python -m pytest tests/test_charging_estimator.py -v
```

Expected: All tests pass.

- [ ] **Step 3: Run the dashboard in replay mode and verify charging panel**

```bash
cd Dashboard && launch_dashboard.bat
```

If replay data includes a charging session, the panel should appear. If not, verify the backend logs show `Loaded charging curve from ...` at startup.

- [ ] **Step 4: Final commit if any fixups needed**

```bash
git add -A && git commit -m "fix(charging): integration fixups"
```
