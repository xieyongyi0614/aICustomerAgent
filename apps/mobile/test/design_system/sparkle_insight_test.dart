import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:mobile/app/theme/app_theme.dart';
import 'package:mobile/design_system/components/components.dart';
import 'package:mobile/design_system/orb/orb.dart';
import 'package:mobile/design_system/tokens/tokens.dart';

Widget _wrap(Widget child) => MaterialApp(
      theme: buildAppTheme(),
      home: Scaffold(
        backgroundColor: AppColors.light.canvas,
        body: Center(
          child: SingleChildScrollView(
            padding: const EdgeInsets.all(16),
            child: SizedBox(width: 320, child: child),
          ),
        ),
      ),
    );

Future<void> _pump(WidgetTester tester, Widget child) async {
  await tester.pumpWidget(_wrap(child));
  await tester.pump(const Duration(milliseconds: 16));
}

void main() {
  testWidgets('test_sparkle_icon_uses_fixed_size_and_painter_color',
      (tester) async {
    await _pump(
      tester,
      SparkleIcon(size: 17, color: AppColors.light.aiPrimary),
    );
    final box = tester.widget<SizedBox>(
      find.descendant(
        of: find.byType(SparkleIcon),
        matching: find.byType(SizedBox),
      ),
    );
    expect(box.width, 17);
    expect(box.height, 17);
    final custom = tester.widget<CustomPaint>(
      find.descendant(
        of: find.byType(SparkleIcon),
        matching: find.byType(CustomPaint),
      ),
    );
    final painter = custom.painter! as SparklePainter;
    expect(painter.color, AppColors.light.aiPrimary);
  });

  testWidgets('test_sparkle_painter_repaints_only_on_color_change',
      (tester) async {
    const painter = SparklePainter(Color(0xFF7A5CFF));
    expect(
      painter.shouldRepaint(const SparklePainter(Color(0xFF7A5CFF))),
      isFalse,
    );
    expect(
      painter.shouldRepaint(const SparklePainter(Color(0xFF33BC8C))),
      isTrue,
    );
  });

  testWidgets('test_insight_hero_renders_title_body_and_tag', (tester) async {
    await _pump(
      tester,
      const InsightHero(
        title: '今天状态不错',
        body: '昨晚 7h12m，周中缺口已补上。',
        tag: '综合 86 分',
      ),
    );
    expect(find.text('今天状态不错'), findsOneWidget);
    expect(find.text('昨晚 7h12m，周中缺口已补上。'), findsOneWidget);
    expect(find.text('综合 86 分'), findsOneWidget);
    expect(find.byType(Orb), findsOneWidget);
  });

  testWidgets('test_insight_hero_without_tag_renders_no_pill', (tester) async {
    await _pump(
      tester,
      const InsightHero(title: '状态平稳', body: '未授权评分数据时不编造分数'),
    );
    expect(find.text('状态平稳'), findsOneWidget);
    expect(find.text('综合 86 分'), findsNothing);
  });

  testWidgets('test_sparkle_icon_golden', (tester) async {
    await _pump(
      tester,
      const Row(
        mainAxisAlignment: MainAxisAlignment.center,
        children: [
          SparkleIcon(size: 13, color: Color(0xFF7A5CFF)),
          SizedBox(width: 8),
          SparkleIcon(size: 17, color: Color(0xFF7A5CFF)),
        ],
      ),
    );
    await expectLater(
      find.byType(Scaffold),
      matchesGoldenFile('goldens/sparkle_icon.png'),
    );
  });

  testWidgets('test_insight_hero_golden', (tester) async {
    await _pump(
      tester,
      const InsightHero(
        title: '今天状态不错',
        body: '趋势向好，傍晚有空档，建议 20 分钟快走。',
        tag: '综合 86 分',
      ),
    );
    await expectLater(
      find.byType(Scaffold),
      matchesGoldenFile('goldens/insight_hero.png'),
    );
  });
}
