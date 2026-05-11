class StationInfo {
  final String name;
  final int order;
  final double lat;
  final double lon;
  final double km;

  StationInfo({
    required this.name,
    required this.order,
    required this.lat,
    required this.lon,
    required this.km,
  });

  factory StationInfo.fromMap(Map<String, dynamic> m) => StationInfo(
        name: m['name'] ?? '',
        order: m['order'] ?? 0,
        lat: (m['lat'] as num?)?.toDouble() ?? 0,
        lon: (m['lon'] as num?)?.toDouble() ?? 0,
        km: (m['km'] as num?)?.toDouble() ?? 0,
      );
}

class AutoPrediction {
  final String departure;
  final String destination;
  final String? predictedSoc;
  final String? socReduction;
  final String? reachKm;
  final String safetyStatus;
  final String? direction; // "upstream" or "downstream"

  AutoPrediction({
    required this.departure,
    required this.destination,
    this.predictedSoc,
    this.socReduction,
    this.reachKm,
    this.safetyStatus = 'UNKNOWN',
    this.direction,
  });

  factory AutoPrediction.fromMap(Map<String, dynamic> m) => AutoPrediction(
        departure: m['departure'] ?? '',
        destination: m['destination'] ?? '',
        predictedSoc: m['predicted_soc']?.toString(),
        socReduction: m['soc_reduction']?.toString(),
        reachKm: m['reach_km']?.toString(),
        safetyStatus: m['safety_status'] ?? 'UNKNOWN',
        direction: m['direction'],
      );
}

class SpeedPrediction {
  final double speedKn;
  final String? predictedSoc;
  final String? socReduction;
  final String safetyStatus; // RECOMMENDED, CAUTION, CRITICAL

  SpeedPrediction({
    required this.speedKn,
    this.predictedSoc,
    this.socReduction,
    this.safetyStatus = 'UNKNOWN',
  });

  factory SpeedPrediction.fromMap(Map<String, dynamic> m) => SpeedPrediction(
        speedKn: (m['speed_kn'] as num?)?.toDouble() ?? 0,
        predictedSoc: m['predicted_soc']?.toString(),
        socReduction: m['soc_reduction']?.toString(),
        safetyStatus: m['safety_status'] ?? 'UNKNOWN',
      );
}

class DashboardData {
  // Live data from vessel
  int passengerCount;
  int? soc;
  double? speed;
  String vesselState;
  String safetyStatus;
  bool connected;

  // Weather (from Open-Meteo via RPi)
  double temperatureC;
  double windSpeedKn;
  double windDirectionDeg;
  double humidity;
  double precipitationMm;
  double waveHeightM;
  String weatherDescription;

  // Tide (from harmonic model via RPi)
  double tideHeightM;
  double hoursSinceHighTide;
  int tidePhase; // 0 = rising, 1 = falling

  // Live anomaly (continuous)
  String liveMotorHealth;
  String liveBatteryHealth;
  double? motorAnomalyScore;
  double? motorAnomalyThreshold;
  double? batteryAnomalyScore;
  double? batteryAnomalyThreshold;

  // Charging status
  bool isCharging;
  double? chargingPowerKw;
  double? chargingSocPercent;
  double? estMinutesToFull;
  double? estMinutesToTarget;
  double chargingTargetSoc;

  // Navigation state (from GPS-based state machine)
  String navState; // UNKNOWN, DOCKED, DEPARTING, IN_TRANSIT, ARRIVING
  String? currentStation;
  String? departureStation;
  String? nextStation;
  String? direction; // "upstream" or "downstream"
  List<StationInfo> stations;

  // Ferry position (GPS)
  double ferryLat;
  double ferryLon;
  double ferryHeading;
  double ferrySpeed;

  // Auto-predictions (pushed by server)
  String autoPredictionMode; // "docked" or "moving"
  List<AutoPrediction> autoPredictions;

  // Multi-speed prediction table (from speed_prediction_result)
  String? speedPredDeparture;
  String? speedPredDestination;
  List<SpeedPrediction> speedPredictions;

  // Realtime SOC (Model 1B, updates every 1s during trip)
  double? realtimePredictedSoc;
  double? realtimeSocDelta;
  double? realtimeSocLower;   // conformal lower bound
  double? realtimeSocUpper;   // conformal upper bound
  List<Map<String, dynamic>>? reachableStations;

