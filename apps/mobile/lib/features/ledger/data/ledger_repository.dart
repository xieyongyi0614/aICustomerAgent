import 'package:dio/dio.dart';

import '../../../core/network/dio_client.dart';

class LedgerCategoryTotal {
  const LedgerCategoryTotal({
    required this.categoryId,
    required this.expenseMinor,
    required this.incomeMinor,
  });

  final String? categoryId;
  final int expenseMinor;
  final int incomeMinor;
}

class LedgerSummaryData {
  const LedgerSummaryData({
    required this.periodLabel,
    required this.expenseText,
    required this.incomeText,
    required this.netText,
    required this.entryCount,
    required this.byCategory,
    this.comparisonLabel,
  });

  final String periodLabel;
  final String expenseText;
  final String incomeText;
  final String netText;
  final int entryCount;
  final List<LedgerCategoryTotal> byCategory;
  final String? comparisonLabel;
}

class LedgerEntryData {
  const LedgerEntryData({
    required this.id,
    required this.amountText,
    required this.direction,
    required this.occurredAt,
    this.merchant,
    this.note,
    this.categoryId,
  });

  final String id;
  final String amountText;
  final String direction;
  final String occurredAt;
  final String? merchant;
  final String? note;
  final String? categoryId;
}

class LedgerCategoryData {
  const LedgerCategoryData({
    required this.id,
    required this.name,
    required this.kind,
    this.parentId,
    this.aliases = const [],
  });

  final String id;
  final String name;
  final String kind;
  final String? parentId;
  final List<String> aliases;
}

class LedgerPreviewData {
  const LedgerPreviewData({
    required this.matched,
    required this.categoryName,
    required this.reason,
    required this.isFallback,
    this.categoryId,
  });

  final bool matched;
  final String categoryName;
  final String reason;
  final bool isFallback;
  final String? categoryId;
}

class LedgerCreateResult {
  const LedgerCreateResult({required this.id});

  final String id;
}

class LedgerRepository {
  LedgerRepository({Dio? dio}) : _dio = dio ?? createDio();

  final Dio _dio;

  Future<LedgerSummaryData> fetchSummary({String period = 'month'}) async {
    final resp = await _dio.get<Map<String, dynamic>>(
      '/ledger/summary',
      queryParameters: {'period': period},
    );
    final data = resp.data ?? const {};
    final periodMap = data['period'] as Map? ?? const {};
    final compared = data['compared_to_previous'] as Map?;
    String? comparisonLabel;
    if (compared != null) {
      final ratio = compared['expense_ratio'];
      if (ratio is num) {
        final pct = ((ratio - 1) * 100).round();
        comparisonLabel = pct == 0
            ? '与上月同期持平'
            : pct < 0
                ? '比上月同期少 ${pct.abs()}%'
                : '比上月同期多 $pct%';
      }
    }
    return LedgerSummaryData(
      periodLabel: periodMap['label'] as String? ?? period,
      expenseText: data['expense_text'] as String? ?? '0.00',
      incomeText: data['income_text'] as String? ?? '0.00',
      netText: data['net_text'] as String? ?? '0.00',
      entryCount: data['entry_count'] as int? ?? 0,
      byCategory: [
        for (final c in (data['by_category'] as List?) ?? const [])
          LedgerCategoryTotal(
            categoryId: (c as Map)['category_id'] as String?,
            expenseMinor: c['expense_minor'] as int? ?? 0,
            incomeMinor: c['income_minor'] as int? ?? 0,
          ),
      ],
      comparisonLabel: comparisonLabel,
    );
  }

  Future<List<LedgerEntryData>> fetchEntries({int limit = 20}) async {
    final resp = await _dio.get<Map<String, dynamic>>(
      '/ledger/entries',
      queryParameters: {'limit': limit},
    );
    final items = (resp.data?['items'] as List?) ?? const [];
    return [
      for (final raw in items)
        LedgerEntryData(
          id: (raw as Map)['id'] as String? ?? '',
          amountText: raw['amount_text'] as String? ?? '',
          direction: raw['direction'] as String? ?? 'expense',
          occurredAt: raw['occurred_at'] as String? ?? '',
          merchant: raw['merchant'] as String?,
          note: raw['note'] as String?,
          categoryId: raw['category_id'] as String?,
        ),
    ];
  }

  Future<List<LedgerCategoryData>> fetchCategories({String? kind}) async {
    final resp = await _dio.get<List<dynamic>>('/ledger/categories');
    final items = resp.data ?? const [];
    return [
      for (final raw in items)
        LedgerCategoryData(
          id: (raw as Map)['id'] as String? ?? '',
          name: raw['name'] as String? ?? '',
          kind: raw['kind'] as String? ?? 'expense',
          parentId: raw['parent_id'] as String?,
          aliases: [
            for (final alias in (raw['aliases'] as List?) ?? const [])
              alias as String,
          ],
        ),
    ].where((row) => kind == null || row.kind == kind).toList();
  }

  Future<LedgerPreviewData> classifyPreview(
    String note, {
    String kind = 'expense',
  }) async {
    final resp = await _dio.get<Map<String, dynamic>>(
      '/ledger/classify-preview',
      queryParameters: {'note': note, 'kind': kind},
    );
    final data = resp.data ?? const {};
    return LedgerPreviewData(
      matched: data['matched'] as bool? ?? false,
      categoryId: data['category_id'] as String?,
      categoryName: data['category_name'] as String? ?? '',
      reason: data['reason'] as String? ?? '',
      isFallback: data['is_fallback'] as bool? ?? false,
    );
  }

  Future<LedgerCreateResult> createEntry({
    required int amountMinor,
    required String direction,
    required String idempotencyKey,
    String? categoryId,
    DateTime? occurredAt,
    String? note,
  }) async {
    final resp = await _dio.post<Map<String, dynamic>>(
      '/ledger/entries',
      data: {
        'amount_minor': amountMinor,
        'direction': direction,
        'category_id': ?categoryId,
        'occurred_at': ?occurredAt?.toIso8601String(),
        if (note != null && note.isNotEmpty) 'note': note,
        'idempotency_key': idempotencyKey,
      },
    );
    final data = resp.data ?? const {};
    return LedgerCreateResult(id: data['id'] as String? ?? '');
  }
}
