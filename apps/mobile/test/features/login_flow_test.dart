import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:go_router/go_router.dart';
import 'package:mobile/app/theme/app_theme.dart';
import 'package:mobile/core/storage/prefs_store.dart';
import 'package:mobile/design_system/tokens/app_icons.dart';
import 'package:mobile/features/profile/data/auth_repository.dart';
import 'package:mobile/features/profile/presentation/login_page.dart';
import 'package:mobile/features/profile/presentation/verify_code_page.dart';
import 'package:shared_preferences/shared_preferences.dart';

Widget _app(Widget home) => MaterialApp(theme: buildAppTheme(), home: home);

Future<void> _dismissSnackBar(WidgetTester tester) async {
  await tester.pump(const Duration(seconds: 5));
  await tester.pump(const Duration(seconds: 5));
  await tester.pump(const Duration(seconds: 1));
}

/// 重发 Timer.periodic 不随页面销毁自动取消，测试结束前必须泵完。
Future<void> _drainResendCountdown(WidgetTester tester) async {
  for (var i = 0; i < 61; i++) {
    await tester.pump(const Duration(seconds: 1));
  }
  await tester.pump();
}

class _FakeAuthRepository extends AuthRepository {
  _FakeAuthRepository({this.sendError, this.verifyError});

  Object? sendError;
  Object? verifyError;
  final List<String> codeRequests = [];
  final List<String> verifiedCodes = [];

  @override
  Future<void> requestEmailCode(String email) async {
    if (sendError != null) throw sendError!;
    codeRequests.add(email);
  }

