import 'package:dio/dio.dart';

import '../../../core/format/money.dart';
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
    this.createdAt,
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

  /// ISO 时间串；`null` = 服务端未下发（备忘行的「记录时间」）。
  final String? createdAt;

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
    createdAt: row['created_at'] as String?,
    completedAt: row['completed_at'] as String?,
  );

  /// 解析层统一转本地时区：带 Z 的 ISO 串 parse 出的是 UTC，
  /// 消费点直接取 year/month/day 会把北京时间早晨的提醒归到前一天。
  static DateTime? _parseLocal(String? raw) {
    final parsed = raw == null ? null : DateTime.tryParse(raw);
    return parsed?.toLocal();
  }

  DateTime? get remindDateTime => _parseLocal(remindAt);

  DateTime? get dueDateTime => _parseLocal(dueDate);

  DateTime? get createdDateTime => _parseLocal(createdAt);

  DateTime? get completedDateTime => _parseLocal(completedAt);
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
    final data = resp.data ?? const {};
    final minor = (data['expense_total_minor'] as num?)?.toInt() ?? 0;
    return LifeCarSummary(
      text: formatYuanWhole(minor),
      isEmpty: minor <= 0,
      restrictionDetail: _restrictionDetail(data['reminders'] as List?),
    );
  }

  /// 限行提醒的服务端原文（`下周三 · 尾号 4 和 9 · 建议地铁通勤`）：生活页只用它拼 trend，
  /// 不自己推算日期。没有限行项时返回 null，宁可不出这一行。
  String? _restrictionDetail(List? reminders) {
    for (final raw in reminders ?? const []) {
      if (raw is! Map || raw['kind'] != 'restriction') continue;
      final detail = raw['detail'] as String?;
      if (detail != null && detail.isNotEmpty) return detail;
      final title = raw['title'] as String?;
      if (title != null && title.isNotEmpty) return title;
    }
    return null;
  }
}

/// 养车支出摘要：`isEmpty` 为真时卡片要说实话，不显示 `¥0`。
class LifeCarSummary {
  const LifeCarSummary({
    required this.text,
    required this.isEmpty,
    this.restrictionDetail,
  });

  final String text;
  final bool isEmpty;
  final String? restrictionDetail;
}
