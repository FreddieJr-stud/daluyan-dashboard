# ETA Estimation for M/B Dalaray — Design Spec

**Date:** 2026-03-28
**Status:** Approved
**Scope:** Backend ETA computation + Socket.IO emission + Gemini LLM context injection

## Summary

Add Estimated Time of Arrival (ETA) to the dashboard backend so that:
- The next-station ETA is computed proactively during transit
- ETA to any reachable station is available on demand (voice: "Dalaray, gaano pa katagal papuntang Quinta?")
- ETAs are emitted via a new `eta_update` Socket.IO event for future Flutter UI consumption
- ETAs are injected into the Gemini LLM context so Dalaray can report them to the Kapitans

## Design Decisions

| Decision | Choice | Rationale |
|---|---|---|
| ETA scope | Next station + final destination + any station on demand | Most useful for Kapitans (Option D) |
| Estimation method | Historical baseline adjusted by current conditions | Good accuracy without a new ML model (Approach 1 / Option C hybrid) |
| Dwell time | Include dwell only at OPEN_STATIONS | Matches real operations — closed stations are skipped |
| Update strategy | Dynamic with smoothing (30s threshold) | Avoids flickering while staying responsive |
| Surface area | LLM context + Socket.IO event (no Flutter UI yet) | Delivers the goal (Dalaray voice) without scope creep |

## Section 1: Data Layer — Historical Baselines

On backend startup, the `ETAEstimator` queries DuckDB once to build two lookup tables.

### Segment Travel Times

Average transit time (in seconds) per `(departure_station, arrival_station, direction)` tuple.

- Source: `segments` table — `AVG(arrival_time - departure_time)`
- Also stores average speed per segment, derived from `distance_km / duration_hours` using the station registry cumulative km (`|km_arrival - km_departure|`)
- This avoids reading parquet files at startup

### Dwell Times

Average stop duration at each OPEN_STATION, per direction.

- Derived by finding consecutive segments on the same date where one segment's arrival station equals the next segment's departure station
- `AVG(next_departure_time - this_arrival_time)`
- Only computed for stations in `OPEN_STATIONS`: Guadalupe, Hulo, Lambingan, PUP, Quinta, Escolta

### Fallbacks

- Missing segment pair: `distance_km / 6.0 kn` (conservative average speed)
- Missing dwell data: 120 seconds default

## Section 2: Real-Time ETA Computation

Every telemetry tick (~1s), when `_nav["state"] == "IN_TRANSIT"`, the estimator computes:

### Current Segment ETA (to next station)

1. **Remaining distance** = haversine from current GPS to next station's lat/lon
2. **Historical baseline time** for this segment = lookup from Section 1
3. **Speed ratio** = `current_speed / historical_avg_speed` for this segment, clamped to `[0.3, 3.0]`
4. **Adjusted segment time** = `historical_baseline * (1 / speed_ratio)` — faster than average → time shrinks
5. **Remaining time** = `adjusted_segment_time * (remaining_distance / total_segment_distance)` — proportional to how much of the segment is left

### Multi-Hop ETA (to any downstream station)

1. Start with current segment remaining time (above)
2. For each intermediate segment between next_station and target: add historical baseline adjusted by the same speed ratio (proxy: if the ferry is going fast now, it'll likely continue)
3. For each intermediate OPEN_STATION: add historical dwell time
4. Sum all components

### Tide Adjustment

Simple multiplier based on tide phase and direction:

| Tide Phase | Upstream | Downstream |
|---|---|---|
| Rising | ×0.9 (favorable) | ×1.1 (unfavorable) |
| Falling | ×1.1 (unfavorable) | ×0.9 (favorable) |
| High/Low | ×1.0 (neutral) | ×1.0 (neutral) |

These are modest adjustments — the speed ratio already captures most of the effect implicitly.

### Output

A dict mapping each reachable station to its ETA in seconds:

```python
{
  "Hulo": 312,
  "Lambingan": 795,
  "PUP": 1380,
  ...
}
```

## Section 3: Smoothing and Emission

### Smoothing Logic

- Maintain `_last_emitted_eta` dict (station → seconds)
- On each tick, compare new ETA against last emitted value
- Only update if difference exceeds **30 seconds** or the **target station changed** (ferry arrived, next-station shifts)
- On `DOCKED` or `UNKNOWN` nav state: reset and emit empty ETAs
- On nav state transition to `IN_TRANSIT`: recompute fresh

### Socket.IO Event: `eta_update`

Emitted at most once per second (tied to telemetry tick), only when smoothed values change.

```json
{
  "next_station": "Hulo",
  "next_station_eta_s": 312,
  "next_station_eta_min": 5.2,
  "all_stations": {
    "Hulo": {"eta_s": 312, "eta_min": 5.2},
    "Lambingan": {"eta_s": 795, "eta_min": 13.3},
    "PUP": {"eta_s": 1380, "eta_min": 23.0}
  },
  "direction": "downstream",
  "timestamp": "2026-03-28T14:32:01"
}
```

### LLM Context Injection

`_build_dashboard_context()` gets a new block after station predictions:

```
ETA to next station (Hulo): ~5 minutes
ETA to Lambingan: ~13 minutes
ETA to Escolta: ~42 minutes
```

Only includes reachable stations in the current travel direction. **Reachable stations** are defined as all stations with a higher order than the current position when traveling downstream (increasing order: Napindan=0 → Escolta=8), or lower order when traveling upstream (decreasing order). This is derived from the STATIONS registry. No changes needed to Dalaray's system prompt — it already answers using the provided context.

## Files Modified

| File | Change |
|---|---|
| `Dashboard/dashboard_backend.py` | New `ETAEstimator` class, integrate into `DashboardServer` telemetry loop, add `eta_update` emission, extend `_build_dashboard_context()` |

## Dependencies

- DuckDB (already available on RPi5)
- No new Python packages
- No new ML models

## Future Work

- Flutter dashboard UI widget showing ETA (follow-up — Socket.IO event is ready)
- Graduate to ML-based ETA (Model 4) if accuracy demands it
- Per-segment speed profiles from parquet data (Approach 2) if needed
