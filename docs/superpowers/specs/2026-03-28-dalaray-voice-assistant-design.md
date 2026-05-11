# Dalaray Voice Assistant — Design Spec

**Date:** 2026-03-28
**Status:** Approved
**Target Device:** Amazon Fire HD 8 (10th gen), Fire OS 7, 2GB RAM

## Overview

Add a voice assistant named "Dalaray" to the existing Flutter dashboard for the M/B Dalaray ferry. The assistant serves the **crew/captain only** — it provides a voice interface to live dashboard data, announces reachable stations when docked, alerts on anomalies, and allows voice-based passenger count correction.

## Architecture

### 3-Tier STT Fallback

| Priority | Source | When Used | Languages | Latency |
|----------|--------|-----------|-----------|---------|
| Tier 1 | Cloud API (Google Cloud STT or OpenAI Whisper API) | Internet available | EN + Filipino | ~1-2s |
| Tier 2 | RPi5 Vosk (LAN) | No internet, RPi5 reachable | EN + Filipino | ~3-5s |
| Tier 3 | Fire OS Platform STT | Both above unavailable | English only | ~1s |

Fallback is automatic and silent to the crew. If Tier 1 fails/times out (3s), falls to Tier 2, then Tier 3.

### Component Distribution

**Fire HD 8 Tablet (on-device, always):**
- Porcupine wake word detection ("Dalaray") — ~2MB model, on-device
- `flutter_tts` — text-to-speech using Fire OS built-in engine, works offline
- Intent matcher — keyword/pattern matching in Dart (~12 intents)
- Push-to-talk (default) with toggle to always-listening mode
- Platform STT as Tier 3 fallback

**RPi5 4GB (LAN, new addition):**
- Vosk STT HTTP/WebSocket service — lazy-loaded on first voice request
- ~200MB RAM when active, unloads after idle timeout
- Supports English + Filipino models
- Primary RPi5 workload (Python backend, XGBoost inference, DuckDB) unchanged

**Cloud (internet):**
- Google Cloud STT or OpenAI Whisper API — best accuracy
- Estimated cost: ~$0.50-1/day at crew usage levels (~50-100 requests/day)

### Data Flow

**Voice command flow:**
1. Crew activates mic (push-to-talk button or "Dalaray" wake word in auto mode)
2. Audio recorded on tablet
3. Audio sent to STT (Tier 1 → 2 → 3 fallback)
4. Transcribed text processed by intent matcher (on-device Dart)
5. Intent matcher reads current `DashboardData` state from Provider
6. Response constructed and spoken via `flutter_tts`
7. Response text shown in panel conversation log

**Auto-announce flow (no STT):**
1. Backend sends `station_status` event (ferry docked) or anomaly score exceeds threshold
2. Dashboard provider receives event, triggers voice service
3. Voice service constructs announcement from `auto_prediction` data or anomaly scores
4. Spoken via `flutter_tts` (works offline)

## Voice Commands & Intents

### Auto-Triggered Announcements (TTS only)

| Trigger | English Response | Filipino Response |
|---------|-----------------|-------------------|
| Ferry docks | "Docked at {station}. Reachable stations: {list}." | "Naka-dock sa {station}. Maaaring puntahan: {list}." |
| Motor anomaly | "Warning. Motor anomaly detected. Score: {score}." | "Babala. May nakitang anomalya sa motor. Score: {score}." |
| Battery anomaly | "Warning. Battery anomaly detected. Check dashboard." | "Babala. May anomalya sa baterya. Tingnan ang dashboard." |
| SOC below threshold | "Caution. Battery at {soc} percent. Consider docking soon." | "Ingat. Baterya nasa {soc} porsyento. Pag-isipang mag-dock na." |

### Status Queries (~6 intents)

