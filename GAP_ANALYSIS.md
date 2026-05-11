# Gap Analysis: Partner Production Backend vs. Replay Server / Flutter Frontend

**Date:** 2026-03-14
**Files compared:**
- `client_sub_actual.py` (partner production backend, 1045 lines)
- `replay_server.py` (our replay server, 949 lines)
- `dashboard_provider.dart` (Flutter data model/provider, 536 lines)
- `socket_service.dart` (Flutter Socket.IO client, 130 lines)
- `dashboard_data.dart` (Flutter data classes, 210 lines)
- `main.dart` (Flutter UI, ~2300 lines)

---

## A. Socket.IO Events -- Emission Comparison

### Events the frontend LISTENS to (from `socket_service.dart` lines 46-89):

| # | Event Name | Frontend Expects | client_sub_actual.py | replay_server.py | Status |
|---|---|---|---|---|---|
| 1 | `vessel_data` | `{soc, speed, vessel_state}` | YES (line 655) | YES (line 748-752) | MATCH but see notes |
| 2 | `ferry_position` | `{lat, lon, heading, speed}` | YES (line 656-661) | YES (line 740-745) | MATCH |
| 3 | `station_status` | `{state, current_station, departure_station, next_station, direction, stations}` | YES (line 884-891) | YES (line 646-653, 690-697, etc.) | MATCH |
| 4 | `weather_data` | `{temperature_c, wind_speed_kn, wind_direction_deg, humidity, precipitation_mm, wave_height_m, weather_description, tide_height_m, hours_since_high_tide, tide_phase}` | PARTIAL (line 571) | YES (line 669-680) | **GAP -- see details** |
| 5 | `passenger_count` | `{count}` | YES (line 483-487) | YES (line 665) | MATCH but extra fields |
| 6 | `anomaly_status` | `{motor_health, battery_health}` | YES (line 625, 691) | YES (line 765-768) | **GAP in values -- see details** |
| 7 | `auto_prediction` | `{mode, predictions: [{departure, destination, predicted_soc, soc_reduction, reach_km, safety_status, direction}]}` | YES (line 357, 371) | YES (line 661) | **GAP -- payload structure differs** |
| 8 | `realtime_prediction` | `{predicted_arrival_soc, soc_remaining_delta, reachable_stations}` | PARTIAL (line 713) | YES (line 787-794) | **GAP -- see details** |
| 9 | `speed_prediction_result` | `{departure, destination, speeds: [{speed_kn, predicted_soc, soc_reduction, safety_status}]}` | YES (line 982-987) | YES (line 549) | **GAP -- payload differs** |
| 10 | `safety_status` | `{status}` | YES (line 665) | NO | **GAP -- replay_server never emits this** |
| 11 | `prediction_result` | `{predicted_soc, soc_reduction, reach_km, safety_status, anomalies: {motor_health, battery_health, other}}` | YES (line 969) | NO | Legacy -- replay_server doesn't emit (OK) |

### Detailed Event Gaps:

#### 4. `weather_data` -- CRITICAL GAP

**replay_server.py emits (line 669-680):**
```python
{
    "temperature_c": ...,
    "wind_speed_kn": ...,
    "wind_direction_deg": ...,
    "humidity": ...,            # mapped from relative_humidity
    "precipitation_mm": ...,
    "wave_height_m": ...,
    "weather_description": ...,
    "tide_height_m": ...,       # from harmonic model
    "hours_since_high_tide": ...,
    "tide_phase": ...,          # from harmonic model
}
```

**client_sub_actual.py emits (line 571):**
```python
socketio.emit('weather_data', weather_state)
```
Where `weather_state` (lines 111-123) is:
```python
{
    "temperature_c": 28.0,
    "wind_speed_kn": 5.0,
    "wind_direction_deg": 180.0,
    "humidity": 75.0,
    "precipitation_mm": 0.0,
    "wave_height_m": 0.1,
    "wave_direction_deg": 0.0,       # extra -- frontend doesn't use
    "wave_period_s": 0.0,            # extra -- frontend doesn't use
    "ocean_current_velocity_ms": 0.0, # extra -- frontend doesn't use
    "ocean_current_direction_deg": 0.0, # extra -- frontend doesn't use
    "weather_description": "Unknown",
    # MISSING: tide_height_m
    # MISSING: hours_since_high_tide
    # MISSING: tide_phase
}
```

