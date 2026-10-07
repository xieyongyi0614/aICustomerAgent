import 'package:shared_preferences/shared_preferences.dart';

/// 非敏感偏好：只存参数类值；禁止功能开关位、金额、健康、记忆正文。
class PrefsStore {
  PrefsStore(this._prefs);

  static const keyMorningBriefAt = 'care.morning_brief_at';
  static const keyEveningBriefAt = 'care.evening_brief_at';
  static const keyLastConversationId = 'chat.last_conversation_id';
  static const keyLastSyncAt = 'sync.last_at';
  static const keyNickname = 'profile.nickname';
  static const keyLastEmail = 'profile.last_email';
  static const keyLoginSeen = 'profile.login_seen';
  static const keyFirstUsedAt = 'profile.first_used_at';
  static const keyModuleOrder = 'life.module_order';

  static const allKeys = [
    keyMorningBriefAt,
    keyEveningBriefAt,
    keyLastConversationId,
    keyLastSyncAt,
    keyNickname,
    keyLastEmail,
    keyLoginSeen,
    keyFirstUsedAt,
    keyModuleOrder,
  ];

  final SharedPreferences _prefs;

  static Future<PrefsStore> load() async =>
      PrefsStore(await SharedPreferences.getInstance());

  String? morningBriefAt() => _prefs.getString(keyMorningBriefAt);
  Future<void> setMorningBriefAt(String hhmm) =>
      _prefs.setString(keyMorningBriefAt, hhmm);

  String? eveningBriefAt() => _prefs.getString(keyEveningBriefAt);
  Future<void> setEveningBriefAt(String hhmm) =>
      _prefs.setString(keyEveningBriefAt, hhmm);

  String? lastConversationId() => _prefs.getString(keyLastConversationId);
  Future<void> setLastConversationId(String id) =>
      _prefs.setString(keyLastConversationId, id);

  int? lastSyncAtMillis() => _prefs.getInt(keyLastSyncAt);
  Future<void> setLastSyncAtMillis(int millis) =>
      _prefs.setInt(keyLastSyncAt, millis);

  String? nickname() => _prefs.getString(keyNickname);
  Future<void> setNickname(String value) =>
      _prefs.setString(keyNickname, value);

  /// 上次登录成功的邮箱：仅本机留存，供登录页一键回填。
  String? lastEmail() => _prefs.getString(keyLastEmail);
  Future<void> setLastEmail(String email) =>
      _prefs.setString(keyLastEmail, email);

  bool loginSeen() => _prefs.getBool(keyLoginSeen) ?? false;
  Future<void> markLoginSeen() async {
    await _prefs.setBool(keyLoginSeen, true);
    await _ensureFirstUsedAt();
  }

  String? firstUsedAt() => _prefs.getString(keyFirstUsedAt);

  String? moduleOrder() => _prefs.getString(keyModuleOrder);
  Future<void> setModuleOrder(String order) =>
      _prefs.setString(keyModuleOrder, order);

  Future<void> _ensureFirstUsedAt() async {
    if (_prefs.getString(keyFirstUsedAt) == null) {
      await _prefs.setString(
          keyFirstUsedAt, DateTime.now().toIso8601String());
    }
  }

  /// 退出登录：清称呼与登录标记；first_used_at 与 last_email 保留
  /// （相识天数不因登出重置；下次登录仍可选择上次账号一键回填）。
  Future<void> clearIdentity() async {
    await _prefs.remove(keyNickname);
    await _prefs.remove(keyLoginSeen);
  }

  Future<void> clearNonCredential() async {
    for (final k in allKeys) {
      await _prefs.remove(k);
    }
  }

  /// 一键清空的本地侧（/life/data 成功后调用）：除非凭据偏好外，
  /// 连同各域写在 SharedPreferences 里的私有键（`album.*` 等）一并清除。
  static const _businessKeyPrefixes = ['album.'];

  Future<void> clearBusinessData() async {
    await clearNonCredential();
    for (final key in _prefs.getKeys()) {
      if (_businessKeyPrefixes.any(key.startsWith)) {
        await _prefs.remove(key);
      }
    }
  }
}
