import 'dart:io';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:mobile/app/theme/app_theme.dart';
import 'package:mobile/design_system/components/components.dart';
import 'package:mobile/design_system/tokens/tokens.dart';

final _colors = AppColors.light;
const _chargeAccent = Color(0x00000000);

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

Future<void> _golden(WidgetTester tester, String name, Widget child) async {
  await _pump(tester, child);
  await expectLater(
    find.byType(Scaffold),
    matchesGoldenFile('goldens/$name.png'),
  );
}

BoxDecoration _decorationOf(Container container) =>
    container.decoration! as BoxDecoration;

Container _byKey(WidgetTester tester, Key key) =>
    tester.widget<Container>(find.byKey(key));

Widget _loanCard() => LoanCard(
      label: '车贷 · 已还 18 / 36 期',
      badgeText: '下期 10 月 5 日',
      remainingText: '¥69,300',
      subText: '/ 36 期',
      progress: 0.5,
      leftNote: '月供 ¥3,850',
      rightNote: '2028 年 9 月结清',
    );

Widget _timeline() => const Timeline(
      items: [
        TimelineItem(
          icon: AppIcons.wrench,
          accent: Color(0xFF33BC8C),
          title: '小保养 · 机油机滤',
          subtitle: '2026-08-16 · 10,380 km',
          valueText: '¥200',
        ),
        TimelineItem(
          icon: AppIcons.wrench,
          accent: Color(0xFF33BC8C),
          title: '首保',
          subtitle: '2026-03-02 · 5,000 km',
          valueText: '免费',
        ),
        TimelineItem(
          icon: AppIcons.clock,
          title: '下一次保养',
          subtitle: '还剩 2,100 km 或 45 天',
          valueText: '13,500 km',
          isUpcoming: true,
        ),
      ],
    );

