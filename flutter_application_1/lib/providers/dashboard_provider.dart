import 'dart:async';
import 'dart:math' as math;
import 'package:flutter/material.dart';
import 'package:shared_preferences/shared_preferences.dart';
import '../models/dashboard_data.dart';
import '../services/socket_service.dart';

class DashboardProvider extends ChangeNotifier {
  final DashboardData data = DashboardData();
  late final SocketService _socketService;
  Timer? _tripTimer;
  bool get isSimulatingTrip => _tripTimer != null;

  DashboardProvider({String serverUrl = 'http://CONFIGURE_SERVER_HOST:5000'}) {
    _socketService = SocketService(serverUrl: serverUrl);

    _socketService.onConnectionChanged = (connected) {
      data.connected = connected;
      if (connected) {
        // Fetch available dates on connect
        _socketService.getReplayDates();
      }
      notifyListeners();
    };

    _socketService.onPassengerCount = (payload) {
      data.passengerCount = payload['count'] ?? 0;
      notifyListeners();
    };

    _socketService.onVesselData = (payload) {
      data.soc = (payload['soc'] as num?)?.round();
      data.speed = (payload['speed'] as num?)?.toDouble();
      data.vesselState = payload['vessel_state'] ?? 'UNKNOWN';
      notifyListeners();
    };

    _socketService.onSafetyStatus = (payload) {
      data.safetyStatus = payload['status'] ?? 'UNKNOWN';
      notifyListeners();
    };

    _socketService.onWeatherData = (payload) {
      data.temperatureC = (payload['temperature_c'] as num?)?.toDouble() ?? 28.0;
      data.windSpeedKn = (payload['wind_speed_kn'] as num?)?.toDouble() ?? 5.0;
      data.windDirectionDeg = (payload['wind_direction_deg'] as num?)?.toDouble() ?? 180.0;
      data.humidity = (payload['humidity'] as num?)?.toDouble() ?? 75.0;
      data.precipitationMm = (payload['precipitation_mm'] as num?)?.toDouble() ?? 0.0;
      data.waveHeightM = (payload['wave_height_m'] as num?)?.toDouble() ?? 0.1;
      data.weatherDescription = payload['weather_description'] ?? 'Unknown';
      data.tideHeightM = (payload['tide_height_m'] as num?)?.toDouble() ?? 0.0;
      data.hoursSinceHighTide = (payload['hours_since_high_tide'] as num?)?.toDouble() ?? 0.0;
      data.tidePhase = (payload['tide_phase'] as num?)?.toInt() ?? 0;
      notifyListeners();
    };

    _socketService.onAnomalyStatus = (payload) {
      data.liveMotorHealth = payload['motor_health'] ?? 'OK';
      data.liveBatteryHealth = payload['battery_health'] ?? 'OK';
      data.motorAnomalyScore = (payload['motor_score'] as num?)?.toDouble();
      data.motorAnomalyThreshold = (payload['motor_threshold'] as num?)?.toDouble();
      data.batteryAnomalyScore = (payload['battery_score'] as num?)?.toDouble();
      data.batteryAnomalyThreshold = (payload['battery_threshold'] as num?)?.toDouble();
      notifyListeners();
    };

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

    _socketService.onRealtimePrediction = (payload) {
      data.realtimePredictedSoc = (payload['predicted_arrival_soc'] as num?)?.toDouble();
      data.realtimeSocDelta = (payload['soc_remaining_delta'] as num?)?.toDouble();
      data.realtimeSocLower = (payload['arrival_soc_lower'] as num?)?.toDouble();
      data.realtimeSocUpper = (payload['arrival_soc_upper'] as num?)?.toDouble();
      final stations = payload['reachable_stations'];
      if (stations != null && stations is List) {
        data.reachableStations = stations
            .map((s) => Map<String, dynamic>.from(s as Map))
            .toList();
      } else {
        data.reachableStations = null;
      }
      notifyListeners();
    };

    // New: station_status (navigation state machine)
    _socketService.onStationStatus = (payload) {
      data.navState = payload['state'] ?? 'UNKNOWN';
      data.currentStation = payload['current_station'];
      data.departureStation = payload['departure_station'];
      data.nextStation = payload['next_station'];
      data.direction = payload['direction'];

      final stationsList = payload['stations'];
      if (stationsList != null && stationsList is List) {
        data.stations = stationsList
            .map((s) => StationInfo.fromMap(Map<String, dynamic>.from(s as Map)))
            .toList();
      }
      notifyListeners();
    };

    // New: auto_prediction (auto-pushed predictions)
    _socketService.onAutoPrediction = (payload) {
      data.autoPredictionMode = payload['mode'] ?? 'docked';
      final preds = payload['predictions'];
      if (preds != null && preds is List) {
        data.autoPredictions = preds
            .map((p) => AutoPrediction.fromMap(Map<String, dynamic>.from(p as Map)))
            .toList();
      }
      notifyListeners();
    };

    // New: ferry_position (GPS updates)
    _socketService.onFerryPosition = (payload) {
      data.ferryLat = (payload['lat'] as num?)?.toDouble() ?? 0;
      data.ferryLon = (payload['lon'] as num?)?.toDouble() ?? 0;
      data.ferryHeading = (payload['heading'] as num?)?.toDouble() ?? 0;
      data.ferrySpeed = (payload['speed'] as num?)?.toDouble() ?? 0;
      notifyListeners();
    };

    // New: speed_prediction_result (multi-speed table)
    _socketService.onSpeedPredictionResult = (payload) {
      data.speedPredDeparture = payload['departure'];
      data.speedPredDestination = payload['destination'];
      final speeds = payload['speeds'];
      if (speeds != null && speeds is List) {
        data.speedPredictions = speeds
            .map((s) => SpeedPrediction.fromMap(Map<String, dynamic>.from(s as Map)))
            .toList();
      }
      notifyListeners();
    };

    // Legacy: prediction_result
    _socketService.onPredictionResult = (payload) {
      data.predictedSoc = payload['predicted_soc']?.toString();
      data.socReduction = payload['soc_reduction']?.toString();
      data.reachKm = payload['reach_km']?.toString();
      data.predictedSafety = payload['safety_status'] ?? 'UNKNOWN';
      final anomalies = payload['anomalies'];
      if (anomalies != null && anomalies is Map) {
        data.motorHealth = anomalies['motor_health'] ?? 'OK';
        data.batteryHealth = anomalies['battery_health'] ?? 'OK';
        data.otherAnomalies = anomalies['other'] ?? 'No Anomalies Detected';
      }
      data.hasPrediction = true;
      notifyListeners();
    };

    // Replay events
    _socketService.onReplaySegments = (segments) {
      data.replaySegments = segments
          .map((s) => Map<String, dynamic>.from(s as Map))
          .toList();
      notifyListeners();
    };

    _socketService.onReplayDates = (payload) {
      final dates = payload['dates'];
      if (dates != null && dates is List && dates.isNotEmpty) {
        data.replayAvailableDates = dates.map((d) => d.toString()).toList();
      }
      final current = payload['current'];
      if (current != null) {
        data.replayCurrentDate = current.toString();
      }
      notifyListeners();
    };

    _socketService.onReplayStatus = (payload) {
      final status = payload['status'] as Map<String, dynamic>? ?? payload;
      data.replayPlaying = status['playing'] == true;
      data.replayMode = status['mode']?.toString() ?? 'docked';
      data.replaySpeedMultiplier = (status['speed_multiplier'] as num?)?.toInt() ?? 1;
      data.replayCurrentRow = (status['current_row'] as num?)?.toInt() ?? 0;
      data.replayTotalRows = (status['total_rows'] as num?)?.toInt() ?? 0;
      data.replayProgressPct = (status['progress_pct'] as num?)?.toDouble() ?? 0;
      if (status['date'] != null) {
        data.replayCurrentDate = status['date'].toString();
      }
      if (status['current_segment'] != null) {
        data.replayCurrentSegment = Map<String, dynamic>.from(status['current_segment'] as Map);
      } else {
        data.replayCurrentSegment = null;
      }
      notifyListeners();
    };

    _socketService.connect();
  }

