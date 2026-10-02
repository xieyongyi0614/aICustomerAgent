import 'package:dio/dio.dart';

import '../../../core/network/dio_client.dart';

/// `/health/score` 读面。健康域当前是 M4 门控空读面：`authorized` 恒为 false、
/// `score` 为空，端上必须据此走诚实空态，**不得**编造评分或指标（红线 8）。
class HealthScoreData {
  const HealthScoreData({
    required this.authorized,
    this.score,
    this.narrative,
    this.disclaimer,
  });

  final bool authorized;
  final int? score;
  final String? narrative;
  final String? disclaimer;

  bool get hasInsight =>
      authorized && score != null && (narrative ?? '').isNotEmpty;
}

class HealthRepository {
  HealthRepository({Dio? dio}) : _dio = dio ?? createDio();

  final Dio _dio;

  Future<HealthScoreData> fetchScore() async {
    final resp = await _dio.get<Map<String, dynamic>>('/health/score');
    final data = resp.data ?? const {};
    return HealthScoreData(
      authorized: data['authorized'] as bool? ?? false,
      score: (data['score'] as num?)?.toInt(),
      narrative: data['narrative'] as String?,
      disclaimer: data['disclaimer'] as String?,
    );
  }
}