**What needs to change in client_sub_actual.py:**
- Import `compute_tide_features` from the inference bundle (like replay_server line 93)
- Before emitting `weather_data`, compute tide features: `tide = compute_tide_features(datetime.now())`
- Add three fields to the emitted payload: `tide_height_m`, `hours_since_high_tide`, `tide_phase`
- The frontend reads all three (dashboard_provider.dart lines 46-48) and displays them in the UI

#### 5. `passenger_count` -- MINOR

**client_sub_actual.py emits (line 483-487):**
```python
{'count': ..., 'total_boarded': ..., 'total_alighted': ...}
```

**replay_server.py emits (line 665):**
```python
{'count': ...}
```

**Frontend reads (dashboard_provider.dart line 22):**
```dart
data.passengerCount = payload['count'] ?? 0;
```

**Impact:** No gap. Frontend only reads `count`. The extra fields (`total_boarded`, `total_alighted`) are harmless -- the frontend ignores them.

#### 6. `anomaly_status` -- VALUE VOCABULARY GAP

**Motor health values emitted by client_sub_actual.py (lines 681-690):**
- `"OK"`, `"FAULT"`, `"WARNING"`

**Motor health values emitted by replay_server.py (line 764):**
- `"OK"`, `"ANOMALY"`

**Frontend reads (dashboard_provider.dart lines 53-54):**
```dart
data.liveMotorHealth = payload['motor_health'] ?? 'OK';
data.liveBatteryHealth = payload['battery_health'] ?? 'OK';
```

**Frontend UI usage (main.dart):** The UI compares against `'OK'` to decide color. Anything not `'OK'` is shown as a warning/alert.

**What needs to change:** Decide on a consistent vocabulary. The frontend treats any non-`'OK'` value as bad, so both `"FAULT"` and `"ANOMALY"` work, but `"WARNING"` vs `"FAULT"` gives more granularity in client_sub_actual.py. Replay server should ideally also emit `"WARNING"` level. Not a blocking issue but a semantic inconsistency.

#### 7. `auto_prediction` -- STRUCTURAL GAP

**replay_server.py emits (line 661, computed at line 273-279):**
```python
{
    "mode": "docked",
    "predictions": [{
        "departure": "...",
        "destination": "...",
        "predicted_soc": "78.2",        # point estimate as string
        "soc_reduction": "6.8",         # point estimate as string
        "safety_status": "SAFE",        # SAFE / CAUTION / CRITICAL
        "direction": "downstream",
        # NO reach_km field
    }]
}
```

**client_sub_actual.py emits (lines 341-371):**
```python
{
    "mode": "docked",
    "current_station": "...",           # extra field -- frontend ignores
    "predictions": [{
        "departure": "...",
        "destination": "...",
        "predicted_soc": "75.2-81.0%",  # RANGE string with "%" suffix
        "soc_reduction": "-3.5% to -6.2%", # RANGE string
        "reach_km": "45.2km",           # present, with "km" suffix
        "safety_status": "SAFE",        # SAFE / CAUTION / UNSAFE
        "direction": "upstream",
    }]
}
```

**Flutter AutoPrediction.fromMap (dashboard_data.dart line 44-52):**
```dart
predictedSoc: m['predicted_soc']?.toString(),
socReduction: m['soc_reduction']?.toString(),
reachKm: m['reach_km']?.toString(),
safetyStatus: m['safety_status'] ?? 'UNKNOWN',
```