  /// Request multi-speed prediction table for a route
  void requestSpeedPrediction({
    required String departure,
    required String destination,
  }) {
    if (_debugMode) {
      // In debug mode, generate mock predictions immediately
      _generateMockSpeedPredictions(departure, destination);
      return;
    }
    _socketService.requestSpeedPrediction(
      departure: departure,
      destination: destination,
    );
  }

  /// Legacy: Request a prediction from the RPi model
  void requestPrediction({
    required String departure,
    required String destination,
  }) {
    _socketService.requestPrediction(
      departure: departure,
      destination: destination,
      soc: data.soc,
      passengerCount: data.passengerCount,
    );
  }

  void endTrip() {
    _socketService.endTrip();
  }

  void setChargingTarget(double targetSoc) {
    data.chargingTargetSoc = targetSoc;
    _socketService.setChargingTarget(targetSoc);
    notifyListeners();
  }

  // ---- DEBUG: simulate docking at a station (press 1-9 to test) ----
  // Coordinates from OpenStreetMap ferry terminals (ON the Pasig River)
  static const List<Map<String, dynamic>> _fallbackStations = [
    {'name': 'Napindan',    'order': 0, 'lat': 14.55713, 'lon': 121.06836, 'km': 0.0},
    {'name': 'Guadalupe',   'order': 1, 'lat': 14.5681100, 'lon': 121.0478946, 'km': 6.5},
    {'name': 'Hulo',        'order': 2, 'lat': 14.5679545, 'lon': 121.0336782, 'km': 8.3},
    {'name': 'Valenzuela',  'order': 3, 'lat': 14.5739778, 'lon': 121.0257656, 'km': 9.8},
    {'name': 'Lambingan',   'order': 4, 'lat': 14.5872813, 'lon': 121.0184560, 'km': 11.2},
    {'name': 'Sta Ana',     'order': 5, 'lat': 14.5827238, 'lon': 121.0119451, 'km': 12.7},
    {'name': 'PUP',         'order': 6, 'lat': 14.5960355, 'lon': 121.0107013, 'km': 14.0},
    {'name': 'Quinta',      'order': 7, 'lat': 14.5957803, 'lon': 120.9814485, 'km': 15.6},
    {'name': 'Escolta',     'order': 8, 'lat': 14.5963832, 'lon': 120.9775262, 'km': 16.0},
  ];

