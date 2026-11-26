import 'package:dio/dio.dart';

import '../../../core/network/dio_client.dart';

class ChatLedgerSummary {
  const ChatLedgerSummary({
    required this.periodLabel,
    required this.expenseText,
    required this.entryCount,
    this.comparisonLabel,
  });

  final String periodLabel;
  final String expenseText;
  final int entryCount;
  final String? comparisonLabel;
}

/// chat 域自有账本数据面：只读月度摘要。
/// 独立直连后端，避免跨 feature 依赖（L1 分层守卫）。
class ChatLedgerRepository {
  ChatLedgerRepository({Dio? dio}) : _dio = dio ?? createDio();

  final Dio _dio;

  Future<ChatLedgerSummary> fetchMonthSummary() async {
    final resp = await _dio.get<Map<String, dynamic>>(
      '/ledger/summary',
      queryParameters: {'period': 'month'},
    );
    final data = resp.data ?? const {};
    final periodMap = data['period'] as Map? ?? const {};
    final compared = data['compared_to_previous'] as Map?;
    String? comparisonLabel;
    final ratio = compared?['expense_ratio'];
    if (ratio is num) {
      final pct = ((ratio - 1) * 100).round();
      comparisonLabel = pct == 0
          ? '与上月同期持平'
          : pct < 0
              ? '比上月同期少 ${pct.abs()}%'
              : '比上月同期多 $pct%';
    }
    return ChatLedgerSummary(
      periodLabel: periodMap['label'] as String? ?? '本月',
      expenseText: data['expense_text'] as String? ?? '0.00',
      entryCount: data['entry_count'] as int? ?? 0,
      comparisonLabel: comparisonLabel,
    );
  }
}
