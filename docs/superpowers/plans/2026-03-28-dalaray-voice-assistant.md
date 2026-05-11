# Dalaray Voice Assistant Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a bilingual (EN/Filipino) voice assistant named "Dalaray" to the Flutter ferry dashboard — providing voice queries of live data, auto-announcements, and passenger count correction.

**Architecture:** 3-tier STT fallback (Cloud API > RPi5 Vosk LAN > Platform STT) with on-device TTS, keyword-based intent matching (~12 intents), and a Positioned overlay panel matching the existing debug panel pattern. RPi5 gets a new Vosk STT endpoint alongside the existing FastAPI backend.

**Tech Stack:** Flutter 3.11+, flutter_tts, speech_to_text, porcupine_flutter, record, http, Provider, Vosk (Python), FastAPI

**Spec:** `docs/superpowers/specs/2026-03-28-dalaray-voice-assistant-design.md`

---

## File Structure

### New Files (Flutter)

| File | Responsibility |
|------|---------------|
| `lib/models/voice_models.dart` | Enums (VoiceState, ListeningMode, VoiceLanguage, SpeechRate), VoiceSettings class, ConversationEntry class |
| `lib/services/intent_matcher.dart` | Keyword-based intent matching, bilingual keyword maps, number extraction, station fuzzy matching, response template generation |
| `lib/services/tts_service.dart` | flutter_tts wrapper: speak queue, interrupt for alerts, volume/rate/language control |
| `lib/services/stt_service.dart` | 3-tier STT fallback: cloud API, RPi5 Vosk HTTP, platform speech_to_text. Audio recording via record package. Connection status tracking |
| `lib/services/voice_service.dart` | Orchestrator ChangeNotifier: coordinates TTS+STT+IntentMatcher, manages VoiceState, auto-announcements, conversation log, reads DashboardData |
| `lib/widgets/dalaray_panel.dart` | Overlay panel widget: settings toggles, announcement switches, passenger correction, connection status, mic button, conversation log |
| `test/intent_matcher_test.dart` | Unit tests for intent matching (pure Dart, no platform deps) |

### Modified Files (Flutter)

| File | Changes |
|------|---------|
| `pubspec.yaml` | Add flutter_tts, speech_to_text, porcupine_flutter, record, http |
| `lib/services/socket_service.dart` | Add `emitPassengerCorrection(int count, String source)` method |
| `lib/providers/dashboard_provider.dart` | Add passenger correction forwarding, expose auto-announce trigger hooks |
| `lib/main.dart` | Add Dalaray button in `_buildDebugToggle()`, add `_buildDalarayPanel()` overlay in Stack, init VoiceService via MultiProvider |

### New Files (RPi5 Backend)

| File | Responsibility |
|------|---------------|
| `Daluyan_V2/backend/app/api/stt.py` | FastAPI router: `POST /stt` endpoint accepting WAV audio |
| `Daluyan_V2/backend/app/services/vosk_stt.py` | Vosk model lazy-loading, transcription, idle unload timer |

### Modified Files (RPi5 Backend)

| File | Changes |
|------|---------|
| `Daluyan_V2/backend/app/main.py` | Include stt router |

---

## Task 1: Add Flutter Dependencies

**Files:**
- Modify: `flutter_application_1/pubspec.yaml`

- [ ] **Step 1: Add voice dependencies to pubspec.yaml**

Open `flutter_application_1/pubspec.yaml` and add these dependencies under the existing `dependencies:` section, after `path_provider`:

```yaml
  flutter_tts: ^4.2.0
  speech_to_text: ^7.0.0
  porcupine_flutter: ^3.0.0
  record: ^5.1.0
  http: ^1.2.0
```

- [ ] **Step 2: Run flutter pub get**

```bash
cd flutter_application_1
flutter pub get
```

Expected: All packages resolve successfully. If `porcupine_flutter` has version conflicts, use the latest compatible version shown in the error.

- [ ] **Step 3: Commit**

```bash
git add flutter_application_1/pubspec.yaml flutter_application_1/pubspec.lock
git commit -m "feat(voice): add TTS, STT, wake word, and audio recording dependencies"
```

---

## Task 2: Voice Models

**Files:**
- Create: `flutter_application_1/lib/models/voice_models.dart`
- Create: `flutter_application_1/test/voice_models_test.dart`

- [ ] **Step 1: Write the voice models test**

Create `flutter_application_1/test/voice_models_test.dart`:

```dart
import 'package:flutter_test/flutter_test.dart';
import 'package:flutter_application_1/models/voice_models.dart';

void main() {
  group('VoiceSettings', () {
    test('defaults are correct', () {
      final s = VoiceSettings();
      expect(s.listeningMode, ListeningMode.ptt);
      expect(s.language, VoiceLanguage.en);
      expect(s.volume, 0.75);
      expect(s.speechRate, SpeechRate.normal);
      expect(s.announceDocking, true);
      expect(s.announceMotorAnomaly, true);
      expect(s.announceBatteryAnomaly, true);
      expect(s.announceLowSoc, true);
      expect(s.lowSocThreshold, 15);
    });

    test('copyWith preserves unchanged fields', () {
      final s = VoiceSettings();
      final s2 = s.copyWith(volume: 0.5, language: VoiceLanguage.fil);
      expect(s2.volume, 0.5);
      expect(s2.language, VoiceLanguage.fil);
      expect(s2.listeningMode, ListeningMode.ptt); // unchanged
      expect(s2.lowSocThreshold, 15); // unchanged
    });
  });

  group('ConversationEntry', () {
    test('creates crew entry', () {
      final e = ConversationEntry.crew('What is the battery?');
      expect(e.speaker, Speaker.crew);
      expect(e.text, 'What is the battery?');
      expect(e.isAuto, false);
    });

    test('creates dalaray entry', () {
      final e = ConversationEntry.dalaray('Battery is at 64 percent.');
      expect(e.speaker, Speaker.dalaray);
      expect(e.text, 'Battery is at 64 percent.');
      expect(e.isAuto, false);
    });

    test('creates auto-announcement entry', () {
      final e = ConversationEntry.autoAnnounce('Docked at Guadalupe.');
      expect(e.speaker, Speaker.dalaray);
      expect(e.isAuto, true);
    });
  });
}
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd flutter_application_1
flutter test test/voice_models_test.dart
```

Expected: FAIL — `voice_models.dart` does not exist.

- [ ] **Step 3: Implement voice models**

Create `flutter_application_1/lib/models/voice_models.dart`:

```dart
enum VoiceState { idle, listening, processing, speaking }

enum ListeningMode { ptt, auto }

enum VoiceLanguage { en, fil, auto }

enum SpeechRate { slow, normal, fast }

enum Speaker { crew, dalaray }

enum SttTier { cloud, rpi5, platform, none }

class VoiceSettings {
  final ListeningMode listeningMode;
  final VoiceLanguage language;
  final double volume;
  final SpeechRate speechRate;
  final bool announceDocking;
  final bool announceMotorAnomaly;
  final bool announceBatteryAnomaly;
  final bool announceLowSoc;
  final int lowSocThreshold;

  const VoiceSettings({
    this.listeningMode = ListeningMode.ptt,
    this.language = VoiceLanguage.en,
    this.volume = 0.75,
    this.speechRate = SpeechRate.normal,
    this.announceDocking = true,
    this.announceMotorAnomaly = true,
    this.announceBatteryAnomaly = true,
    this.announceLowSoc = true,
    this.lowSocThreshold = 15,
  });

  VoiceSettings copyWith({
    ListeningMode? listeningMode,
    VoiceLanguage? language,
    double? volume,
    SpeechRate? speechRate,
    bool? announceDocking,
    bool? announceMotorAnomaly,
    bool? announceBatteryAnomaly,
    bool? announceLowSoc,
    int? lowSocThreshold,
  }) {
    return VoiceSettings(
      listeningMode: listeningMode ?? this.listeningMode,
      language: language ?? this.language,
      volume: volume ?? this.volume,
      speechRate: speechRate ?? this.speechRate,
      announceDocking: announceDocking ?? this.announceDocking,
      announceMotorAnomaly: announceMotorAnomaly ?? this.announceMotorAnomaly,
      announceBatteryAnomaly: announceBatteryAnomaly ?? this.announceBatteryAnomaly,
      announceLowSoc: announceLowSoc ?? this.announceLowSoc,
      lowSocThreshold: lowSocThreshold ?? this.lowSocThreshold,
    );
  }
}

class ConversationEntry {
  final Speaker speaker;
  final String text;
  final DateTime timestamp;
  final bool isAuto;

  ConversationEntry({
    required this.speaker,
    required this.text,
    DateTime? timestamp,
    this.isAuto = false,
  }) : timestamp = timestamp ?? DateTime.now();

  factory ConversationEntry.crew(String text) {
    return ConversationEntry(speaker: Speaker.crew, text: text);
  }

  factory ConversationEntry.dalaray(String text) {
    return ConversationEntry(speaker: Speaker.dalaray, text: text);
  }

  factory ConversationEntry.autoAnnounce(String text) {
    return ConversationEntry(speaker: Speaker.dalaray, text: text, isAuto: true);
  }
}
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd flutter_application_1
flutter test test/voice_models_test.dart
```

Expected: All 5 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add flutter_application_1/lib/models/voice_models.dart flutter_application_1/test/voice_models_test.dart
git commit -m "feat(voice): add voice state enums, VoiceSettings, and ConversationEntry models"
```

---

## Task 3: Intent Matcher (TDD)

**Files:**
- Create: `flutter_application_1/lib/services/intent_matcher.dart`
- Create: `flutter_application_1/test/intent_matcher_test.dart`

This is the core logic — pure Dart, no platform dependencies, fully testable.

- [ ] **Step 1: Write the intent matcher tests**

Create `flutter_application_1/test/intent_matcher_test.dart`:

```dart
import 'package:flutter_test/flutter_test.dart';
import 'package:flutter_application_1/services/intent_matcher.dart';
import 'package:flutter_application_1/models/voice_models.dart';

