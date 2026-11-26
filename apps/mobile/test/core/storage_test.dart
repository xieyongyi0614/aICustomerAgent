import 'dart:io';

import 'package:drift/drift.dart' show Value;
import 'package:drift/native.dart';
import 'package:flutter_secure_storage/flutter_secure_storage.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:mobile/core/storage/cache_db.dart';
import 'package:mobile/core/storage/prefs_store.dart';
import 'package:mobile/core/storage/retry_store.dart';
import 'package:mobile/core/storage/secure_token_store.dart';

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();

  test('test_token_only_in_secure_storage', () {
    final secure = File('lib/core/storage/secure_token_store.dart').readAsStringSync();
    expect(secure.contains('access_token'), isTrue);
    final prefs = File('lib/core/storage/prefs_store.dart').readAsStringSync();
    expect(prefs.toLowerCase().contains('token'), isFalse);
    final db = File('lib/core/storage/cache_db.dart').readAsStringSync();
    expect(db.toLowerCase().contains('accesstoken'), isFalse);
    expect(db.toLowerCase().contains('bearer'), isFalse);
  });

  test('test_token_cache_is_shared_across_store_instances', () async {
    FlutterSecureStorage.setMockInitialValues({});
    final writer = SecureTokenStore();
    final reader = SecureTokenStore();
    expect(await reader.readAccessToken(), isNull);

    await writer.writeAccessToken('t-1');
    expect(
      await reader.readAccessToken(),
      't-1',
      reason: '登录写入必须对共享 Dio 的读取实例立刻可见，否则登录后全量 401',
    );

    await writer.clearCredentials();
    expect(
      await reader.readAccessToken(),
      isNull,
      reason: '清凭据后其它实例也不得再回旧令牌',
    );
  });

  test('test_memory_cache_only_active_not_forgotten', () async {
    final db = AppCacheDb(NativeDatabase.memory());
    await db.into(db.memoryItems).insertOnConflictUpdate(
          MemoryItemsCompanion.insert(
            id: 'a',
            kind: 'preference',
            label: '旅行',
            content: '喜欢海边',
            active: const Value(true),
            forgotten: const Value(false),
            cachedAt: DateTime.now(),
          ),
        );
    await db.into(db.memoryItems).insertOnConflictUpdate(
          MemoryItemsCompanion.insert(
            id: 'b',
            kind: 'preference',
            label: '旧',
            content: 'x',
            active: const Value(true),
            forgotten: const Value(true),
            cachedAt: DateTime.now(),
          ),
        );
    final rows = await db.activeMemories();
    expect(rows.length, 1);
    expect(rows.single.id, 'a');
    await db.close();
  });

  test('test_cache_tables_have_timestamps', () {
    final src = File('lib/core/storage/cache_db.dart').readAsStringSync();
    expect('cachedAt'.allMatches(src).length, greaterThanOrEqualTo(5));
  });

  test('test_prefs_no_feature_flags_no_money', () {
    final src = File('lib/core/storage/prefs_store.dart').readAsStringSync();
    expect(src.contains('_enabled'), isFalse);
    expect(src.contains('amount'), isFalse);
  });

  test('test_retry_store_persists_pending', () async {
    final db = AppCacheDb(NativeDatabase.memory());
    final retry = DriftRetryStore(db);
    await retry.enqueue(
      id: 'r1',
      kind: 'ledger.create',
      endpoint: '/ledger/entries',
      payloadJson: '{}',
      errorKind: 'timeout',
    );
    final pending = await retry.pending();
    expect(pending.length, 1);
    await retry.mark('r1', 'failed');
    expect((await retry.pending()).single.status, 'failed');
    await db.close();
  });

  test('test_wipe_clears_caches', () async {
    final db = AppCacheDb(NativeDatabase.memory());
    await db.into(db.homeSummaries).insertOnConflictUpdate(
          HomeSummariesCompanion.insert(
            id: 'h',
            payloadJson: '{}',
            cachedAt: DateTime.now(),
          ),
        );
    await db.wipeAllCaches();
    expect(await db.select(db.homeSummaries).get(), isEmpty);
    await db.close();
  });

  /// v1 库（无 brief_contents）打开时走 onUpgrade 1→2：v2 新表建出来、
  /// v1 老数据原样保留。createAll 时代的空壳迁移会在这里崩（no such column）。
  test('test_upgrade_v1_to_v2_creates_brief_contents_and_keeps_data',
      () async {
    final db = AppCacheDb(NativeDatabase.memory(setup: (raw) {
      raw.execute(
          'CREATE TABLE session_messages (conversation_id TEXT NOT NULL, message_id TEXT NOT NULL, role TEXT NOT NULL, content TEXT NOT NULL, event_time INTEGER NOT NULL, cached_at INTEGER NOT NULL, PRIMARY KEY (conversation_id, message_id))');
      raw.execute(
          'CREATE TABLE memory_items (id TEXT NOT NULL PRIMARY KEY, kind TEXT NOT NULL, label TEXT NOT NULL, content TEXT NOT NULL, source_summary TEXT NULL, last_updated INTEGER NULL, usage_receipts_json TEXT NULL, active INTEGER NOT NULL DEFAULT 1, forgotten INTEGER NOT NULL DEFAULT 0, cached_at INTEGER NOT NULL)');
      raw.execute(
          "INSERT INTO memory_items (id, kind, label, content, active, forgotten, cached_at) VALUES ('m1', 'preference', '旅行', '喜欢海边', 1, 0, 1700000000)");
      raw.execute(
          'CREATE TABLE ledger_summaries (id TEXT NOT NULL PRIMARY KEY, payload_json TEXT NOT NULL, formatted_amount TEXT NULL, cached_at INTEGER NOT NULL)');
      raw.execute(
          'CREATE TABLE ledger_entries (id TEXT NOT NULL PRIMARY KEY, title TEXT NOT NULL, formatted_amount TEXT NOT NULL, source TEXT NULL, event_time INTEGER NULL, cached_at INTEGER NOT NULL)');
      raw.execute(
          "INSERT INTO ledger_entries (id, title, formatted_amount, cached_at) VALUES ('e1', '拉面', '35.00', 1700000000)");
      raw.execute(
          'CREATE TABLE home_summaries (id TEXT NOT NULL PRIMARY KEY, payload_json TEXT NOT NULL, cached_at INTEGER NOT NULL)');
      raw.execute(
          'CREATE TABLE retry_ops (id TEXT NOT NULL PRIMARY KEY, kind TEXT NOT NULL, endpoint TEXT NOT NULL, payload_json TEXT NULL, status TEXT NOT NULL, error_kind TEXT NULL, failed_at INTEGER NOT NULL)');
      raw.execute('PRAGMA user_version = 1');
    }));
    final memories = await db.activeMemories();
    expect(memories.single.id, 'm1');
    final entries = await db.select(db.ledgerEntries).get();
    expect(entries.single.title, '拉面');
    await db.into(db.briefContents).insertOnConflictUpdate(
          BriefContentsCompanion.insert(
            id: 'morning',
            payloadJson: '{}',
            cachedAt: DateTime.now(),
          ),
        );
    expect(
      (await db.select(db.briefContents).get()).single.id,
      'morning',
    );
    await db.close();
  });

  test('test_secure_token_store_keys_centralized', () {
    final src = File('lib/core/storage/secure_token_store.dart').readAsStringSync();
    expect(src.contains('zhaoxi.access_token'), isTrue);
    expect(src.contains('zhaoxi.device_id'), isTrue);
  });

  test('test_prefs_keys_centralized', () {
    // 12 = 既有 9 项 + 更新域 3 项（last_check_at / ignored_version_code / wifi_only）
    expect(PrefsStore.allKeys.length, 12);
    expect(PrefsStore.allKeys.toSet().length, 12);
    expect(
      PrefsStore.allKeys.where((key) => key.startsWith('update.')).toSet(),
      {
        PrefsStore.keyUpdateLastCheckAt,
        PrefsStore.keyUpdateIgnoredVersionCode,
        PrefsStore.keyUpdateWifiOnly,
      },
    );
  });
}
