import 'package:flutter_secure_storage/flutter_secure_storage.dart';

import '../network/interceptors/token_reader.dart';

/// 令牌只进 Keychain / Keystore；禁止进 drift / prefs / 日志。
class SecureTokenStore implements TokenReader {
  SecureTokenStore({FlutterSecureStorage? storage})
      : _storage = storage ?? const FlutterSecureStorage();

  static const _keyAccessToken = 'zhaoxi.access_token';
  static const _keyDeviceId = 'zhaoxi.device_id';

  /// 全进程令牌写入序号：任何实例写入 / 清除令牌都 +1，使其余实例的缓存立刻失效。
  /// 缓存只认「自己读过」，会让登录写入的令牌（AuthRepository 的实例）
  /// 对共享 Dio 的读取实例（dio_client 的实例）不可见 —— 表现为登录后每个
  /// 请求仍发旧令牌 / 不发令牌，服务端一律 401，再被 401 收口清掉令牌踢回登录页。
  static int _tokenRevision = 0;

  final FlutterSecureStorage _storage;
  String? _cachedToken;
  int _cachedTokenRevision = -1;

  /// 每次请求都直读 Keystore 是可感知的延迟；实例内做单飞缓存，
  /// 且按全进程序号校验，任一实例写入 / 清除都会让本实例缓存立刻失效。
  @override
  Future<String?> readAccessToken() async {
    if (_cachedTokenRevision != _tokenRevision) {
      _cachedToken = await _storage.read(key: _keyAccessToken);
      _cachedTokenRevision = _tokenRevision;
    }
    return _cachedToken;
  }

  Future<void> writeAccessToken(String token) async {
    await _storage.write(key: _keyAccessToken, value: token);
    _cachedToken = token;
    _cachedTokenRevision = ++_tokenRevision;
  }

  Future<void> writeDeviceId(String id) =>
      _storage.write(key: _keyDeviceId, value: id);

  Future<String?> readDeviceId() => _storage.read(key: _keyDeviceId);

  Future<void> clearCredentials() async {
    await _storage.delete(key: _keyAccessToken);
    await _storage.delete(key: _keyDeviceId);
    _cachedToken = null;
    _cachedTokenRevision = ++_tokenRevision;
  }
}
