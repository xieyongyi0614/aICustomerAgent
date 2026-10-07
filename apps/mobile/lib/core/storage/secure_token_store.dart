import 'package:flutter_secure_storage/flutter_secure_storage.dart';

import '../network/interceptors/token_reader.dart';

/// 令牌只进 Keychain / Keystore；禁止进 drift / prefs / 日志。
class SecureTokenStore implements TokenReader {
  SecureTokenStore({FlutterSecureStorage? storage})
      : _storage = storage ?? const FlutterSecureStorage();

  static const _keyAccessToken = 'zhaoxi.access_token';
  static const _keyDeviceId = 'zhaoxi.device_id';

  final FlutterSecureStorage _storage;
  String? _cachedToken;
  bool _tokenLoaded = false;

  /// 每次请求都直读 Keystore 是可感知的延迟；实例内做单飞缓存，
  /// 写入与清除路径同步失效，登出后不会带旧令牌。
  @override
  Future<String?> readAccessToken() async {
    if (!_tokenLoaded) {
      _cachedToken = await _storage.read(key: _keyAccessToken);
      _tokenLoaded = true;
    }
    return _cachedToken;
  }

  Future<void> writeAccessToken(String token) async {
    await _storage.write(key: _keyAccessToken, value: token);
    _cachedToken = token;
    _tokenLoaded = true;
  }

  Future<void> writeDeviceId(String id) =>
      _storage.write(key: _keyDeviceId, value: id);

  Future<String?> readDeviceId() => _storage.read(key: _keyDeviceId);

  Future<void> clearCredentials() async {
    await _storage.delete(key: _keyAccessToken);
    await _storage.delete(key: _keyDeviceId);
    _cachedToken = null;
    _tokenLoaded = false;
  }
}
