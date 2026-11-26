import 'package:drift/drift.dart';

import 'cache_db.dart';

/// 重试队列持久化：只记录与状态流转，V1 不自动重放、不做本地先行写。
class DriftRetryStore {
  DriftRetryStore(this._db);

  final AppCacheDb _db;

  Future<void> enqueue({
    required String id,
    required String kind,
    required String endpoint,
    String? payloadJson,
    String? errorKind,
  }) {
    return _db.into(_db.retryOps).insertOnConflictUpdate(
          RetryOpsCompanion.insert(
            id: id,
            kind: kind,
            endpoint: endpoint,
            payloadJson: Value(payloadJson),
            status: 'pending',
            errorKind: Value(errorKind),
            failedAt: DateTime.now(),
          ),
        );
  }

  Future<void> mark(String id, String status) {
    return (_db.update(_db.retryOps)..where((t) => t.id.equals(id)))
        .write(RetryOpsCompanion(status: Value(status)));
  }

  Future<List<RetryOp>> pending() => (_db.select(_db.retryOps)
        ..where((t) => t.status.isIn(['pending', 'failed'])))
      .get();

  Future<void> clear() => _db.delete(_db.retryOps).go();
}