  // Flag to track whether we're in debug/mock mode
  bool _debugMode = false;

  void simulateDock(int stationIndex) {
    if (stationIndex < 0 || stationIndex > 8) return;
    _debugMode = true;

    // Cancel any running trip
    _tripTimer?.cancel();
    _tripTimer = null;

    // Populate stations if empty
    if (data.stations.isEmpty) {
      data.stations = _fallbackStations
          .map((s) => StationInfo.fromMap(s))
          .toList();
    }

    final station = _fallbackStations[stationIndex];
    data.navState = 'DOCKED';
    data.currentStation = station['name'] as String;
    data.ferryLat = station['lat'] as double;
    data.ferryLon = station['lon'] as double;
    data.ferryHeading = 0;
    data.ferrySpeed = 0;
    data.speed = 0;

    // Set next station (downstream neighbor)
    if (stationIndex < 8) {
      data.nextStation = _fallbackStations[stationIndex + 1]['name'] as String;
    } else {
      data.nextStation = _fallbackStations[stationIndex - 1]['name'] as String;
    }

    data.departureStation = null;
    data.direction = null;

    // --- MOCK DATA: realistic sample values ---
    data.connected = true;
    data.soc = 85;
    data.vesselState = 'IDLE';
    data.safetyStatus = 'SAFE';
    data.passengerCount = 18;

    // Weather
    data.temperatureC = 32.0;
    data.windSpeedKn = 8.5;
    data.windDirectionDeg = 225.0;
    data.humidity = 72.0;
    data.precipitationMm = 0.0;
    data.waveHeightM = 0.2;
    data.weatherDescription = 'Partly Cloudy';
    data.tideHeightM = 0.66;
    data.hoursSinceHighTide = 6.0;
    data.tidePhase = 0;

    // Anomalies — all OK when docked
    data.liveMotorHealth = 'OK';
    data.liveBatteryHealth = 'OK';

    // Auto predictions — show predictions for adjacent stations
    final currentName = station['name'] as String;
    data.autoPredictionMode = 'docked';
    data.autoPredictions = [];
    if (stationIndex < 8) {
      final nextName = _fallbackStations[stationIndex + 1]['name'] as String;
      data.autoPredictions.add(AutoPrediction(
        departure: currentName,
        destination: nextName,
        predictedSoc: '78.2%',
        socReduction: '6.8%',
        reachKm: '${(_fallbackStations[stationIndex + 1]['km'] as double) - (station['km'] as double)}',
        safetyStatus: 'CLEAR TO GO',
        direction: 'downstream',
      ));
    }
    if (stationIndex > 0) {
      final prevName = _fallbackStations[stationIndex - 1]['name'] as String;
      data.autoPredictions.add(AutoPrediction(
        departure: currentName,
        destination: prevName,
        predictedSoc: '76.5%',
        socReduction: '8.5%',
        reachKm: '${(station['km'] as double) - (_fallbackStations[stationIndex - 1]['km'] as double)}',
        safetyStatus: 'CLEAR TO GO',
        direction: 'upstream',
      ));
    }

    // Clear speed predictions (will be populated when user opens speed table)
    data.speedPredictions = [];
    data.speedPredDeparture = null;
    data.speedPredDestination = null;

    notifyListeners();
  }

