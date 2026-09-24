import 'package:shared_preferences/shared_preferences.dart';

/// 非敏感偏好：只存参数类值；禁止功能开关位、金额、健康、记忆正文。
class PrefsStore {
  PrefsStore(this._prefs);

  static const keyMorningBriefAt = 'care.morning_brief_at';
  static const keyEveningBriefAt = 'care.evening_brief_at';
  static const keyLastConversationId = 'chat.last_conversation_id';
  static const keyLastSyncAt = 'sync.last_at';

  static const allKeys = [
    keyMorningBriefAt,
    keyEveningBriefAt,
    keyLastConversationId,
    keyLastSyncAt,
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

  Future<void> clearNonCredential() async {
    for (final k in allKeys) {
      await _prefs.remove(k);
    }
  }
}
