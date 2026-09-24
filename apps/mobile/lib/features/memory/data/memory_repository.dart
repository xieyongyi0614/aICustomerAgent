import 'package:dio/dio.dart';

import '../../../core/network/dio_client.dart';

class MemoryItemData {
  const MemoryItemData({
    required this.id,
    required this.kind,
    required this.label,
    required this.content,
    this.sourceKind,
    this.sourceCount,
    this.lastUpdated,
    this.usageReceipts = const [],
  });

  final String id;
  final String kind;
  final String label;
  final String content;
  final String? sourceKind;
  final int? sourceCount;
  final String? lastUpdated;
  final List<String> usageReceipts;
}

/// API-007 产品级记忆读写。
class MemoryRepository {
  MemoryRepository({Dio? dio}) : _dio = dio ?? createDio();

  final Dio _dio;

  Future<List<MemoryItemData>> listItems({int limit = 50}) async {
    final resp = await _dio.get<List<dynamic>>(
      '/memory/items',
      queryParameters: {'limit': limit},
    );
    return [
      for (final raw in resp.data ?? const [])
        MemoryItemData(
          id: (raw as Map)['id'] as String? ?? '',
          kind: raw['kind'] as String? ?? '',
          label: raw['label'] as String? ?? '',
          content: raw['content'] as String? ?? '',
          sourceKind: raw['source_kind'] as String?,
          sourceCount: raw['source_count'] as int?,
          lastUpdated: raw['last_updated'] as String?,
          usageReceipts: [
            for (final u in (raw['usage_receipts'] as List?) ?? const [])
              u.toString(),
          ],
        ),
    ];
  }

  Future<void> forget(String id) => _dio.post('/memory/items/$id/forget');

  Future<void> updateContent(String id, String content) =>
      _dio.patch('/memory/items/$id', data: {'content': content});
}
