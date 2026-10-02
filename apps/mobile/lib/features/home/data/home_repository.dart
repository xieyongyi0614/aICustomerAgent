import 'package:dio/dio.dart';

import '../../../core/network/dio_client.dart';

class HomeTaskItem {
  const HomeTaskItem({
    required this.id,
    required this.title,
    this.tag,
    this.done = false,
    this.subtitle,
  });

  final String id;
  final String title;
  final String? tag;
  final bool done;
  final String? subtitle;
}

class HomeSpend {
  const HomeSpend({
    required this.amountLabel,
    required this.budgetLabel,
    required this.progress,
    required this.conclusion,
  });

  final String amountLabel;
  final String budgetLabel;
  final double progress;
  final String conclusion;
}

class HomeHealthMetric {
  const HomeHealthMetric({
    required this.label,
    required this.value,
    this.unit,
    this.note,
  });

  final String label;
  final String value;
  final String? unit;
  final String? note;
}

class HomeSummaryData {
  const HomeSummaryData({
    required this.dateLabel,
    required this.greeting,
    required this.headline,
    required this.sub,
    required this.modeChip,
    required this.insightTitle,
    required this.insightNarrative,
    this.insightAction,
    required this.healthAuthorized,
    this.healthEmptyHint,
    this.healthSource,
    this.healthMetrics = const <HomeHealthMetric>[],
    required this.tasks,
    required this.tasksHint,
    this.spend,
  });

  final String dateLabel;
  final String greeting;
  final String headline;
  final String sub;
  final String modeChip;
  final String insightTitle;
  final String insightNarrative;
  final String? insightAction;
  final bool healthAuthorized;
  final String? healthEmptyHint;

  /// 设备名（如「小米手环 9 Pro」）；后端未接入时缺省，端上不得编造。
  final String? healthSource;
  final List<HomeHealthMetric> healthMetrics;
  final List<HomeTaskItem> tasks;
  final String tasksHint;
  final HomeSpend? spend;
}

/// APP-014：GET /home/summary 单请求聚合。
class HomeRepository {
  HomeRepository({Dio? dio}) : _dio = dio ?? createDio();

  final Dio _dio;

  Future<HomeSummaryData> fetchSummary() async {
    final resp = await _dio.get<Map<String, dynamic>>('/home/summary');
    final data = resp.data ?? const {};
    final greeting = data['greeting'] as Map? ?? const {};
    final hero = data['hero'] as Map? ?? const {};
    final insight = data['insight'] as Map? ?? const {};
    final health = data['health'] as Map? ?? const {};
    final spend = data['spend'] as Map?;
    final tasksRaw = (data['tasks'] as List?) ?? const [];
    return HomeSummaryData(
      dateLabel: greeting['date_label'] as String? ?? '今天',
      greeting: greeting['greeting'] as String? ?? '你好',
      headline: hero['headline'] as String? ?? '今天也交给我吧',
      sub: hero['sub'] as String? ?? '',
      modeChip: hero['mode_chip'] as String? ?? '',
      insightTitle: insight['title'] as String? ?? '今日 AI 总结',
      insightNarrative: insight['narrative'] as String? ?? '',
      insightAction: insight['action_label'] as String?,
      healthAuthorized: health['authorized'] as bool? ?? false,
      healthEmptyHint: health['empty_hint'] as String?,
      healthSource: health['source'] as String?,
      healthMetrics: [
        for (final cell in (health['cells'] as List?) ?? const [])
          if (cell is Map)
            HomeHealthMetric(
              label: cell['label'] as String? ?? '',
              value: cell['value'] as String? ?? '',
              unit: cell['unit'] as String?,
              note: cell['note'] as String?,
            ),
      ],
      tasks: [
        for (final t in tasksRaw)
          HomeTaskItem(
            id: (t as Map)['id'] as String? ?? '',
            title: t['title'] as String? ?? '',
            tag: t['tag'] as String?,
            done: t['done'] as bool? ?? false,
            subtitle: t['order_reason'] as String?,
          ),
      ],
      tasksHint: data['tasks_hint'] as String? ?? '',
      spend: spend == null
          ? null
          : HomeSpend(
              amountLabel: spend['amount_label'] as String? ?? '¥0',
              budgetLabel: spend['budget_label'] as String? ?? '',
              progress: (spend['progress'] as num?)?.toDouble() ?? 0,
              conclusion: spend['conclusion'] as String? ?? '',
            ),
    );
  }
}
