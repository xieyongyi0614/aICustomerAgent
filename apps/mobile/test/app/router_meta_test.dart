import 'package:flutter_test/flutter_test.dart';
import 'package:mobile/app/router/app_router.dart';

void main() {
  test('test_all_route_anchors_mapped', () {
    for (final p in const [
      '/home',
      '/chat',
      '/chat/ledger',
      '/life',
      '/ledger',
      '/health',
      '/memory',
      '/profile',
      '/briefing',
      '/profile/privacy',
      '/health/consent',
      '/login',
      '/verify',
    ]) {
      expect(chromeByPath.containsKey(p), isTrue, reason: p);
    }
    expect(chromeByPath.length, 13);
  });

  test('test_tab_hidden_on_immersive_routes', () {
    for (final p in const [
      '/ledger',
      '/chat/ledger',
      '/briefing',
      '/profile/privacy',
      '/health/consent',
      '/chat',
      '/login',
      '/verify',
    ]) {
      expect(chromeForLocation(p).hideTabBar, isTrue, reason: p);
    }
    expect(chromeForLocation('/home').hideTabBar, isFalse);
    expect(chromeForLocation('/health').hideTabBar, isFalse);
  });

  test('test_briefing_status_bar_light', () {
    expect(chromeForLocation('/briefing').lightStatusBar, isTrue);
    expect(chromeForLocation('/home').lightStatusBar, isFalse);
    expect(chromeForLocation('/login').lightStatusBar, isFalse);
  });
}
