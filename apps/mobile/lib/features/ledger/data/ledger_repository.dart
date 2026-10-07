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
    this.occurredLabel = '',
    this.merchant,
    this.note,
    this.categoryId,
  });

  final String id;
  final String amountText;
  final String direction;
  final String occurredAt;

  /// 服务端按**产品时区**渲染的展示文案（「今天 00:23」等）。
  /// 设备时区不可靠（模拟器默认 UTC），端上只做兜底格式化。
  final String occurredLabel;
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

class LedgerPendingCandidate {
  const LedgerPendingCandidate({required this.value, required this.label});

  final String value;
  final String label;
}

class LedgerPendingData {
  const LedgerPendingData({
    required this.pendingKey,
    required this.reason,
    required this.question,
    this.candidates = const [],
    this.amountMinor,
    this.categoryHint,
    this.direction,
    this.merchantHint,
  });

  final String pendingKey;
  final String reason;
  final String question;
  final List<LedgerPendingCandidate> candidates;
  final int? amountMinor;
  final String? categoryHint;
  final String? direction;
  final String? merchantHint;

  String get amountText => amountMinor == null
      ? ''
      : (amountMinor! / 100).toStringAsFixed(2);
}

class LedgerAutoSummaryData {
  const LedgerAutoSummaryData({
    required this.periodLabel,
    required this.autoCount,
    required this.pendingCount,
    this.accuracy,
  });

  final String periodLabel;
  final int autoCount;
  final int pendingCount;
  final double? accuracy;
}

class LedgerRuleData {
  const LedgerRuleData({
    required this.keyword,
    required this.categoryName,
    this.sourceNote,
  });

  final String keyword;
  final String categoryName;
  final String? sourceNote;
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
          occurredLabel: raw['occurred_label'] as String? ?? '',
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

  Future<LedgerAutoSummaryData> fetchAutoSummary() async {
    final resp = await _dio.get<Map<String, dynamic>>('/ledger/auto-summary');
    final data = resp.data ?? const {};
    final period = data['period'] as Map? ?? const {};
    final accuracy = data['accuracy'];
    return LedgerAutoSummaryData(
      periodLabel: period['label'] as String? ?? 'month',
      autoCount: data['auto_count'] as int? ?? 0,
      pendingCount: data['pending_count'] as int? ?? 0,
      accuracy: accuracy is num ? accuracy.toDouble() : null,
    );
  }

  Future<List<LedgerPendingData>> fetchPending() async {
    final resp = await _dio.get<Map<String, dynamic>>('/ledger/pending');
    final items = (resp.data?['items'] as List?) ?? const [];
    return [
      for (final raw in items)
        LedgerPendingData(
          pendingKey: (raw as Map)['pending_key'] as String? ?? '',
          reason: raw['reason'] as String? ?? '',
          question: raw['question'] as String? ?? '',
          amountMinor: raw['amount_minor'] as int?,
          candidates: [
            for (final option in (raw['candidates'] as List?) ?? const [])
              LedgerPendingCandidate(
                value: (option as Map)['value'] as String? ?? '',
                label: option['label'] as String? ?? '',
              ),
          ],
          categoryHint: (raw['ai_guess'] as Map?)?['category_hint'] as String?,
          direction: (raw['ai_guess'] as Map?)?['direction'] as String?,
          merchantHint: (raw['ai_guess'] as Map?)?['merchant_hint'] as String?,
        ),
    ];
  }

  Future<void> confirmPending(
    String pendingKey, {
    String? categoryName,
    String? direction,
    int? amountMinor,
  }) async {
    await _dio.post<Map<String, dynamic>>(
      '/ledger/pending/$pendingKey/confirm',
      data: {
        'category_name': ?categoryName,
        'direction': ?direction,
        'amount_minor': ?amountMinor,
      },
    );
  }

  Future<void> ignorePending(String pendingKey) async {
    await _dio.post<Map<String, dynamic>>(
      '/ledger/pending/$pendingKey/ignore',
    );
  }

  Future<List<LedgerRuleData>> fetchRules() async {
    final resp = await _dio.get<Map<String, dynamic>>('/ledger/rules');
    final items = (resp.data?['items'] as List?) ?? const [];
    return [
      for (final raw in items)
        LedgerRuleData(
          keyword: (raw as Map)['keyword'] as String? ?? '',
          categoryName: raw['category_name'] as String? ?? '',
          sourceNote: raw['learned_from'] as String?,
        ),
    ];
  }
}