void main() {
  late IntentMatcher matcher;

  setUp(() {
    matcher = IntentMatcher();
  });

  group('English intent matching', () {
    test('battery keywords match batteryStatus', () {
      final r = matcher.match("what's the battery");
      expect(r.intent, Intent.batteryStatus);
      expect(r.language, VoiceLanguage.en);
    });

    test('SOC keyword matches batteryStatus', () {
      final r = matcher.match('how much SOC do we have');
      expect(r.intent, Intent.batteryStatus);
    });

    test('weather keyword matches weather', () {
      final r = matcher.match("what's the weather like");
      expect(r.intent, Intent.weather);
    });

    test('wind keyword matches weather', () {
      final r = matcher.match('how strong is the wind');
      expect(r.intent, Intent.weather);
    });

    test('where keyword matches position', () {
      final r = matcher.match('where are we');
      expect(r.intent, Intent.position);
    });

    test('passengers keyword matches passengerCount', () {
      final r = matcher.match('how many passengers');
      expect(r.intent, Intent.passengerCount);
    });

    test('anomaly keyword matches anomalyStatus', () {
      final r = matcher.match('any anomalies');
      expect(r.intent, Intent.anomalyStatus);
    });

    test('reach keyword matches reachableStations', () {
      final r = matcher.match('what stations can we reach');
      expect(r.intent, Intent.reachableStations);
    });
  });

  group('Filipino intent matching', () {
    test('baterya matches batteryStatus in Filipino', () {
      final r = matcher.match('ano yung baterya');
      expect(r.intent, Intent.batteryStatus);
      expect(r.language, VoiceLanguage.fil);
    });

    test('pasahero matches passengerCount in Filipino', () {
      final r = matcher.match('ilan ang pasahero');
      expect(r.intent, Intent.passengerCount);
      expect(r.language, VoiceLanguage.fil);
    });

    test('nasaan matches position in Filipino', () {
      final r = matcher.match('nasaan tayo');
      expect(r.intent, Intent.position);
      expect(r.language, VoiceLanguage.fil);
    });

    test('panahon matches weather in Filipino', () {
      final r = matcher.match('ano yung panahon');
      expect(r.intent, Intent.weather);
      expect(r.language, VoiceLanguage.fil);
    });

    test('problema matches anomalyStatus in Filipino', () {
      final r = matcher.match('may problema ba');
      expect(r.intent, Intent.anomalyStatus);
      expect(r.language, VoiceLanguage.fil);
    });

    test('punta matches reachableStations in Filipino', () {
      final r = matcher.match('saan tayo pwedeng pumunta');
      expect(r.intent, Intent.reachableStations);
      expect(r.language, VoiceLanguage.fil);
    });
  });

  group('Passenger correction', () {
    test('set passengers to N', () {
      final r = matcher.match('set passengers to 15');
      expect(r.intent, Intent.setPassengers);
      expect(r.number, 15);
    });

    test('add N passengers', () {
      final r = matcher.match('add 3 passengers');
      expect(r.intent, Intent.addPassengers);
      expect(r.number, 3);
    });

    test('remove N passengers', () {
      final r = matcher.match('remove 2 passengers');
      expect(r.intent, Intent.removePassengers);
      expect(r.number, 2);
    });

    test('Filipino set passengers', () {
      final r = matcher.match('palitan ang pasahero sa 15');
      expect(r.intent, Intent.setPassengers);
      expect(r.number, 15);
      expect(r.language, VoiceLanguage.fil);
    });

    test('Filipino add passengers', () {
      final r = matcher.match('dagdagan ng 3 ang pasahero');
      expect(r.intent, Intent.addPassengers);
      expect(r.number, 3);
    });

    test('Filipino remove passengers', () {
      final r = matcher.match('bawasan ng 2 ang pasahero');
      expect(r.intent, Intent.removePassengers);
      expect(r.number, 2);
    });
  });

  group('Station prediction', () {
    test('predict to Escolta', () {
      final r = matcher.match('predict to Escolta');
      expect(r.intent, Intent.predictToStation);
      expect(r.station, 'Escolta');
    });

    test('predict to Guadalupe', () {
      final r = matcher.match('can we reach Guadalupe');
      expect(r.intent, Intent.predictToStation);
      expect(r.station, 'Guadalupe');
    });

    test('fuzzy matches station name', () {
      final r = matcher.match('predict to Guadaloupe'); // misspelling
      expect(r.intent, Intent.predictToStation);
      expect(r.station, 'Guadalupe');
    });

    test('Filipino predict', () {
      final r = matcher.match('hulaan papuntang Escolta');
      expect(r.intent, Intent.predictToStation);
      expect(r.station, 'Escolta');
    });
  });

  group('Taglish and edge cases', () {
    test('mixed language uses majority language', () {
      // "baterya" is Filipino, rest is English
      final r = matcher.match('check the baterya level');
      expect(r.intent, Intent.batteryStatus);
    });

    test('unknown input returns unknown intent', () {
      final r = matcher.match('play some music');
      expect(r.intent, Intent.unknown);
    });

    test('empty input returns unknown', () {
      final r = matcher.match('');
      expect(r.intent, Intent.unknown);
    });
  });

  group('Response generation', () {
    test('generates English battery response', () {
      final response = IntentMatcher.batteryResponse(
        soc: 64, predictedSoc: 52.0, language: VoiceLanguage.en,
      );
      expect(response, 'Battery is at 64 percent. Predicted arrival SOC: 52 percent.');
    });

    test('generates Filipino battery response', () {
      final response = IntentMatcher.batteryResponse(
        soc: 64, predictedSoc: 52.0, language: VoiceLanguage.fil,
      );
      expect(response, 'Baterya nasa 64 porsyento. Inaasahang SOC sa dating: 52 porsyento.');
    });

    test('generates English docking announcement', () {
      final response = IntentMatcher.dockingAnnouncement(
        station: 'Guadalupe',
        reachable: ['Napindan', 'Hulo', 'Lambingan'],
        language: VoiceLanguage.en,
      );
      expect(response, 'Docked at Guadalupe. Reachable stations: Napindan, Hulo, Lambingan.');
    });

    test('generates Filipino docking announcement', () {
      final response = IntentMatcher.dockingAnnouncement(
        station: 'Guadalupe',
        reachable: ['Napindan', 'Hulo'],
        language: VoiceLanguage.fil,
      );
      expect(response, 'Naka-dock sa Guadalupe. Maaaring puntahan: Napindan, Hulo.');
    });

    test('generates passenger set confirmation', () {
      final response = IntentMatcher.passengerSetResponse(
        count: 15, language: VoiceLanguage.en,
      );
      expect(response, 'Passenger count updated to 15.');
    });
  });
}
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd flutter_application_1
flutter test test/intent_matcher_test.dart
```

Expected: FAIL — `intent_matcher.dart` does not exist.

- [ ] **Step 3: Implement the intent matcher**

Create `flutter_application_1/lib/services/intent_matcher.dart`:

```dart
import 'dart:math';
import '../models/voice_models.dart';

enum Intent {
  batteryStatus,
  weather,
  position,
  passengerCount,
  anomalyStatus,
  reachableStations,
  setPassengers,
  addPassengers,
  removePassengers,
  predictToStation,
  unknown,
}

class MatchResult {
  final Intent intent;
  final VoiceLanguage language;
  final int? number;
  final String? station;

  const MatchResult({
    required this.intent,
    this.language = VoiceLanguage.en,
    this.number,
    this.station,
  });
}

class IntentMatcher {
  static const _stationNames = [
    'Napindan', 'Guadalupe', 'Hulo', 'Valenzuela',
    'Lambingan', 'Sta Ana', 'PUP', 'Quinta', 'Escolta',
  ];

  // English keyword → intent mapping
  static const _enKeywords = <Intent, List<String>>{
    Intent.batteryStatus: ['battery', 'soc', 'charge'],
    Intent.weather: ['weather', 'wind', 'wave', 'waves', 'tide'],
    Intent.position: ['where', 'position', 'location'],
    Intent.passengerCount: ['passengers', 'passenger', 'how many', 'count'],
    Intent.anomalyStatus: ['anomaly', 'anomalies', 'health', 'motor status', 'system status'],
    Intent.reachableStations: ['reach', 'reachable', 'where can we go'],
  };

  // Filipino keyword → intent mapping
  static const _filKeywords = <Intent, List<String>>{
    Intent.batteryStatus: ['baterya', 'karga', 'tsarging'],
    Intent.weather: ['panahon', 'hangin', 'alon', 'taog'],
    Intent.position: ['nasaan', 'saan', 'posisyon', 'istasyon'],
    Intent.passengerCount: ['pasahero', 'ilan', 'sakay'],
    Intent.anomalyStatus: ['problema', 'anomalya', 'kalusugan'],
    Intent.reachableStations: ['punta', 'pumunta', 'abot', 'maabot'],
  };

  // Passenger correction keywords
  static const _enSetPassengers = ['set passengers', 'update passengers', 'correct passengers'];
  static const _enAddPassengers = ['add', 'plus', 'more'];
  static const _enRemovePassengers = ['remove', 'minus', 'less'];

  static const _filSetPassengers = ['palitan', 'baguhin', 'itama'];
  static const _filAddPassengers = ['dagdag', 'dagdagan', 'idagdag'];
  static const _filRemovePassengers = ['bawas', 'bawasan', 'tanggalin'];

  // Prediction keywords
  static const _enPrediction = ['predict to', 'predict', 'can we reach', 'soc to'];
  static const _filPrediction = ['hula', 'hulaan', 'papunta', 'papuntang'];

  MatchResult match(String input) {
    if (input.trim().isEmpty) {
      return const MatchResult(intent: Intent.unknown);
    }

    final lower = input.toLowerCase();

    // 1. Check passenger correction first (more specific)
    final passengerResult = _matchPassengerCorrection(lower);
    if (passengerResult != null) return passengerResult;

    // 2. Check station prediction
    final predictionResult = _matchPrediction(lower);
    if (predictionResult != null) return predictionResult;

    // 3. Check status queries
    return _matchStatusQuery(lower);
  }

  MatchResult? _matchPassengerCorrection(String lower) {
    final number = _extractNumber(lower);
    if (number == null) return null;

    int enHits = 0;
    int filHits = 0;

    // Set
    for (final kw in _enSetPassengers) {
      if (lower.contains(kw)) {
        return MatchResult(intent: Intent.setPassengers, language: VoiceLanguage.en, number: number);
      }
    }
    for (final kw in _filSetPassengers) {
      if (lower.contains(kw)) {
        return MatchResult(intent: Intent.setPassengers, language: VoiceLanguage.fil, number: number);
      }
    }

    // Add
    final hasPassengerWord = lower.contains('passenger') || lower.contains('pasahero');
    for (final kw in _enAddPassengers) {
      if (lower.contains(kw) && hasPassengerWord) {
        enHits++;
      }
    }
    for (final kw in _filAddPassengers) {
      if (lower.contains(kw)) {
        filHits++;
      }
    }
    if (enHits > 0 || filHits > 0) {
      return MatchResult(
        intent: Intent.addPassengers,
        language: filHits > enHits ? VoiceLanguage.fil : VoiceLanguage.en,
        number: number,
      );
    }

    // Remove
    enHits = 0;
    filHits = 0;
    for (final kw in _enRemovePassengers) {
      if (lower.contains(kw) && hasPassengerWord) {
        enHits++;
      }
    }
    for (final kw in _filRemovePassengers) {
      if (lower.contains(kw)) {
        filHits++;
      }
    }
    if (enHits > 0 || filHits > 0) {
      return MatchResult(
        intent: Intent.removePassengers,
        language: filHits > enHits ? VoiceLanguage.fil : VoiceLanguage.en,
        number: number,
      );
    }

    return null;
  }

  MatchResult? _matchPrediction(String lower) {
    bool hasPredictionKeyword = false;
    int enHits = 0;
    int filHits = 0;

    for (final kw in _enPrediction) {
      if (lower.contains(kw)) {
        hasPredictionKeyword = true;
        enHits++;
      }
    }
    for (final kw in _filPrediction) {
      if (lower.contains(kw)) {
        hasPredictionKeyword = true;
        filHits++;
      }
    }

    // Also check if any station name is mentioned (even without prediction keyword for "can we reach X")
    final station = _extractStation(lower);
    if (station != null && (hasPredictionKeyword || lower.contains('reach') || lower.contains('abot'))) {
      return MatchResult(
        intent: Intent.predictToStation,
        language: filHits > enHits ? VoiceLanguage.fil : VoiceLanguage.en,
        station: station,
      );
    }

    return null;
  }

