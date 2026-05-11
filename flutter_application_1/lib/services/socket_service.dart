import 'package:socket_io_client/socket_io_client.dart' as IO;

class SocketService {
  late IO.Socket socket;
  String serverUrl;

  // Existing events
  Function(Map<String, dynamic>)? onPassengerCount;
  Function(Map<String, dynamic>)? onVesselData;
  Function(Map<String, dynamic>)? onSafetyStatus;
  Function(Map<String, dynamic>)? onPredictionResult;
  Function(Map<String, dynamic>)? onWeatherData;
  Function(Map<String, dynamic>)? onAnomalyStatus;
  Function(Map<String, dynamic>)? onRealtimePrediction;
  Function(bool)? onConnectionChanged;

  // New events for auto-prediction dashboard
  Function(Map<String, dynamic>)? onStationStatus;
  Function(Map<String, dynamic>)? onAutoPrediction;
  Function(Map<String, dynamic>)? onFerryPosition;
  Function(Map<String, dynamic>)? onSpeedPredictionResult;

  // Charging events
  Function(Map<String, dynamic>)? onChargingStatus;

  // Replay events
  Function(List<dynamic>)? onReplaySegments;
  Function(Map<String, dynamic>)? onReplayStatus;
  Function(Map<String, dynamic>)? onReplayDates;

  SocketService({required this.serverUrl});

  void connect() {
    socket = IO.io(serverUrl, IO.OptionBuilder()
        .setTransports(['websocket'])
        .disableAutoConnect()
        .enableReconnection()
        .setReconnectionDelay(2000)
        .setReconnectionDelayMax(10000)
        .build());

    socket.onConnect((_) {
      onConnectionChanged?.call(true);
    });

    socket.onDisconnect((_) {
      onConnectionChanged?.call(false);
    });

    socket.onConnectError((err) {
      onConnectionChanged?.call(false);
    });

    socket.on('passenger_count', (data) {
      onPassengerCount?.call(Map<String, dynamic>.from(data));
    });

    socket.on('vessel_data', (data) {
      onVesselData?.call(Map<String, dynamic>.from(data));
    });

    socket.on('safety_status', (data) {
      onSafetyStatus?.call(Map<String, dynamic>.from(data));
    });

    socket.on('prediction_result', (data) {
      onPredictionResult?.call(Map<String, dynamic>.from(data));
    });

    socket.on('weather_data', (data) {
      onWeatherData?.call(Map<String, dynamic>.from(data));
    });

    socket.on('anomaly_status', (data) {
      onAnomalyStatus?.call(Map<String, dynamic>.from(data));
    });

    socket.on('realtime_prediction', (data) {
      onRealtimePrediction?.call(Map<String, dynamic>.from(data));
    });

    // New events
    socket.on('station_status', (data) {
      onStationStatus?.call(Map<String, dynamic>.from(data));
    });

    socket.on('auto_prediction', (data) {
      onAutoPrediction?.call(Map<String, dynamic>.from(data));
    });

    socket.on('ferry_position', (data) {
      onFerryPosition?.call(Map<String, dynamic>.from(data));
    });

    socket.on('speed_prediction_result', (data) {
      onSpeedPredictionResult?.call(Map<String, dynamic>.from(data));
    });

    socket.on('charging_status', (data) {
      onChargingStatus?.call(Map<String, dynamic>.from(data));
    });

    socket.on('replay_segments', (data) {
      if (data is List) {
        onReplaySegments?.call(data);
      }
    });

    socket.on('replay_status', (data) {
      onReplayStatus?.call(Map<String, dynamic>.from(data));
    });

    socket.on('replay_dates', (data) {
      onReplayDates?.call(Map<String, dynamic>.from(data));
    });

    socket.connect();
  }

  /// Request multi-speed predictions for a route
  void requestSpeedPrediction({
    required String departure,
    required String destination,
  }) {
    socket.emit('speed_prediction_request', {
      'departure': departure,
      'destination': destination,
    });
  }

  /// Legacy: Send a prediction request to the Flask server
  void requestPrediction({
    required String departure,
    required String destination,
    int? soc,
    int passengerCount = 0,
    String weather = 'CLOUDY',
  }) {
    socket.emit('predict_request', {
      'departure': departure,
      'destination': destination,
      'soc': soc,
      'passenger_count': passengerCount,
      'weather': weather,
    });
  }

  /// Signal the server to stop the realtime SOC prediction loop
  void endTrip() {
    socket.emit('end_trip');
  }

  /// Replay: fetch available segments
  void getReplaySegments() {
    socket.emit('replay_command', {'action': 'get_segments'});
  }

  /// Replay: start a specific segment or full day
  void startReplay({String? segmentId, bool fullDay = false}) {
    if (fullDay) {
      socket.emit('replay_command', {'action': 'start', 'mode': 'full_day'});
    } else if (segmentId != null) {
      socket.emit('replay_command', {'action': 'start', 'segment_id': segmentId});
    }
  }

  /// Replay: stop playback
  void stopReplay() {
    socket.emit('replay_command', {'action': 'stop'});
  }

  /// Replay: set speed multiplier (1, 5, 10)
  void setReplaySpeed(int multiplier) {
    socket.emit('replay_command', {'action': 'speed', 'multiplier': multiplier});
  }

  /// Replay: get current status
  void getReplayStatus() {
    socket.emit('replay_command', {'action': 'status'});
  }

  /// Replay: get available dates
  void getReplayDates() {
    socket.emit('replay_command', {'action': 'get_dates'});
  }

  /// Replay: change date
  void changeReplayDate(String date) {
    socket.emit('replay_command', {'action': 'change_date', 'date': date});
  }

  /// Set the charging target SOC on the server
  void setChargingTarget(double targetSoc) {
    socket.emit('set_charging_target', {'target_soc': targetSoc});
  }

  void emitPassengerCorrection(int count) {
    socket.emit('passenger_correction', {
      'count': count,
      'source': 'manual',
    });
  }

  void reconnect(String newUrl) {
    socket.dispose();
    serverUrl = newUrl;
    connect();
  }

  void dispose() {
    socket.dispose();
  }
}
