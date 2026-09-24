import 'package:flutter_secure_storage/flutter_secure_storage.dart';

import '../network/interceptors/token_reader.dart';

/// 令牌只进 Keychain / Keystore；禁止进 drift / prefs / 日志。
class SecureTokenStore implements TokenReader {
  SecureTokenStore({FlutterSecureStorage? storage})
      : _storage = storage ?? const FlutterSecureStorage();

  static const _keyAccessToken = 'zhaoxi.access_token';
  static const _keyDeviceId = 'zhaoxi.device_id';

  final FlutterSecureStorage _storage;

  @override
  Future<String?> readAccessToken() => _storage.read(key: _keyAccessToken);

  Future<void> writeAccessToken(String token) =>
      _storage.write(key: _keyAccessToken, value: token);

  Future<void> writeDeviceId(String id) =>
      _storage.write(key: _keyDeviceId, value: id);

  Future<String?> readDeviceId() => _storage.read(key: _keyDeviceId);

  Future<void> clearCredentials() async {
    await _storage.delete(key: _keyAccessToken);
    await _storage.delete(key: _keyDeviceId);
  }
}
