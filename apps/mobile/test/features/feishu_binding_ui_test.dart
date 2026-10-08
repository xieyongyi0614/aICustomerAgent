import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:go_router/go_router.dart';
import 'package:mobile/app/theme/app_theme.dart';
import 'package:mobile/core/storage/prefs_store.dart';
import 'package:mobile/features/profile/data/auth_repository.dart';
import 'package:mobile/features/profile/presentation/feishu_sign_in.dart';
import 'package:mobile/features/profile/presentation/login_page.dart';
import 'package:mobile/features/profile/presentation/profile_page.dart';
import 'package:shared_preferences/shared_preferences.dart';

class _FakeFeishuFlow extends FeishuSignIn {
  _FakeFeishuFlow({this.loginError, this.bindError});

  Object? loginError;
  Object? bindError;
  int loginCalls = 0;
  int bindCalls = 0;

  @override
  Future<TokenResult> login({
    required String platform,
    String? deviceName,
  }) async {
    loginCalls++;
    if (loginError != null) throw loginError!;
    return const TokenResult(
      token: 'feishu-token',
      userId: 'u-1',
      deviceId: 'dev-1',
      expiresAt: '2030-01-01T00:00:00',
    );
  }

  @override
  Future<BindingsResult> bind() async {
    bindCalls++;
    if (bindError != null) throw bindError!;
    return const BindingsResult(
      email: BindingItem(bound: true),
      feishu: BindingItem(bound: true),
    );
  }
}

class _FakeAuthRepository extends AuthRepository {
  _FakeAuthRepository({this.feishuBound = false});

  bool feishuBound;
  int unbindCalls = 0;

  @override
  Future<BindingsResult> fetchBindings() async => BindingsResult(
        email: const BindingItem(bound: true),
        feishu: BindingItem(bound: feishuBound),
      );

  @override
  Future<BindingsResult> unbindFeishu() async {
    unbindCalls++;
    feishuBound = false;
    return const BindingsResult(
      email: BindingItem(bound: true),
      feishu: BindingItem(bound: false),
    );
  }

  @override
  Future<bool> hasToken() async => true;
}

Widget _app(Widget home) => MaterialApp(theme: buildAppTheme(), home: home);

Future<void> _dismissSnackBar(WidgetTester tester) async {
  await tester.pump(const Duration(seconds: 5));
  await tester.pump(const Duration(seconds: 5));
}

/// 登录页在 800×600 测试视口里会把「其他登录方式」压到折叠线以下，
/// 点击前必须先滚到可见位置，否则 tap 会静默落空。
Future<void> _tapVisible(WidgetTester tester, Finder finder) async {
  await tester.ensureVisible(finder);
  await tester.pump();
  await tester.tap(finder);
}

Widget _profileApp(_FakeAuthRepository repo, _FakeFeishuFlow flow) =>
    ProviderScope(
      child: MaterialApp(
        theme: buildAppTheme(),
        home: ProfilePage(authRepository: repo, feishuFlow: flow),
      ),
    );

void main() {
  setUp(() {
    SharedPreferences.setMockInitialValues({});
  });

  testWidgets('login_page_shows_feishu_entry', (tester) async {
    await tester.pumpWidget(_app(LoginPage(feishuFlow: _FakeFeishuFlow())));
    await tester.pump();

    expect(find.text('飞书'), findsOneWidget);
    expect(find.text('微信'), findsOneWidget);
    expect(find.text('手机号'), findsOneWidget);
  });

  testWidgets('login_page_feishu_login_enters_home', (tester) async {
    final flow = _FakeFeishuFlow();
    final router = GoRouter(
      initialLocation: '/login',
      routes: [
        GoRoute(path: '/login', builder: (_, _) => LoginPage(feishuFlow: flow)),
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

    await _tapVisible(tester, find.text('飞书'));
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 50));

    expect(flow.loginCalls, 1);
    expect(find.text('FIRST_DAY_HOME'), findsOneWidget);
    final prefs = await PrefsStore.load();
    expect(prefs.loginSeen(), isTrue);
  });

  testWidgets('login_page_feishu_failure_shows_message', (tester) async {
    final flow = _FakeFeishuFlow(
      loginError: AuthCodeException(
        statusCode: 409,
        message: '该飞书账号已绑定其他账号，如需合并请联系管理员',
      ),
    );
    await tester.pumpWidget(_app(LoginPage(feishuFlow: flow)));
    await tester.pump();

    await _tapVisible(tester, find.text('飞书'));
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 50));

    expect(find.textContaining('已绑定其他账号'), findsOneWidget);
    await _dismissSnackBar(tester);
  });

  testWidgets('login_page_feishu_requires_agreement', (tester) async {
    final flow = _FakeFeishuFlow();
    await tester.pumpWidget(_app(LoginPage(feishuFlow: flow)));
    await tester.pump();

    await _tapVisible(tester, find.textContaining('《用户协议》'));
    await tester.pump();
    await _tapVisible(tester, find.text('飞书'));
    await tester.pump();

    expect(find.text('请先阅读并同意《用户协议》和《隐私政策》'), findsOneWidget);
    expect(flow.loginCalls, 0);
    await _dismissSnackBar(tester);
  });

  testWidgets('profile_page_shows_unbound_feishu_row', (tester) async {
    await tester.pumpWidget(
      _profileApp(_FakeAuthRepository(), _FakeFeishuFlow()),
    );
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 50));

    expect(find.text('飞书账号'), findsOneWidget);
    expect(find.text('去绑定'), findsOneWidget);
    expect(find.textContaining('绑定后可在飞书聊天'), findsOneWidget);
  });

  testWidgets('profile_page_binds_feishu_and_updates_row', (tester) async {
    final flow = _FakeFeishuFlow();
    await tester.pumpWidget(_profileApp(_FakeAuthRepository(), flow));
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 50));

    await tester.tap(find.text('飞书账号'));
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 50));

    expect(flow.bindCalls, 1);
    expect(find.text('已绑定'), findsOneWidget);
    await _dismissSnackBar(tester);
  });

  testWidgets('profile_page_bind_conflict_shows_message', (tester) async {
    final flow = _FakeFeishuFlow(
      bindError: AuthCodeException(
        statusCode: 409,
        message: '该飞书账号已绑定其他账号，如需合并请联系管理员',
      ),
    );
    await tester.pumpWidget(_profileApp(_FakeAuthRepository(), flow));
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 50));

    await tester.tap(find.text('飞书账号'));
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 50));

    expect(find.textContaining('已绑定其他账号'), findsOneWidget);
    expect(find.text('去绑定'), findsOneWidget);
    await _dismissSnackBar(tester);
  });

  testWidgets('profile_page_unbind_requires_confirmation', (tester) async {
    final repo = _FakeAuthRepository(feishuBound: true);
    await tester.pumpWidget(_profileApp(repo, _FakeFeishuFlow()));
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 50));
    expect(find.text('已绑定'), findsOneWidget);

    await tester.tap(find.text('飞书账号'));
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 50));
    expect(find.textContaining('解绑后飞书里会成为独立账号'), findsOneWidget);

    await tester.tap(find.text('解绑'));
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 50));

    expect(repo.unbindCalls, 1);
    expect(find.text('去绑定'), findsOneWidget);
    await _dismissSnackBar(tester);
  });
}