**Gaps:**
1. **`predicted_soc` format:** client_sub_actual sends range `"75.2-81.0%"`, replay_server sends point `"78.2"`. Frontend uses `.toString()` so both technically work, but the displayed string will look different.
2. **`soc_reduction` format:** client_sub_actual sends `"-3.5% to -6.2%"`, replay_server sends `"6.8"`. Same display inconsistency.
3. **`reach_km`:** client_sub_actual includes it (`"45.2km"`), replay_server does NOT include it. Flutter data model supports it (`reachKm` field), but it will be `null` when coming from replay_server.
4. **`safety_status` values:** client_sub_actual uses `"SAFE"/"CAUTION"/"UNSAFE"` (line 295/323-327), replay_server uses `"SAFE"/"CAUTION"/"CRITICAL"` (line 272). Frontend doesn't branch on these specific values in auto_prediction display -- it passes through to the UI text.
5. **`current_station` extra field:** client_sub_actual includes `current_station` in docked mode (line 341) and `next_station` in moving mode (line 368). replay_server does not include these. Frontend ignores them (dashboard_provider.dart line 88-96 only reads `mode` and `predictions`).
6. **Scope of predictions when docked:** client_sub_actual only predicts to ADJACENT stations (upstream neighbor + downstream neighbor, lines 340-355). replay_server predicts to ALL reachable stations in both directions (lines 247-321). The frontend handles either -- it just displays whatever list it receives.

#### 8. `realtime_prediction` -- STRUCTURAL GAP

**replay_server.py emits (lines 787-794):**
```python
{
    "predicted_arrival_soc": 72.3,      # float
    "soc_remaining_delta": -5.2,        # float
    "reachable_stations": [             # list of dicts
        {"station": "Hulo", "soc": 68.1, "reachable": True}, ...
    ],
}
```

**client_sub_actual.py emits (line 713):**
```python
socketio.emit('realtime_prediction', result)
```
Where `result` comes directly from `realtime_predictor.update()` (line 711-712). The raw return from `SOCRealtimePredictor.update()` includes `predicted_arrival_soc`, `soc_remaining_delta`, and `reachable_stations` -- so the payload SHOULD match. However:

**Potential gap:** The `current_time` parameter is not passed in client_sub_actual.py (line 711: `realtime_predictor.update(telemetry_1b)` -- no `current_time` kwarg), whereas replay_server passes it (line 785: `self.rt_predictor.update(telemetry_dict, current_time=tick_time)`). This means tide features inside Model 1B may use `datetime.now()` in production (which is correct for live) vs. the replay timestamp (which is correct for replay). Not a gap per se, but worth noting.

**What needs to change:** Nothing structurally -- the payload should match since both use `SOCRealtimePredictor.update()`.

#### 9. `speed_prediction_result` -- MINOR GAP

**replay_server.py emits (line 549, built at lines 365-378):**
```python
{
    "departure": "...",
    "destination": "...",
    "speeds": [{
        "speed_kn": 5.0,
        "predicted_soc": "78.2%",       # point estimate with "%" suffix
        "soc_reduction": "6.8",         # point estimate
        "safety_status": "RECOMMENDED", # RECOMMENDED / CAUTION / CRITICAL
    }]
}
```

**client_sub_actual.py emits (lines 982-987):**
```python
{
    "departure": "...",
    "destination": "...",
    "current_soc": 70.0,                # extra field -- frontend ignores
    "speeds": [{
        "speed_kn": 4.0,
        "predicted_soc": "67.2-70.5%",  # RANGE with "%" suffix
        "soc_reduction": "-3.5% to -6.2%", # RANGE
        "safety_status": "RECOMMENDED", # RECOMMENDED / CAUTION / CRITICAL
    }]
}
```

**Flutter SpeedPrediction.fromMap (dashboard_data.dart lines 68-73):**
```dart
speedKn: (m['speed_kn'] as num?)?.toDouble() ?? 0,
predictedSoc: m['predicted_soc']?.toString(),
socReduction: m['soc_reduction']?.toString(),
safetyStatus: m['safety_status'] ?? 'UNKNOWN',
```

**Gaps:**
1. **`predicted_soc` format:** Range vs point estimate (same issue as auto_prediction).
2. **`soc_reduction` format:** Range vs point estimate.
3. **`current_soc` extra field:** client_sub_actual includes it; frontend ignores it.
4. **Speed list:** Different speeds used (see Section D).

#### 10. `safety_status` -- MISSING IN REPLAY SERVER

