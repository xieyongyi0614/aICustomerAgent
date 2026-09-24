import 'package:dio/dio.dart';

import '../../../core/network/dio_client.dart';
import '../../../core/storage/secure_token_store.dart';

class PairResult {
  const PairResult({
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

/// API-001 设备配对：pairing_secret + device_id → 长期令牌（进 Keychain）。
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

  Future<PairResult> pair({
    required String pairingSecret,
    required String deviceId,
    required String platform,
    String? deviceName,
  }) async {
    final resp = await _dio.post<Map<String, dynamic>>(
      '/auth/pair',
      data: {
        'pairing_secret': pairingSecret,
        'device_id': deviceId,
        'platform': platform,
        if (deviceName != null) 'device_name': deviceName,
      },
    );
    final data = resp.data ?? const {};
    final token = data['token'] as String? ?? '';
    final userId = data['user_id'] as String? ?? '';
    final boundDevice = data['device_id'] as String? ?? deviceId;
    final expiresAt = data['expires_at'] as String? ?? '';
    if (token.isEmpty) {
      throw StateError('pair failed: empty token');
    }
    await _store.writeAccessToken(token);
    await _store.writeDeviceId(boundDevice);
    return PairResult(
      token: token,
      userId: userId,
      deviceId: boundDevice,
      expiresAt: expiresAt,
    );
  }

  Future<void> signOut() => _store.clearCredentials();
}