| Intent | English Triggers | Filipino Triggers | Response Template |
|--------|-----------------|-------------------|-------------------|
| Battery status | "battery", "SOC", "charge" | "baterya", "karga", "tsarging" | "Battery is at {soc}%. Predicted arrival SOC: {pred}%." / "Baterya nasa {soc}%. Inaasahang SOC sa dating: {pred}%." |
| Weather | "weather", "wind", "waves", "tide" | "panahon", "hangin", "alon", "taog" | "Temperature {temp} degrees. Wind {wind} knots {dir}. Tide height {tide} meters, {phase}." / "Temperatura {temp} digri. Hangin {wind} knots {dir}. Taog {tide} metro, {phase}." |
| Position | "where", "position", "location", "station" | "nasaan", "saan", "posisyon", "istasyon" | "In transit from {dep} to {dest}. Speed: {speed} knots." / "Naglalakbay mula {dep} papuntang {dest}. Bilis: {speed} knots." |
| Passenger count | "passengers", "how many", "count" | "pasahero", "ilan", "sakay" | "There are {count} passengers on board." / "May {count} na pasahero sa barko." |
| Anomaly status | "anomaly", "motor", "health", "status" | "problema", "anomalya", "motor", "kalusugan" | "All systems normal. Motor health: good. Battery health: good." / "Lahat ng sistema normal. Motor: maayos. Baterya: maayos." |
| Reachable stations | "reach", "stations", "where can we go" | "punta", "abot", "maabot", "istasyon" | "From current SOC, you can reach: {list}." / "Mula sa kasalukuyang SOC, maaari mong puntahan: {list}." |

### Passenger Correction (~3 intents)

| Intent | English Triggers | Filipino Triggers | Action |
|--------|-----------------|-------------------|--------|
| Set absolute | "set passengers to {N}" | "palitan ang pasahero sa {N}" | Set count to N, emit `passenger_correction` |
| Add | "add {N} passengers" | "dagdagan ng {N} ang pasahero" | Add N to current, emit `passenger_correction` |
| Remove | "remove {N} passengers" | "bawasan ng {N} ang pasahero" | Subtract N from current, emit `passenger_correction` |

Number extraction via regex from transcribed text. Floor at 0, cap at 150 (ferry capacity).

### Speed Prediction (~1 intent)

| Intent | English Triggers | Filipino Triggers | Action |
|--------|-----------------|-------------------|--------|
| Predict to station | "predict to {station}" | "hulaan papuntang {station}" | Emit `speed_prediction_request`, read back result |

Station name matched against known 9 stations (fuzzy matching for speech recognition errors).

### Intent Matching Strategy

- ~12 intents total, keyword-based matching in Dart
- Both English and Filipino keyword sets checked simultaneously
- Supports Taglish (mixed language) — response in whichever language had more keyword hits
- Number extraction via simple regex
- Station name matching via Levenshtein distance for fuzzy matching
- Fallback: "Sorry, I didn't understand. You can ask about battery, weather, passengers, anomalies, or reachable stations."

## UI Design

### Button Placement

A **blue mic icon button** (36x36) added to the existing bottom-right control row:

`[Map Toggle] [Dalaray] [Settings Gear] [Debug Bug]`

