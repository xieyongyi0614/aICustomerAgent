import 'package:flutter_test/flutter_test.dart';
import 'package:mobile/app/router/app_router.dart';
import 'package:mobile/design_system/components/app_tab_bar.dart';

void main() {
  test('test_all_route_anchors_mapped', () {
    for (final p in const [
      '/home',
      '/dynamic',
      '/chat',
      '/chat/ledger',
      '/life',
      '/ledger',
      '/ledger/add',
      '/ledger/auto',
      '/memo',
      '/schedule',
      '/car',
      '/car/add',
      '/car/profile',
      '/album',
      '/album/manage',
      '/album/detail',
      '/album/photo',
      '/album/ai',
      '/health',
      '/memory',
      '/profile',
      '/briefing',
      '/profile/privacy',
      '/health/consent',
      '/health/probe',
      '/login',
      '/verify',
    ]) {
      expect(chromeByPath.containsKey(p), isTrue, reason: p);
    }
    expect(chromeByPath.length, 27);
  });

  test('test_tab_hidden_on_immersive_routes', () {
    for (final p in const [
      '/ledger',
      '/ledger/add',
      '/ledger/auto',
      '/memo',
      '/schedule',
      '/car',
      '/car/add',
      '/car/profile',
      '/album',
      '/album/manage',
      '/album/detail',
      '/album/photo',
      '/album/ai',
      '/chat/ledger',
      '/briefing',
      '/profile/privacy',
      '/health/consent',
      '/health/probe',
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

  test('test_shell_tab_owner_by_route', () {
    expect(ShellTab.forLocation('/home'), ShellTab.home);
    expect(ShellTab.forLocation('/dynamic'), ShellTab.dynamic);
    expect(ShellTab.forLocation('/chat'), ShellTab.chat);
    expect(ShellTab.forLocation('/chat/ledger?conversationId=1'), ShellTab.chat);
    expect(ShellTab.forLocation('/life'), ShellTab.life);
    for (final p in const [
      '/ledger',
      '/ledger/add',
      '/ledger/auto',
      '/memo',
      '/schedule',
      '/car',
      '/car/add',
      '/car/profile',
      '/album',
      '/album/manage',
      '/album/detail',
      '/album/photo',
      '/album/ai',
      '/health',
      '/health/consent',
      '/health/probe',
    ]) {
      expect(ShellTab.forLocation(p), ShellTab.life, reason: p);
    }
    expect(ShellTab.forLocation('/profile'), ShellTab.profile);
    expect(ShellTab.forLocation('/profile/privacy'), ShellTab.profile);
    expect(ShellTab.forLocation('/memory'), ShellTab.profile);
  });

  test('test_shell_tab_matches_by_segment_not_prefix', () {
    expect(ShellTab.forLocation('/lifestyle'), ShellTab.home);
    expect(ShellTab.forLocation('/profiles'), ShellTab.home);
    expect(ShellTab.forLocation('/briefing?type=morning'), ShellTab.home);
    expect(ShellTab.forLocation(''), ShellTab.home);
  });

  test('test_shell_tab_order_matches_tab_bar', () {
    expect(ShellTab.values.length, AppTabBar.tabCount);
    expect(
      ShellTab.values.map((tab) => tab.path).toList(),
      const ['/home', '/dynamic', '/chat', '/life', '/profile'],
    );
  });
}
