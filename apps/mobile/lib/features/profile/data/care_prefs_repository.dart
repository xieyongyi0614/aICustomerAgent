import 'package:dio/dio.dart';

import '../../../core/network/dio_client.dart';

/// 主动关怀偏好（早/晚简报时刻）。后端 PUT 为整体替换语义，
/// 调用方必须先取当前值再合并提交，city 原样回传避免清空天气定位。
class CarePrefs {
  const CarePrefs({
    this.morningAt,
    this.eveningAt,
    this.city,
  });

  final String? morningAt;
  final String? eveningAt;
  final String? city;

  bool get morningOn => morningAt != null && morningAt!.isNotEmpty;
  bool get eveningOn => eveningAt != null && eveningAt!.isNotEmpty;
}

class CarePrefsRepository {
  CarePrefsRepository({Dio? dio}) : _dio = dio ?? createDio();

  final Dio _dio;

  Future<CarePrefs> fetch() async {
    final resp = await _dio.get<Map<String, dynamic>>('/briefing/preferences');
    final data = resp.data ?? const {};
    return CarePrefs(
      morningAt: data['morning_at'] as String?,
      eveningAt: data['evening_at'] as String?,
      city: data['city'] as String?,
    );
  }

  Future<CarePrefs> save({
    String? morningAt,
    String? eveningAt,
    String? city,
  }) async {
    final resp = await _dio.put<Map<String, dynamic>>(
      '/briefing/preferences',
      data: {
        'morning_at': morningAt,
        'evening_at': eveningAt,
        'city': city,
      },
    );
    final data = resp.data ?? const {};
    return CarePrefs(
      morningAt: data['morning_at'] as String?,
      eveningAt: data['evening_at'] as String?,
      city: data['city'] as String?,
    );
  }
}
