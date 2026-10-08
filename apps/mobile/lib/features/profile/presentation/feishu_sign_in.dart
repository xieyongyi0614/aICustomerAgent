import 'package:url_launcher/url_launcher.dart';

import '../data/auth_repository.dart';

typedef UrlOpener = Future<bool> Function(String url);

Future<bool> openAuthorizationPage(String url) async {
  final uri = Uri.tryParse(url);
  if (uri == null) return false;
  return launchUrl(uri, mode: LaunchMode.externalApplication);
}

/// 飞书授权编排：打开系统浏览器完成授权，再凭 state 轮询领取结果。
///
/// 授权码只在服务端回调里消费一次，App 拿不到也不需要它；`claim*` 返回 null
/// 表示用户还没点完授权，继续等下一轮。零新增原生能力：不注册自定义 scheme，
/// 授权完成后服务端页面提示「请返回 App」，本流程在页面回到前台后自然续上。
class FeishuSignIn {
  FeishuSignIn({
    AuthRepository? authRepository,
    UrlOpener? openUrl,
    Duration? pollInterval,
    int? maxAttempts,
  })  : _injectedAuth = authRepository,
        _openUrl = openUrl ?? openAuthorizationPage,
        _pollInterval = pollInterval ?? const Duration(seconds: 2),
        _maxAttempts = maxAttempts ?? 45;

  final AuthRepository? _injectedAuth;
  final UrlOpener _openUrl;
  final Duration _pollInterval;
  final int _maxAttempts;

  late final AuthRepository _auth = _injectedAuth ?? AuthRepository();

  Future<TokenResult> login({
    required String platform,
    String? deviceName,
  }) async {
    final deviceId = await _auth.deviceIdentity();
    final ticket = await _auth.startFeishuLogin();
    await _open(ticket.authorizeUrl);
    for (var attempt = 0; attempt < _maxAttempts; attempt++) {
      await Future<void>.delayed(_pollInterval);
      final result = await _auth.claimFeishuLogin(
        state: ticket.state,
        deviceId: deviceId,
        platform: platform,
        deviceName: deviceName,
      );
      if (result != null) return result;
    }
    throw AuthCodeException(message: '还没收到飞书授权结果，稍后再试，或先用邮箱登录');
  }

  Future<BindingsResult> bind() async {
    final ticket = await _auth.startFeishuBind();
    await _open(ticket.authorizeUrl);
    for (var attempt = 0; attempt < _maxAttempts; attempt++) {
      await Future<void>.delayed(_pollInterval);
      final result = await _auth.claimFeishuBind(ticket.state);
      if (result != null) return result;
    }
    throw AuthCodeException(message: '还没收到飞书授权结果，稍后再试');
  }

  Future<void> _open(String url) async {
    final opened = await _openUrl(url);
    if (!opened) {
      throw AuthCodeException(message: '没能打开飞书授权页，请稍后重试');
    }
  }
}
