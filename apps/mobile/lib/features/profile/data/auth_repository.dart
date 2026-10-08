import 'package:dio/dio.dart';

import '../../../core/network/dio_client.dart';
import '../../../core/network/errors/app_error.dart';
import '../../../core/storage/secure_token_store.dart';

class TokenResult {
  const TokenResult({
    required this.token,
    required this.userId,
    required this.deviceId,
    required this.expiresAt,
  });

  final String token;
  final String userId;
  final String deviceId;
  final String expiresAt;
}

/// 邮箱验证码登录的域异常：携带状态码 / Retry-After 与可展示消息。
class AuthCodeException implements Exception {
  AuthCodeException({
    this.statusCode,
    this.retryAfterSeconds,
    required this.message,
  });

  final int? statusCode;
  final int? retryAfterSeconds;
  final String message;

  factory AuthCodeException.fromDio(DioException e) {
    final status = e.response?.statusCode;
    final data = e.response?.data;
    final detail =
        data is Map && data['detail'] != null ? data['detail'].toString() : null;
    final retryAfter = int.tryParse(
      e.response?.headers.value('retry-after') ?? '',
    );
    final fallback = e.error is AppError
        ? (e.error as AppError).userMessage
        : '请求失败，请稍后再试';
    return AuthCodeException(
      statusCode: status,
      retryAfterSeconds: retryAfter,
      message: detail ?? fallback,
    );
  }
}

/// 飞书授权入口：浏览器地址 + 一次性 state + 有效期（秒）。
class FeishuAuthorizeResult {
  const FeishuAuthorizeResult({
    required this.authorizeUrl,
    required this.state,
    required this.expiresIn,
  });

  final String authorizeUrl;
  final String state;
  final int expiresIn;

  factory FeishuAuthorizeResult.fromJson(Map<String, dynamic>? data) {
    final json = data ?? const {};
    return FeishuAuthorizeResult(
      authorizeUrl: json['authorize_url'] as String? ?? '',
      state: json['state'] as String? ?? '',
      expiresIn: json['expires_in'] as int? ?? 0,
    );
  }
}

/// 单个通道的绑定状态。
class BindingItem {
  const BindingItem({required this.bound, this.boundAt});

  final bool bound;
  final String? boundAt;

  factory BindingItem.fromJson(Object? data) {
    final json = data is Map ? data : const {};
    return BindingItem(
      bound: json['bound'] as bool? ?? false,
      boundAt: json['bound_at'] as String?,
    );
  }
}

class BindingsResult {
  const BindingsResult({required this.email, required this.feishu});

  final BindingItem email;
  final BindingItem feishu;

  bool get feishuBound => feishu.bound;

  factory BindingsResult.fromJson(Map<String, dynamic>? data) {
    final json = data ?? const {};
    return BindingsResult(
      email: BindingItem.fromJson(json['email']),
      feishu: BindingItem.fromJson(json['feishu']),
    );
  }
}

/// 邮箱验证码登录（API-014）+ 飞书授权登录 / 绑定：换取长期令牌进 Keychain。
class AuthRepository {
  AuthRepository({Dio? dio, SecureTokenStore? tokenStore})
      : _dio = dio ?? createDio(),
        _store = tokenStore ?? SecureTokenStore();

  final Dio _dio;
  final SecureTokenStore _store;

  SecureTokenStore get tokenStore => _store;

  Future<bool> hasToken() async {
    final t = await _store.readAccessToken();
    return t != null && t.isNotEmpty;
  }

  Future<void> requestEmailCode(String email) async {
    try {
      await _dio.post<void>('/auth/email/code', data: {'email': email});
    } on DioException catch (e) {
      throw AuthCodeException.fromDio(e);
    }
  }

  Future<TokenResult> verifyEmailCode({
    required String email,
    required String code,
    required String deviceId,
    required String platform,
    String? deviceName,
  }) async {
    try {
      final resp = await _dio.post<Map<String, dynamic>>(
        '/auth/email/verify',
        data: {
          'email': email,
          'code': code,
          'device_id': deviceId,
          'platform': platform,
          'device_name': ?deviceName,
        },
      );
      return await _persistTokenResponse(resp, deviceId);
    } on DioException catch (e) {
      throw AuthCodeException.fromDio(e);
    }
  }

