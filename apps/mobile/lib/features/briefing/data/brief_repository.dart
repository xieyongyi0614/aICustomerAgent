import 'package:dio/dio.dart';

import '../../../core/network/dio_client.dart';

class BriefCardData {
  const BriefCardData({required this.title, required this.body, this.note});

  final String title;
  final String body;
  final String? note;
}

class BriefContentData {
  const BriefContentData({
    required this.form,
    required this.eyebrow,
    required this.headline,
    required this.orbLine,
    required this.cards,
    required this.footer,
  });

  final String form;
  final String eyebrow;
  final String headline;
  final String orbLine;
  final List<BriefCardData> cards;
  final String footer;
}

class BriefPrefsData {
  const BriefPrefsData({this.morningAt, this.eveningAt});

  final String? morningAt;
  final String? eveningAt;
}

/// API-008 简报读写。
class BriefRepository {
  BriefRepository({Dio? dio}) : _dio = dio ?? createDio();

  final Dio _dio;

  Future<BriefContentData> fetchBrief(String form) async {
    final resp = await _dio.get<Map<String, dynamic>>('/brief/$form');
    final data = resp.data ?? const {};
    return BriefContentData(
      form: data['form'] as String? ?? form,
      eyebrow: data['eyebrow'] as String? ?? '',
      headline: data['headline'] as String? ?? '',
      orbLine: data['orb_line'] as String? ?? '',
      cards: [
        for (final c in (data['cards'] as List?) ?? const [])
          BriefCardData(
            title: (c as Map)['title'] as String? ?? '',
            body: c['body'] as String? ?? '',
            note: c['note'] as String?,
          ),
      ],
      footer: data['footer'] as String? ?? '',
    );
  }

  Future<BriefPrefsData> fetchPrefs() async {
    final resp = await _dio.get<Map<String, dynamic>>('/brief/prefs/me');
    final data = resp.data ?? const {};
    return BriefPrefsData(
      morningAt: data['morning_at'] as String?,
      eveningAt: data['evening_at'] as String?,
    );
  }

  Future<BriefPrefsData> savePrefs({
    String? morningAt,
    String? eveningAt,
  }) async {
    final resp = await _dio.put<Map<String, dynamic>>(
      '/brief/prefs/me',
      data: {'morning_at': morningAt, 'evening_at': eveningAt},
    );
    final data = resp.data ?? const {};
    return BriefPrefsData(
      morningAt: data['morning_at'] as String?,
      eveningAt: data['evening_at'] as String?,
    );
  }
}
