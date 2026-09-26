import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_secure_storage/flutter_secure_storage.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:go_router/go_router.dart';
import 'package:mobile/app/state/persona_mode.dart';
import 'package:mobile/app/theme/app_theme.dart';
import 'package:mobile/core/storage/prefs_store.dart';
import 'package:mobile/design_system/components/mode_selector.dart';
import 'package:mobile/features/profile/presentation/profile_page.dart';
import 'package:shared_preferences/shared_preferences.dart';

Widget _app() {
  final router = GoRouter(
    initialLocation: '/profile',
    routes: [
      GoRoute(path: '/profile', builder: (_, _) => const ProfilePage()),
      GoRoute(
        path: '/login',
        builder: (_, _) => const Scaffold(body: Text('LOGIN_PAGE')),
      ),
    ],
  );
  return ProviderScope(
    child: MaterialApp.router(theme: buildAppTheme(), routerConfig: router),
  );
}

void _useTallViewport(WidgetTester tester) {
  tester.view.physicalSize = const Size(390, 1400);
  tester.view.devicePixelRatio = 1.0;
  addTearDown(tester.view.reset);
}

Future<void> _settle(WidgetTester tester) async {
  await tester.pump();
  await tester.pump(const Duration(milliseconds: 100));
  await tester.pump(const Duration(milliseconds: 200));
}

void main() {
  setUp(() {
    FlutterSecureStorage.setMockInitialValues({});
    SharedPreferences.setMockInitialValues({});
  });

  testWidgets('profile_renders_identity_persona_and_settings', (tester) async {
    _useTallViewport(tester);
    final firstUsedAt = DateTime.now().subtract(const Duration(days: 45));
    SharedPreferences.setMockInitialValues({
      PrefsStore.keyNickname: '阿远',
      PrefsStore.keyFirstUsedAt: firstUsedAt.toIso8601String(),
    });
    await tester.pumpWidget(_app());
    await _settle(tester);
    expect(find.text('阿远'), findsOneWidget);
    expect(find.text('与亚丝娜相识 46 天'), findsOneWidget);
    expect(find.text('亚丝娜'), findsOneWidget);
    expect(find.text('温柔可靠 · 会主动关心你的生活'), findsOneWidget);
    expect(find.text('编辑人格'), findsOneWidget);
    expect(find.text('设备连接'), findsOneWidget);
    expect(find.text('健康数据授权'), findsOneWidget);
    expect(find.text('记忆管理'), findsOneWidget);
    expect(find.text('隐私设置'), findsOneWidget);
    expect(find.text('设备配对'), findsOneWidget);
    expect(find.text('主动关怀'), findsOneWidget);
    expect(find.text('状态异常提醒'), findsOneWidget);
    expect(find.text('退出登录'), findsOneWidget);
    expect(
      find.text('朝夕 v0.1.0 (MVP) · Personal AI OS 的第一步'),
      findsOneWidget,
    );
    final context = tester.element(find.text('阿远'));
    final container = ProviderScope.containerOf(context);
    expect(container.read(personaModeProvider), RoleMode.defaultMode);
  });

  testWidgets('profile_mode_selection_updates_shared_provider', (tester) async {
    _useTallViewport(tester);
    await tester.pumpWidget(_app());
    await _settle(tester);
    await tester.tap(find.text('Immersive'));
    await tester.pump();
    final context = tester.element(find.text('亚丝娜'));
    final container = ProviderScope.containerOf(context);
    expect(container.read(personaModeProvider), RoleMode.immersive);
  });

  testWidgets('profile_logout_clears_identity_and_returns_to_login',
      (tester) async {
    _useTallViewport(tester);
    SharedPreferences.setMockInitialValues({
      PrefsStore.keyNickname: '阿远',
      PrefsStore.keyLoginSeen: true,
    });
    await tester.pumpWidget(_app());
    await _settle(tester);
    await tester.tap(find.text('退出登录'));
    await tester.pump();
    expect(
      find.text('退出后需要重新登录或配对才能继续同步，本机数据不会丢失。'),
      findsOneWidget,
    );
    await tester.tap(find.text('取消'));
    await tester.pump();
    expect(find.text('阿远'), findsOneWidget);
    await tester.tap(find.text('退出登录'));
    await tester.pump();
    await tester.tap(find.widgetWithText(TextButton, '退出登录'));
    await tester.pump(const Duration(milliseconds: 200));
    await tester.pump(const Duration(milliseconds: 300));
    expect(find.text('LOGIN_PAGE'), findsOneWidget);
    final prefs = await SharedPreferences.getInstance();
    expect(prefs.getString(PrefsStore.keyNickname), isNull);
    expect(prefs.getBool(PrefsStore.keyLoginSeen), isNull);
  });
}
