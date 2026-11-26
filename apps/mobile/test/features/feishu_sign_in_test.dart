import 'package:flutter_test/flutter_test.dart';
import 'package:mobile/features/profile/data/auth_repository.dart';
import 'package:mobile/features/profile/presentation/feishu_sign_in.dart';

class _RecordingRepository extends AuthRepository {
  _RecordingRepository({
    this.pendingPolls = 0,
    this.claimError,
    this.claimBindError,
  });

  final int pendingPolls;
  final Object? claimError;
  final Object? claimBindError;
  int claims = 0;
  int bindClaims = 0;

  @override
  Future<String> deviceIdentity() async => 'dev-1';

  @override
  Future<FeishuAuthorizeResult> startFeishuLogin() async =>
      const FeishuAuthorizeResult(
        authorizeUrl: 'https://accounts.feishu.cn/authen?state=st-1',
        state: 'st-1',
        expiresIn: 300,
      );

  @override
  Future<FeishuAuthorizeResult> startFeishuBind() async =>
      const FeishuAuthorizeResult(
        authorizeUrl: 'https://accounts.feishu.cn/authen?state=st-2',
        state: 'st-2',
        expiresIn: 300,
      );

  @override
  Future<TokenResult?> claimFeishuLogin({
    required String state,
    required String deviceId,
    required String platform,
    String? deviceName,
  }) async {
    claims++;
    if (claimError != null) throw claimError!;
    if (claims <= pendingPolls) return null;
    return TokenResult(
      token: 'token-$state',
      userId: 'u-1',
      deviceId: deviceId,
      expiresAt: '2030-01-01T00:00:00',
    );
  }

  @override
  Future<BindingsResult?> claimFeishuBind(String state) async {
    bindClaims++;
    if (claimBindError != null) throw claimBindError!;
    if (bindClaims <= pendingPolls) return null;
    return const BindingsResult(
      email: BindingItem(bound: true),
      feishu: BindingItem(bound: true),
    );
  }
}

void main() {
  test('login_opens_browser_then_polls_until_ready', () async {
    final repo = _RecordingRepository(pendingPolls: 2);
    final opened = <String>[];
    final flow = FeishuSignIn(
      authRepository: repo,
      openUrl: (url) async {
        opened.add(url);
        return true;
      },
      pollInterval: Duration.zero,
    );

    final result = await flow.login(platform: 'android');

    expect(opened, ['https://accounts.feishu.cn/authen?state=st-1']);
    expect(repo.claims, 3);
    expect(result.token, 'token-st-1');
    expect(result.deviceId, 'dev-1');
  });

  test('login_reports_when_browser_cannot_open', () async {
    final repo = _RecordingRepository();
    final flow = FeishuSignIn(
      authRepository: repo,
      openUrl: (_) async => false,
      pollInterval: Duration.zero,
    );

    await expectLater(
      flow.login(platform: 'android'),
      throwsA(isA<AuthCodeException>()),
    );
    expect(repo.claims, 0);
  });

  test('login_gives_up_after_max_attempts', () async {
    final repo = _RecordingRepository(pendingPolls: 99);
    final flow = FeishuSignIn(
      authRepository: repo,
      openUrl: (_) async => true,
      pollInterval: Duration.zero,
      maxAttempts: 3,
    );

    await expectLater(
      flow.login(platform: 'android'),
      throwsA(
        isA<AuthCodeException>().having(
          (e) => e.message,
          'message',
          contains('还没收到飞书授权结果'),
        ),
      ),
    );
    expect(repo.claims, 3);
  });

  test('login_propagates_server_message', () async {
    final repo = _RecordingRepository(
      claimError: AuthCodeException(statusCode: 400, message: '授权请求已失效，请重新发起飞书登录'),
    );
    final flow = FeishuSignIn(
      authRepository: repo,
      openUrl: (_) async => true,
      pollInterval: Duration.zero,
    );

    await expectLater(
      flow.login(platform: 'android'),
      throwsA(
        isA<AuthCodeException>().having(
          (e) => e.message,
          'message',
          '授权请求已失效，请重新发起飞书登录',
        ),
      ),
    );
  });

  test('bind_opens_browser_then_polls_until_ready', () async {
    final repo = _RecordingRepository(pendingPolls: 1);
    final opened = <String>[];
    final flow = FeishuSignIn(
      authRepository: repo,
      openUrl: (url) async {
        opened.add(url);
        return true;
      },
      pollInterval: Duration.zero,
    );

    final result = await flow.bind();

    expect(opened, ['https://accounts.feishu.cn/authen?state=st-2']);
    expect(repo.bindClaims, 2);
    expect(result.feishuBound, isTrue);
  });

  test('bind_surfaces_conflict_message', () async {
    final repo = _RecordingRepository(
      claimBindError: AuthCodeException(statusCode: 409, message: '该飞书账号已绑定其他账号，如需合并请联系管理员'),
    );
    final flow = FeishuSignIn(
      authRepository: repo,
      openUrl: (_) async => true,
      pollInterval: Duration.zero,
    );

    await expectLater(
      flow.bind(),
      throwsA(
        isA<AuthCodeException>().having(
          (e) => e.message,
          'message',
          contains('已绑定其他账号'),
        ),
      ),
    );
  });
}
