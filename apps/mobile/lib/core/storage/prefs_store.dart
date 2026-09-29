import 'package:shared_preferences/shared_preferences.dart';

/// 非敏感偏好：只存参数类值；禁止功能开关位、金额、健康、记忆正文。
class PrefsStore {
  PrefsStore(this._prefs);

  static const keyMorningBriefAt = 'care.morning_brief_at';
  static const keyEveningBriefAt = 'care.evening_brief_at';
  static const keyLastConversationId = 'chat.last_conversation_id';
  static const keyLastSyncAt = 'sync.last_at';
  static const keyNickname = 'profile.nickname';
  static const keyLoginSeen = 'profile.login_seen';
  static const keyFirstUsedAt = 'profile.first_used_at';
  static const keyHealthConsentGranted = 'health.consent_granted';

  static const allKeys = [
    keyMorningBriefAt,
    keyEveningBriefAt,
    keyLastConversationId,
    keyLastSyncAt,
    keyNickname,
    keyLoginSeen,
    keyHealthConsentGranted,
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

  bool loginSeen() => _prefs.getBool(keyLoginSeen) ?? false;
  Future<void> markLoginSeen() async {
    await _prefs.setBool(keyLoginSeen, true);
    await _ensureFirstUsedAt();
  }

  String? firstUsedAt() => _prefs.getString(keyFirstUsedAt);

  /// APP-025 单独同意：健康数据授权的端侧同意记录（Q9 裁决）。
  bool healthConsentGranted() =>
      _prefs.getBool(keyHealthConsentGranted) ?? false;
  Future<void> setHealthConsentGranted(bool granted) =>
      _prefs.setBool(keyHealthConsentGranted, granted);

  Future<void> _ensureFirstUsedAt() async {
    if (_prefs.getString(keyFirstUsedAt) == null) {
      await _prefs.setString(
          keyFirstUsedAt, DateTime.now().toIso8601String());
    }
  }

  /// 退出登录：清称呼与登录标记；first_used_at 保留（相识天数不因登出重置）。
  Future<void> clearIdentity() async {
    await _prefs.remove(keyNickname);
    await _prefs.remove(keyLoginSeen);
  }

  Future<void> clearNonCredential() async {
    for (final k in allKeys) {
      await _prefs.remove(k);
    }
  }
}
