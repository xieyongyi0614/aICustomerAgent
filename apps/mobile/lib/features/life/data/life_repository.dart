import 'package:dio/dio.dart';

import '../../../core/network/dio_client.dart';

class LifeTaskItem {
  const LifeTaskItem({
    required this.id,
    required this.title,
    required this.kind,
    required this.status,
    this.orderReason,
    this.tag,
    this.note,
    this.remindAt,
    this.dueDate,
    this.completedAt,
  });

  final String id;
  final String title;

  /// `memo`（备忘录）或 `task`（日程待办）；API-005 契约。
  final String kind;
  final String status;
  final String? orderReason;
  final String? tag;
  final String? note;

  /// ISO 时间串；`null` = 未设提醒。
  final String? remindAt;

  /// `yyyy-MM-dd`；`null` = 未定日期。
  final String? dueDate;

  /// ISO 时间串；`null` = 未完成（DA-19 完成态数据源）。
  final String? completedAt;

  static LifeTaskItem fromRow(Map row) => LifeTaskItem(
    id: row['id'] as String? ?? '',
    title: row['title'] as String? ?? '',
    kind: row['kind'] as String? ?? 'task',
    status: row['status'] as String? ?? '',
    orderReason: row['order_reason'] as String?,
    tag: row['tag'] as String?,
    note: row['note'] as String?,
    remindAt: row['remind_at'] as String?,
    dueDate: row['due_date'] as String?,
    completedAt: row['completed_at'] as String?,
  );

  DateTime? get remindDateTime =>
      remindAt == null ? null : DateTime.tryParse(remindAt!);

  DateTime? get dueDateTime {
    final raw = dueDate;
    return raw == null ? null : DateTime.tryParse(raw);
  }

  DateTime? get completedDateTime =>
      completedAt == null ? null : DateTime.tryParse(completedAt!);
}

/// life 域自有数据面：任务域 CRUD + 账本月度摘要。
/// 独立直连后端，避免跨 feature 依赖（L1 分层守卫）。
class LifeRepository {
  LifeRepository({Dio? dio}) : _dio = dio ?? createDio();

  final Dio _dio;

  Future<List<LifeTaskItem>> listOpenTasks() async {
    return listTasks(status: 'open');
  }

  /// `status`：`open`（默认）/ `done` / `all`（open + done，不含软删 cancelled）。
  Future<List<LifeTaskItem>> listTasks({String status = 'open'}) async {
    final resp = await _dio.get<List<dynamic>>(
      '/tasks',
      queryParameters: {'status': status},
    );
    final rows = resp.data ?? const [];
    return [
      for (final row in rows)
        if (row is Map) LifeTaskItem.fromRow(row),
    ];
  }

  Future<LifeTaskItem> createTask({
    required String title,
    String kind = 'task',
  }) async {
    final resp = await _dio.post<Map<String, dynamic>>(
      '/tasks',
      data: {'title': title, 'kind': kind},
    );
    return LifeTaskItem.fromRow(resp.data ?? const {});
  }

  Future<void> deleteTask(String id) async {
    await _dio.delete<void>('/tasks/$id');
  }

  Future<void> completeTask(String id) async {
    await _dio.post<void>('/tasks/$id/complete');
  }

  Future<String> monthExpenseText() async {
    final resp = await _dio.get<Map<String, dynamic>>(
      '/ledger/summary',
      queryParameters: {'period': 'month'},
    );
    final data = resp.data ?? const {};
    return data['expense_text'] as String? ?? '0.00';
  }

  Future<LifeCarSummary> monthCarExpense() async {
    final resp = await _dio.get<Map<String, dynamic>>('/car/overview');
    final minor = resp.data?['expense_total_minor'] as int? ?? 0;
    return LifeCarSummary(
      text: (minor / 100).toStringAsFixed(0),
      isEmpty: minor <= 0,
    );
  }
}

/// 养车支出摘要：`isEmpty` 为真时卡片要说实话，不显示 `¥0`。
class LifeCarSummary {
  const LifeCarSummary({required this.text, required this.isEmpty});

  final String text;
  final bool isEmpty;
}