**client_sub_actual.py emits (line 665):**
```python
socketio.emit('safety_status', {'status': safety, 'soc': soc})
```
Where `safety` is `"SAFE"` if SOC > 15, else `"UNSAFE"`.

**replay_server.py:** Never emits this event.

**Frontend reads (dashboard_provider.dart lines 33-36):**
```dart
_socketService.onSafetyStatus = (payload) {
    data.safetyStatus = payload['status'] ?? 'UNKNOWN';
    notifyListeners();
};
```

**Impact:** In replay mode, `data.safetyStatus` stays `"UNKNOWN"` forever. The UI uses this in the top bar. However, looking at main.dart, the actual safety display uses `d.safetyStatus` from `safety_status`, but the main safety indicator that matters is computed from `d.soc` inline in the UI. So this is low severity but should still be addressed for completeness.

**What needs to change in replay_server.py:** Emit `safety_status` event alongside `vessel_data`, or in client_sub_actual.py this already works.

---

## B. Socket.IO Events -- Client Requests

Events the frontend SENDS (from `socket_service.dart` lines 95-125):

| # | Event Sent | Payload | client_sub_actual.py Handles | replay_server.py Handles | Status |
|---|---|---|---|---|---|
| 1 | `speed_prediction_request` | `{departure, destination}` | YES (line 972-987) | YES (line 526-549) | MATCH |
| 2 | `predict_request` | `{departure, destination, soc, passenger_count, weather}` | YES (line 944-969) | NO | Legacy -- OK |
| 3 | `end_trip` | (no payload) | YES (line 990-995) | NO | **GAP** |

### Detailed gaps:

**`end_trip`:** client_sub_actual.py handles it (sets `trip_active = False`, line 994). replay_server.py does not handle it -- the trip ends naturally when the segment's telemetry runs out. For production, this matters if the operator wants to manually end a trip.

**Replay-only events not in client_sub_actual.py:** The replay_server handles `set_replay_speed`, `start_replay`, `get_available_dates`, `load_date` (lines 552-598). These are replay-specific and should NOT be in client_sub_actual.py.

---

## C. Station Registry

### Station list comparison (all 3 files agree on 9 stations):

| Station | Order | client_sub_actual.py | replay_server.py | Flutter _fallbackStations |
|---|---|---|---|---|
| Napindan | 0 | 14.55713, 121.06836 | 14.55713, 121.06836 | 14.55713, 121.06836 |
| Guadalupe | 1 | 14.56811, 121.04792 | 14.5681100, 121.0478946 | 14.5681100, 121.0478946 |
| Hulo | 2 | 14.56794, 121.03364 | 14.5679545, 121.0336782 | 14.5679545, 121.0336782 |
| Valenzuela | 3 | 14.57400, 121.02578 | 14.5739778, 121.0257656 | 14.5739778, 121.0257656 |
| Lambingan | 4 | 14.58728, 121.01846 | 14.5872813, 121.0184560 | 14.5872813, 121.0184560 |
| Sta Ana | 5 | 14.58272, 121.01195 | 14.5827238, 121.0119451 | 14.5827238, 121.0119451 |
| PUP | 6 | 14.59604, 121.01070 | 14.5960355, 121.0107013 | 14.5960355, 121.0107013 |
| Quinta | 7 | 14.59578, 120.98145 | 14.5957803, 120.9814485 | 14.5957803, 120.9814485 |
| Escolta | 8 | 14.59638, 120.97753 | 14.5963832, 120.9775262 | 14.5963832, 120.9775262 |

### Coordinate precision gap:

**client_sub_actual.py uses lower precision (5 decimal places)** for ALL stations except Napindan. For example:
- Guadalupe: `14.56811, 121.04792` vs `14.5681100, 121.0478946`
- Hulo: `14.56794, 121.03364` vs `14.5679545, 121.0336782`

The differences are small but non-zero:
- Guadalupe lat: `14.56811` vs `14.56811` (same), lon: `121.04792` vs `121.0478946` (13m difference)
- Hulo lat: `14.56794` vs `14.5679545` (0.5m difference), lon: `121.03364` vs `121.0336782` (3.6m difference)

