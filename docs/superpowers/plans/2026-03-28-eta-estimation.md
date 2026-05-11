# ETA Estimation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add real-time ETA estimation to the dashboard backend so Dalaray can report arrival times to the Kapitans via voice, and emit `eta_update` Socket.IO events for future Flutter UI consumption.

**Architecture:** A standalone `ETAEstimator` class loaded with pre-computed historical baselines (JSON). On each telemetry tick during transit, it computes remaining time to each reachable station using a speed-ratio + tide adjustment on historical segment times. Smoothed output (30s threshold) emitted via Socket.IO and injected into the Gemini LLM context.

**Tech Stack:** Python 3, DuckDB (offline baseline script only — NOT a runtime dependency), JSON config, Socket.IO, existing `dashboard_backend.py` infrastructure.

**Spec:** `Dashboard/docs/superpowers/specs/2026-03-28-eta-estimation-design.md`

---

### Task 1: Compute ETA baselines from historical segment data

**Files:**
- Create: `Models/data/compute_eta_baselines.py`
- Create: `Models/rpi5_bundle/config/eta_baselines.json` (generated output)

This script runs offline on the development machine (not on the RPi5). It queries DuckDB for historical segment travel times and dwell times, then exports them as a JSON config file that ships with the rpi5_bundle.

- [ ] **Step 1: Create the baseline computation script**