  MatchResult _matchStatusQuery(String lower) {
    int enTotal = 0;
    int filTotal = 0;
    Intent? bestIntent;
    int bestScore = 0;

    // Score each intent against EN keywords
    for (final entry in _enKeywords.entries) {
      int score = 0;
      for (final kw in entry.value) {
        if (lower.contains(kw)) score++;
      }
      if (score > bestScore) {
        bestScore = score;
        bestIntent = entry.key;
      }
      enTotal += score;
    }

    // Score each intent against FIL keywords
    Intent? bestFilIntent;
    int bestFilScore = 0;
    for (final entry in _filKeywords.entries) {
      int score = 0;
      for (final kw in entry.value) {
        if (lower.contains(kw)) score++;
      }
      if (score > bestFilScore) {
        bestFilScore = score;
        bestFilIntent = entry.key;
      }
      filTotal += score;
    }

    // Pick whichever language had more keyword hits
    if (bestFilScore > bestScore) {
      return MatchResult(intent: bestFilIntent!, language: VoiceLanguage.fil);
    }
    if (bestScore > 0) {
      return MatchResult(intent: bestIntent!, language: filTotal > enTotal ? VoiceLanguage.fil : VoiceLanguage.en);
    }

    return const MatchResult(intent: Intent.unknown);
  }

  int? _extractNumber(String text) {
    final match = RegExp(r'\b(\d+)\b').firstMatch(text);
    if (match == null) return null;
    return int.tryParse(match.group(1)!);
  }

  String? _extractStation(String text) {
    final lower = text.toLowerCase();

    // Exact match first
    for (final name in _stationNames) {
      if (lower.contains(name.toLowerCase())) return name;
    }

    // Fuzzy match — find words > 3 chars and check Levenshtein distance
    final words = text.split(RegExp(r'\s+'));
    String? bestMatch;
    int bestDistance = 4; // max acceptable distance

    for (final word in words) {
      if (word.length < 4) continue;
      for (final name in _stationNames) {
        final d = _levenshtein(word.toLowerCase(), name.toLowerCase());
        if (d < bestDistance) {
          bestDistance = d;
          bestMatch = name;
        }
      }
    }
    return bestMatch;
  }

  static int _levenshtein(String a, String b) {
    if (a.isEmpty) return b.length;
    if (b.isEmpty) return a.length;

    final matrix = List.generate(
      a.length + 1,
      (i) => List.generate(b.length + 1, (j) => i == 0 ? j : (j == 0 ? i : 0)),
    );

    for (int i = 1; i <= a.length; i++) {
      for (int j = 1; j <= b.length; j++) {
        final cost = a[i - 1] == b[j - 1] ? 0 : 1;
        matrix[i][j] = [
          matrix[i - 1][j] + 1,
          matrix[i][j - 1] + 1,
          matrix[i - 1][j - 1] + cost,
        ].reduce(min);
      }
    }
    return matrix[a.length][b.length];
  }

  // ── Response generators ──

  static String batteryResponse({
    required int soc,
    required double? predictedSoc,
    required VoiceLanguage language,
  }) {
    final pred = predictedSoc?.round() ?? soc;
    if (language == VoiceLanguage.fil) {
      return 'Baterya nasa $soc porsyento. Inaasahang SOC sa dating: $pred porsyento.';
    }
    return 'Battery is at $soc percent. Predicted arrival SOC: $pred percent.';
  }

  static String weatherResponse({
    required double tempC,
    required double windKn,
    required double windDirDeg,
    required double tideM,
    required int tidePhase,
    required VoiceLanguage language,
  }) {
    final windDir = _degToCardinal(windDirDeg);
    final phase = tidePhase == 0 ? (language == VoiceLanguage.fil ? 'tumataas' : 'rising')
                                 : (language == VoiceLanguage.fil ? 'bumababa' : 'falling');
    if (language == VoiceLanguage.fil) {
      return 'Temperatura ${tempC.round()} digri. Hangin ${windKn.round()} knots $windDir. Taog ${tideM.toStringAsFixed(1)} metro, $phase.';
    }
    return 'Temperature ${tempC.round()} degrees. Wind ${windKn.round()} knots $windDir. Tide height ${tideM.toStringAsFixed(1)} meters, $phase.';
  }

  static String positionResponse({
    required String navState,
    required String? departure,
    required String? destination,
    required String? currentStation,
    required double speed,
    required VoiceLanguage language,
  }) {
    if (navState == 'DOCKED') {
      if (language == VoiceLanguage.fil) {
        return 'Naka-dock sa ${currentStation ?? "hindi alam"}.';
      }
      return 'Docked at ${currentStation ?? "unknown station"}.';
    }
    if (language == VoiceLanguage.fil) {
      return 'Naglalakbay mula ${departure ?? "?"} papuntang ${destination ?? "?"}. Bilis: ${speed.toStringAsFixed(1)} knots.';
    }
    return 'In transit from ${departure ?? "?"} to ${destination ?? "?"}. Speed: ${speed.toStringAsFixed(1)} knots.';
  }

  static String passengerCountResponse({required int count, required VoiceLanguage language}) {
    if (language == VoiceLanguage.fil) {
      return 'May $count na pasahero sa barko.';
    }
    return 'There are $count passengers on board.';
  }

  static String anomalyResponse({
    required String motorHealth,
    required String batteryHealth,
    required VoiceLanguage language,
  }) {
    final motorOk = motorHealth.toLowerCase() == 'good' || motorHealth.toLowerCase() == 'normal';
    final batteryOk = batteryHealth.toLowerCase() == 'good' || batteryHealth.toLowerCase() == 'normal';

    if (motorOk && batteryOk) {
      if (language == VoiceLanguage.fil) {
        return 'Lahat ng sistema normal. Motor: maayos. Baterya: maayos.';
      }
      return 'All systems normal. Motor health: good. Battery health: good.';
    }
    if (language == VoiceLanguage.fil) {
      return 'Motor: ${motorOk ? "maayos" : "may problema"}. Baterya: ${batteryOk ? "maayos" : "may problema"}.';
    }
    return 'Motor health: ${motorOk ? "good" : "anomaly detected"}. Battery health: ${batteryOk ? "good" : "anomaly detected"}.';
  }

  static String reachableStationsResponse({
    required List<String> stations,
    required VoiceLanguage language,
  }) {
    if (stations.isEmpty) {
      if (language == VoiceLanguage.fil) return 'Walang maaaring puntahan mula sa kasalukuyang SOC.';
      return 'No reachable stations from current SOC.';
    }
    final list = stations.join(', ');
    if (language == VoiceLanguage.fil) {
      return 'Mula sa kasalukuyang SOC, maaari mong puntahan: $list.';
    }
    return 'From current SOC, you can reach: $list.';
  }

  static String passengerSetResponse({required int count, required VoiceLanguage language}) {
    if (language == VoiceLanguage.fil) return 'Bilang ng pasahero binago sa $count.';
    return 'Passenger count updated to $count.';
  }

  static String passengerAddResponse({required int added, required int total, required VoiceLanguage language}) {
    if (language == VoiceLanguage.fil) return 'Dinagdagan ng $added. Bilang ng pasahero ngayon $total.';
    return 'Added $added. Passenger count is now $total.';
  }

  static String passengerRemoveResponse({required int removed, required int total, required VoiceLanguage language}) {
    if (language == VoiceLanguage.fil) return 'Binawasan ng $removed. Bilang ng pasahero ngayon $total.';
    return 'Removed $removed. Passenger count is now $total.';
  }

  static String passengerErrorResponse({required String reason, required VoiceLanguage language}) {
    if (language == VoiceLanguage.fil) return 'Hindi maaaring baguhin ang bilang ng pasahero: $reason.';
    return 'Passenger count cannot be $reason.';
  }

  static String dockingAnnouncement({
    required String station,
    required List<String> reachable,
    required VoiceLanguage language,
  }) {
    final list = reachable.join(', ');
    if (language == VoiceLanguage.fil) {
      return 'Naka-dock sa $station. Maaaring puntahan: $list.';
    }
    return 'Docked at $station. Reachable stations: $list.';
  }

  static String motorAnomalyAlert({required double score, required VoiceLanguage language}) {
    if (language == VoiceLanguage.fil) {
      return 'Babala. May nakitang anomalya sa motor. Score: ${score.toStringAsFixed(1)}.';
    }
    return 'Warning. Motor anomaly detected. Score: ${score.toStringAsFixed(1)}.';
  }

  static String batteryAnomalyAlert({required VoiceLanguage language}) {
    if (language == VoiceLanguage.fil) return 'Babala. May anomalya sa baterya. Tingnan ang dashboard.';
    return 'Warning. Battery anomaly detected. Check dashboard.';
  }

  static String lowSocAlert({required int soc, required VoiceLanguage language}) {
    if (language == VoiceLanguage.fil) {
      return 'Ingat. Baterya nasa $soc porsyento. Pag-isipang mag-dock na.';
    }
    return 'Caution. Battery at $soc percent. Consider docking soon.';
  }

  static String fallbackResponse({required VoiceLanguage language}) {
    if (language == VoiceLanguage.fil) {
      return 'Pasensya, hindi ko naintindihan. Pwede kang magtanong tungkol sa baterya, panahon, pasahero, anomalya, o mga istasyon.';
    }
    return "Sorry, I didn't understand. You can ask about battery, weather, passengers, anomalies, or reachable stations.";
  }

  static String sttFailedResponse({required VoiceLanguage language}) {
    if (language == VoiceLanguage.fil) return 'Pasensya, hindi ko narinig. Subukan ulit.';
    return "Sorry, I couldn't hear that. Please try again.";
  }

  static String _degToCardinal(double deg) {
    const dirs = ['N', 'NE', 'E', 'SE', 'S', 'SW', 'W', 'NW'];
    return dirs[((deg % 360) / 45).round() % 8];
  }
}
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd flutter_application_1
flutter test test/intent_matcher_test.dart
```

Expected: All tests PASS. If any fail, adjust keyword logic.

- [ ] **Step 5: Commit**

```bash
git add flutter_application_1/lib/services/intent_matcher.dart flutter_application_1/test/intent_matcher_test.dart
git commit -m "feat(voice): add bilingual intent matcher with keyword matching and response generation"
```

---

## Task 4: TTS Service

**Files:**
- Create: `flutter_application_1/lib/services/tts_service.dart`

- [ ] **Step 1: Implement the TTS service**

Create `flutter_application_1/lib/services/tts_service.dart`:

```dart
import 'dart:async';
import 'dart:collection';
import 'package:flutter_tts/flutter_tts.dart';
import '../models/voice_models.dart';

class TtsService {
  final FlutterTts _tts = FlutterTts();
  final Queue<String> _queue = Queue();
  bool _isSpeaking = false;

  VoidCallback? onSpeakingStarted;
  VoidCallback? onSpeakingDone;