  /// Generate mock speed predictions for a route
  void _generateMockSpeedPredictions(String departure, String destination) {
    // Find distance between stations
    final depIdx = _fallbackStations.indexWhere((s) => s['name'] == departure);
    final destIdx = _fallbackStations.indexWhere((s) => s['name'] == destination);
    if (depIdx < 0 || destIdx < 0) return;

    final depKm = _fallbackStations[depIdx]['km'] as double;
    final destKm = _fallbackStations[destIdx]['km'] as double;
    final distKm = (destKm - depKm).abs();
    final currentSoc = data.soc ?? 85;

    // Generate predictions for speeds 5/7/10/12/15 kn (matching replay server)
    // Higher speed = more SOC drain, lower = less drain but longer trip
    data.speedPredDeparture = departure;
    data.speedPredDestination = destination;
    data.speedPredictions = [
      SpeedPrediction(
        speedKn: 5,
        predictedSoc: '${(currentSoc - distKm * 0.8).toStringAsFixed(1)}%',
        socReduction: '${(distKm * 0.8).toStringAsFixed(1)}%',
        safetyStatus: 'CLEAR TO GO',
      ),
      SpeedPrediction(
        speedKn: 7,
        predictedSoc: '${(currentSoc - distKm * 1.2).toStringAsFixed(1)}%',
        socReduction: '${(distKm * 1.2).toStringAsFixed(1)}%',
        safetyStatus: 'CLEAR TO GO',
      ),
      SpeedPrediction(
        speedKn: 10,
        predictedSoc: '${(currentSoc - distKm * 1.8).toStringAsFixed(1)}%',
        socReduction: '${(distKm * 1.8).toStringAsFixed(1)}%',
        safetyStatus: (currentSoc - distKm * 1.8) >= 50 ? 'CLEAR TO GO' : 'CAUTION',
      ),
      SpeedPrediction(
        speedKn: 12,
        predictedSoc: '${(currentSoc - distKm * 2.5).toStringAsFixed(1)}%',
        socReduction: '${(distKm * 2.5).toStringAsFixed(1)}%',
        safetyStatus: (currentSoc - distKm * 2.5) >= 50
            ? 'CLEAR TO GO'
            : (currentSoc - distKm * 2.5) >= 20
                ? 'CAUTION'
                : 'CRITICAL',
      ),
      SpeedPrediction(
        speedKn: 15,
        predictedSoc: '${(currentSoc - distKm * 3.5).toStringAsFixed(1)}%',
        socReduction: '${(distKm * 3.5).toStringAsFixed(1)}%',
        safetyStatus: (currentSoc - distKm * 3.5) >= 50
            ? 'CLEAR TO GO'
            : (currentSoc - distKm * 3.5) >= 20
                ? 'CAUTION'
                : 'CRITICAL',
      ),
    ];
    notifyListeners();
  }

