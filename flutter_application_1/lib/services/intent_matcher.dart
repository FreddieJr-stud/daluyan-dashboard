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

  static const _enKeywords = <Intent, List<String>>{
    Intent.batteryStatus: ['battery', 'soc', 'charge'],
    Intent.weather: ['weather', 'wind', 'wave', 'waves', 'tide'],
    Intent.position: ['where', 'position', 'location'],
    Intent.passengerCount: ['passengers', 'passenger', 'how many', 'count'],
    Intent.anomalyStatus: ['anomaly', 'anomalies', 'health', 'motor status', 'system status'],
    Intent.reachableStations: ['reach', 'reachable', 'where can we go'],
  };

  static const _filKeywords = <Intent, List<String>>{
    Intent.batteryStatus: ['baterya', 'karga', 'tsarging'],
    Intent.weather: ['panahon', 'hangin', 'alon', 'taog'],
    Intent.position: ['nasaan', 'posisyon', 'istasyon'],
    Intent.passengerCount: ['pasahero', 'ilan', 'sakay'],
    Intent.anomalyStatus: ['problema', 'anomalya', 'kalusugan'],
    Intent.reachableStations: ['punta', 'pumunta', 'abot', 'maabot'],
  };

  static const _enSetPassengers = ['set passengers', 'update passengers', 'correct passengers'];
  static const _enAddPassengers = ['add', 'plus', 'more'];
  static const _enRemovePassengers = ['remove', 'minus', 'less'];

  static const _filSetPassengers = ['palitan', 'baguhin', 'itama'];
  static const _filAddPassengers = ['dagdag', 'dagdagan', 'idagdag'];
  static const _filRemovePassengers = ['bawas', 'bawasan', 'tanggalin'];

  static const _enPrediction = ['predict to', 'predict', 'can we reach', 'soc to'];
  static const _filPrediction = ['hula', 'hulaan', 'papunta', 'papuntang'];

  MatchResult match(String input) {
    if (input.trim().isEmpty) {
      return const MatchResult(intent: Intent.unknown);
    }

    final lower = input.toLowerCase();

    final passengerResult = _matchPassengerCorrection(lower);
    if (passengerResult != null) return passengerResult;

    final predictionResult = _matchPrediction(lower);
    if (predictionResult != null) return predictionResult;

    return _matchStatusQuery(lower);
  }

  MatchResult? _matchPassengerCorrection(String lower) {
    final number = _extractNumber(lower);
    if (number == null) return null;

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

    int enHits = 0;
    int filHits = 0;
    final hasPassengerWord = lower.contains('passenger') || lower.contains('pasahero');
    for (final kw in _enAddPassengers) {
      if (lower.contains(kw) && hasPassengerWord) enHits++;
    }
    for (final kw in _filAddPassengers) {
      if (lower.contains(kw)) filHits++;
    }
    if (enHits > 0 || filHits > 0) {
      return MatchResult(
        intent: Intent.addPassengers,
        language: filHits > enHits ? VoiceLanguage.fil : VoiceLanguage.en,
        number: number,
      );
    }

    enHits = 0;
    filHits = 0;
    for (final kw in _enRemovePassengers) {
      if (lower.contains(kw) && hasPassengerWord) enHits++;
    }
    for (final kw in _filRemovePassengers) {
      if (lower.contains(kw)) filHits++;
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
      if (lower.contains(kw)) { hasPredictionKeyword = true; enHits++; }
    }
    for (final kw in _filPrediction) {
      if (lower.contains(kw)) { hasPredictionKeyword = true; filHits++; }
    }

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

    for (final entry in _enKeywords.entries) {
      int score = 0;
      for (final kw in entry.value) {
        if (lower.contains(kw)) score++;
      }
      if (score > bestScore) { bestScore = score; bestIntent = entry.key; }
      enTotal += score;
    }

    Intent? bestFilIntent;
    int bestFilScore = 0;
    for (final entry in _filKeywords.entries) {
      int score = 0;
      for (final kw in entry.value) {
        if (lower.contains(kw)) score++;
      }
      if (score > bestFilScore) { bestFilScore = score; bestFilIntent = entry.key; }
      filTotal += score;
    }

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
    for (final name in _stationNames) {
      if (lower.contains(name.toLowerCase())) return name;
    }
    final words = text.split(RegExp(r'\s+'));
    String? bestMatch;
    int bestDistance = 4;
    for (final word in words) {
      if (word.length < 4) continue;
      for (final name in _stationNames) {
        final d = _levenshtein(word.toLowerCase(), name.toLowerCase());
        if (d < bestDistance) { bestDistance = d; bestMatch = name; }
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

  static String batteryResponse({required int soc, required double? predictedSoc, required VoiceLanguage language}) {
    final pred = predictedSoc?.round() ?? soc;
    if (language == VoiceLanguage.fil) return 'Baterya nasa $soc porsyento. Inaasahang SOC sa dating: $pred porsyento.';
    return 'Battery is at $soc percent. Predicted arrival SOC: $pred percent.';
  }

  static String weatherResponse({required double tempC, required double windKn, required double windDirDeg, required double tideM, required int tidePhase, required VoiceLanguage language}) {
    final windDir = _degToCardinal(windDirDeg);
    final phase = tidePhase == 0 ? (language == VoiceLanguage.fil ? 'tumataas' : 'rising') : (language == VoiceLanguage.fil ? 'bumababa' : 'falling');
    if (language == VoiceLanguage.fil) return 'Temperatura ${tempC.round()} digri. Hangin ${windKn.round()} knots $windDir. Taog ${tideM.toStringAsFixed(1)} metro, $phase.';
    return 'Temperature ${tempC.round()} degrees. Wind ${windKn.round()} knots $windDir. Tide height ${tideM.toStringAsFixed(1)} meters, $phase.';
  }

  static String positionResponse({required String navState, required String? departure, required String? destination, required String? currentStation, required double speed, required VoiceLanguage language}) {
    if (navState == 'DOCKED') {
      if (language == VoiceLanguage.fil) return 'Naka-dock sa ${currentStation ?? "hindi alam"}.';
      return 'Docked at ${currentStation ?? "unknown station"}.';
    }
    if (language == VoiceLanguage.fil) return 'Naglalakbay mula ${departure ?? "?"} papuntang ${destination ?? "?"}. Bilis: ${speed.toStringAsFixed(1)} knots.';
    return 'In transit from ${departure ?? "?"} to ${destination ?? "?"}. Speed: ${speed.toStringAsFixed(1)} knots.';
  }

  static String passengerCountResponse({required int count, required VoiceLanguage language}) {
    if (language == VoiceLanguage.fil) return 'May $count na pasahero sa barko.';
    return 'There are $count passengers on board.';
  }

  static String anomalyResponse({required String motorHealth, required String batteryHealth, required VoiceLanguage language}) {
    final motorOk = motorHealth.toLowerCase() == 'good' || motorHealth.toLowerCase() == 'normal';
    final batteryOk = batteryHealth.toLowerCase() == 'good' || batteryHealth.toLowerCase() == 'normal';
    if (motorOk && batteryOk) {
      if (language == VoiceLanguage.fil) return 'Lahat ng sistema normal. Motor: maayos. Baterya: maayos.';
      return 'All systems normal. Motor health: good. Battery health: good.';
    }
    if (language == VoiceLanguage.fil) return 'Motor: ${motorOk ? "maayos" : "may problema"}. Baterya: ${batteryOk ? "maayos" : "may problema"}.';
    return 'Motor health: ${motorOk ? "good" : "anomaly detected"}. Battery health: ${batteryOk ? "good" : "anomaly detected"}.';
  }

  static String reachableStationsResponse({required List<String> stations, required VoiceLanguage language}) {
    if (stations.isEmpty) {
      if (language == VoiceLanguage.fil) return 'Walang maaaring puntahan mula sa kasalukuyang SOC.';
      return 'No reachable stations from current SOC.';
    }
    final list = stations.join(', ');
    if (language == VoiceLanguage.fil) return 'Mula sa kasalukuyang SOC, maaari mong puntahan: $list.';
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

  static String dockingAnnouncement({required String station, required List<String> reachable, required VoiceLanguage language}) {
    final list = reachable.join(', ');
    if (language == VoiceLanguage.fil) return 'Naka-dock sa $station. Maaaring puntahan: $list.';
    return 'Docked at $station. Reachable stations: $list.';
  }

  static String motorAnomalyAlert({required double score, required VoiceLanguage language}) {
    if (language == VoiceLanguage.fil) return 'Babala. May nakitang anomalya sa motor. Score: ${score.toStringAsFixed(1)}.';
    return 'Warning. Motor anomaly detected. Score: ${score.toStringAsFixed(1)}.';
  }

  static String batteryAnomalyAlert({required VoiceLanguage language}) {
    if (language == VoiceLanguage.fil) return 'Babala. May anomalya sa baterya. Tingnan ang dashboard.';
    return 'Warning. Battery anomaly detected. Check dashboard.';
  }

  static String lowSocAlert({required int soc, required VoiceLanguage language}) {
    if (language == VoiceLanguage.fil) return 'Ingat. Baterya nasa $soc porsyento. Pag-isipang mag-dock na.';
    return 'Caution. Battery at $soc percent. Consider docking soon.';
  }

  static String fallbackResponse({required VoiceLanguage language}) {
    if (language == VoiceLanguage.fil) return 'Pasensya, hindi ko naintindihan. Pwede kang magtanong tungkol sa baterya, panahon, pasahero, anomalya, o mga istasyon.';
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
