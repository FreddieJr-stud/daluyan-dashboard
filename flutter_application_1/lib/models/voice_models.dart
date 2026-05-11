enum VoiceState { idle, listening, processing, speaking }

enum VoiceLanguage { en, fil, auto }

enum SpeechRate { slow, normal, fast }

enum Speaker { crew, dalaray }

enum SttTier { cloud, rpi5, platform, none }

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
