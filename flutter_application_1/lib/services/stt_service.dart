import 'dart:async';
import 'package:http/http.dart' as http;
import 'package:permission_handler/permission_handler.dart';
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
  final stt.SpeechToText _platformStt = stt.SpeechToText();
  bool _platformSttAvailable = false;
  void _log(String msg) => print('[STT] $msg');

  String? cloudApiUrl;
  String? cloudApiKey;
  String? rpi5SttUrl;

  SttTier _activeTier = SttTier.none;
  SttTier get activeTier => _activeTier;

  // Cloud and RPi5 tiers require raw audio recording (record package).
  // Currently disabled due to record_linux build incompatibility.
  // Set to true when audio recording is re-added.
  bool _cloudAvailable = false;
  bool _rpi5Available = false;
  bool _platformAvailable = false;

  bool get cloudAvailable => _cloudAvailable;
  bool get rpi5Available => _rpi5Available;
  bool get platformAvailable => _platformAvailable;

  Future<void> init({String? serverUrl, String? cloudSttKey}) async {
    if (serverUrl != null) {
      final uri = Uri.parse(serverUrl);
      rpi5SttUrl = '${uri.scheme}://${uri.host}:${uri.port}/stt';
    }

    if (cloudSttKey != null) {
      cloudApiKey = cloudSttKey;
      cloudApiUrl = 'https://speech.googleapis.com/v1/speech:recognize';
    }

    // Request microphone permission at runtime (required on Android)
    final micStatus = await Permission.microphone.request();
    _log('microphone permission: $micStatus');
    if (!micStatus.isGranted) {
      _log('microphone permission denied — STT disabled');
      _platformAvailable = false;
      _updateActiveTier();
      return;
    }

    _platformSttAvailable = await _platformStt.initialize(
      onError: (error) => _log('initialize onError: $error'),
      onStatus: (status) => _log('initialize onStatus: $status'),
    );
    _platformAvailable = _platformSttAvailable;
    _log('initialize result: $_platformSttAvailable');
    final locales = await _platformStt.locales();
    for (final l in locales) {
      _log('locale: ${l.localeId} — ${l.name}');
    }
    _log('system locale: ${await _platformStt.systemLocale()}');

    await checkRpi5();

    _cloudAvailable = cloudApiKey != null && cloudApiKey!.isNotEmpty;

    _updateActiveTier();
    _log('activeTier: $_activeTier, platform: $_platformAvailable');
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
    // Cloud and RPi5 tiers need raw audio recording (not yet available).
    // For now, only platform STT is functional.
    if (_platformAvailable) {
      _activeTier = SttTier.platform;
    } else {
      _activeTier = SttTier.none;
    }
  }

  Future<SttResult> listen() async {
    // Platform STT (on-device, works offline on Fire OS)
    if (_platformAvailable) {
      try {
        final result = await _platformTranscribe();
        if (result.text.isNotEmpty) return result;
      } catch (_) {}
    }

    return SttResult.empty;
  }

  Future<SttResult> _platformTranscribe() async {
    if (!_platformSttAvailable) return SttResult.empty;

    final completer = Completer<SttResult>();
    String lastWords = '';

    _log('_platformTranscribe: starting listen...');

    // Set status listener BEFORE calling listen() to avoid race condition
    // where 'done' fires before the listener is attached.
    _platformStt.statusListener = (status) {
      _log('statusListener: $status (lastWords="$lastWords")');
      if (status == 'done' && !completer.isCompleted) {
        Future.delayed(const Duration(seconds: 2), () {
          if (!completer.isCompleted) {
            _log('completing with lastWords="$lastWords"');
            completer.complete(SttResult(
              text: lastWords,
              tier: SttTier.platform,
              confidence: lastWords.isNotEmpty ? 0.5 : 0.0,
            ));
          }
        });
      }
    };

    try {
      _platformStt.listen(
        onResult: (result) {
          _log('onResult: final=${result.finalResult}, '
              'words="${result.recognizedWords}", '
              'confidence=${result.confidence}');
          // Capture partial results as they come
          if (result.recognizedWords.isNotEmpty) {
            lastWords = result.recognizedWords;
          }
          if (result.finalResult && !completer.isCompleted) {
            completer.complete(SttResult(
              text: result.recognizedWords,
              tier: SttTier.platform,
              confidence: result.confidence,
            ));
          }
        },
        listenFor: const Duration(seconds: 15),
        pauseFor: const Duration(seconds: 5),
        localeId: 'fil-PH',
      );
      _log('listen() called successfully');
    } catch (e) {
      _log('listen() threw: $e');
      if (!completer.isCompleted) {
        completer.complete(SttResult.empty);
      }
      return completer.future;
    }

    // Hard timeout — prevents hanging forever
    Timer(const Duration(seconds: 20), () {
      if (!completer.isCompleted) {
        _platformStt.stop();
        completer.complete(SttResult(
          text: lastWords,
          tier: SttTier.platform,
          confidence: lastWords.isNotEmpty ? 0.5 : 0.0,
        ));
      }
    });

    return completer.future;
  }

  Future<void> stopRecording() async {
    await _platformStt.stop();
  }

  Future<void> dispose() async {
    await _platformStt.stop();
  }
}
