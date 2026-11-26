import 'package:dio/dio.dart';

import '../../../core/network/dio_client.dart';

/// B8 「记忆管理」副文案条数的数据面：只取 /memory/items 的 total，不拉明细。
class MemoryCountRepository {
  MemoryCountRepository({Dio? dio}) : _dio = dio ?? createDio();

  final Dio _dio;

  Future<int> fetchTotal() async {
    final resp = await _dio.get<Map<String, dynamic>>(
      '/memory/items',
      queryParameters: {'limit': 1},
    );
    return (resp.data ?? const {})['total'] as int? ?? 0;
  }
}
