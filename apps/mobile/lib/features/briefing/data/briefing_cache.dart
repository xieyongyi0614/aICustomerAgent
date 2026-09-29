import 'dart:convert';

import '../../../core/storage/cache_db.dart';
import 'briefing_repository.dart';

/// [BriefCacheStore] 的 drift 只读缓存适配（表 `brief_contents`）。
///
/// 随工程存储门面（`LocalStores`）接线时注入 `BriefingRepository(cache: ...)`；
/// 接线前简报页以无缓存模式运行，行为与既有各页一致。
class DriftBriefCache implements BriefCacheStore {
  DriftBriefCache(this._db);

  final AppCacheDb _db;

  @override
  Future<({Map<String, dynamic> payload, DateTime cachedAt})?> load(
    String type,
  ) async {
    final row = await (_db.select(_db.briefContents)
          ..where((t) => t.id.equals(type)))
        .getSingleOrNull();
    if (row == null) return null;
    final payload = jsonDecode(row.payloadJson);
    if (payload is! Map<String, dynamic>) return null;
    return (payload: payload, cachedAt: row.cachedAt);
  }

  @override
  Future<void> save(String type, Map<String, dynamic> payload) async {
    await _db.into(_db.briefContents).insertOnConflictUpdate(
          BriefContentsCompanion.insert(
            id: type,
            payloadJson: jsonEncode(payload),
            cachedAt: DateTime.now(),
          ),
        );
  }
}
