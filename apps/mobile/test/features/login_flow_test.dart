import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:go_router/go_router.dart';
import 'package:mobile/app/theme/app_theme.dart';
import 'package:mobile/core/storage/prefs_store.dart';
import 'package:mobile/design_system/tokens/app_icons.dart';
import 'package:mobile/features/profile/presentation/login_page.dart';
import 'package:mobile/features/profile/presentation/verify_code_page.dart';
import 'package:shared_preferences/shared_preferences.dart';

Widget _app(Widget home) => MaterialApp(theme: buildAppTheme(), home: home);

Future<void> _dismissSnackBar(WidgetTester tester) async {
  await tester.pump(const Duration(seconds: 5));
  await tester.pump(const Duration(seconds: 5));
  await tester.pump(const Duration(seconds: 1));
}

void main() {
  setUp(() {
    SharedPreferences.setMockInitialValues({});
  });

  testWidgets('login_page_renders_first_meeting_copy', (tester) async {
    await tester.pumpWidget(_app(const LoginPage()));
    await tester.pump();
    expect(find.text('朝夕'), findsOneWidget);
    expect(find.text('一个有长期记忆的 AI 生命管家'), findsOneWidget);
    expect(find.textContaining('你好，我是亚丝娜'), findsOneWidget);
    expect(find.text('微信一键登录'), findsOneWidget);
    expect(find.text('手机号登录 / 注册'), findsOneWidget);
    expect(find.text('先逛逛，稍后再登录 →'), findsOneWidget);
    expect(find.textContaining('《用户协议》'), findsOneWidget);
  });

  testWidgets('login_page_wechat_login_requires_agreement', (tester) async {
    await tester.pumpWidget(_app(const LoginPage()));
    await tester.pump();
    await tester.drag(find.byType(Scrollable).first, const Offset(0, -300));
    await tester.pump();
    expect(find.byIcon(AppIcons.check), findsOneWidget);
    await tester.tap(find.textContaining('《用户协议》'));
    await tester.pump();
    expect(find.byIcon(AppIcons.check), findsNothing);
    await tester.tap(find.text('微信一键登录'));
    await tester.pump();
    expect(find.textContaining('请先阅读并同意'), findsOneWidget);
    await _dismissSnackBar(tester);
    await tester.tap(find.textContaining('《用户协议》'));
    await tester.pump();
    await tester.tap(find.text('微信一键登录'));
    await tester.pump();
    expect(find.text('微信登录还没接入，先用手机号见亚丝娜吧'), findsOneWidget);
    await _dismissSnackBar(tester);
  });

  testWidgets('login_page_guest_marks_login_seen_and_enters', (tester) async {
    final router = GoRouter(
      initialLocation: '/login',
      routes: [
        GoRoute(path: '/login', builder: (_, _) => const LoginPage()),
        GoRoute(
          path: '/home',
          builder: (_, _) => const Scaffold(body: Text('GUEST_HOME')),
        ),
      ],
    );
    await tester.pumpWidget(
      MaterialApp.router(theme: buildAppTheme(), routerConfig: router),
    );
    await tester.pump();
    await tester.drag(find.byType(Scrollable).first, const Offset(0, -300));
    await tester.pump();
    await tester.tap(find.text('先逛逛，稍后再登录 →'));
    await tester.pump(const Duration(milliseconds: 200));
    await tester.pump(const Duration(milliseconds: 200));
    expect(find.text('GUEST_HOME'), findsOneWidget);
    final prefs = await SharedPreferences.getInstance();
    expect(prefs.getBool(PrefsStore.keyLoginSeen), isTrue);
  });

  testWidgets('verify_page_renders_and_validates_phone', (tester) async {
    await tester.pumpWidget(_app(const VerifyCodePage()));
    await tester.pump();
    expect(find.text('亚丝娜 · 初次见面'), findsOneWidget);
    expect(find.text('手机号登录 / 注册'), findsOneWidget);
    expect(find.text('未注册的手机号将自动创建账号'), findsOneWidget);
    expect(find.text('获取验证码'), findsOneWidget);
    expect(find.text('开始我们的第一天'), findsOneWidget);
    expect(find.textContaining('你的数据只属于你'), findsOneWidget);
    await tester.tap(find.text('开始我们的第一天'));
    await tester.pump();
    expect(find.text('请输入正确的手机号'), findsOneWidget);
  });

  testWidgets('verify_page_resend_countdown_starts', (tester) async {
    await tester.pumpWidget(_app(const VerifyCodePage()));
    await tester.pump();
    await tester.enterText(find.widgetWithText(TextField, '输入手机号'), '13800138000');
    await tester.tap(find.text('获取验证码'));
    await tester.pump();
    expect(find.text('重发（60 s）'), findsOneWidget);
    expect(find.text('验证码通道还没接入，填好信息后直接点「开始我们的第一天」'), findsOneWidget);
    for (var i = 0; i < 62; i++) {
      await tester.pump(const Duration(seconds: 1));
    }
    await tester.pump();
    expect(find.text('获取验证码'), findsOneWidget);
  });

  testWidgets('verify_page_start_requires_code_and_saves_nickname',
      (tester) async {
    final router = GoRouter(
      initialLocation: '/verify',
      routes: [
        GoRoute(path: '/verify', builder: (_, _) => const VerifyCodePage()),
        GoRoute(
          path: '/home',
          builder: (_, _) => const Scaffold(body: Text('FIRST_DAY_HOME')),
        ),
      ],
    );
    await tester.pumpWidget(
      MaterialApp.router(theme: buildAppTheme(), routerConfig: router),
    );
    await tester.pump();
    await tester.enterText(
        find.widgetWithText(TextField, '输入手机号'), '13800138000');
    await tester.enterText(
        find.widgetWithText(TextField, '输入 6 位验证码'), '123456');
    await tester.enterText(
        find.widgetWithText(TextField, '想让我怎么称呼你？（选填）'), '小夕');
    await tester.tap(find.text('开始我们的第一天'));
    await tester.pump(const Duration(milliseconds: 100));
    await tester.pump(const Duration(milliseconds: 200));
    expect(find.text('FIRST_DAY_HOME'), findsOneWidget);
    final prefs = await SharedPreferences.getInstance();
    expect(prefs.getString(PrefsStore.keyNickname), '小夕');
    expect(prefs.getBool(PrefsStore.keyLoginSeen), isTrue);
  });
}
