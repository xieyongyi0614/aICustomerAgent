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

/// 邮箱验证码登录（API-014）：换取长期令牌进 Keychain。
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
    final resp = await _dio.post<Map<String, dynamic>>(
      '/auth/email/verify',
      data: {
        'email': email,
        'code': code,
        'device_id': deviceId,
        'platform': platform,
        if (deviceName != null) 'device_name': deviceName,
      },
    );
    return _persistTokenResponse(resp, deviceId);
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
