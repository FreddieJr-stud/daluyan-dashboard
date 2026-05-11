import 'dart:async';
import 'dart:collection';
import 'dart:convert';
import 'package:audioplayers/audioplayers.dart';
import 'package:flutter/foundation.dart';
import 'package:flutter_tts/flutter_tts.dart';
import 'package:http/http.dart' as http;
import '../models/voice_models.dart';

class _TtsRequest {
  final String text;
  final VoiceLanguage language;
  _TtsRequest(this.text, this.language);
}

class TtsService {
  final FlutterTts _tts = FlutterTts();
  final AudioPlayer _edgePlayer = AudioPlayer();
  final Queue<_TtsRequest> _queue = Queue();
  bool _isSpeaking = false;
  bool _usingEdgePlayer = false;
  String? _serverUrl;

  set serverUrl(String? url) => _serverUrl = url;

  static const _englishVoice = 'en-US-JennyNeural';
  static const _filipinoVoice = 'fil-PH-BlessicaNeural';

  VoidCallback? onSpeakingStarted;
  VoidCallback? onSpeakingDone;

  Future<void> init({String? serverUrl}) async {
    _serverUrl = serverUrl;

    // On-device TTS (fallback)
    await _tts.setLanguage('en-US');
    await _tts.setSpeechRate(0.5);
    await _tts.setVolume(0.75);

    _tts.setStartHandler(() {
      _isSpeaking = true;
      onSpeakingStarted?.call();
    });

    _tts.setCompletionHandler(() {
      _isSpeaking = false;
      _usingEdgePlayer = false;
      onSpeakingDone?.call();
      _processQueue();
    });

    _tts.setCancelHandler(() {
      _isSpeaking = false;
      _usingEdgePlayer = false;
      onSpeakingDone?.call();
    });

    _tts.setErrorHandler((msg) {
      _isSpeaking = false;
      _usingEdgePlayer = false;
      onSpeakingDone?.call();
      _processQueue();
    });

    // Edge TTS audio player completion
    _edgePlayer.onPlayerComplete.listen((_) {
      _isSpeaking = false;
      _usingEdgePlayer = false;
      onSpeakingDone?.call();
      _processQueue();
    });
  }

  Future<void> speak(String text, {VoiceLanguage language = VoiceLanguage.en}) async {
    if (_isSpeaking) {
      _queue.add(_TtsRequest(text, language));
      return;
    }
    await _doSpeak(text, language);
  }

  /// Interrupt current speech and speak immediately (for anomaly alerts).
  Future<void> interruptAndSpeak(String text, {VoiceLanguage language = VoiceLanguage.en}) async {
    _queue.clear();
    if (_isSpeaking) {
      await _stopCurrent();
    }
    await _doSpeak(text, language);
  }

  Future<void> _doSpeak(String text, VoiceLanguage language) async {
    _isSpeaking = true;
    onSpeakingStarted?.call();

    // Try Edge TTS via backend first
    if (_serverUrl != null) {
      try {
        // Always use Blessica (Filipino neural voice) — sounds natural for both languages
        final voice = _filipinoVoice;
        final response = await http.post(
          Uri.parse('$_serverUrl/tts'),
          headers: {'Content-Type': 'application/json'},
          body: jsonEncode({'text': text, 'voice': voice}),
        ).timeout(const Duration(seconds: 15));

        if (response.statusCode == 200 && response.bodyBytes.length > 1000) {
          _usingEdgePlayer = true;
          await _edgePlayer.play(BytesSource(response.bodyBytes));
          return;
        }
      } catch (_) {
        // Fall through to on-device TTS
      }
    }

    // Fallback: on-device flutter_tts
    _usingEdgePlayer = false;
    await _tts.speak(text);
  }

  Future<void> _stopCurrent() async {
    if (_usingEdgePlayer) {
      await _edgePlayer.stop();
    }
    await _tts.stop();
    _isSpeaking = false;
    _usingEdgePlayer = false;
  }

  void _processQueue() {
    if (_queue.isNotEmpty) {
      final next = _queue.removeFirst();
      _doSpeak(next.text, next.language);
    }
  }

  Future<void> setVolume(double vol) async {
    await _tts.setVolume(vol.clamp(0.0, 1.0));
    await _edgePlayer.setVolume(vol.clamp(0.0, 1.0));
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
    await _stopCurrent();
  }

  Future<void> dispose() async {
    await stop();
    await _edgePlayer.dispose();
  }
}
