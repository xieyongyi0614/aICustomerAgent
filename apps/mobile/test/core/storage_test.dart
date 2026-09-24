import 'dart:io';

import 'package:drift/drift.dart' show Value;
import 'package:drift/native.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:mobile/core/storage/cache_db.dart';
import 'package:mobile/core/storage/prefs_store.dart';
import 'package:mobile/core/storage/retry_store.dart';

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

  test('test_secure_token_store_keys_centralized', () {
    final src = File('lib/core/storage/secure_token_store.dart').readAsStringSync();
    expect(src.contains('zhaoxi.access_token'), isTrue);
    expect(src.contains('zhaoxi.device_id'), isTrue);
  });

  test('test_prefs_keys_centralized', () {
    expect(PrefsStore.allKeys.length, 4);
    expect(PrefsStore.allKeys.toSet().length, 4);
  });
}
