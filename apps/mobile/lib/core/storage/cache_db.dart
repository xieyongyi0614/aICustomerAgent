import 'package:drift/drift.dart';

part 'cache_db.drift.dart';

/// 只读缓存表：字段全部为服务端 DTO 投影，禁止本地推导。
/// 每表必带 cachedAt 数据时间戳。

class SessionMessages extends Table {
  TextColumn get conversationId => text()();
  TextColumn get messageId => text()();
  TextColumn get role => text()();
  TextColumn get content => text()();
  DateTimeColumn get eventTime => dateTime()();
  DateTimeColumn get cachedAt => dateTime()();

  @override
  Set<Column> get primaryKey => {conversationId, messageId};
}

class MemoryItems extends Table {
  TextColumn get id => text()();
  TextColumn get kind => text()();
  TextColumn get label => text()();
  TextColumn get content => text()();
  TextColumn get sourceSummary => text().nullable()();
  DateTimeColumn get lastUpdated => dateTime().nullable()();
  TextColumn get usageReceiptsJson => text().nullable()();
  BoolColumn get active => boolean().withDefault(const Constant(true))();
  BoolColumn get forgotten => boolean().withDefault(const Constant(false))();
  DateTimeColumn get cachedAt => dateTime()();

  @override
  Set<Column> get primaryKey => {id};
}

class LedgerSummaries extends Table {
  TextColumn get id => text()();
  TextColumn get payloadJson => text()();
  TextColumn get formattedAmount => text().nullable()();
  DateTimeColumn get cachedAt => dateTime()();

  @override
  Set<Column> get primaryKey => {id};
}

class LedgerEntries extends Table {
  TextColumn get id => text()();
  TextColumn get title => text()();
  TextColumn get formattedAmount => text()();
  TextColumn get source => text().nullable()();
  DateTimeColumn get eventTime => dateTime().nullable()();
  DateTimeColumn get cachedAt => dateTime()();

  @override
  Set<Column> get primaryKey => {id};
}

class HomeSummaries extends Table {
  TextColumn get id => text()();
  TextColumn get payloadJson => text()();
  DateTimeColumn get cachedAt => dateTime()();

  @override
  Set<Column> get primaryKey => {id};
}

class RetryOps extends Table {
  TextColumn get id => text()();
  TextColumn get kind => text()();
  TextColumn get endpoint => text()();
  TextColumn get payloadJson => text().nullable()();
  TextColumn get status => text()();
  TextColumn get errorKind => text().nullable()();
  DateTimeColumn get failedAt => dateTime()();

  @override
  Set<Column> get primaryKey => {id};
}

@DriftDatabase(tables: [
  SessionMessages,
  MemoryItems,
  LedgerSummaries,
  LedgerEntries,
  HomeSummaries,
  RetryOps,
])
class AppCacheDb extends _$AppCacheDb {
  AppCacheDb(super.e);

  @override
  int get schemaVersion => 1;

  @override
  MigrationStrategy get migration => MigrationStrategy(
        beforeOpen: (details) async {
          await customStatement('PRAGMA foreign_keys = ON');
        },
      );

  Future<void> wipeAllCaches() async {
    await delete(sessionMessages).go();
    await delete(memoryItems).go();
    await delete(ledgerSummaries).go();
    await delete(ledgerEntries).go();
    await delete(homeSummaries).go();
  }

  /// 记忆缓存只含 active 且未 forgotten（决策 D5）
  Future<List<MemoryItem>> activeMemories() =>
      (select(memoryItems)
            ..where((t) => t.active.equals(true) & t.forgotten.equals(false)))
          .get();

  Future<void> replaceMemories(List<MemoryItemsCompanion> rows) async {
    await transaction(() async {
      await delete(memoryItems).go();
      await batch((b) => b.insertAll(memoryItems, rows));
    });
  }
}
