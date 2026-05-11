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
      final r = matcher.match('predict to Guadaloupe');
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