**Impact:** With a 200m geofence radius (line 52), these differences (~3-13m) are well within tolerance. However, for consistency, client_sub_actual.py should be updated to use the same high-precision coordinates.

### Cumulative distance (km) gap:

| Station | client_sub_actual.py | replay_server.py / Flutter |
|---|---|---|
| Napindan | 0.0 | 0.0 |
| Guadalupe | **3.5** | **6.5** |
| Hulo | **5.2** | **8.3** |
| Valenzuela | **6.8** | **9.8** |
| Lambingan | **8.2** | **11.2** |
| Sta Ana | **10.0** | **12.7** |
| PUP | **11.5** | **14.0** |
| Quinta | **14.0** | **15.6** |
| Escolta | **14.5** | **16.0** |

**CRITICAL GAP:** The cumulative distances differ by 1.5-3.0 km across the board. This affects:
- `_route_distance()` calculations in client_sub_actual.py (line 231-235)
- `reach_km` computations in `_predict_for_station()` (line 288-289)
- Any distance-based features passed to ML models

**What needs to change:** client_sub_actual.py should adopt the replay_server.py / Flutter km values, which appear to be the corrected measurements.

### Napindan coordinate:
Both files use identical coordinates for Napindan: `14.55713, 121.06836`. Note that this is the station registry coordinate used for geofencing. The `_riverPath` in main.dart uses a different coordinate for the Napindan waypoint `(14.5359379, 121.1021445)` -- this is the actual river start point (further south-east), distinct from the station GPS marker. This is by design and not a gap.

---

## D. Speed Predictions

### Speed values used:

| client_sub_actual.py (line 377) | replay_server.py (line 339) | Flutter mock (provider line 300-338) |
|---|---|---|
| `[4.0, 8.0, 12.0, 15.0]` | `[5.0, 7.0, 10.0, 12.0, 15.0]` | `[5, 7, 10, 12, 15]` |

**GAP:** client_sub_actual.py uses 4 speeds `[4, 8, 12, 15]` while the frontend/replay use 5 speeds `[5, 7, 10, 12, 15]`.

**Impact:** The Flutter UI (main.dart) renders a table of whatever speeds arrive -- it doesn't hardcode speed values. So both will display correctly, but the data will show different speeds.

**What needs to change:** client_sub_actual.py should use `[5.0, 7.0, 10.0, 12.0, 15.0]` to match the replay_server and Flutter mock data.

### Prediction method:

| Aspect | client_sub_actual.py | replay_server.py |
|---|---|---|
| Method | `predict_interval()` (conformal) -- returns range | `predict()` -- returns point estimate |
| Output format | `"75.2-81.0%"` (range) | `"78.2%"` (point) |
| Safety thresholds | `RECOMMENDED` (>25), `CAUTION` (>15), `CRITICAL` (<15) | `RECOMMENDED` (>50), `CAUTION` (>20), `CRITICAL` (<20) |

**CRITICAL GAP:** client_sub_actual.py calls `predict_interval()` (line 256, 388) which returns `{point, lower, upper}` from conformal prediction. replay_server.py calls `predict()` (line 251, 344) which returns just the point estimate.

This means:
1. client_sub_actual.py gives the operator a best/worst case range -- more informative
2. replay_server.py only gives a point estimate

**Also CRITICAL:** Safety thresholds differ:
- client_sub_actual.py: SAFE if `avg > SOC_SAFETY_THRESHOLD` (15%, line 30/295)
- replay_server.py: SAFE if `arrival_soc > 50`, CAUTION if `> 20` (line 272)

These are completely different safety regimes. The replay_server uses much more conservative thresholds.

### Battery capacity:

| Aspect | client_sub_actual.py | replay_server.py |
|---|---|---|
| HV capacity | Dynamic from vessel API: `vessel_telemetry.get("hvBatteryCapacity", 136.0)` (line 253) | Hardcoded: `NOMINAL_HV_CAPACITY = 160.0` (line 72) |

**GAP:** client_sub_actual.py defaults to 136 kWh (wrong -- actual is 160 kWh), replay_server.py correctly uses 160 kWh. If the vessel API returns the correct value, client_sub_actual.py will be fine, but the fallback default of 136 is wrong.