  /// Simulate a trip from one station to another along river waypoints.
  /// [waypoints] should be the _riverPath list from main.dart.
  /// The ferry moves along the waypoints at ~500ms intervals, transitioning
  /// through DEPARTING → IN_TRANSIT → ARRIVING → DOCKED.
  void simulateTrip({
    required int fromStationIndex,
    required int toStationIndex,
    required List<({double lat, double lon, String? station})> waypoints,
  }) {
    // Cancel any existing trip
    _tripTimer?.cancel();
    _tripTimer = null;

    if (fromStationIndex < 0 || fromStationIndex > 8) return;
    if (toStationIndex < 0 || toStationIndex > 8) return;
    if (fromStationIndex == toStationIndex) return;

    // Populate stations if empty
    if (data.stations.isEmpty) {
      data.stations = _fallbackStations
          .map((s) => StationInfo.fromMap(s))
          .toList();
    }

    final fromStation = _fallbackStations[fromStationIndex];
    final toStation = _fallbackStations[toStationIndex];
    final fromName = fromStation['name'] as String;
    final toName = toStation['name'] as String;
    final goingDownstream = toStationIndex > fromStationIndex; // higher order = downstream

    // Find waypoint indices for departure and destination stations
    int wpFrom = -1, wpTo = -1;
    for (int i = 0; i < waypoints.length; i++) {
      if (waypoints[i].station == fromName) wpFrom = i;
      if (waypoints[i].station == toName) wpTo = i;
    }
    if (wpFrom < 0 || wpTo < 0) return;

    // Build the ordered list of waypoint indices to traverse
    final List<int> route;
    if (wpFrom < wpTo) {
      route = List.generate(wpTo - wpFrom + 1, (i) => wpFrom + i);
    } else {
      route = List.generate(wpFrom - wpTo + 1, (i) => wpFrom - i);
    }

    // Simulate SOC drain: start from current SOC, drain per waypoint
    double simulatedSoc = (data.soc ?? 85).toDouble();
    data.soc = simulatedSoc.round();
    data.speed = 12.0;
    data.ferrySpeed = 12.0;
    data.connected = true;
    data.vesselState = 'SAILING';

    // Set initial state: DEPARTING
    data.navState = 'DEPARTING';
    data.departureStation = fromName;
    data.currentStation = fromName;
    data.nextStation = toName;
    data.direction = goingDownstream ? 'downstream' : 'upstream';
    data.ferryLat = waypoints[route[0]].lat;
    data.ferryLon = waypoints[route[0]].lon;

    // Set mock auto prediction for the in-transit overlay
    data.autoPredictionMode = 'moving';
    final destKm = _fallbackStations[toStationIndex]['km'] as double;
    final depKm = _fallbackStations[fromStationIndex]['km'] as double;
    final distKm = (destKm - depKm).abs();
    final predictedArrivalSoc = simulatedSoc - (distKm * 2.0);
    data.autoPredictions = [
      AutoPrediction(
        departure: fromName,
        destination: toName,
        predictedSoc: '${predictedArrivalSoc.toStringAsFixed(1)}%',
        socReduction: '${(distKm * 2.0).toStringAsFixed(1)}%',
        safetyStatus: predictedArrivalSoc >= 50 ? 'CLEAR TO GO' : predictedArrivalSoc >= 20 ? 'CAUTION' : 'CRITICAL',
        direction: goingDownstream ? 'downstream' : 'upstream',
      ),
    ];

    notifyListeners();

    int stepIndex = 0;
    final totalSteps = route.length;
    // ~3 waypoints for DEPARTING, ~3 for ARRIVING, rest IN_TRANSIT
    final departingEnd = math.min(3, totalSteps ~/ 4);
    final arrivingStart = math.max(totalSteps - 3, totalSteps * 3 ~/ 4);

    // SOC drain per step — total drain based on distance
    final socDrainPerStep = (distKm * 2.0) / totalSteps;
    final rng = math.Random();

    _tripTimer = Timer.periodic(const Duration(milliseconds: 500), (timer) {
      stepIndex++;
      if (stepIndex >= totalSteps) {
        // Arrived — dock at destination
        timer.cancel();
        _tripTimer = null;
        simulateDock(toStationIndex);
        return;
      }

      final wpIdx = route[stepIndex];
      final wp = waypoints[wpIdx];

      // Update ferry position
      data.ferryLat = wp.lat;
      data.ferryLon = wp.lon;

      // Calculate heading from previous to current waypoint
      final prevWpIdx = route[stepIndex - 1];
      final prevWp = waypoints[prevWpIdx];
      data.ferryHeading = _calcHeading(prevWp.lat, prevWp.lon, wp.lat, wp.lon);

      // Simulate speed with slight variation
      if (stepIndex < departingEnd) {
        data.navState = 'DEPARTING';
        data.speed = 5.0 + (rng.nextDouble() * 5.0); // 5-10 kn ramping up
      } else if (stepIndex >= arrivingStart) {
        data.navState = 'ARRIVING';
        data.speed = 3.0 + (rng.nextDouble() * 4.0); // 3-7 kn slowing down
      } else {
        data.navState = 'IN_TRANSIT';
        data.speed = 11.0 + (rng.nextDouble() * 4.0); // 11-15 kn cruising
      }
      data.ferrySpeed = data.speed!;

      // Drain SOC gradually
      simulatedSoc = (simulatedSoc - socDrainPerStep).clamp(0, 100);
      data.soc = simulatedSoc.round();

      // Update the auto prediction with remaining SOC estimate
      final progress = stepIndex / totalSteps;
      final remainingDrain = (1.0 - progress) * distKm * 2.0;
      final estArrivalSoc = simulatedSoc - remainingDrain;
      data.autoPredictions = [
        AutoPrediction(
          departure: fromName,
          destination: toName,
          predictedSoc: '${estArrivalSoc.toStringAsFixed(1)}%',
          socReduction: '${remainingDrain.toStringAsFixed(1)}%',
          safetyStatus: estArrivalSoc >= 50 ? 'CLEAR TO GO' : estArrivalSoc >= 20 ? 'CAUTION' : 'CRITICAL',
          direction: goingDownstream ? 'downstream' : 'upstream',
        ),
      ];

      // Realtime prediction data
      data.realtimePredictedSoc = estArrivalSoc;
      data.realtimeSocDelta = simulatedSoc - estArrivalSoc;

      // Check if passing through intermediate stations
      if (wp.station != null && wp.station != fromName && wp.station != toName) {
        data.currentStation = wp.station;
      }

      // Simulate occasional passenger count change at intermediate stations
      if (wp.station != null && wp.station != fromName) {
        data.passengerCount = data.passengerCount + rng.nextInt(5) - 2; // ±2
        if (data.passengerCount < 0) data.passengerCount = 0;
      }

      notifyListeners();
    });
  }