  Future<void> init() async {
    await _tts.setLanguage('en-US');
    await _tts.setSpeechRate(0.5);
    await _tts.setVolume(0.75);

    _tts.setStartHandler(() {
      _isSpeaking = true;
      onSpeakingStarted?.call();
    });

    _tts.setCompletionHandler(() {
      _isSpeaking = false;
      onSpeakingDone?.call();
      _processQueue();
    });

    _tts.setCancelHandler(() {
      _isSpeaking = false;
      onSpeakingDone?.call();
    });

    _tts.setErrorHandler((msg) {
      _isSpeaking = false;
      onSpeakingDone?.call();
      _processQueue();
    });
  }

  Future<void> speak(String text) async {
    if (_isSpeaking) {
      _queue.add(text);
      return;
    }
    await _doSpeak(text);
  }

  /// Interrupt current speech and speak immediately (for anomaly alerts).
  Future<void> interruptAndSpeak(String text) async {
    _queue.clear();
    if (_isSpeaking) {
      await _tts.stop();
    }
    await _doSpeak(text);
  }

  Future<void> _doSpeak(String text) async {
    _isSpeaking = true;
    onSpeakingStarted?.call();
    await _tts.speak(text);
  }

  void _processQueue() {
    if (_queue.isNotEmpty) {
      final next = _queue.removeFirst();
      _doSpeak(next);
    }
  }

  Future<void> setVolume(double vol) async {
    await _tts.setVolume(vol.clamp(0.0, 1.0));
  }

  Future<void> setSpeechRate(SpeechRate rate) async {
    final mapping = {
      SpeechRate.slow: 0.35,
      SpeechRate.normal: 0.5,
      SpeechRate.fast: 0.65,
    };
    await _tts.setSpeechRate(mapping[rate]!);
  }

  Future<void> setLanguage(VoiceLanguage lang) async {
    // Fire OS may not support Filipino TTS — fall back to English
    if (lang == VoiceLanguage.fil) {
      final available = await _tts.isLanguageAvailable('fil-PH');
      if (available == 1) {
        await _tts.setLanguage('fil-PH');
        return;
      }
    }
    await _tts.setLanguage('en-US');
  }

  bool get isSpeaking => _isSpeaking;

  Future<void> stop() async {
    _queue.clear();
    await _tts.stop();
    _isSpeaking = false;
  }

  Future<void> dispose() async {
    await stop();
  }
}
```

- [ ] **Step 2: Verify it compiles**

```bash
cd flutter_application_1
flutter analyze lib/services/tts_service.dart
```

Expected: No analysis issues (warnings about unused imports are fine at this stage).

- [ ] **Step 3: Commit**

```bash
git add flutter_application_1/lib/services/tts_service.dart
git commit -m "feat(voice): add TTS service with speech queue and interrupt support"
```

---

## Task 5: STT Service

**Files:**
- Create: `flutter_application_1/lib/services/stt_service.dart`

- [ ] **Step 1: Implement the STT service**

Create `flutter_application_1/lib/services/stt_service.dart`:

```dart
import 'dart:async';
import 'dart:convert';
import 'dart:typed_data';
import 'package:http/http.dart' as http;
import 'package:record/record.dart';
import 'package:speech_to_text/speech_to_text.dart' as stt;
import '../models/voice_models.dart';

class SttResult {
  final String text;
  final SttTier tier;
  final double confidence;

  const SttResult({required this.text, required this.tier, this.confidence = 0.0});

  static const empty = SttResult(text: '', tier: SttTier.none);
}

class SttService {
  final AudioRecorder _recorder = AudioRecorder();
  final stt.SpeechToText _platformStt = stt.SpeechToText();
  bool _platformSttAvailable = false;

  String? cloudApiUrl;   // e.g., 'https://speech.googleapis.com/v1/speech:recognize'
  String? cloudApiKey;   // API key for cloud STT
  String? rpi5SttUrl;    // e.g., 'http://192.168.1.111:5000/stt'

  SttTier _activeTier = SttTier.none;
  SttTier get activeTier => _activeTier;

  bool _cloudAvailable = false;
  bool _rpi5Available = false;
  bool _platformAvailable = false;

  bool get cloudAvailable => _cloudAvailable;
  bool get rpi5Available => _rpi5Available;
  bool get platformAvailable => _platformAvailable;

  Future<void> init({String? serverUrl}) async {
    // Derive RPi5 STT URL from the dashboard server URL
    if (serverUrl != null) {
      final uri = Uri.parse(serverUrl);
      rpi5SttUrl = '${uri.scheme}://${uri.host}:${uri.port}/stt';
    }

    // Check platform STT availability
    _platformSttAvailable = await _platformStt.initialize();
    _platformAvailable = _platformSttAvailable;

    // Check RPi5 availability
    await checkRpi5();

    // Cloud is assumed available if API key is set
    _cloudAvailable = cloudApiKey != null && cloudApiKey!.isNotEmpty;

    _updateActiveTier();
  }

  Future<void> checkRpi5() async {
    if (rpi5SttUrl == null) {
      _rpi5Available = false;
      return;
    }
    try {
      final response = await http.get(
        Uri.parse(rpi5SttUrl!.replaceAll('/stt', '/health')),
      ).timeout(const Duration(seconds: 2));
      _rpi5Available = response.statusCode == 200;
    } catch (_) {
      _rpi5Available = false;
    }
    _updateActiveTier();
  }

  void _updateActiveTier() {
    if (_cloudAvailable) {
      _activeTier = SttTier.cloud;
    } else if (_rpi5Available) {
      _activeTier = SttTier.rpi5;
    } else if (_platformAvailable) {
      _activeTier = SttTier.platform;
    } else {
      _activeTier = SttTier.none;
    }
  }

  /// Record audio and transcribe with 3-tier fallback.
  /// Returns transcribed text or empty string on failure.
  Future<SttResult> listen() async {
    // Record audio as WAV
    final audioBytes = await _recordAudio();
    if (audioBytes == null || audioBytes.isEmpty) return SttResult.empty;

    // Tier 1: Cloud STT
    if (_cloudAvailable) {
      try {
        final result = await _cloudTranscribe(audioBytes)
            .timeout(const Duration(seconds: 3));
        if (result.text.isNotEmpty) return result;
      } catch (_) {
        // Fall through to Tier 2
      }
    }

    // Tier 2: RPi5 Vosk
    if (_rpi5Available) {
      try {
        final result = await _rpi5Transcribe(audioBytes)
            .timeout(const Duration(seconds: 5));
        if (result.text.isNotEmpty) return result;
      } catch (_) {
        // Fall through to Tier 3
      }
    }

    // Tier 3: Platform STT
    if (_platformAvailable) {
      try {
        final result = await _platformTranscribe();
        if (result.text.isNotEmpty) return result;
      } catch (_) {
        // All tiers failed
      }
    }

    return SttResult.empty;
  }

  Future<Uint8List?> _recordAudio() async {
    if (!await _recorder.hasPermission()) return null;

    // Record to a temporary file as WAV, 16kHz mono (optimal for STT)
    final stream = await _recorder.startStream(
      const RecordConfig(
        encoder: AudioEncoder.pcm16bits,
        sampleRate: 16000,
        numChannels: 1,
      ),
    );

    final chunks = <Uint8List>[];
    final completer = Completer<Uint8List>();

    // Collect audio chunks for up to 10 seconds
    Timer? timeout;
    final sub = stream.listen((data) {
      chunks.add(data);
    });

    timeout = Timer(const Duration(seconds: 10), () async {
      await sub.cancel();
      await _recorder.stop();
      final allBytes = chunks.expand((c) => c).toList();
      completer.complete(Uint8List.fromList(allBytes));
    });

    return completer.future;
  }

  /// Stop recording early (when user releases push-to-talk).
  Future<void> stopRecording() async {
    await _recorder.stop();
  }

  Future<SttResult> _cloudTranscribe(Uint8List audio) async {
    if (cloudApiUrl == null || cloudApiKey == null) {
      return SttResult.empty;
    }

    final base64Audio = base64Encode(audio);
    final response = await http.post(
      Uri.parse('$cloudApiUrl?key=$cloudApiKey'),
      headers: {'Content-Type': 'application/json'},
      body: jsonEncode({
        'config': {
          'encoding': 'LINEAR16',
          'sampleRateHertz': 16000,
          'languageCode': 'en-US',
          'alternativeLanguageCodes': ['fil-PH'],
        },
        'audio': {'content': base64Audio},
      }),
    );

    if (response.statusCode == 200) {
      final json = jsonDecode(response.body);
      final results = json['results'] as List?;
      if (results != null && results.isNotEmpty) {
        final alt = results[0]['alternatives'][0];
        return SttResult(
          text: alt['transcript'] as String,
          tier: SttTier.cloud,
          confidence: (alt['confidence'] as num?)?.toDouble() ?? 0.0,
        );
      }
    }
    return SttResult.empty;
  }

  Future<SttResult> _rpi5Transcribe(Uint8List audio) async {
    if (rpi5SttUrl == null) return SttResult.empty;

    final request = http.MultipartRequest('POST', Uri.parse(rpi5SttUrl!));
    request.files.add(http.MultipartFile.fromBytes('audio', audio, filename: 'audio.pcm'));

    final streamedResponse = await request.send();
    final response = await http.Response.fromStream(streamedResponse);

    if (response.statusCode == 200) {
      final json = jsonDecode(response.body);
      return SttResult(
        text: json['text'] as String? ?? '',
        tier: SttTier.rpi5,
        confidence: (json['confidence'] as num?)?.toDouble() ?? 0.0,
      );
    }
    return SttResult.empty;
  }

  Future<SttResult> _platformTranscribe() async {
    if (!_platformSttAvailable) return SttResult.empty;

    final completer = Completer<SttResult>();

    _platformStt.listen(
      onResult: (result) {
        if (result.finalResult && !completer.isCompleted) {
          completer.complete(SttResult(
            text: result.recognizedWords,
            tier: SttTier.platform,
            confidence: result.confidence,
          ));
        }
      },
      listenFor: const Duration(seconds: 10),
      localeId: 'en_US',
    );

    // Timeout fallback
    Timer(const Duration(seconds: 12), () {
      if (!completer.isCompleted) {
        _platformStt.stop();
        completer.complete(SttResult.empty);
      }
    });

    return completer.future;
  }

  Future<void> dispose() async {
    await _recorder.dispose();
    await _platformStt.stop();
  }
}
```

- [ ] **Step 2: Verify it compiles**

```bash
cd flutter_application_1
flutter analyze lib/services/stt_service.dart
```

Expected: No errors. Warnings about unused imports are acceptable.

- [ ] **Step 3: Commit**

```bash
git add flutter_application_1/lib/services/stt_service.dart
git commit -m "feat(voice): add 3-tier STT service with cloud, RPi5 Vosk, and platform fallback"
```

---

## Task 6: Voice Service (Orchestrator)

**Files:**
- Create: `flutter_application_1/lib/services/voice_service.dart`

- [ ] **Step 1: Implement the voice service**

Create `flutter_application_1/lib/services/voice_service.dart`:

```dart
import 'dart:async';
import 'package:flutter/foundation.dart';
import 'package:shared_preferences/shared_preferences.dart';
import '../models/dashboard_data.dart';
import '../models/voice_models.dart';
import '../providers/dashboard_provider.dart';
import 'intent_matcher.dart';
import 'tts_service.dart';
import 'stt_service.dart';

