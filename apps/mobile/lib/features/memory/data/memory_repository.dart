import 'package:dio/dio.dart';

import '../../../core/network/dio_client.dart';

class MemoryReceiptData {
  const MemoryReceiptData({
    required this.kind,
    required this.label,
    this.ts,
    this.ref,
  });

  final String kind;
  final String label;
  final String? ts;
  final String? ref;
}

class MemoryItemData {
  const MemoryItemData({
    required this.id,
    required this.kind,
    required this.type,
    required this.typeLabel,
    required this.content,
    required this.sourceKind,
    required this.sourceLabel,
    required this.sourceCount,
    this.lastUpdated,
    this.usageReceipts = const [],
  });

  final String id;
  final String kind;
  final String type;
  final String typeLabel;
  final String content;
  final String sourceKind;
  final String sourceLabel;
  final int sourceCount;
  final String? lastUpdated;
  final List<MemoryReceiptData> usageReceipts;
}

class MemoryGroupData {
  const MemoryGroupData({
    required this.kind,
    required this.label,
    required this.items,
  });

  final String kind;
  final String label;
  final List<MemoryItemData> items;
}

class MemoryItemsData {
  const MemoryItemsData({
    required this.generatedAt,
    required this.total,
    required this.addedThisWeek,
    required this.groups,
    this.degraded = false,
  });

  final String generatedAt;
  final int total;
  final int addedThisWeek;
  final List<MemoryGroupData> groups;

  /// 用途回执派生失败时为 true（列表照常可用）。
  final bool degraded;

  List<MemoryItemData> get allItems => [
        for (final group in groups) ...group.items,
      ];
}

MemoryReceiptData _receiptFrom(Map raw) => MemoryReceiptData(
      kind: raw['kind'] as String? ?? '',
      label: raw['label'] as String? ?? '',
      ts: raw['ts'] as String?,
      ref: raw['ref'] as String?,
    );

MemoryItemData _itemFrom(Map raw) => MemoryItemData(
      id: raw['id'] as String? ?? '',
      kind: raw['kind'] as String? ?? '',
      type: raw['type'] as String? ?? '',
      typeLabel: raw['type_label'] as String? ?? '',
      content: raw['content'] as String? ?? '',
      sourceKind: raw['source_kind'] as String? ?? '',
      sourceLabel: raw['source_label'] as String? ?? '',
      sourceCount: raw['source_count'] as int? ?? 1,
      lastUpdated: raw['last_updated'] as String?,
      usageReceipts: [
        for (final entry in (raw['usage_receipts'] as List?) ?? const [])
          if (entry is Map) _receiptFrom(entry),
      ],
    );

/// API-007 产品级记忆读写（分组口径；D5：只含 active 且未 forgotten）。
class MemoryRepository {
  MemoryRepository({Dio? dio}) : _dio = dio ?? createDio();

  final Dio _dio;

  Future<MemoryItemsData> listItems({int limit = 200}) async {
    final resp = await _dio.get<Map<String, dynamic>>(
      '/memory/items',
      queryParameters: {'limit': limit},
    );
    final data = resp.data ?? const {};
    return MemoryItemsData(
      generatedAt: data['generated_at'] as String? ?? '',
      total: data['total'] as int? ?? 0,
      addedThisWeek: data['added_this_week'] as int? ?? 0,
      degraded: data['degraded'] as bool? ?? false,
      groups: [
        for (final group in (data['groups'] as List?) ?? const [])
          if (group is Map)
            MemoryGroupData(
              kind: group['kind'] as String? ?? '',
              label: group['label'] as String? ?? '',
              items: [
                for (final raw in (group['items'] as List?) ?? const [])
                  if (raw is Map) _itemFrom(raw),
              ],
            ),
      ],
    );
  }

  Future<MemoryItemData> updateContent(String id, String content) async {
    final resp = await _dio.patch<Map<String, dynamic>>(
      '/memory/items/$id',
      data: {'content': content},
    );
    return _itemFrom(resp.data ?? const {});
  }

  Future<void> forget(String id) => _dio.post('/memory/items/$id/forget');
}
