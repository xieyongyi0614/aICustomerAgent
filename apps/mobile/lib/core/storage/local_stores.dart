import 'package:drift/native.dart';

import 'cache_db.dart';
import 'prefs_store.dart';
import 'retry_store.dart';
import 'secure_token_store.dart';

/// 本地存储门面：清空（/life/data）时同步清缓存与偏好；令牌单独处理。
class LocalStores {
  LocalStores({
    required this.db,
    required this.prefs,
    required this.tokens,
    required this.retry,
  });

  final AppCacheDb db;
  final PrefsStore prefs;
  final SecureTokenStore tokens;
  final DriftRetryStore retry;

  static Future<LocalStores> openInMemory() async {
    final db = AppCacheDb(NativeDatabase.memory());
    final prefs = await PrefsStore.load();
    final tokens = SecureTokenStore();
    return LocalStores(
      db: db,
      prefs: prefs,
      tokens: tokens,
      retry: DriftRetryStore(db),
    );
  }

  /// 一键清空本地联动（不含令牌删除策略时可先 clearLocalBusiness）
  Future<void> clearLocalBusiness() async {
    await db.wipeAllCaches();
    await prefs.clearBusinessData();
  }

  Future<void> clearAllIncludingCredentials() async {
    await clearLocalBusiness();
    await retry.clear();
    await tokens.clearCredentials();
  }
}