```python
# Models/data/compute_eta_baselines.py
"""Compute ETA baselines from historical DuckDB segment data.

Run offline on the development machine whenever data is updated.
Output: rpi5_bundle/config/eta_baselines.json

Usage:
    python -m data.compute_eta_baselines
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import duckdb

DUCKDB_PATH = (
    Path(__file__).resolve().parent.parent.parent
    / "Daluyan_V2" / "backend" / "data" / "daluyan.duckdb"
)
OUTPUT_PATH = (
    Path(__file__).resolve().parent.parent
    / "rpi5_bundle" / "config" / "eta_baselines.json"
)

# Station cumulative km (mirrors STATIONS in dashboard_backend.py)
STATION_KM = {
    "Napindan": 0.0, "Guadalupe": 6.5, "Hulo": 8.3,
    "Valenzuela": 9.8, "Lambingan": 11.2, "Sta Ana": 12.7,
    "PUP": 14.0, "Quinta": 15.6, "Escolta": 16.0,
}

KM_TO_NM = 1 / 1.852


def main() -> None:
    if not DUCKDB_PATH.exists():
        print(f"ERROR: DuckDB not found at {DUCKDB_PATH}")
        return

    con = duckdb.connect(str(DUCKDB_PATH), read_only=True)

    # --- 1. Segment travel times ---
    rows = con.execute("""
        SELECT
            departure_station, arrival_station, direction,
            COUNT(*) AS n,
            MEDIAN(EXTRACT(EPOCH FROM (arrival_time - departure_time))) AS median_time_s
        FROM segments
        WHERE departure_station IS NOT NULL
          AND arrival_station IS NOT NULL
          AND direction IN ('upstream', 'downstream')
          AND EXTRACT(EPOCH FROM (arrival_time - departure_time)) BETWEEN 30 AND 7200
        GROUP BY departure_station, arrival_station, direction
    """).fetchall()

    segment_baselines: dict[str, dict] = {}
    for dep, arr, direction, n, median_s in rows:
        km_dep = STATION_KM.get(dep)
        km_arr = STATION_KM.get(arr)
        if km_dep is not None and km_arr is not None:
            distance_km = abs(km_arr - km_dep)
            distance_nm = distance_km * KM_TO_NM
            hours = median_s / 3600
            avg_speed_kn = distance_nm / hours if hours > 0 else 5.0
        else:
            distance_km = 0.0
            avg_speed_kn = 5.0

        key = f"{dep}|{arr}|{direction}"
        segment_baselines[key] = {
            "time_s": round(median_s, 1),
            "distance_km": round(distance_km, 2),
            "avg_speed_kn": round(avg_speed_kn, 2),
            "count": n,
        }

    # --- 2. Dwell times (consecutive segments at same station) ---
    dwell_rows = con.execute("""
        SELECT
            s1.arrival_station AS station,
            s1.direction,
            COUNT(*) AS n,
            MEDIAN(EXTRACT(EPOCH FROM (s2.departure_time - s1.arrival_time)))
                AS median_dwell_s
        FROM segments s1
        JOIN segments s2
          ON s1.arrival_station = s2.departure_station
         AND CAST(s1.departure_time AS DATE) = CAST(s2.departure_time AS DATE)
         AND s2.departure_time > s1.arrival_time
         AND EXTRACT(EPOCH FROM (s2.departure_time - s1.arrival_time))
             BETWEEN 10 AND 600
         AND s1.direction = s2.direction
        GROUP BY s1.arrival_station, s1.direction
    """).fetchall()

    dwell_baselines: dict[str, dict] = {}
    for station, direction, n, median_dwell in dwell_rows:
        key = f"{station}|{direction}"
        dwell_baselines[key] = {
            "dwell_s": round(median_dwell),
            "count": n,
        }

    con.close()

    # --- 3. Export ---
    output = {
        "segment_baselines": segment_baselines,
        "dwell_baselines": dwell_baselines,
        "generated_at": datetime.now().isoformat(),
        "source": str(DUCKDB_PATH),
    }
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(json.dumps(output, indent=2))

    print(f"ETA baselines saved to {OUTPUT_PATH}")
    print(f"  Segment baselines: {len(segment_baselines)} route-direction pairs")
    print(f"  Dwell baselines:   {len(dwell_baselines)} station-direction pairs")

    # Summary table
    print("\nSegment baselines:")
    for key, val in sorted(segment_baselines.items()):
        print(f"  {key:40s}  {val['time_s']:7.1f}s  "
              f"{val['avg_speed_kn']:5.2f}kn  (n={val['count']})")

    print("\nDwell baselines:")
    for key, val in sorted(dwell_baselines.items()):
        print(f"  {key:30s}  {val['dwell_s']:5.0f}s  (n={val['count']})")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Run the script and verify output**

Run: `cd Models && python -m data.compute_eta_baselines`

Expected: JSON file created at `Models/rpi5_bundle/config/eta_baselines.json` with segment and dwell baselines. Verify:
- Segment baselines include pairs like `Guadalupe|Hulo|downstream`, `Hulo|Lambingan|downstream`, etc.
- Dwell baselines include entries for OPEN_STATIONS (Guadalupe, Hulo, Lambingan, PUP, Quinta, Escolta)
- Segment times are reasonable (e.g., Guadalupe→Hulo ~300-400s, not 0 or 99999)
- Avg speeds are in the 3-15 kn range

- [ ] **Step 3: Commit**

```bash
git add Models/data/compute_eta_baselines.py Models/rpi5_bundle/config/eta_baselines.json
git commit -m "feat(eta): add offline script to compute ETA baselines from DuckDB"
```

---

### Task 2: Add ETAEstimator class to dashboard_backend.py

**Files:**
- Modify: `Dashboard/dashboard_backend.py` — insert new class between the geo helpers section (ends around line 320, after `_resolve_station`) and the `_cors_middleware` / `DashboardServer` class.

The class is fully self-contained: loads JSON baselines, computes ETAs, handles smoothing. No DuckDB at runtime.

- [ ] **Step 1: Insert the ETAEstimator class**

Find the line containing `def _resolve_station(name: str) -> str:` and its body. After the full function (there's a blank line, then the weather cache / default weather section), insert the `ETAEstimator` class. It should go **before** the `WEATHER_CACHE_FILE` line.

Insert this code after `_resolve_station` and before the weather defaults section:

```python
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
```

- [ ] **Step 2: Verify the class parses correctly**

Run: `python -c "import ast; ast.parse(open('Dashboard/dashboard_backend.py').read()); print('OK')"`

Expected: `OK` (no syntax errors)

- [ ] **Step 3: Commit**

```bash
git add Dashboard/dashboard_backend.py
git commit -m "feat(eta): add ETAEstimator class with speed-ratio and tide adjustment"
```

---

### Task 3: Wire ETAEstimator into DashboardServer

**Files:**
- Modify: `Dashboard/dashboard_backend.py` — four insertion points inside the `DashboardServer` class.

- [ ] **Step 1: Instantiate ETAEstimator in `__init__`**

Find this line inside `DashboardServer.__init__`:

```python
        # --- Load ML models (graceful fallback) ---
        self._load_models()
