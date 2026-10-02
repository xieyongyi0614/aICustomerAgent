import 'package:dio/dio.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:mobile/app/theme/app_theme.dart';
import 'package:mobile/design_system/components/components.dart';
import 'package:mobile/features/health/data/health_repository.dart';
import 'package:mobile/features/health/presentation/health_page.dart';

class _FakeHealthRepository extends HealthRepository {
  _FakeHealthRepository({this.score, this.fails = false}) : super(dio: Dio());

  final HealthScoreData? score;
  final bool fails;

  @override
  Future<HealthScoreData> fetchScore() async {
    if (fails) throw Exception('health down');
    return score ?? const HealthScoreData(authorized: false);
  }
}

void _useTallSurface(WidgetTester tester) {
  tester.view.physicalSize = const Size(390, 1400);
  tester.view.devicePixelRatio = 1;
  addTearDown(tester.view.reset);
}

Future<void> _pump(WidgetTester tester, HealthRepository repo) async {
  _useTallSurface(tester);
  await tester.pumpWidget(
    MaterialApp(theme: buildAppTheme(), home: HealthPage(repository: repo)),
  );
  await tester.pump();
  await tester.pump(const Duration(milliseconds: 50));
}

void main() {
  testWidgets('test_health_page_empty_state_is_honest_when_unauthorized',
      (tester) async {
    await _pump(tester, _FakeHealthRepository());

    expect(find.text('健康'), findsOneWidget);
    expect(find.text('不是数据，是亚丝娜对你的理解'), findsOneWidget);
    expect(find.text('还没有可解读的数据'), findsOneWidget);
    expect(
      find.textContaining('连接手环并授权后'),
      findsOneWidget,
      reason: '未授权时只讲「有数据后会怎样」，不出任何数值',
    );
    expect(find.textContaining('综合'), findsNothing, reason: '不得编造评分');
    expect(find.byType(SourceNote), findsNothing);
    expect(find.text(HealthPage.disclaimer), findsOneWidget);
  });

  testWidgets('test_health_page_renders_insight_when_authorized',
      (tester) async {
    await _pump(
      tester,
      _FakeHealthRepository(
        score: const HealthScoreData(
          authorized: true,
          score: 86,
          narrative: '睡眠时长回到 7 小时以上，静息心率平稳。',
        ),
      ),
    );

    expect(find.text('亚丝娜的解读'), findsOneWidget);
    expect(find.text('综合 86 分'), findsOneWidget);
    expect(find.text('睡眠时长回到 7 小时以上，静息心率平稳。'), findsOneWidget);
    expect(find.byType(SourceNote), findsOneWidget);
  });

  testWidgets('test_health_page_ai_block_precedes_raw_sections',
      (tester) async {
    await _pump(tester, _FakeHealthRepository());

    double topOf(Finder finder) => tester.getTopLeft(finder).dy;
    expect(
      topOf(find.byType(InsightHero)),
      lessThan(topOf(find.text('睡眠趋势'))),
      reason: '红线 4：AI 结论块必须排在原始数据之前',
    );
    expect(
      topOf(find.text('睡眠趋势')),
      lessThan(topOf(find.text('今日指标'))),
    );
  });

  testWidgets('test_health_page_degrades_to_empty_on_failure', (tester) async {
    await _pump(tester, _FakeHealthRepository(fails: true));

    expect(find.text('还没有可解读的数据'), findsOneWidget);
    expect(find.text(HealthPage.disclaimer), findsOneWidget);
    expect(tester.takeException(), isNull);
  });

  testWidgets('test_health_page_uses_server_disclaimer_when_provided',
      (tester) async {
    await _pump(
      tester,
      _FakeHealthRepository(
        score: const HealthScoreData(
          authorized: false,
          disclaimer: '非医疗建议，请咨询医生（服务端）',
        ),
      ),
    );

    expect(find.text('非医疗建议，请咨询医生（服务端）'), findsOneWidget);
  });
}