**What needs to change:** Change client_sub_actual.py default from 136.0 to 160.0.

---

## E. Model Integration

### Models loaded:

| Model | client_sub_actual.py | replay_server.py |
|---|---|---|
| 1A (trip SOC) | YES -- `SOCTripPredictor` (line 71) | YES -- `SOCTripPredictor` (line 417) |
| 1B (realtime SOC) | YES -- `SOCRealtimePredictor` (line 92) | YES -- `SOCRealtimePredictor` (line 420) |
| 2 (motor anomaly) | YES -- `MotorAnomalyDetector` (line 78) | YES -- `MotorAnomalyDetector` (line 423) |
| 3a/3b (battery anomaly) | YES -- `BatteryAnomalyDetector` (line 84) | **NO** |
| Tide harmonic model | **NO** | YES -- `compute_tide_features` (line 93) |

### Missing integrations:

1. **client_sub_actual.py is MISSING tide model:** Does not import or use `compute_tide_features`. This is why the `weather_data` event lacks tide fields. The tide module is bundled in `rpi5_bundle/inference/features/tide.py` and requires no internet.

2. **replay_server.py is MISSING battery anomaly model (3a/3b):** Does not import `BatteryAnomalyDetector`. It hardcodes `battery_health: "OK"` (line 768). This means the dashboard always shows battery health as OK during replay. For replay purposes this may be acceptable (historical BMS data would need to be in the parquet), but for completeness it should be noted.

### Model paths:

| Aspect | client_sub_actual.py | replay_server.py |
|---|---|---|
| Bundle root | `D:/2ndSem/new_empty_folder/Thesis/Ferry_digial_shadow/Models/rpi5_bundle` (line 33) | Relative: `../Ferry_digial_shadow/Models/rpi5_bundle` (line 37) |
| Models dir | `{BUNDLE_DIR}/models` | `{BUNDLE_DIR}/models` |
| Config dir | `{BUNDLE_DIR}/config` | `{BUNDLE_DIR}/config` |

**GAP:** client_sub_actual.py uses an absolute Windows path that is specific to the partner's machine. This is expected for production deployment but will break on any other machine. The path also contains a typo (`Ferry_digial_shadow` -- "digial" instead of "digital") but this matches the actual directory name in the repo, so it's consistent.

### Inference call differences:

**Model 1A -- `predict()` vs `predict_interval()`:**
- client_sub_actual.py calls `trip_predictor.predict_interval(method="conformal", ...)` (lines 256, 388)
- replay_server.py calls `trip_predictor.predict(...)` (lines 251, 344)

This is the biggest functional difference. `predict_interval` returns `{point, lower, upper}` which enables range-based predictions.

**Model 1B -- `start_trip()` parameters:**
Both files pass the same parameters. MATCH.

**Model 1B -- `update()` call:**
- client_sub_actual.py: `realtime_predictor.update(telemetry_1b)` -- no `current_time` (line 711)
- replay_server.py: `self.rt_predictor.update(telemetry_dict, current_time=tick_time)` (line 785)

In production, omitting `current_time` means the predictor uses `datetime.now()`, which is correct for live operation. Not a gap.

**Model 1B -- `trip_nm` field mapping:**
- client_sub_actual.py: `"trip_nm": data.get("trip", 0)` (line 709) -- reads from vessel API field `"trip"`
- replay_server.py: `"trip_nm": trip_nm or 0.0` (line 779) -- reads from parquet column `trip_nm`

**Potential issue:** If the vessel API field for nautical miles traveled is not `"trip"`, Model 1B's predictions will be degraded. Need to verify the actual vessel API field name.

---

## F. Navigation State Machine

### State names:

| State | client_sub_actual.py | replay_server.py | Frontend expects |
|---|---|---|---|
| UNKNOWN | YES (line 133) | NO (starts directly with DOCKED) | YES (navState init = 'UNKNOWN') |
| DOCKED | YES | YES | YES |
| DEPARTING | YES | YES | YES |
| IN_TRANSIT | YES | YES | YES |
| ARRIVING | YES | YES | YES |