  /// Calculate compass heading (degrees) from point A to point B.
  double _calcHeading(double lat1, double lon1, double lat2, double lon2) {
    final dLon = (lon2 - lon1) * math.pi / 180;
    final y = math.sin(dLon) * math.cos(lat2 * math.pi / 180);
    final x = math.cos(lat1 * math.pi / 180) * math.sin(lat2 * math.pi / 180) -
        math.sin(lat1 * math.pi / 180) * math.cos(lat2 * math.pi / 180) * math.cos(dLon);
    final heading = math.atan2(y, x) * 180 / math.pi;
    return (heading + 360) % 360;
  }

  /// Stop any running trip simulation
  void stopTripSimulation() {
    _tripTimer?.cancel();
    _tripTimer = null;
  }

  // ── Replay controls ──────────────────────────────────────────
  void fetchReplaySegments() => _socketService.getReplaySegments();

  void startReplaySegment(String segmentId) =>
      _socketService.startReplay(segmentId: segmentId);

  void startReplayFullDay() =>
      _socketService.startReplay(fullDay: true);

  void stopReplay() => _socketService.stopReplay();

  void setReplaySpeed(int multiplier) =>
      _socketService.setReplaySpeed(multiplier);

  void fetchReplayStatus() => _socketService.getReplayStatus();

  void fetchReplayDates() => _socketService.getReplayDates();

  void changeReplayDate(String date) => _socketService.changeReplayDate(date);

  Future<void> changeServerUrl(String newUrl) async {
    final prefs = await SharedPreferences.getInstance();
    await prefs.setString('server_url', newUrl);
    _socketService.reconnect(newUrl);
  }

  String get currentServerUrl => _socketService.serverUrl;

  void emitPassengerCorrection(int count) {
    _socketService.emitPassengerCorrection(count);
  }

  void clearPrediction() {
    endTrip();
    data.clearPrediction();
    notifyListeners();
  }

  @override
  void dispose() {
    _tripTimer?.cancel();
    _socketService.dispose();
    super.dispose();
  }
}
