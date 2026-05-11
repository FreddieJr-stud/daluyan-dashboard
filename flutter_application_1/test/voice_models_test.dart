import 'package:flutter_test/flutter_test.dart';
import 'package:flutter_application_1/models/voice_models.dart';

void main() {
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