class VoiceService extends ChangeNotifier {
  final DashboardProvider _dashProvider;
  final TtsService _tts = TtsService();
  final SttService _stt = SttService();
  final IntentMatcher _matcher = IntentMatcher();

  VoiceState _state = VoiceState.idle;
  VoiceSettings _settings = const VoiceSettings();
  final List<ConversationEntry> _log = [];
  bool _panelOpen = false;
  bool _manualPassengerCorrection = false;
  int _manualPassengerCount = 0;

  // Track previous state for auto-announce change detection
  String? _prevNavState;
  String? _prevMotorHealth;
  String? _prevBatteryHealth;
  int? _prevSoc;
  bool _lowSocAlerted = false;

  VoiceService(this._dashProvider) {
    _dashProvider.addListener(_onDashboardChanged);
  }

  // ── Getters ──

  VoiceState get state => _state;
  VoiceSettings get settings => _settings;
  List<ConversationEntry> get log => List.unmodifiable(_log);
  bool get panelOpen => _panelOpen;
  bool get manualPassengerCorrection => _manualPassengerCorrection;
  int get displayPassengerCount =>
      _manualPassengerCorrection ? _manualPassengerCount : _dashProvider.data.passengerCount;
  SttTier get activeSttTier => _stt.activeTier;
  bool get cloudAvailable => _stt.cloudAvailable;
  bool get rpi5Available => _stt.rpi5Available;
  bool get platformAvailable => _stt.platformAvailable;

  // ── Initialization ──

  Future<void> init() async {
    await _tts.init();
    await _stt.init(serverUrl: _dashProvider.currentServerUrl);
    await _loadSettings();

    _tts.onSpeakingStarted = () {
      _state = VoiceState.speaking;
      notifyListeners();
    };
    _tts.onSpeakingDone = () {
      _state = VoiceState.idle;
      notifyListeners();
    };

    // Initialize prev state for change detection
    final d = _dashProvider.data;
    _prevNavState = d.navState;
    _prevMotorHealth = d.liveMotorHealth;
    _prevBatteryHealth = d.liveBatteryHealth;
    _prevSoc = d.soc;
  }

  // ── Panel ──

  void togglePanel() {
    _panelOpen = !_panelOpen;
    notifyListeners();
  }

  void closePanel() {
    _panelOpen = false;
    notifyListeners();
  }

  // ── Push-to-Talk Flow ──

  Future<void> startListening() async {
    if (_state != VoiceState.idle) return;

    _state = VoiceState.listening;
    notifyListeners();

    final result = await _stt.listen();

    _state = VoiceState.processing;
    notifyListeners();

    if (result.text.isEmpty) {
      final lang = _effectiveLanguage();
      final response = IntentMatcher.sttFailedResponse(language: lang);
      _addLog(ConversationEntry.dalaray(response));
      await _tts.speak(response);
      return;
    }

    _addLog(ConversationEntry.crew(result.text));
    await _processTranscription(result.text);
  }

  Future<void> stopListening() async {
    await _stt.stopRecording();
  }

  // ── Intent Processing ──

  Future<void> _processTranscription(String text) async {
    final match = _matcher.match(text);
    final lang = match.language == VoiceLanguage.en || match.language == VoiceLanguage.fil
        ? match.language
        : _effectiveLanguage();

    final d = _dashProvider.data;
    String response;

    switch (match.intent) {
      case Intent.batteryStatus:
        response = IntentMatcher.batteryResponse(
          soc: d.soc ?? 0, predictedSoc: d.realtimePredictedSoc, language: lang,
        );
      case Intent.weather:
        response = IntentMatcher.weatherResponse(
          tempC: d.temperatureC, windKn: d.windSpeedKn, windDirDeg: d.windDirectionDeg,
          tideM: d.tideHeightM, tidePhase: d.tidePhase, language: lang,
        );
      case Intent.position:
        response = IntentMatcher.positionResponse(
          navState: d.navState, departure: d.departureStation,
          destination: d.nextStation, currentStation: d.currentStation,
          speed: d.ferrySpeed, language: lang,
        );
      case Intent.passengerCount:
        response = IntentMatcher.passengerCountResponse(count: displayPassengerCount, language: lang);
      case Intent.anomalyStatus:
        response = IntentMatcher.anomalyResponse(
          motorHealth: d.liveMotorHealth, batteryHealth: d.liveBatteryHealth, language: lang,
        );
      case Intent.reachableStations:
        final reachable = d.autoPredictions
            .where((p) => p.safetyStatus.toLowerCase() == 'safe')
            .map((p) => p.destination)
            .toList();
        response = IntentMatcher.reachableStationsResponse(stations: reachable, language: lang);
      case Intent.setPassengers:
        response = _handleSetPassengers(match.number!, lang);
      case Intent.addPassengers:
        response = _handleAddPassengers(match.number!, lang);
      case Intent.removePassengers:
        response = _handleRemovePassengers(match.number!, lang);
      case Intent.predictToStation:
        _dashProvider.requestSpeedPrediction(
          d.currentStation ?? d.departureStation ?? 'Napindan',
          match.station!,
        );
        response = lang == VoiceLanguage.fil
            ? 'Kinakalkula ang hula papuntang ${match.station}. Tingnan ang speed table.'
            : 'Calculating prediction to ${match.station}. Check the speed table.';
      case Intent.unknown:
        response = IntentMatcher.fallbackResponse(language: lang);
    }

    _addLog(ConversationEntry.dalaray(response));
    await _tts.speak(response);
  }

  // ── Passenger Correction ──

  String _handleSetPassengers(int count, VoiceLanguage lang) {
    if (count < 0) return IntentMatcher.passengerErrorResponse(reason: 'negative', language: lang);
    if (count > 150) return IntentMatcher.passengerErrorResponse(reason: 'above 150', language: lang);
    _manualPassengerCount = count;
    _manualPassengerCorrection = true;
    _dashProvider.emitPassengerCorrection(count);
    notifyListeners();
    return IntentMatcher.passengerSetResponse(count: count, language: lang);
  }

  String _handleAddPassengers(int n, VoiceLanguage lang) {
    final newCount = (displayPassengerCount + n).clamp(0, 150);
    _manualPassengerCount = newCount;
    _manualPassengerCorrection = true;
    _dashProvider.emitPassengerCorrection(newCount);
    notifyListeners();
    return IntentMatcher.passengerAddResponse(added: n, total: newCount, language: lang);
  }

  String _handleRemovePassengers(int n, VoiceLanguage lang) {
    final newCount = (displayPassengerCount - n).clamp(0, 150);
    _manualPassengerCount = newCount;
    _manualPassengerCorrection = true;
    _dashProvider.emitPassengerCorrection(newCount);
    notifyListeners();
    return IntentMatcher.passengerRemoveResponse(removed: n, total: newCount, language: lang);
  }

  void adjustPassengerCount(int delta) {
    final newCount = (displayPassengerCount + delta).clamp(0, 150);
    _manualPassengerCount = newCount;
    _manualPassengerCorrection = true;
    _dashProvider.emitPassengerCorrection(newCount);
    notifyListeners();
  }

  void resetPassengerToSensor() {
    _manualPassengerCorrection = false;
    notifyListeners();
  }

  // ── Auto-Announcements ──

  void _onDashboardChanged() {
    final d = _dashProvider.data;

    // Docking announcement
    if (_settings.announceDocking &&
        d.navState == 'DOCKED' && _prevNavState != 'DOCKED') {
      final reachable = d.autoPredictions
          .where((p) => p.safetyStatus.toLowerCase() == 'safe')
          .map((p) => p.destination)
          .toList();
      final lang = _effectiveLanguage();
      final text = IntentMatcher.dockingAnnouncement(
        station: d.currentStation ?? 'unknown',
        reachable: reachable,
        language: lang,
      );
      _addLog(ConversationEntry.autoAnnounce(text));
      _tts.speak(text);
    }

    // Motor anomaly alert
    if (_settings.announceMotorAnomaly &&
        d.liveMotorHealth.toLowerCase() != 'good' &&
        d.liveMotorHealth.toLowerCase() != 'normal' &&
        _prevMotorHealth != d.liveMotorHealth) {
      final lang = _effectiveLanguage();
      final text = IntentMatcher.motorAnomalyAlert(
        score: d.motorAnomalyScore ?? 0.0, language: lang,
      );
      _addLog(ConversationEntry.autoAnnounce(text));
      _tts.interruptAndSpeak(text); // anomaly alerts interrupt
    }

    // Battery anomaly alert
    if (_settings.announceBatteryAnomaly &&
        d.liveBatteryHealth.toLowerCase() != 'good' &&
        d.liveBatteryHealth.toLowerCase() != 'normal' &&
        _prevBatteryHealth != d.liveBatteryHealth) {
      final lang = _effectiveLanguage();
      final text = IntentMatcher.batteryAnomalyAlert(language: lang);
      _addLog(ConversationEntry.autoAnnounce(text));
      _tts.interruptAndSpeak(text);
    }

    // Low SOC warning
    if (_settings.announceLowSoc && d.soc != null) {
      if (d.soc! <= _settings.lowSocThreshold && !_lowSocAlerted) {
        _lowSocAlerted = true;
        final lang = _effectiveLanguage();
        final text = IntentMatcher.lowSocAlert(soc: d.soc!, language: lang);
        _addLog(ConversationEntry.autoAnnounce(text));
        _tts.speak(text);
      } else if (d.soc! > _settings.lowSocThreshold) {
        _lowSocAlerted = false; // Reset when SOC recovers (e.g., charging)
      }
    }

    // Update previous state
    _prevNavState = d.navState;
    _prevMotorHealth = d.liveMotorHealth;
    _prevBatteryHealth = d.liveBatteryHealth;
    _prevSoc = d.soc;
  }

  // ── Settings ──

  Future<void> updateSettings(VoiceSettings newSettings) async {
    _settings = newSettings;
    await _tts.setVolume(newSettings.volume);
    await _tts.setSpeechRate(newSettings.speechRate);
    await _saveSettings();
    notifyListeners();
  }

  VoiceLanguage _effectiveLanguage() {
    if (_settings.language == VoiceLanguage.auto) return VoiceLanguage.en;
    return _settings.language;
  }

  Future<void> _loadSettings() async {
    final prefs = await SharedPreferences.getInstance();
    _settings = VoiceSettings(
      listeningMode: ListeningMode.values.byName(
        prefs.getString('dalaray_listening_mode') ?? 'ptt',
      ),
      language: VoiceLanguage.values.byName(
        prefs.getString('dalaray_language') ?? 'en',
      ),
      volume: prefs.getDouble('dalaray_volume') ?? 0.75,
      speechRate: SpeechRate.values.byName(
        prefs.getString('dalaray_speech_rate') ?? 'normal',
      ),
      announceDocking: prefs.getBool('dalaray_announce_docking') ?? true,
      announceMotorAnomaly: prefs.getBool('dalaray_announce_motor_anomaly') ?? true,
      announceBatteryAnomaly: prefs.getBool('dalaray_announce_battery_anomaly') ?? true,
      announceLowSoc: prefs.getBool('dalaray_announce_low_soc') ?? true,
      lowSocThreshold: prefs.getInt('dalaray_low_soc_threshold') ?? 15,
    );
    await _tts.setVolume(_settings.volume);
    await _tts.setSpeechRate(_settings.speechRate);
  }