void main() {
  testWidgets('test_loan_card_progress_uses_warm_not_ai_gradient',
      (tester) async {
    await _pump(tester, _loanCard());
    final decoration = _decorationOf(
      _byKey(tester, LoanCard.progressFillKey),
    );
    expect(decoration.gradient, AppGradients.values.warmBar);
    expect(decoration.gradient, isNot(AppGradients.values.ai));
    expect(decoration.gradient!.colors, isNot(contains(_colors.aiPrimary)));
  });

  testWidgets('test_loan_card_renders_badge_and_both_notes', (tester) async {
    await _pump(tester, _loanCard());
    expect(find.text('下期 10 月 5 日'), findsOneWidget);
    expect(find.text('月供 ¥3,850'), findsOneWidget);
    expect(find.text('2028 年 9 月结清'), findsOneWidget);
    expect(find.text('¥69,300'), findsOneWidget);
  });

  testWidgets('test_loan_card_hides_badge_when_absent', (tester) async {
    await _pump(
      tester,
      const LoanCard(label: '车贷', remainingText: '¥0', progress: 1),
    );
    expect(find.text('车贷'), findsOneWidget);
    expect(find.byKey(LoanCard.progressFillKey), findsOneWidget);
  });

  testWidgets('test_type_scroll_selected_border_is_accent_55_percent',
      (tester) async {
    await _pump(
      tester,
      TypeScroll(
        selectedKey: 'charge',
        onSelected: (_) {},
        items: const [
          TypeScrollItem(
            key: 'charge',
            label: '充电',
            icon: AppIcons.zap,
            accent: Color(0xFF33BC8C),
          ),
          TypeScrollItem(
            key: 'fuel',
            label: '加油',
            icon: AppIcons.fuel,
            accent: Color(0xFFFF9D76),
          ),
        ],
      ),
    );
    final selected = _byKey(tester, TypeScroll.itemKey('charge'));
    final border = _decorationOf(selected).border! as Border;
    expect(border.top.width, 1.5);
    expect(border.top.color, const Color(0xFF33BC8C).withValues(alpha: 0.55));
    expect(border.top.color, isNot(_colors.aiPrimary.withValues(alpha: 0.55)));
  });

  testWidgets('test_type_scroll_unselected_has_transparent_border',
      (tester) async {
    await _pump(
      tester,
      TypeScroll(
        selectedKey: 'charge',
        onSelected: (_) {},
        items: const [
          TypeScrollItem(
            key: 'charge',
            label: '充电',
            icon: AppIcons.zap,
            accent: Color(0xFF33BC8C),
          ),
          TypeScrollItem(
            key: 'fuel',
            label: '加油',
            icon: AppIcons.fuel,
            accent: Color(0xFFFF9D76),
          ),
        ],
      ),
    );
    final unselected = _byKey(tester, TypeScroll.itemKey('fuel'));
    final border = _decorationOf(unselected).border! as Border;
    expect(border.top.width, 1.5);
    expect(border.top.color, _chargeAccent);
  });

  testWidgets('test_type_scroll_is_horizontally_scrollable_without_scrollbar',
      (tester) async {
    await _pump(
      tester,
      TypeScroll(
        selectedKey: 'charge',
        onSelected: (_) {},
        items: const [
          TypeScrollItem(
            key: 'charge',
            label: '充电',
            icon: AppIcons.zap,
            accent: Color(0xFF33BC8C),
          ),
          TypeScrollItem(
            key: 'fuel',
            label: '加油',
            icon: AppIcons.fuel,
            accent: Color(0xFFFF9D76),
          ),
        ],
      ),
    );
    final scroll = tester.widget<SingleChildScrollView>(
      find.descendant(
        of: find.byType(TypeScroll),
        matching: find.byType(SingleChildScrollView),
      ),
    );
    expect(scroll.scrollDirection, Axis.horizontal);
    expect(
      find.descendant(
        of: find.byType(TypeScroll),
        matching: find.byType(Scrollbar),
      ),
      findsNothing,
    );
  });

  testWidgets('test_timeline_last_row_has_no_divider', (tester) async {
    await _pump(tester, _timeline());
    expect(_byKey(tester, Timeline.rowKey(0)).decoration, isNotNull);
    expect(_byKey(tester, Timeline.rowKey(1)).decoration, isNotNull);
    expect(_byKey(tester, Timeline.rowKey(2)).decoration, isNull);
  });

  testWidgets('test_timeline_upcoming_row_uses_soon_token_colors',
      (tester) async {
    await _pump(tester, _timeline());
    final value = tester.widget<Text>(
      find.byKey(Timeline.valueKey(2)),
    );
    expect(value.style!.color, _colors.inkOnSoon);
    expect(value.style!.fontSize, 12);
    expect(value.style!.fontWeight, FontWeight.w600);
    expect(_byKey(tester, Timeline.rowKey(2)).decoration, isNull);
  });

  testWidgets('test_timeline_values_use_tabular_figures', (tester) async {
    await _pump(tester, _timeline());
    final value = tester.widget<Text>(find.byKey(Timeline.valueKey(0)));
    expect(
      value.style!.fontFeatures,
      contains(const FontFeature.tabularFigures()),
    );
  });

  test('test_car_icons_are_registered_and_in_cmap', () {
    final source = File(
      'lib/design_system/tokens/app_icons.dart',
    ).readAsStringSync();
    for (final name in const [
      'car',
      'zap',
      'fuel',
      'gauge',
      'parking',
      'ticket',
      'wrench',
      'history',
      'coins',
      'batteryCharging',
      'creditCard',
      'droplet',
      'percent',
      'timer',
      'fileText',
      'mapPin',
      'clock',
      'settings',
    ]) {
      expect(
        source.contains('static const $name = IconData('),
        isTrue,
        reason: name,
      );
    }
  });

  test('test_no_hardcoded_color_in_car_components', () {
    const files = [
      'lib/design_system/components/car_cards.dart',
      'lib/design_system/components/car_input.dart',
      'lib/design_system/components/timeline.dart',
    ];
    for (final path in files) {
      final content = File(path).readAsStringSync();
      expect(RegExp(r'Color\(0x').hasMatch(content), isFalse, reason: path);
      expect(RegExp(r'\bColors\.').hasMatch(content), isFalse, reason: path);
      for (final bad in [
        'FontWeight.w550',
        'FontWeight.w650',
        'FontWeight.w750',
      ]) {
        expect(content.contains(bad), isFalse, reason: '$path has $bad');
      }
    }
  });

  testWidgets('golden_car_components', (tester) async {
    await _golden(tester, 'car_loan', _loanCard());
    await _golden(
      tester,
      'car_type_scroll_selected',
      TypeScroll(
        selectedKey: 'charge',
        onSelected: (_) {},
        items: const [
          TypeScrollItem(
            key: 'charge',
            label: '充电',
            icon: AppIcons.zap,
            accent: Color(0xFF33BC8C),
          ),
          TypeScrollItem(
            key: 'fuel',
            label: '加油',
            icon: AppIcons.fuel,
            accent: Color(0xFFFF9D76),
          ),
          TypeScrollItem(
            key: 'mileage',
            label: '里程',
            icon: AppIcons.gauge,
            accent: Color(0xFF3E8BFF),
          ),
        ],
      ),
    );
    await _golden(
      tester,
      'car_type_scroll_plain',
      TypeScroll(
        onSelected: (_) {},
        items: const [
          TypeScrollItem(
            key: 'charge',
            label: '充电',
            icon: AppIcons.zap,
            accent: Color(0xFF33BC8C),
          ),
          TypeScrollItem(
            key: 'fuel',
            label: '加油',
            icon: AppIcons.fuel,
            accent: Color(0xFFFF9D76),
          ),
        ],
      ),
    );
    await _golden(tester, 'car_timeline', _timeline());
    await _golden(
      tester,
      'car_timeline_upcoming',
      const Timeline(
        items: [
          TimelineItem(
            icon: AppIcons.clock,
            title: '下一次保养',
            subtitle: '还剩 2,100 km 或 45 天',
            valueText: '13,500 km',
            isUpcoming: true,
          ),
        ],
      ),
    );
  });
}
