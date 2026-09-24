import 'package:flutter_test/flutter_test.dart';
import 'package:mobile/app/router/app_router.dart';

void main() {
  test('test_all_nine_anchors_mapped', () {
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
    ]) {
      expect(chromeByPath.containsKey(p), isTrue, reason: p);
    }
    expect(chromeByPath.length, 9);
  });

  test('test_tab_hidden_on_ledger_chatledger_briefing', () {
    expect(chromeForLocation('/ledger').hideTabBar, isTrue);
    expect(chromeForLocation('/chat/ledger').hideTabBar, isTrue);
    expect(chromeForLocation('/briefing').hideTabBar, isTrue);
    expect(chromeForLocation('/home').hideTabBar, isFalse);
    expect(chromeForLocation('/health').hideTabBar, isFalse);
  });

  test('test_briefing_status_bar_light', () {
    expect(chromeForLocation('/briefing').lightStatusBar, isTrue);
    expect(chromeForLocation('/home').lightStatusBar, isFalse);
  });
}