  Future<void> _saveSettings() async {
    final prefs = await SharedPreferences.getInstance();
    await prefs.setString('dalaray_listening_mode', _settings.listeningMode.name);
    await prefs.setString('dalaray_language', _settings.language.name);
    await prefs.setDouble('dalaray_volume', _settings.volume);
    await prefs.setString('dalaray_speech_rate', _settings.speechRate.name);
    await prefs.setBool('dalaray_announce_docking', _settings.announceDocking);
    await prefs.setBool('dalaray_announce_motor_anomaly', _settings.announceMotorAnomaly);
    await prefs.setBool('dalaray_announce_battery_anomaly', _settings.announceBatteryAnomaly);
    await prefs.setBool('dalaray_announce_low_soc', _settings.announceLowSoc);
    await prefs.setInt('dalaray_low_soc_threshold', _settings.lowSocThreshold);
  }

  // ── Helpers ──

  void _addLog(ConversationEntry entry) {
    _log.add(entry);
    // Keep last 50 entries
    if (_log.length > 50) _log.removeAt(0);
    notifyListeners();
  }

  @override
  void dispose() {
    _dashProvider.removeListener(_onDashboardChanged);
    _tts.dispose();
    _stt.dispose();
    super.dispose();
  }
}
```

- [ ] **Step 2: Verify it compiles**

Note: This file references `_dashProvider.emitPassengerCorrection()` and `_dashProvider.currentServerUrl` which don't exist yet. That's fine — Task 7 adds them. For now, verify there are no syntax errors:

```bash
cd flutter_application_1
flutter analyze lib/services/voice_service.dart 2>&1 | head -20
```

Expected: Errors about missing `emitPassengerCorrection` and `currentServerUrl` — these are resolved in Task 7.

- [ ] **Step 3: Commit**

```bash
git add flutter_application_1/lib/services/voice_service.dart
git commit -m "feat(voice): add VoiceService orchestrator with auto-announcements and settings persistence"
```

---

## Task 7: Socket.IO and Provider Changes

**Files:**
- Modify: `flutter_application_1/lib/services/socket_service.dart`
- Modify: `flutter_application_1/lib/providers/dashboard_provider.dart`

- [ ] **Step 1: Add emitPassengerCorrection to SocketService**

Open `flutter_application_1/lib/services/socket_service.dart`. Find the existing emit methods (like `emit` calls for `speed_prediction_request`). Add this new method in the same section:

```dart
void emitPassengerCorrection(int count) {
  socket?.emit('passenger_correction', {
    'count': count,
    'source': 'manual',
  });
}
```

- [ ] **Step 2: Add emitPassengerCorrection and currentServerUrl to DashboardProvider**

Open `flutter_application_1/lib/providers/dashboard_provider.dart`. Add:

1. A getter for `currentServerUrl` (the server URL is already stored — expose it):

```dart
String get currentServerUrl => _socketService.serverUrl;
```

If `serverUrl` is private in SocketService, also add a getter there:

In `socket_service.dart`, add near the top of the class:
```dart
String get serverUrl => _serverUrl; // or whatever the field name is
```

2. A method to emit passenger correction:

```dart
void emitPassengerCorrection(int count) {
  _socketService.emitPassengerCorrection(count);
}
```

- [ ] **Step 3: Verify the full app compiles**

```bash
cd flutter_application_1
flutter analyze
```

Expected: No errors (voice_service.dart should now resolve all references).

- [ ] **Step 4: Commit**

```bash
git add flutter_application_1/lib/services/socket_service.dart flutter_application_1/lib/providers/dashboard_provider.dart
git commit -m "feat(voice): add passenger_correction socket event and expose server URL"
```

---

## Task 8: Dalaray Panel Widget

**Files:**
- Create: `flutter_application_1/lib/widgets/dalaray_panel.dart`

- [ ] **Step 1: Create the widgets directory**

```bash
mkdir -p flutter_application_1/lib/widgets
```

- [ ] **Step 2: Implement the Dalaray panel widget**

Create `flutter_application_1/lib/widgets/dalaray_panel.dart`:

```dart
import 'package:flutter/material.dart';
import '../models/voice_models.dart';
import '../services/voice_service.dart';

class DalarayPanel extends StatelessWidget {
  final VoiceService voice;
  final double maxHeight;

  const DalarayPanel({super.key, required this.voice, required this.maxHeight});