- Follows the same `Container` + `GestureDetector` pattern as existing buttons
- Blue background (#2563EB) with blue border (#60A5FA) to distinguish from the dark gear/debug buttons
- Always visible on all views (like the gear button)

### Dalaray Panel (Overlay)

Clicking the Dalaray button opens a **Positioned overlay panel** (same pattern as the debug panel) anchored bottom-right:

- **Width:** 280px
- **Position:** `bottom: 54, right: 12` (stacked above button row)
- **Border:** 1.5px solid #60A5FA (blue, matching button)
- **Background:** rgba(0,0,0,0.92)

**Panel sections (top to bottom):**

1. **Header** — "DALARAY" title + ready/listening/processing/speaking status indicator + close button
2. **Voice Settings**
   - Listening mode toggle: PTT (default) / Auto
   - Response language toggle: EN / FIL / Auto
   - Volume slider
   - Speech rate: Slow / Normal / Fast
3. **Auto Announcements** — Toggle switches for:
   - Docking station announcements (default: on)
   - Motor anomaly alerts (default: on)
   - Battery anomaly alerts (default: on)
   - Low SOC warnings (default: on)
   - Low SOC threshold input (default: 15%)
4. **Passenger Correction**
   - +/- stepper buttons with current count
   - "manually corrected" / "from sensor" indicator
   - "Reset to sensor value" link
5. **Connection Status**
   - Cloud STT: Connected/Disconnected
   - RPi5 Vosk: Available/Unavailable
   - Platform STT: Ready
   - Active STT: which tier is currently being used
6. **Mic Button (bottom bar)** — Push-to-talk button + "Tap to speak" label

### Mic Button States

| State | Color | Icon | Description |
|-------|-------|------|-------------|
| Idle | Blue (#3B82F6) | Microphone | Ready for push-to-talk |
| Listening | Red (#EF4444), pulsing glow | Microphone | Recording audio |
| Processing | Amber (#F59E0B) | Spinner | STT + intent matching |
| Speaking | Green (#34D399), glow | Speaker | TTS playing response |

### Settings Persistence

All voice settings saved via `SharedPreferences`:
- `dalaray_listening_mode`: "ptt" | "auto"
- `dalaray_language`: "en" | "fil" | "auto"
- `dalaray_volume`: 0.0 - 1.0
- `dalaray_speech_rate`: "slow" | "normal" | "fast"
- `dalaray_announce_docking`: bool
- `dalaray_announce_motor_anomaly`: bool
- `dalaray_announce_battery_anomaly`: bool
- `dalaray_announce_low_soc`: bool
- `dalaray_low_soc_threshold`: int (percent)

## Error Handling

### STT Failures
- Tier 1 timeout: 3 seconds → fall to Tier 2
- Tier 2 timeout: 5 seconds → fall to Tier 3
- All tiers fail → TTS: "Sorry, I couldn't hear that. Please try again."
- Fallback is transparent to crew — no manual tier selection needed

### TTS Failures
- If `flutter_tts` fails → show text-only response in panel conversation log
- TTS queue: new announcements queued behind current speech
- Exception: anomaly alerts interrupt current speech immediately

### Wake Word (Auto Mode)
- Porcupine triggers but STT returns empty/nonsense → silently ignore
- Sensitivity configurable if false activations are frequent

### Passenger Correction Guards
- Floor: 0 (cannot go negative)
- Cap: 150 (ferry capacity)
- Invalid voice input → "Passenger count cannot be {negative/above 150}."
- Backend notification: new `passenger_correction` Socket.IO event with `{count: N, source: "manual"}`

### Concurrent Events
- Anomaly alert during voice response → interrupt and announce alert
- Docking announcement during crew command → queue after response completes

### Offline Behavior
- TTS always works (on-device) — auto-announcements continue regardless of connectivity
- STT degrades gracefully through 3 tiers
- Connection Status section in panel shows current tier

## New Dependencies (Flutter)

| Package | Purpose |
|---------|---------|
| `flutter_tts` | Text-to-speech (Fire OS built-in engine) |
| `speech_to_text` | Platform STT (Tier 3 fallback) |
| `porcupine_flutter` | Wake word detection ("Dalaray") |
| `record` or `flutter_sound` | Audio recording for cloud/RPi5 STT |
| `http` or `dio` | Send audio to Cloud STT API / RPi5 Vosk endpoint |

## New RPi5 Component

A lightweight Vosk STT HTTP endpoint added to the existing Python backend:

- **Endpoint:** `POST /stt` — accepts audio (WAV/PCM), returns `{text, language, confidence}`
- **Models:** Vosk `vosk-model-small-en-us` (~40MB) + `vosk-model-small-tl-ph` (~40MB) if available, else `vosk-model-en-us` (~200MB)
- **Lifecycle:** Model lazy-loaded on first `/stt` request, unloaded after 5 minutes idle
- **Integration:** Added as a new route in the existing FastAPI app, no separate service needed

## Out of Scope

- Passenger-facing announcements (crew only)
- LLM-based conversational AI (keyword matching only)
- Historical data queries ("How much SOC did we use yesterday?")
- Custom voice/persona for TTS (uses system default)
- Offline Filipino STT on Fire OS platform (Tier 3 is English-only)
