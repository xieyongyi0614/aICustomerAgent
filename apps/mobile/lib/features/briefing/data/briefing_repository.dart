import 'package:dio/dio.dart';

import '../../../core/network/dio_client.dart';

class BriefCardData {
  const BriefCardData({required this.title, required this.body, this.note});

  final String title;
  final String body;
  final String? note;
}

/// API-008 简报响应（APP-018 §4.4 契约字段），端上只渲染不拼装。
class BriefContentData {
  const BriefContentData({
    required this.type,
    required this.greeting,
    required this.title,
    required this.orbNote,
    required this.cards,
    required this.cta,
    this.generatedAt,
  });

  final String type; // morning | evening
  final String greeting; // 如「08:00 · 早间简报」
  final String title;
  final String orbNote;
  final List<BriefCardData> cards;
  final String cta;
  final String? generatedAt;

  factory BriefContentData.fromApi(Map<String, dynamic> data) {
    return BriefContentData(
      type: data['type'] as String? ?? 'morning',
      greeting: data['greeting'] as String? ?? '',
      title: data['title'] as String? ?? '',
      orbNote: data['orb_note'] as String? ?? '',
      cards: [
        for (final c in (data['cards'] as List?) ?? const [])
          BriefCardData(
            title: (c as Map)['title'] as String? ?? '',
            body: c['body'] as String? ?? '',
            note: c['note'] as String?,
          ),
      ],
      cta: data['cta'] as String? ?? '',
      generatedAt: data['generated_at'] as String?,
    );
  }
}

class BriefPrefsData {
  const BriefPrefsData({this.morningAt, this.eveningAt, this.city});

  final String? morningAt;
  final String? eveningAt;
  final String? city;
}

/// 简报只读缓存端口（D9）：进页先渲染缓存，再拉接口刷新。
///
/// 实现见 `briefing_cache.dart`（drift 适配，随存储门面注入）；未注入时
/// 缓存停用——只读命中为空、写入静默跳过，渲染不受影响。
abstract interface class BriefCacheStore {
  Future<({Map<String, dynamic> payload, DateTime cachedAt})?> load(String type);

  Future<void> save(String type, Map<String, dynamic> payload);
}

/// API-008 简报读写。
class BriefingRepository {
  BriefingRepository({Dio? dio, this.cache})
      : _dio = dio ?? createDio();

  final Dio _dio;

  /// 只读缓存端口；未注入时缓存停用（见 [BriefCacheStore]）。
  final BriefCacheStore? cache;

  Future<BriefContentData?> cachedBrief(String type) async {
    final cached = await cache?.load(type);
    final payload = cached?.payload;
    if (payload == null) return null;
    return BriefContentData.fromApi(payload);
  }

  Future<BriefContentData> fetchBrief(
    String type, {
    double? lat,
    double? lon,
  }) async {
    final resp = await _dio.get<Map<String, dynamic>>(
      '/briefing',
      queryParameters: {
        'type': type,
        'lat': ?lat,
        'lon': ?lon,
      },
    );
    final data = resp.data ?? const <String, dynamic>{};
    final content = BriefContentData.fromApi(data);
    try {
      await cache?.save(type, data);
    } catch (_) {
      // 缓存写失败不影响本次渲染
    }
    return content;
  }

  Future<BriefPrefsData> fetchPrefs() async {
    final resp = await _dio.get<Map<String, dynamic>>('/briefing/preferences');
    final data = resp.data ?? const {};
    return BriefPrefsData(
      morningAt: data['morning_at'] as String?,
      eveningAt: data['evening_at'] as String?,
      city: data['city'] as String?,
    );
  }

  Future<BriefPrefsData> savePrefs({
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
    return BriefPrefsData(
      morningAt: data['morning_at'] as String?,
      eveningAt: data['evening_at'] as String?,
      city: data['city'] as String?,
    );
  }
}