  /// 飞书登录授权地址（未登录可调用）。
  Future<FeishuAuthorizeResult> startFeishuLogin() async {
    try {
      final resp = await _dio.get<Map<String, dynamic>>('/auth/feishu/authorize');
      return FeishuAuthorizeResult.fromJson(resp.data);
    } on DioException catch (e) {
      throw AuthCodeException.fromDio(e);
    }
  }

  /// 飞书绑定授权地址（需已登录）。
  Future<FeishuAuthorizeResult> startFeishuBind() async {
    try {
      final resp =
          await _dio.get<Map<String, dynamic>>('/auth/feishu/bind/authorize');
      return FeishuAuthorizeResult.fromJson(resp.data);
    } on DioException catch (e) {
      throw AuthCodeException.fromDio(e);
    }
  }

  /// 领取飞书登录结果；返回 null 表示授权尚未完成（继续轮询）。
  Future<TokenResult?> claimFeishuLogin({
    required String state,
    required String deviceId,
    required String platform,
    String? deviceName,
  }) async {
    try {
      final resp = await _dio.post<Map<String, dynamic>>(
        '/auth/feishu/login/claim',
        data: {
          'state': state,
          'device_id': deviceId,
          'platform': platform,
          'device_name': ?deviceName,
        },
      );
      return await _persistTokenResponse(resp, deviceId);
    } on DioException catch (e) {
      if (e.response?.statusCode == 404) return null;
      throw AuthCodeException.fromDio(e);
    }
  }

  /// 领取飞书绑定结果；返回 null 表示授权尚未完成（继续轮询）。
  Future<BindingsResult?> claimFeishuBind(String state) async {
    try {
      final resp = await _dio.post<Map<String, dynamic>>(
        '/auth/feishu/bind/claim',
        data: {'state': state},
      );
      return BindingsResult.fromJson(resp.data);
    } on DioException catch (e) {
      if (e.response?.statusCode == 404) return null;
      throw AuthCodeException.fromDio(e);
    }
  }

  Future<BindingsResult> fetchBindings() async {
    try {
      final resp = await _dio.get<Map<String, dynamic>>('/auth/bindings');
      return BindingsResult.fromJson(resp.data);
    } on DioException catch (e) {
      throw AuthCodeException.fromDio(e);
    }
  }

  Future<BindingsResult> unbindFeishu() async {
    try {
      final resp = await _dio.delete<Map<String, dynamic>>('/auth/feishu/bind');
      return BindingsResult.fromJson(resp.data);
    } on DioException catch (e) {
      throw AuthCodeException.fromDio(e);
    }
  }

  /// 本机设备标识：同一次登录流程内的重试必须复用同一 id，
  /// 每次尝试都生成新 id 会让服务端把同一台设备当成多台。
  Future<String> deviceIdentity() async {
    final existing = await _store.readDeviceId();
    if (existing != null && existing.isNotEmpty) return existing;
    final id = 'dev-${DateTime.now().microsecondsSinceEpoch.toRadixString(36)}';
    await _store.writeDeviceId(id);
    return id;
  }

  Future<TokenResult> _persistTokenResponse(
    Response<Map<String, dynamic>?> resp,
    String fallbackDeviceId,
  ) async {
    final data = resp.data ?? const {};
    final token = data['token'] as String? ?? '';
    final userId = data['user_id'] as String? ?? '';
    final boundDevice = data['device_id'] as String? ?? fallbackDeviceId;
    final expiresAt = data['expires_at'] as String? ?? '';
    if (token.isEmpty) {
      throw StateError('auth failed: empty token');
    }
    await _store.writeAccessToken(token);
    await _store.writeDeviceId(boundDevice);
    return TokenResult(
      token: token,
      userId: userId,
      deviceId: boundDevice,
      expiresAt: expiresAt,
    );
  }

  Future<void> signOut() => _store.clearCredentials();
}