  @override
  Widget build(BuildContext context) {
    return ListenableBuilder(
      listenable: voice,
      builder: (context, _) => Container(
        width: 280,
        constraints: BoxConstraints(maxHeight: maxHeight),
        decoration: BoxDecoration(
          color: Colors.black.withValues(alpha: 0.92),
          borderRadius: BorderRadius.circular(10),
          border: Border.all(color: const Color(0xFF60A5FA), width: 1.5),
        ),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            _buildHeader(),
            Flexible(
              child: SingleChildScrollView(
                padding: const EdgeInsets.all(8),
                child: Column(
                  mainAxisSize: MainAxisSize.min,
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    _buildVoiceSettings(),
                    const Divider(color: Colors.grey, height: 16),
                    _buildAnnouncementSettings(),
                    const Divider(color: Colors.grey, height: 16),
                    _buildPassengerCorrection(),
                    const Divider(color: Colors.grey, height: 16),
                    _buildConnectionStatus(),
                    const Divider(color: Colors.grey, height: 16),
                    _buildConversationLog(),
                  ],
                ),
              ),
            ),
            _buildMicBar(),
          ],
        ),
      ),
    );
  }

  Widget _buildHeader() {
    final stateColors = {
      VoiceState.idle: const Color(0xFF34D399),
      VoiceState.listening: const Color(0xFFEF4444),
      VoiceState.processing: const Color(0xFFF59E0B),
      VoiceState.speaking: const Color(0xFF34D399),
    };
    final stateLabels = {
      VoiceState.idle: 'Ready',
      VoiceState.listening: 'Listening...',
      VoiceState.processing: 'Processing...',
      VoiceState.speaking: 'Speaking...',
    };

    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 8),
      decoration: const BoxDecoration(
        color: Color(0xFF1E293B),
        borderRadius: BorderRadius.vertical(top: Radius.circular(9)),
      ),
      child: Row(
        children: [
          const Text('DALARAY', style: TextStyle(
            color: Color(0xFF60A5FA), fontWeight: FontWeight.bold, fontSize: 14,
          )),
          const SizedBox(width: 8),
          Container(
            width: 7, height: 7,
            decoration: BoxDecoration(
              shape: BoxShape.circle,
              color: stateColors[voice.state],
              boxShadow: [BoxShadow(color: stateColors[voice.state]!, blurRadius: 4)],
            ),
          ),
          const SizedBox(width: 6),
          Text(stateLabels[voice.state]!, style: const TextStyle(
            color: Color(0xFF94A3B8), fontSize: 11,
          )),
          const Spacer(),
          GestureDetector(
            onTap: voice.closePanel,
            child: const Icon(Icons.close, color: Color(0xFF94A3B8), size: 16),
          ),
        ],
      ),
    );
  }

  Widget _buildVoiceSettings() {
    final s = voice.settings;
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        _sectionLabel('VOICE SETTINGS'),
        _toggleRow('Listening Mode',
          options: ['PTT', 'Auto'],
          selected: s.listeningMode == ListeningMode.ptt ? 0 : 1,
          onChanged: (i) => voice.updateSettings(s.copyWith(
            listeningMode: i == 0 ? ListeningMode.ptt : ListeningMode.auto,
          )),
        ),
        const SizedBox(height: 6),
        _toggleRow('Language',
          options: ['EN', 'FIL', 'Auto'],
          selected: s.language.index,
          onChanged: (i) => voice.updateSettings(s.copyWith(
            language: VoiceLanguage.values[i],
          )),
        ),
        const SizedBox(height: 6),
        _sliderRow('Volume', s.volume, (v) => voice.updateSettings(s.copyWith(volume: v))),
        const SizedBox(height: 6),
        _toggleRow('Speech Rate',
          options: ['Slow', 'Normal', 'Fast'],
          selected: s.speechRate.index,
          onChanged: (i) => voice.updateSettings(s.copyWith(
            speechRate: SpeechRate.values[i],
          )),
        ),
      ],
    );
  }

  Widget _buildAnnouncementSettings() {
    final s = voice.settings;
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        _sectionLabel('AUTO ANNOUNCEMENTS'),
        _switchRow('Docking stations', s.announceDocking,
          (v) => voice.updateSettings(s.copyWith(announceDocking: v)),
        ),
        _switchRow('Motor anomaly', s.announceMotorAnomaly,
          (v) => voice.updateSettings(s.copyWith(announceMotorAnomaly: v)),
        ),
        _switchRow('Battery anomaly', s.announceBatteryAnomaly,
          (v) => voice.updateSettings(s.copyWith(announceBatteryAnomaly: v)),
        ),
        _switchRow('Low SOC warning', s.announceLowSoc,
          (v) => voice.updateSettings(s.copyWith(announceLowSoc: v)),
        ),
        const SizedBox(height: 4),
        Row(
          mainAxisAlignment: MainAxisAlignment.spaceBetween,
          children: [
            const Text('Low SOC threshold', style: TextStyle(color: Color(0xFFE2E8F0), fontSize: 12)),
            Container(
              padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 2),
              decoration: BoxDecoration(
                color: const Color(0xFF0F172A),
                border: Border.all(color: const Color(0xFF334155)),
                borderRadius: BorderRadius.circular(4),
              ),
              child: Text('${s.lowSocThreshold}%', style: const TextStyle(
                color: Color(0xFFE2E8F0), fontSize: 12,
              )),
            ),
          ],
        ),
      ],
    );
  }

  Widget _buildPassengerCorrection() {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        _sectionLabel('PASSENGER CORRECTION'),
        Container(
          padding: const EdgeInsets.all(8),
          decoration: BoxDecoration(
            color: const Color(0xFF0F172A),
            borderRadius: BorderRadius.circular(8),
            border: Border.all(color: const Color(0xFF334155)),
          ),
          child: Column(
            children: [
              Row(
                mainAxisAlignment: MainAxisAlignment.center,
                children: [
                  _circleButton('-', const Color(0xFFEF4444), () => voice.adjustPassengerCount(-1)),
                  Padding(
                    padding: const EdgeInsets.symmetric(horizontal: 16),
                    child: Column(
                      children: [
                        Text(
                          '${voice.displayPassengerCount}',
                          style: const TextStyle(
                            color: Color(0xFFE2E8F0), fontSize: 24, fontWeight: FontWeight.bold,
                          ),
                        ),
                        Text(
                          voice.manualPassengerCorrection ? 'manually corrected' : 'from sensor',
                          style: TextStyle(
                            color: voice.manualPassengerCorrection
                                ? const Color(0xFFF59E0B)
                                : const Color(0xFF60A5FA),
                            fontSize: 9,
                          ),
                        ),
                      ],
                    ),
                  ),
                  _circleButton('+', const Color(0xFF34D399), () => voice.adjustPassengerCount(1)),
                ],
              ),
              if (voice.manualPassengerCorrection) ...[
                const SizedBox(height: 6),
                GestureDetector(
                  onTap: voice.resetPassengerToSensor,
                  child: const Text('Reset to sensor value',
                    style: TextStyle(
                      color: Color(0xFF94A3B8), fontSize: 10, decoration: TextDecoration.underline,
                    ),
                  ),
                ),
              ],
            ],
          ),
        ),
      ],
    );
  }

  Widget _buildConnectionStatus() {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        _sectionLabel('CONNECTION STATUS'),
        _statusRow('Cloud STT', voice.cloudAvailable),
        _statusRow('RPi5 Vosk', voice.rpi5Available),
        _statusRow('Platform STT', voice.platformAvailable),
        const SizedBox(height: 4),
        Row(
          mainAxisAlignment: MainAxisAlignment.spaceBetween,
          children: [
            const Text('Active STT', style: TextStyle(color: Color(0xFF94A3B8), fontSize: 11)),
            Text(
              _tierLabel(voice.activeSttTier),
              style: const TextStyle(color: Color(0xFF60A5FA), fontSize: 11),
            ),
          ],
        ),
      ],
    );
  }

  Widget _buildConversationLog() {
    final entries = voice.log.reversed.take(10).toList();
    if (entries.isEmpty) {
      return Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          _sectionLabel('CONVERSATION LOG'),
          const Text('No conversations yet.',
            style: TextStyle(color: Color(0xFF94A3B8), fontSize: 11)),
        ],
      );
    }
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        _sectionLabel('CONVERSATION LOG'),
        ...entries.map((e) => Padding(
          padding: const EdgeInsets.only(bottom: 6),
          child: Row(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Container(
                width: 16, height: 16,
                margin: const EdgeInsets.only(right: 6, top: 1),
                decoration: BoxDecoration(
                  shape: BoxShape.circle,
                  color: e.speaker == Speaker.crew
                      ? const Color(0xFF334155)
                      : const Color(0xFF1E3A5F),
                ),
                child: Center(child: Text(
                  e.speaker == Speaker.crew ? 'C' : 'D',
                  style: TextStyle(
                    fontSize: 9,
                    color: e.speaker == Speaker.crew
                        ? const Color(0xFF94A3B8)
                        : const Color(0xFF60A5FA),
                  ),
                )),
              ),
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Row(
                      children: [
                        Text(
                          e.speaker == Speaker.crew ? 'Captain' : 'Dalaray',
                          style: TextStyle(
                            color: e.speaker == Speaker.crew
                                ? const Color(0xFF94A3B8)
                                : const Color(0xFF60A5FA),
                            fontSize: 10,
                          ),
                        ),
                        if (e.isAuto) ...[
                          const SizedBox(width: 4),
                          const Text('AUTO', style: TextStyle(color: Color(0xFFF59E0B), fontSize: 9)),
                        ],
                      ],
                    ),
                    Text(e.text, style: const TextStyle(color: Color(0xFFE2E8F0), fontSize: 11)),
                  ],
                ),
              ),
            ],
          ),
        )),
      ],
    );
  }

  Widget _buildMicBar() {
    final isListening = voice.state == VoiceState.listening;
    final isProcessing = voice.state == VoiceState.processing;

    final Color micColor;
    if (isListening) {
      micColor = const Color(0xFFEF4444);
    } else if (isProcessing) {
      micColor = const Color(0xFFF59E0B);
    } else {
      micColor = const Color(0xFF3B82F6);
    }

    return Container(
      padding: const EdgeInsets.symmetric(vertical: 10, horizontal: 12),
      decoration: const BoxDecoration(
        color: Color(0xFF1E293B),
        borderRadius: BorderRadius.vertical(bottom: Radius.circular(9)),
        border: Border(top: BorderSide(color: Color(0xFF334155))),
      ),
      child: Row(
        mainAxisAlignment: MainAxisAlignment.center,
        children: [
          GestureDetector(
            onTapDown: (_) => voice.startListening(),
            onTapUp: (_) => voice.stopListening(),
            onTapCancel: () => voice.stopListening(),
            child: Container(
              width: 44, height: 44,
              decoration: BoxDecoration(
                shape: BoxShape.circle,
                gradient: LinearGradient(
                  begin: Alignment.topLeft, end: Alignment.bottomRight,
                  colors: [micColor, micColor.withValues(alpha: 0.8)],
                ),
                border: Border.all(color: micColor.withValues(alpha: 0.6), width: 2),
              ),
              child: Icon(
                isProcessing ? Icons.hourglass_top : Icons.mic,
                color: Colors.white, size: 22,
              ),
            ),
          ),
          const SizedBox(width: 10),
          Text(
            isListening ? 'Listening...' : (isProcessing ? 'Processing...' : 'Tap to speak'),
            style: const TextStyle(color: Color(0xFF94A3B8), fontSize: 11),
          ),
        ],
      ),
    );
  }

  // ── Helper widgets ──

  Widget _sectionLabel(String text) {
    return Padding(
      padding: const EdgeInsets.only(bottom: 6),
      child: Text(text, style: const TextStyle(
        color: Color(0xFF94A3B8), fontSize: 10, fontWeight: FontWeight.bold, letterSpacing: 0.5,
      )),
    );
  }

  Widget _toggleRow(String label, {
    required List<String> options,
    required int selected,
    required ValueChanged<int> onChanged,
  }) {
    return Row(
      mainAxisAlignment: MainAxisAlignment.spaceBetween,
      children: [
        Text(label, style: const TextStyle(color: Color(0xFFE2E8F0), fontSize: 12)),
        Container(
          decoration: BoxDecoration(
            color: const Color(0xFF0F172A),
            border: Border.all(color: const Color(0xFF334155)),
            borderRadius: BorderRadius.circular(6),
          ),
          padding: const EdgeInsets.all(2),
          child: Row(
            mainAxisSize: MainAxisSize.min,
            children: List.generate(options.length, (i) {
              final isSelected = i == selected;
              return GestureDetector(
                onTap: () => onChanged(i),
                child: Container(
                  padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 3),
                  decoration: BoxDecoration(
                    color: isSelected ? const Color(0xFF3B82F6) : Colors.transparent,
                    borderRadius: BorderRadius.circular(4),
                  ),
                  child: Text(options[i], style: TextStyle(
                    color: isSelected ? Colors.white : const Color(0xFF94A3B8),
                    fontSize: 10,
                  )),
                ),
              );
            }),
          ),
        ),
      ],
    );
  }

  Widget _switchRow(String label, bool value, ValueChanged<bool> onChanged) {
    return Padding(
      padding: const EdgeInsets.only(bottom: 4),
      child: Row(
        mainAxisAlignment: MainAxisAlignment.spaceBetween,
        children: [
          Text(label, style: const TextStyle(color: Color(0xFFE2E8F0), fontSize: 12)),
          SizedBox(
            width: 36, height: 20,
            child: Switch(
              value: value,
              onChanged: onChanged,
              activeColor: const Color(0xFF3B82F6),
              materialTapTargetSize: MaterialTapTargetSize.shrinkWrap,
            ),
          ),
        ],
      ),
    );
  }

  Widget _sliderRow(String label, double value, ValueChanged<double> onChanged) {
    return Row(
      mainAxisAlignment: MainAxisAlignment.spaceBetween,
      children: [
        Text(label, style: const TextStyle(color: Color(0xFFE2E8F0), fontSize: 12)),
        SizedBox(
          width: 120,
          child: SliderTheme(
            data: const SliderThemeData(
              trackHeight: 3,
              thumbShape: RoundSliderThumbShape(enabledThumbRadius: 7),
              overlayShape: RoundSliderOverlayShape(overlayRadius: 12),
            ),
            child: Slider(
              value: value,
              onChanged: onChanged,
              activeColor: const Color(0xFF3B82F6),
              inactiveColor: const Color(0xFF334155),
            ),
          ),
        ),
      ],
    );
  }

  Widget _circleButton(String label, Color color, VoidCallback onTap) {
    return GestureDetector(
      onTap: onTap,
      child: Container(
        width: 32, height: 32,
        decoration: BoxDecoration(
          shape: BoxShape.circle,
          color: const Color(0xFF1E293B),
          border: Border.all(color: color),
        ),
        child: Center(child: Text(label, style: TextStyle(
          color: color, fontSize: 18, fontWeight: FontWeight.bold,
        ))),
      ),
    );
  }

  Widget _statusRow(String label, bool available) {
    return Padding(
      padding: const EdgeInsets.only(bottom: 2),
      child: Row(
        mainAxisAlignment: MainAxisAlignment.spaceBetween,
        children: [
          Text(label, style: const TextStyle(color: Color(0xFF94A3B8), fontSize: 11)),
          Text(
            available ? 'Available' : 'Unavailable',
            style: TextStyle(
              color: available ? const Color(0xFF34D399) : const Color(0xFFEF4444),
              fontSize: 11,
            ),
          ),
        ],
      ),
    );
  }

  String _tierLabel(SttTier tier) {
    return switch (tier) {
      SttTier.cloud => 'Cloud (Tier 1)',
      SttTier.rpi5 => 'RPi5 Vosk (Tier 2)',
      SttTier.platform => 'Platform (Tier 3)',
      SttTier.none => 'None',
    };
  }
}
```

- [ ] **Step 3: Verify it compiles**

```bash
cd flutter_application_1
flutter analyze lib/widgets/dalaray_panel.dart
```

Expected: No errors.

- [ ] **Step 4: Commit**

```bash
git add flutter_application_1/lib/widgets/dalaray_panel.dart
git commit -m "feat(voice): add Dalaray panel overlay widget with settings, passenger correction, and conversation log"
```

---

## Task 9: Main.dart Integration

**Files:**
- Modify: `flutter_application_1/lib/main.dart`

- [ ] **Step 1: Add imports at the top of main.dart**

Add these imports alongside the existing ones at the top of the file:

```dart
import 'services/voice_service.dart';
import 'widgets/dalaray_panel.dart';
import 'models/voice_models.dart';
```

- [ ] **Step 2: Add VoiceService to the MultiProvider in main()**

Change the existing `runApp` in `main()` from:

```dart
runApp(
  ChangeNotifierProvider(
    create: (_) => DashboardProvider(serverUrl: serverUrl),
    child: const DalarayApp(),
  ),
);
```

To:

```dart
final dashProvider = DashboardProvider(serverUrl: serverUrl);
final voiceService = VoiceService(dashProvider);
voiceService.init();