  @override
  Future<TokenResult> verifyEmailCode({
    required String email,
    required String code,
    required String deviceId,
    required String platform,
    String? deviceName,
  }) async {
    if (verifyError != null) throw verifyError!;
    verifiedCodes.add(code);
    return TokenResult(
      token: 'test-token',
      userId: 'u1',
      deviceId: deviceId,
      expiresAt: '2030-01-01T00:00:00',
    );
  }
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
    expect(find.text('邮箱登录 / 注册'), findsOneWidget);
    expect(find.text('未注册的邮箱将自动创建账号'), findsOneWidget);
    expect(find.text('其他登录方式'), findsOneWidget);
    expect(find.text('微信'), findsOneWidget);
    expect(find.text('手机号'), findsOneWidget);
    expect(find.textContaining('《用户协议》'), findsOneWidget);
    expect(find.textContaining('先逛逛'), findsNothing);
  });

  testWidgets('login_page_email_login_validates_and_passes_email',
      (tester) async {
    Object? verifyExtra;
    final router = GoRouter(
      initialLocation: '/login',
      routes: [
        GoRoute(path: '/login', builder: (_, _) => const LoginPage()),
        GoRoute(
          path: '/verify',
          builder: (_, state) {
            verifyExtra = state.extra;
            return const Scaffold(body: Text('VERIFY_PAGE'));
          },
        ),
      ],
    );
    await tester.pumpWidget(
      MaterialApp.router(theme: buildAppTheme(), routerConfig: router),
    );
    await tester.pump();
    await tester.drag(find.byType(Scrollable).first, const Offset(0, -450));
    await tester.pump();
    await tester.enterText(
        find.widgetWithText(TextField, '输入邮箱地址'), 'not-an-email');
    await tester.tap(find.text('邮箱登录 / 注册'));
    await tester.pump();
    expect(find.text('请输入正确的邮箱地址'), findsOneWidget);
    await _dismissSnackBar(tester);

    await tester.enterText(
        find.widgetWithText(TextField, '输入邮箱地址'), 'asuna@example.com');
    await tester.tap(find.text('邮箱登录 / 注册'));
    await tester.pump(const Duration(milliseconds: 200));
    await tester.pump(const Duration(milliseconds: 200));
    expect(find.text('VERIFY_PAGE'), findsOneWidget);
    expect(verifyExtra, 'asuna@example.com');
  });

  testWidgets('login_page_email_keyboard_done_submits', (tester) async {
    Object? verifyExtra;
    final router = GoRouter(
      initialLocation: '/login',
      routes: [
        GoRoute(path: '/login', builder: (_, _) => const LoginPage()),
        GoRoute(
          path: '/verify',
          builder: (_, state) {
            verifyExtra = state.extra;
            return const Scaffold(body: Text('VERIFY_PAGE'));
          },
        ),
      ],
    );
    await tester.pumpWidget(
      MaterialApp.router(theme: buildAppTheme(), routerConfig: router),
    );
    await tester.pump();
    await tester.enterText(
        find.widgetWithText(TextField, '输入邮箱地址'), 'asuna@example.com');
    await tester.testTextInput.receiveAction(TextInputAction.done);
    await tester.pump(const Duration(milliseconds: 200));
    await tester.pump(const Duration(milliseconds: 200));
    expect(find.text('VERIFY_PAGE'), findsOneWidget);
    expect(verifyExtra, 'asuna@example.com');
  });

  testWidgets('login_page_alt_login_requires_agreement_and_is_honest',
      (tester) async {
    await tester.pumpWidget(_app(const LoginPage()));
    await tester.pump();
    await tester.drag(find.byType(Scrollable).first, const Offset(0, -450));
    await tester.pump();
    expect(find.byIcon(AppIcons.check), findsOneWidget);
    await tester.tap(find.textContaining('《用户协议》'));
    await tester.pump();
    expect(find.byIcon(AppIcons.check), findsNothing);
    await tester.tap(find.text('微信'));
    await tester.pump();
    expect(find.textContaining('请先阅读并同意'), findsOneWidget);
    await _dismissSnackBar(tester);
    await tester.tap(find.textContaining('《用户协议》'));
    await tester.pump();
    await tester.tap(find.text('微信'));
    await tester.pump();
    expect(find.text('微信登录还没接入，先用邮箱见亚丝娜吧'), findsOneWidget);
    await _dismissSnackBar(tester);
    await tester.tap(find.text('手机号'));
    await tester.pump();
    expect(find.text('手机号登录还没接入，先用邮箱吧'), findsOneWidget);
    await _dismissSnackBar(tester);
  });

  testWidgets('verify_page_renders_email_code_state', (tester) async {
    final repo = _FakeAuthRepository();
    await tester.pumpWidget(_app(VerifyCodePage(
      email: 'asuna@example.com',
      authRepository: repo,
    )));
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 100));
    expect(find.text('亚丝娜 · 初次见面'), findsOneWidget);
    expect(find.text('输入邮箱验证码'), findsOneWidget);
    expect(find.text('asu***@example.com'), findsOneWidget);
    expect(find.text('修改'), findsOneWidget);
    expect(find.text('收不到验证码？'), findsOneWidget);
    expect(find.text('后可重新发送'), findsOneWidget);
    expect(find.text('开始我们的第一天'), findsOneWidget);
    expect(find.textContaining('你的数据只属于你'), findsOneWidget);
    expect(find.textContaining('验证码通道还没接入'), findsNothing);
    expect(repo.codeRequests, ['asuna@example.com']);
    await _dismissSnackBar(tester);
    await _drainResendCountdown(tester);
    expect(find.text('重新发送'), findsOneWidget);
  });

  testWidgets('verify_page_start_requires_six_digits', (tester) async {
    final repo = _FakeAuthRepository();
    await tester.pumpWidget(_app(VerifyCodePage(
      email: 'asuna@example.com',
      authRepository: repo,
    )));
    await tester.pump();
    await _dismissSnackBar(tester);
    await tester.enterText(find.byKey(const Key('verify_code_field')), '123');
    await tester.pump();
    expect(find.text('1'), findsOneWidget);
    expect(find.text('3'), findsOneWidget);
    await tester.tap(find.text('开始我们的第一天'));
    await tester.pump();
    expect(find.text('请输入 6 位验证码'), findsOneWidget);
    expect(repo.verifiedCodes, isEmpty);
    await _drainResendCountdown(tester);
  });

  testWidgets('verify_page_start_requires_agreement', (tester) async {
    final repo = _FakeAuthRepository();
    await tester.pumpWidget(_app(VerifyCodePage(
      email: 'asuna@example.com',
      authRepository: repo,
    )));
    await tester.pump();
    await _dismissSnackBar(tester);
    await tester.enterText(find.byKey(const Key('verify_code_field')), '123456');
    await tester.pump();
    await tester.tap(find.textContaining('《用户协议》'));
    await tester.pump();
    await tester.tap(find.text('开始我们的第一天'));
    await tester.pump();
    expect(find.text('请先阅读并同意《用户协议》和《隐私政策》'), findsOneWidget);
    expect(repo.verifiedCodes, isEmpty);
    await _drainResendCountdown(tester);
  });

  testWidgets('verify_page_start_saves_nickname_and_enters', (tester) async {
    final repo = _FakeAuthRepository();
    final router = GoRouter(
      initialLocation: '/verify',
      routes: [
        GoRoute(
          path: '/verify',
          builder: (_, _) => VerifyCodePage(
            email: 'asuna@example.com',
            authRepository: repo,
          ),
        ),
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
    await _dismissSnackBar(tester);
    await tester.enterText(find.byKey(const Key('verify_code_field')), '123456');
    await tester.pump();
    expect(find.text('1'), findsOneWidget);
    expect(find.text('6'), findsOneWidget);
    await tester.enterText(
        find.widgetWithText(TextField, '想让我怎么称呼你？（选填）'), '小夕');
    await tester.tap(find.text('开始我们的第一天'));
    await tester.pump(const Duration(milliseconds: 100));
    await tester.pump(const Duration(milliseconds: 200));
    expect(find.text('FIRST_DAY_HOME'), findsOneWidget);
    expect(repo.verifiedCodes, ['123456']);
    final prefs = await SharedPreferences.getInstance();
    expect(prefs.getString(PrefsStore.keyNickname), '小夕');
    expect(prefs.getBool(PrefsStore.keyLoginSeen), isTrue);
    await _drainResendCountdown(tester);
  });

  testWidgets('verify_page_wrong_code_shows_server_message', (tester) async {
    final repo = _FakeAuthRepository(
      verifyError: AuthCodeException(statusCode: 401, message: '验证码错误'),
    );
    await tester.pumpWidget(_app(VerifyCodePage(
      email: 'asuna@example.com',
      authRepository: repo,
    )));
    await tester.pump();
    await _dismissSnackBar(tester);
    await tester.enterText(find.byKey(const Key('verify_code_field')), '999999');
    await tester.pump();
    await tester.tap(find.text('开始我们的第一天'));
    await tester.pump(const Duration(milliseconds: 100));
    await tester.pump(const Duration(milliseconds: 200));
    expect(find.text('验证码错误'), findsOneWidget);
    expect(find.text('开始我们的第一天'), findsOneWidget);
    await _drainResendCountdown(tester);
  });

  testWidgets('verify_page_resend_after_countdown', (tester) async {
    final repo = _FakeAuthRepository();
    await tester.pumpWidget(_app(VerifyCodePage(
      email: 'asuna@example.com',
      authRepository: repo,
    )));
    await tester.pump();
    await _dismissSnackBar(tester);
    await _drainResendCountdown(tester);
    await tester.tap(find.text('重新发送'));
    await tester.pump(const Duration(milliseconds: 100));
    await tester.pump(const Duration(milliseconds: 100));
    expect(find.textContaining('验证码已重新发送'), findsOneWidget);
    expect(repo.codeRequests.length, 2);
    await _dismissSnackBar(tester);
    await _drainResendCountdown(tester);
  });

  testWidgets('verify_page_resend_rate_limited_shows_retry', (tester) async {
    final repo = _FakeAuthRepository(
      sendError: AuthCodeException(
        statusCode: 429,
        retryAfterSeconds: 37,
        message: '发送过于频繁，请 37 秒后重试',
      ),
    );
    await tester.pumpWidget(_app(VerifyCodePage(
      email: 'asuna@example.com',
      authRepository: repo,
    )));
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 100));
    expect(find.textContaining('发送过于频繁'), findsOneWidget);
    expect(find.textContaining('37 s'), findsOneWidget);
    await _dismissSnackBar(tester);
    await _drainResendCountdown(tester);
  });

  testWidgets('verify_page_help_link_copy', (tester) async {
    final repo = _FakeAuthRepository();
    await tester.pumpWidget(_app(VerifyCodePage(
      email: 'asuna@example.com',
      authRepository: repo,
    )));
    await tester.pump();
    await _dismissSnackBar(tester);
    await tester.tap(find.text('收不到验证码？'));
    await tester.pump();
    expect(find.textContaining('垃圾箱'), findsOneWidget);
    await _dismissSnackBar(tester);
    await _drainResendCountdown(tester);
  });
}
