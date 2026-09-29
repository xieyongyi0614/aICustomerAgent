import 'package:dio/dio.dart';

import '../../../core/network/dio_client.dart';

class LifeTaskItem {
  const LifeTaskItem({
    required this.id,
    required this.title,
    required this.kind,
    required this.status,
    this.orderReason,
  });

  final String id;
  final String title;
  final String kind;
  final String status;
  final String? orderReason;
}

/// life 域自有数据面：任务域 CRUD + 账本月度摘要。
/// 独立直连后端，避免跨 feature 依赖（L1 分层守卫）。
class LifeRepository {
  LifeRepository({Dio? dio}) : _dio = dio ?? createDio();

  final Dio _dio;

  Future<List<LifeTaskItem>> listOpenTasks() async {
    final resp = await _dio.get<List<dynamic>>('/tasks');
    final rows = resp.data ?? const [];
    return [
      for (final row in rows)
        if (row is Map)
          LifeTaskItem(
            id: row['id'] as String? ?? '',
            title: row['title'] as String? ?? '',
            kind: row['kind'] as String? ?? 'task',
            status: row['status'] as String? ?? '',
            orderReason: row['order_reason'] as String?,
          ),
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
    final row = resp.data ?? const {};
    return LifeTaskItem(
      id: row['id'] as String? ?? '',
      title: row['title'] as String? ?? title,
      kind: row['kind'] as String? ?? kind,
      status: row['status'] as String? ?? '',
      orderReason: row['order_reason'] as String?,
    );
  }

  Future<void> deleteTask(String id) async {
    await _dio.delete<void>('/tasks/$id');
  }

  Future<String> monthExpenseText() async {
    final resp = await _dio.get<Map<String, dynamic>>(
      '/ledger/summary',
      queryParameters: {'period': 'month'},
    );
    final data = resp.data ?? const {};
    return data['expense_text'] as String? ?? '0.00';
  }
}