runApp(
  MultiProvider(
    providers: [
      ChangeNotifierProvider.value(value: dashProvider),
      ChangeNotifierProvider.value(value: voiceService),
    ],
    child: const DalarayApp(),
  ),
);
```

- [ ] **Step 3: Add state variable for panel visibility in _DashboardScreenState**

In the `_DashboardScreenState` class, find the existing state variables (like `_showDebugPanel`, `_terrainMap`). Add:

```dart
bool _showDalarayPanel = false;
```

- [ ] **Step 4: Add Dalaray button to _buildDebugToggle()**

In the `_buildDebugToggle()` method, find the settings gear `GestureDetector`. Add the Dalaray button **before** the gear button (so the order is: Map Toggle | Dalaray | Gear | Debug):

```dart
// Dalaray voice button
GestureDetector(
  onTap: () => setState(() => _showDalarayPanel = !_showDalarayPanel),
  child: Container(
    width: 36,
    height: 36,
    decoration: BoxDecoration(
      color: _showDalarayPanel ? const Color(0xFF2563EB) : Colors.black54,
      borderRadius: BorderRadius.circular(8),
      border: _showDalarayPanel
          ? Border.all(color: const Color(0xFF60A5FA), width: 1.5)
          : null,
    ),
    child: const Icon(Icons.mic, color: Colors.white, size: 20),
  ),
),
const SizedBox(width: 8),
```

- [ ] **Step 5: Add Dalaray panel to the Scaffold Stack**

In the `build` method of `_DashboardScreenState`, find the `Stack` children where `_buildDebugPanel()` is conditionally shown. Add the Dalaray panel in the same pattern:

```dart
if (_showDalarayPanel)
  Positioned(
    bottom: 54,
    right: 12,
    child: DalarayPanel(
      voice: context.read<VoiceService>(),
      maxHeight: MediaQuery.of(context).size.height - 80,
    ),
  ),
```

Place this **before** the `_buildDebugToggle()` widget in the Stack so the toggle buttons render on top of the panel.

- [ ] **Step 6: Verify the full app compiles**

```bash
cd flutter_application_1
flutter analyze
```

Expected: No errors.

- [ ] **Step 7: Commit**

```bash
git add flutter_application_1/lib/main.dart
git commit -m "feat(voice): integrate Dalaray button and panel into main dashboard"
```

---

## Task 10: RPi5 Vosk STT Endpoint

**Files:**
- Create: `Daluyan_V2/backend/app/services/vosk_stt.py`
- Create: `Daluyan_V2/backend/app/api/stt.py`
- Modify: `Daluyan_V2/backend/app/main.py`

- [ ] **Step 1: Create the Vosk STT service**

Create `Daluyan_V2/backend/app/services/vosk_stt.py`:

```python
"""Vosk speech-to-text service with lazy model loading and idle unload."""

import asyncio
import json
import logging
import wave
import io
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# Model directory — download models here
MODEL_DIR = Path(__file__).parent.parent.parent / "models" / "vosk"
EN_MODEL = "vosk-model-small-en-us-0.15"
FIL_MODEL = "vosk-model-small-tl-ph-0.1"  # May not exist; fall back to EN

IDLE_TIMEOUT_S = 300  # 5 minutes


class VoskSttService:
    """Lazy-loading Vosk STT with automatic idle unload."""

    def __init__(self):
        self._en_model = None
        self._fil_model = None
        self._idle_task: Optional[asyncio.Task] = None
        self._loaded = False

    @property
    def loaded(self) -> bool:
        return self._loaded

    def _load_models(self):
        """Load Vosk models on first use."""
        if self._loaded:
            return

        try:
            from vosk import Model, SetLogLevel

            SetLogLevel(-1)  # Suppress Vosk logs

            en_path = MODEL_DIR / EN_MODEL
            if en_path.exists():
                logger.info("Loading Vosk EN model from %s", en_path)
                self._en_model = Model(str(en_path))
            else:
                logger.warning("Vosk EN model not found at %s", en_path)

            fil_path = MODEL_DIR / FIL_MODEL
            if fil_path.exists():
                logger.info("Loading Vosk Filipino model from %s", fil_path)
                self._fil_model = Model(str(fil_path))
            else:
                logger.info("Vosk Filipino model not found — using EN only")

            self._loaded = self._en_model is not None
            logger.info("Vosk models loaded (EN=%s, FIL=%s)",
                        self._en_model is not None, self._fil_model is not None)

        except ImportError:
            logger.error("vosk package not installed — run: pip install vosk")
            self._loaded = False

    def _unload_models(self):
        """Free model memory."""
        self._en_model = None
        self._fil_model = None
        self._loaded = False
        logger.info("Vosk models unloaded (idle timeout)")

    def _reset_idle_timer(self):
        """Reset the idle unload timer."""
        if self._idle_task and not self._idle_task.done():
            self._idle_task.cancel()
        self._idle_task = asyncio.create_task(self._idle_unload())

    async def _idle_unload(self):
        """Unload models after idle timeout."""
        await asyncio.sleep(IDLE_TIMEOUT_S)
        self._unload_models()

    def transcribe(self, audio_bytes: bytes, sample_rate: int = 16000) -> dict:
        """
        Transcribe raw PCM audio bytes.

        Returns: {"text": str, "confidence": float, "language": str}
        """
        self._load_models()
        self._reset_idle_timer()

        if not self._loaded:
            return {"text": "", "confidence": 0.0, "language": "en"}

        from vosk import KaldiRecognizer

        # Try EN model
        results = []
        if self._en_model:
            rec = KaldiRecognizer(self._en_model, sample_rate)
            rec.AcceptWaveform(audio_bytes)
            result = json.loads(rec.FinalResult())
            en_text = result.get("text", "")
            results.append(("en", en_text))

        # Try Filipino model if available
        if self._fil_model:
            rec = KaldiRecognizer(self._fil_model, sample_rate)
            rec.AcceptWaveform(audio_bytes)
            result = json.loads(rec.FinalResult())
            fil_text = result.get("text", "")
            results.append(("fil", fil_text))

        # Return the longer transcription (heuristic for better match)
        if not results:
            return {"text": "", "confidence": 0.0, "language": "en"}

        best = max(results, key=lambda r: len(r[1]))
        return {
            "text": best[1],
            "confidence": 0.8 if best[1] else 0.0,
            "language": best[0],
        }


# Singleton instance
vosk_service = VoskSttService()
```

- [ ] **Step 2: Create the STT API router**

Create `Daluyan_V2/backend/app/api/stt.py`:

```python
"""Speech-to-text API endpoint for Dalaray voice assistant."""

import logging
from fastapi import APIRouter, File, UploadFile, HTTPException

from app.services.vosk_stt import vosk_service

logger = logging.getLogger(__name__)

router = APIRouter(tags=["stt"])


@router.post("/stt")
async def transcribe_audio(audio: UploadFile = File(...)):
    """
    Transcribe uploaded audio using Vosk.

    Accepts: PCM 16-bit mono 16kHz audio (raw or WAV).
    Returns: {"text": str, "confidence": float, "language": str}
    """
    try:
        audio_bytes = await audio.read()
        if not audio_bytes:
            raise HTTPException(status_code=400, detail="Empty audio file")

        result = vosk_service.transcribe(audio_bytes)
        return result

    except Exception as e:
        logger.error("STT transcription failed: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/stt/status")
async def stt_status():
    """Check if Vosk STT is available and loaded."""
    return {
        "available": True,
        "loaded": vosk_service.loaded,
    }
```

- [ ] **Step 3: Wire the STT router into main.py**

Open `Daluyan_V2/backend/app/main.py`. Add the import alongside existing router imports:

```python
from app.api.stt import router as stt_router
```

Then add the router inclusion alongside the existing `app.include_router()` calls:

```python
app.include_router(stt_router)
```

- [ ] **Step 4: Create the Vosk model directory**

```bash
mkdir -p "Daluyan_V2/backend/models/vosk"
echo "Download Vosk models here:" > "Daluyan_V2/backend/models/vosk/README.md"
echo "- EN: https://alphacephei.com/vosk/models/vosk-model-small-en-us-0.15.zip" >> "Daluyan_V2/backend/models/vosk/README.md"
echo "- Filipino: https://alphacephei.com/vosk/models (check for tl-ph model)" >> "Daluyan_V2/backend/models/vosk/README.md"
echo "Unzip each model into its own directory under this folder." >> "Daluyan_V2/backend/models/vosk/README.md"
```

- [ ] **Step 5: Verify the backend starts**

```bash
cd Daluyan_V2/backend
pip install vosk
python -c "from app.api.stt import router; print('STT router imported OK')"
```

Expected: "STT router imported OK" (Vosk models not loaded until first request).

- [ ] **Step 6: Commit**

```bash
git add Daluyan_V2/backend/app/services/vosk_stt.py Daluyan_V2/backend/app/api/stt.py Daluyan_V2/backend/app/main.py Daluyan_V2/backend/models/vosk/README.md
git commit -m "feat(voice): add Vosk STT endpoint to RPi5 backend with lazy model loading"
```

---

## Task 11: End-to-End Verification

**Files:** None (testing only)

- [ ] **Step 1: Run all Flutter tests**

```bash
cd flutter_application_1
flutter test
```

Expected: All tests pass (voice_models_test.dart + intent_matcher_test.dart).

- [ ] **Step 2: Run Flutter analyze**

```bash
cd flutter_application_1
flutter analyze
```

Expected: No errors.

- [ ] **Step 3: Build for Android**

```bash
cd flutter_application_1
flutter build apk --debug
```

Expected: APK builds successfully. This verifies all dependencies resolve and native plugins compile.

- [ ] **Step 4: Manual testing checklist**

On the Fire HD 8 tablet (or Android emulator):

1. Open the app — verify the blue mic button appears in the bottom-right control row
2. Tap the mic button — verify the Dalaray panel opens
3. Check voice settings — toggle PTT/Auto, EN/FIL, volume slider, speech rate
4. Check announcement switches — all should default to ON
5. Check passenger correction — tap +/- buttons, verify count changes
6. Check connection status — should show STT tier availability
7. Tap the mic in the panel — verify recording starts (button turns red)
8. Say "What's the battery?" — verify Dalaray speaks the response
9. Simulate docking (debug panel) — verify auto-announcement plays
10. Test Filipino: say "Ilan ang pasahero?" — verify Filipino response

- [ ] **Step 5: Final commit**

```bash
git add -A
git commit -m "feat(voice): Dalaray voice assistant - complete implementation"
```

---

## Follow-Up: Porcupine Wake Word (Always-Listening Mode)

The plan implements the PTT/Auto toggle in the UI, but **always-listening mode requires Porcupine wake word detection** which is not wired up in this plan. Reason: Porcupine requires:

1. A **Picovoice account** and access key (free tier available)
2. A **custom wake word model** (`.ppn` file) for "Dalaray" — trained via the Picovoice Console
3. Platform-specific permissions for background microphone access on Fire OS

**To add later:**
- Sign up at console.picovoice.ai, train a "Dalaray" wake word, download the `.ppn` file
- Add `porcupine_flutter` initialization in `VoiceService.init()` when `ListeningMode.auto` is selected
- On wake word detection, call `startListening()` automatically
- Handle microphone permission for background listening on Fire OS

This is a configuration-heavy step best done with the physical tablet in hand. The core voice assistant (PTT mode) works fully without it.

## Follow-Up: Cloud STT API Key Configuration

The plan leaves `cloudApiKey` and `cloudApiUrl` as nullable fields in `SttService`. To enable Tier 1:

- Add a Cloud STT API key field to the settings dialog (or hardcode in environment variable)
- For Google Cloud STT: `cloudApiUrl = 'https://speech.googleapis.com/v1/speech:recognize'`
- For OpenAI Whisper API: Adjust `_cloudTranscribe()` to use the Whisper endpoint format
- Store the key in SharedPreferences as `dalaray_cloud_api_key`
