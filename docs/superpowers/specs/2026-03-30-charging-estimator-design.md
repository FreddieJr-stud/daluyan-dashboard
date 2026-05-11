# Charging Speed & Time-to-Full Estimator — Design Spec

**Date:** 2026-03-30
**Status:** Approved

## Problem

The M/B Dalaray dashboard currently has no visibility into charging status. Operators cannot see how fast the ferry is charging or how long until it reaches a desired SOC level. The thesis also lacks analysis of the ferry's charging behavior patterns.

## Solution

Build an empirical charging power-vs-SOC lookup curve from historical data, integrate a real-time charging panel into the Flutter dashboard, and produce thesis-ready charging analysis artifacts.

## Data Foundation

- **58 valid charging sessions** (of 67 total) in `charging_sessions` table
- **22,301 telemetry rows** across 59 dates in `charging_telemetry` table
- SOC coverage: 22.75% to 100%
- Peak charger power: 337 kW, average: 177 kW
- Battery capacity: 160 kWh fixed, SOH: 99.5% (no degradation signal)

## Architecture

### 1. Empirical Lookup Curve (Offline)

**Build script:** `Models/evaluate/build_charging_curve.py`

1. Query `charging_telemetry` from DuckDB — filter to rows where `charger_power_kw > 0`
2. Bucket SOC into 1% bins (23%, 24%, ..., 99%)
3. Compute **median** charging power (kW) per bin — median resists outliers from session start/stop transients
4. Also compute p25 and p75 for confidence bands (thesis plots)
5. Store as JSON: `{ "bins": [23, 24, ...], "median_kw": [310.5, 308.2, ...], "p25_kw": [...], "p75_kw": [...] }`

**Output:** `Models/artifacts/charging_curve.json`

### 2. Time-to-Target Calculation

**Estimator class:** `Models/rpi5_bundle/inference/charging_estimator.py`

Given current SOC and target SOC:

1. Walk from `ceil(current_soc)` to `target_soc`
2. For each 1% bin: `minutes += (1% x 160 kWh) / power_at_bin_kW x 60`
3. Handle partial first bin proportionally
4. Return estimated minutes to target

Two outputs:
- `est_minutes_to_full` — always targets 100%
- `est_minutes_to_target` — targets operator-configurable SOC (default 80%)

### 3. Dashboard Integration

**Backend:** `dashboard_backend.py` (existing Socket.IO server on RPi5)

- **Charging state detection:** `charger_power_kw > 0` triggers charging mode
- **New fields in telemetry payload:**
  - `is_charging`: bool
  - `charging_power_kw`: current charger power (live from BMS)
  - `soc_percent`: current SOC (already emitted)
  - `est_minutes_to_full`: time to 100%
  - `est_minutes_to_target`: time to operator target
  - `charging_target_soc`: current target setting

**Frontend:** Flutter dashboard

- When `is_charging == true`, show a charging panel (replaces/overlays trip view)
- Displays: current kW, SOC %, time-to-full, time-to-target
- Operator adjusts target SOC via slider or preset buttons (80%, 90%, 100%)

**RPi5 deployment:** `charging_curve.json` ships in `rpi5_bundle/` alongside model artifacts.

### 4. Thesis Analysis

**Script:** `Models/evaluate/analyze_charging.py`

**Charging profile characterization:**
- Power-vs-SOC curve with p25-p75 confidence band
- Duration-vs-starting-SOC scatter (58 sessions)
- Energy-per-session histogram
- Summary statistics table (min/max/mean/median for duration, energy, power, SOC)

**Operational patterns:**
- Charging time-of-day histogram (when does the ferry plug in?)
- Discharge depth distribution (soc_start values)
- Typical SOC operating window
- Weekday vs weekend comparison

**Outputs:**
- `Models/artifacts/progress_report/charging_analysis.png` — multi-panel figure
- `Models/artifacts/progress_report/charging_summary_stats.csv`

## New Files

| File | Purpose |
|---|---|
| `Models/evaluate/build_charging_curve.py` | Builds lookup curve from DuckDB |
| `Models/artifacts/charging_curve.json` | The lookup table (also copied to rpi5_bundle) |
| `Models/rpi5_bundle/inference/charging_estimator.py` | Lightweight estimator for RPi5 |
| `Models/evaluate/analyze_charging.py` | Thesis analysis plots + stats |

## Out of Scope

- ML-based charging prediction (SOH is 99.5% — no degradation signal to model)
- Battery degradation tracking or SOH-adjusted estimates
- Charger hardware integration or control (display-only)
- Modifications to Model 3a/3b anomaly detection

## Dependencies

- `charging_telemetry` and `charging_sessions` tables (already populated in DuckDB)
- `dashboard_backend.py` for Socket.IO integration
- Flutter dashboard for UI rendering