```

Insert **after** `self._load_models()` (and before the `# --- Instance state ---` comment):

```python
        # --- ETA estimator ---
        _config_dir = str(Path(self.config.bundle_dir).resolve() / "config")
        self._eta = ETAEstimator(_config_dir)
```

- [ ] **Step 2: Call ETA update in the telemetry loop**

In `_poll_vessel_loop`, find the block that calls `_update_nav_state`. It looks like:

```python
                await self._update_nav_state(lat, lon, speed, heading)
```

Insert **immediately after** that call (before the safety status emission):

```python
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
                    await self._emit("eta_update", eta_payload)
```

- [ ] **Step 3: Add ETA to LLM context**

In `_build_dashboard_context`, find the block that ends with:

```python
        except Exception:
            pass

        return "\n".join(lines)
```

Insert **between** the `pass` and the `return` statement:

```python
        # ETA estimates
        try:
            eta_lines = self._eta.get_context_lines()
            lines.extend(eta_lines)
        except Exception:
            pass
```

- [ ] **Step 4: Emit ETA on client connect**

In `_register_events`, find the `connect` handler. Locate the block that sends the initial state snapshot. After this line:

```python
            if self._nav["state"] == "DOCKED" and self.trip_predictor:
                await self._run_auto_predictions(to=sid)
```

Insert **after** (still inside the `connect` handler):

```python
            # Send current ETA snapshot
            eta_payload = self._eta.get_payload()
            if eta_payload:
                await self.sio.emit("eta_update", eta_payload, to=sid)
```

- [ ] **Step 5: Verify syntax**

Run: `python -c "import ast; ast.parse(open('Dashboard/dashboard_backend.py').read()); print('OK')"`

Expected: `OK`

- [ ] **Step 6: Commit**

```bash
git add Dashboard/dashboard_backend.py
git commit -m "feat(eta): integrate ETAEstimator into DashboardServer telemetry loop and LLM context"
```

---

### Task 4: End-to-end verification

- [ ] **Step 1: Run backend in desktop mode and check startup logs**

Run: `cd Dashboard && python dashboard_backend.py --vessel-host localhost`

Expected in logs:
- `ETA baselines loaded: NN segments, NN dwell entries` (confirms JSON loaded)
- No `ETAEstimator` errors

If `ETA baselines not found` appears, verify that `rpi5_bundle/config/eta_baselines.json` exists relative to the configured `bundle_dir`.

- [ ] **Step 2: Test with replay data**

If a replay server is available, start a replay and watch the logs for:
- `eta_update` emissions during transit segments
- ETA values resetting when the ferry docks
- No `eta_update` spam (smoothing should throttle emissions)

- [ ] **Step 3: Verify LLM context includes ETA**

Send a chat request while the ferry is in transit:
```bash
curl -X POST http://localhost:5000/chat -H "Content-Type: application/json" -d '{"text": "How long until we arrive?"}'
```

The Gemini response should reference ETA information from the context.

- [ ] **Step 4: Final commit (if any fixes needed)**

```bash
git add Dashboard/dashboard_backend.py
git commit -m "fix(eta): address issues found during verification"
```