### State machine comparison:

**client_sub_actual.py (lines 728-869):** Full GPS-based state machine:
- UNKNOWN -> DOCKED (if geofenced) or IN_TRANSIT (if moving)
- DOCKED -> DEPARTING (speed >= 2.0 kn)
- DEPARTING -> IN_TRANSIT (left geofence) or DOCKED (stopped before leaving)
- IN_TRANSIT -> ARRIVING (entered different station geofence) or stays (updates direction)
- ARRIVING -> DOCKED (stopped for 3s in geofence) or IN_TRANSIT (passed through)

**replay_server.py (lines 641-854):** Scripted linear sequence per segment:
- DOCKED (at departure) -> DEPARTING -> [1Hz ticks with vessel_data] -> ARRIVING (at arrival) -> DOCKED

**Key differences:**
1. client_sub_actual.py uses real GPS geofencing (200m radius) and speed thresholds (2.0/1.0 kn)
2. replay_server.py follows predetermined segments -- no actual geofence logic
3. client_sub_actual.py has `UNKNOWN` initial state; replay_server.py starts at `DOCKED`
4. client_sub_actual.py can detect direction changes mid-trip; replay_server.py has fixed direction per segment
5. client_sub_actual.py handles edge cases (returning to departure station, stopping mid-route for 60s)

**Frontend expectations (dashboard_data.dart lines 190-192):**
```dart
bool get isDocked => navState == 'DOCKED';
bool get isMoving => navState == 'IN_TRANSIT' || navState == 'DEPARTING';
bool get isArriving => navState == 'ARRIVING';
```

Both backends emit states that satisfy these checks. No gap.

**Note:** replay_server.py never emits vessel_state `"IN_TRANSIT"` during the telemetry loop -- it emits it inside `vessel_data` (line 752), but does NOT emit a separate `station_status` with `state: "IN_TRANSIT"`. The station_status goes: DOCKED -> DEPARTING -> ARRIVING. The frontend sees `vessel_state: "IN_TRANSIT"` from `vessel_data` but the `navState` from `station_status` jumps from DEPARTING to ARRIVING without an explicit IN_TRANSIT station_status emit.

**Impact:** Since `isMoving` includes both `DEPARTING` and `IN_TRANSIT`, the ferry will show as "moving" during DEPARTING. But the navState will stay `DEPARTING` for the entire trip until ARRIVING. This is slightly different from client_sub_actual.py which transitions to IN_TRANSIT after leaving the geofence.

---

## G. Configuration Differences

### Network Settings:

| Setting | client_sub_actual.py | replay_server.py |
|---|---|---|
| Server host | `0.0.0.0:5000` | `0.0.0.0:5000` |
| Vessel API | `http://10.0.161.22:8481/vessel` (line 18) | N/A (reads from DuckDB) |
| BMS Port API | `http://10.0.161.22:8481/device/OneAries_IP_3_ID_49` (line 20) | N/A |
| BMS Stbd API | `http://10.0.161.22:8481/device/OneAries_IP_4_ID_49` (line 21) | N/A |
| MQTT Broker | `10.121.235.153:1883` (lines 22-23) | N/A |
| Weather API | Open-Meteo at `14.5873, 121.0107` (lines 26-27) | N/A (reads from DuckDB) |
| Flutter server URL | N/A | `http://192.168.1.111:5000` (main.dart line 14) |

### Flutter connection target:
The Flutter app connects to `http://192.168.1.111:5000` (main.dart line 14, dashboard_provider.dart line 13). This needs to match whichever server is running (client_sub_actual.py or replay_server.py). For production deployment on the vessel, this IP must be the address of the machine running client_sub_actual.py on the vessel's local network.

### Model bundle path:
- client_sub_actual.py: `D:/2ndSem/new_empty_folder/Thesis/Ferry_digial_shadow/Models/rpi5_bundle` (hardcoded absolute path, line 33)
- replay_server.py: `../Ferry_digial_shadow/Models/rpi5_bundle` (relative to script, line 37)

### Hardcoded values that need attention:

| Value | client_sub_actual.py | replay_server.py | Correct Value |
|---|---|---|---|
| HV capacity default | 136.0 kWh (line 253) | 160.0 kWh (line 72) | **160.0 kWh** |
| SOC safety threshold | 15% (line 30) | 50%/20% (line 219-224) | **Needs alignment** |
| Geofence radius | 200m (line 52) | N/A | OK for production |
| Speed moving threshold | 2.0 kn (line 55) | N/A | OK for production |
| Speed stopped threshold | 1.0 kn (line 56) | N/A | OK for production |
| Weather poll interval | 30 min (line 572) | N/A (per-segment from DB) | OK |
| BMS poll interval | 1s telemetry, 5s anomaly (lines 614-615) | N/A | OK |
| Vessel poll interval | 1s (line 725) | 1s (replay tick, line 829) | OK |

### Socket.IO library:
- client_sub_actual.py: Flask-SocketIO (synchronous, threading-based) -- `flask_socketio` (line 3)
- replay_server.py: python-socketio (async, aiohttp-based) -- `socketio.AsyncServer` (line 403)

This is a significant architectural difference. Flask-SocketIO uses `socketio.emit()` (blocking), while replay_server uses `await self.sio.emit()` (async). Both are compatible with the same Socket.IO protocol that the Flutter client speaks.

---

## Summary of Required Changes (Priority Order)

### P0 -- CRITICAL (breaks functionality):

1. **Add tide features to weather_data in client_sub_actual.py:** Import `compute_tide_features`, compute tide at emission time, add `tide_height_m`, `hours_since_high_tide`, `tide_phase` to the `weather_data` payload. Without this, the tide display in the Flutter UI shows zeros.

2. **Fix cumulative km distances in client_sub_actual.py:** Update all station `km` values to match replay_server.py / Flutter (e.g., Guadalupe: 3.5 -> 6.5). Wrong distances affect reach_km calculations and potentially ML model feature inputs.

3. **Fix HV capacity default in client_sub_actual.py:** Change default from `136.0` to `160.0` (line 253, 385). Wrong capacity causes incorrect SOC predictions when vessel API doesn't provide it.

### P1 -- HIGH (affects prediction quality/display):

4. **Align speed list:** Change client_sub_actual.py speeds from `[4.0, 8.0, 12.0, 15.0]` to `[5.0, 7.0, 10.0, 12.0, 15.0]`.

5. **Align safety thresholds:** Decide on consistent thresholds across both backends. Current: client_sub_actual uses 15% (aggressive), replay_server uses 50/20% (conservative).

6. **Update station coordinates precision:** Update client_sub_actual.py station coordinates to match the higher-precision values used by replay_server and Flutter.

### P2 -- MEDIUM (inconsistencies):

7. **Prediction format:** client_sub_actual.py sends range strings (`"75.2-81.0%"`) while replay_server sends point estimates (`"78.2"`). Both work in the UI, but the display is inconsistent. Consider standardizing on the range format since it's more informative.

8. **Auto-prediction scope:** client_sub_actual.py only predicts adjacent stations when docked; replay_server predicts all reachable stations. Consider expanding client_sub_actual.py to match.

9. **Anomaly status vocabulary:** Standardize on `"OK"`, `"WARNING"`, `"FAULT"` (client_sub_actual.py's richer vocabulary) vs. `"OK"`, `"ANOMALY"` (replay_server's simpler vocabulary).

10. **Add `safety_status` emission to replay_server.py:** Currently never emitted; frontend's `safetyStatus` stays `"UNKNOWN"` in replay mode.

### P3 -- LOW (nice to have):

11. **Add battery anomaly model to replay_server.py:** Currently hardcodes `"OK"`.
12. **Verify vessel API field name for trip_nm:** Confirm `data.get("trip", 0)` maps to actual nautical miles in the vessel API.
13. **Add `end_trip` handler to replay_server.py:** Currently not handled; trip ends naturally when segment data runs out.
14. **replay_server.py should emit station_status IN_TRANSIT:** Currently jumps from DEPARTING to ARRIVING without explicit IN_TRANSIT station_status.