  // Legacy prediction results (kept for backward compat)
  String? predictedSoc;
  String? socReduction;
  String? reachKm;
  String predictedSafety;
  String motorHealth;
  String batteryHealth;
  String otherAnomalies;
  bool hasPrediction;

  // Replay state
  List<Map<String, dynamic>> replaySegments;
  bool replayPlaying;
  String replayMode; // "docked", "segment", "full_day"
  int replaySpeedMultiplier;
  int replayCurrentRow;
  int replayTotalRows;
  double replayProgressPct;
  Map<String, dynamic>? replayCurrentSegment;
  List<String> replayAvailableDates;
  String replayCurrentDate;

  DashboardData({
    this.passengerCount = 0,
    this.soc,
    this.speed,
    this.vesselState = 'UNKNOWN',
    this.safetyStatus = 'UNKNOWN',
    this.connected = false,
    this.temperatureC = 28.0,
    this.windSpeedKn = 5.0,
    this.windDirectionDeg = 180.0,
    this.humidity = 75.0,
    this.precipitationMm = 0.0,
    this.waveHeightM = 0.1,
    this.weatherDescription = 'Unknown',
    this.tideHeightM = 0.0,
    this.hoursSinceHighTide = 0.0,
    this.tidePhase = 0,
    this.liveMotorHealth = 'OK',
    this.liveBatteryHealth = 'OK',
    this.motorAnomalyScore,
    this.motorAnomalyThreshold,
    this.batteryAnomalyScore,
    this.batteryAnomalyThreshold,
    this.isCharging = false,
    this.chargingPowerKw,
    this.chargingSocPercent,
    this.estMinutesToFull,
    this.estMinutesToTarget,
    this.chargingTargetSoc = 80.0,
    this.navState = 'UNKNOWN',
    this.currentStation,
    this.departureStation,
    this.nextStation,
    this.direction,
    List<StationInfo>? stations,
    this.ferryLat = 14.5681100,
    this.ferryLon = 121.0478946,
    this.ferryHeading = 0,
    this.ferrySpeed = 0,
    this.autoPredictionMode = 'docked',
    List<AutoPrediction>? autoPredictions,
    this.speedPredDeparture,
    this.speedPredDestination,
    List<SpeedPrediction>? speedPredictions,
    this.realtimePredictedSoc,
    this.realtimeSocDelta,
    this.realtimeSocLower,
    this.realtimeSocUpper,
    this.reachableStations,
    this.predictedSoc,
    this.socReduction,
    this.reachKm,
    this.predictedSafety = 'UNKNOWN',
    this.motorHealth = 'OK',
    this.batteryHealth = 'OK',
    this.otherAnomalies = 'No Anomalies Detected',
    this.hasPrediction = false,
    List<Map<String, dynamic>>? replaySegments,
    this.replayPlaying = false,
    this.replayMode = 'docked',
    this.replaySpeedMultiplier = 1,
    this.replayCurrentRow = 0,
    this.replayTotalRows = 0,
    this.replayProgressPct = 0,
    this.replayCurrentSegment,
    List<String>? replayAvailableDates,
    this.replayCurrentDate = '',
  })  : stations = stations ?? [],
        autoPredictions = autoPredictions ?? [],
        speedPredictions = speedPredictions ?? [],
        replaySegments = replaySegments ?? [],
        replayAvailableDates = replayAvailableDates ?? [];

  bool get isDocked => navState == 'DOCKED';
  bool get isMoving => navState == 'IN_TRANSIT' || navState == 'DEPARTING';
  bool get isArriving => navState == 'ARRIVING';

  void clearPrediction() {
    predictedSoc = null;
    socReduction = null;
    reachKm = null;
    predictedSafety = 'UNKNOWN';
    motorHealth = 'OK';
    batteryHealth = 'OK';
    otherAnomalies = 'No Anomalies Detected';
    hasPrediction = false;
    realtimePredictedSoc = null;
    realtimeSocDelta = null;
    realtimeSocLower = null;
    realtimeSocUpper = null;
    reachableStations = null;
    speedPredictions = [];
    speedPredDeparture = null;
    speedPredDestination = null;
  }
}
