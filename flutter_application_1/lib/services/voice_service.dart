import 'dart:async';
import 'dart:convert';
import 'package:flutter/foundation.dart';
import 'package:http/http.dart' as http;
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
  final List<ConversationEntry> _log = [];

  // Track previous state for auto-announce change detection
  String? _prevNavState;
  bool _lowSocAlerted = false;

  VoiceService(this._dashProvider) {
    _dashProvider.addListener(_onDashboardChanged);
  }

  // ── Getters ──

  VoiceState get state => _state;
  List<ConversationEntry> get log => List.unmodifiable(_log);
  SttTier get activeSttTier => _stt.activeTier;
  bool get cloudAvailable => _stt.cloudAvailable;
  bool get rpi5Available => _stt.rpi5Available;
  bool get platformAvailable => _stt.platformAvailable;
  // ── Initialization ──

  Future<void> init({String? cloudSttKey}) async {
    await _tts.init(serverUrl: _dashProvider.currentServerUrl);
    await _stt.init(
      serverUrl: _dashProvider.currentServerUrl,
      cloudSttKey: cloudSttKey,
    );
    await _tts.setVolume(1.0);
    await _tts.setSpeechRate(SpeechRate.normal);

    _tts.onSpeakingStarted = () {
      _state = VoiceState.speaking;
      notifyListeners();
    };
    _tts.onSpeakingDone = () {
      _state = VoiceState.idle;
      notifyListeners();
    };

    // Initialize prev state for change detection
    _prevNavState = _dashProvider.data.navState;
  }

  // ── Push-to-Talk Flow ──

  Future<void> startListening() async {
    if (_state != VoiceState.idle) return;

    // Check if any STT tier is available before entering listening state
    if (!_stt.platformAvailable && !_stt.cloudAvailable && !_stt.rpi5Available) {
      _addLog(ConversationEntry.dalaray(
        'Speech recognition is not available on this device. '
        'Please check microphone permissions in Settings.',
      ));
      notifyListeners();
      return;
    }

    _state = VoiceState.listening;
    notifyListeners();

    SttResult result;
    try {
      result = await _stt.listen();
    } catch (e) {
      result = SttResult.empty;
    }

    _state = VoiceState.processing;
    notifyListeners();

    if (result.text.isEmpty) {
      final lang = _effectiveLanguage();
      final response = IntentMatcher.sttFailedResponse(language: lang);
      _addLog(ConversationEntry.dalaray(response));
      _state = VoiceState.idle;
      _syncTtsUrl();
      await _tts.speak(response, language: lang);
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
    // Try Gemini LLM first (natural responses)
    final serverUrl = _dashProvider.currentServerUrl;
    if (serverUrl.isNotEmpty) {
      try {
        final chatResponse = await http.post(
          Uri.parse('$serverUrl/chat'),
          headers: {'Content-Type': 'application/json'},
          body: jsonEncode({'text': text}),
        ).timeout(const Duration(seconds: 12));

        if (chatResponse.statusCode == 200) {
          final data = jsonDecode(chatResponse.body);
          final response = data['response'] as String? ?? '';
          if (response.isNotEmpty) {
            // Handle actions from Gemini
            final action = data['action'] as Map<String, dynamic>?;
            if (action != null) {
              final type = action['type'] as String? ?? '';
              if (type == 'predict_station') {
                final station = action['station'] as String? ?? '';
                if (station.isNotEmpty) {
                  final d = _dashProvider.data;
                  _dashProvider.requestSpeedPrediction(
                    departure: d.currentStation ?? d.departureStation ?? 'Napindan',
                    destination: station,
                  );
                }
              }
            }

            // Use language detected by backend (matches response text)
            final detectedLang = data['language'] == 'fil' ? VoiceLanguage.fil : VoiceLanguage.en;
            _addLog(ConversationEntry.dalaray(response));
            _syncTtsUrl();
            await _tts.speak(response, language: detectedLang);
            return;
          }
        }
      } catch (_) {
        // Fall through to offline IntentMatcher
      }
    }

    // Offline fallback: keyword-based IntentMatcher
    await _processTranscriptionOffline(text);
  }

  Future<void> _processTranscriptionOffline(String text) async {
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
        response = IntentMatcher.passengerCountResponse(count: d.passengerCount, language: lang);
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
      case Intent.setPassengers || Intent.addPassengers || Intent.removePassengers:
        response = IntentMatcher.fallbackResponse(language: lang);
      case Intent.predictToStation:
        _dashProvider.requestSpeedPrediction(
          departure: d.currentStation ?? d.departureStation ?? 'Napindan',
          destination: match.station!,
        );
        response = lang == VoiceLanguage.fil
            ? 'Kinakalkula ang hula papuntang ${match.station}. Tingnan ang speed table.'
            : 'Calculating prediction to ${match.station}. Check the speed table.';
      case Intent.unknown:
        response = IntentMatcher.fallbackResponse(language: lang);
    }

    _addLog(ConversationEntry.dalaray(response));
    _syncTtsUrl();
    await _tts.speak(response, language: lang);
  }

  // ── Auto-Announcements (always on) ──

  static const int _lowSocThreshold = 15;

  void _onDashboardChanged() {
    final d = _dashProvider.data;

    // Docking announcement — announce reachable stations
    if (d.navState == 'DOCKED' && _prevNavState != 'DOCKED') {
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
      _syncTtsUrl();
      _tts.speak(text, language: lang);
    }

    // Low SOC warning
    if (d.soc != null) {
      if (d.soc! <= _lowSocThreshold && !_lowSocAlerted) {
        _lowSocAlerted = true;
        final lang = _effectiveLanguage();
        final text = IntentMatcher.lowSocAlert(soc: d.soc!, language: lang);
        _addLog(ConversationEntry.autoAnnounce(text));
        _syncTtsUrl();
        _tts.speak(text, language: lang);
      } else if (d.soc! > _lowSocThreshold) {
        _lowSocAlerted = false;
      }
    }

    // Update previous state
    _prevNavState = d.navState;
  }

  VoiceLanguage _effectiveLanguage() => VoiceLanguage.en;

  /// Keep TTS server URL in sync with current dashboard URL.
  void _syncTtsUrl() {
    _tts.serverUrl = _dashProvider.currentServerUrl;
  }

  // ── Helpers ──

  void _addLog(ConversationEntry entry) {
    _log.add(entry);
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
