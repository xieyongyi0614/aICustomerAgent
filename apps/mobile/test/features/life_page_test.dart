import 'dart:io';

import 'package:dio/dio.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:mobile/app/theme/app_theme.dart';
import 'package:mobile/design_system/components/components.dart';
import 'package:mobile/features/life/data/life_repository.dart';
import 'package:mobile/features/life/presentation/life_page.dart';

class _FakeLifeRepository extends LifeRepository {
  _FakeLifeRepository({
    this.carMinor = 61200,
    this.carFails = false,
    this.tasksFail = false,
  }) : super(dio: Dio());

  static const tasks = [
    LifeTaskItem(id: 't-1', title: '买牛奶', kind: 'memo', status: 'open'),
    LifeTaskItem(id: 't-2', title: '交水费', kind: 'task', status: 'open'),
    LifeTaskItem(id: 't-3', title: '约牙医', kind: 'task', status: 'open'),
  ];

  final int carMinor;
  final bool carFails;
  final bool tasksFail;

  @override
  Future<List<LifeTaskItem>> listOpenTasks() async {
    if (tasksFail) throw Exception('tasks down');
    return tasks;
  }

  @override
  Future<String> monthExpenseText() async => '612.00';

  @override
  Future<LifeCarSummary> monthCarExpense() async {
    if (carFails) throw Exception('car down');
    return LifeCarSummary(
      text: (carMinor / 100).toStringAsFixed(0),
      isEmpty: carMinor <= 0,
    );
  }
}

Widget _host(Widget child) =>
    ProviderScope(child: MaterialApp(theme: buildAppTheme(), home: child));

void _useTallSurface(WidgetTester tester) {
  tester.view.physicalSize = const Size(390, 1400);
  tester.view.devicePixelRatio = 1;
  addTearDown(tester.view.reset);
}

Future<void> _pumpPage(WidgetTester tester, _FakeLifeRepository repo) async {
  _useTallSurface(tester);
  await tester.pumpWidget(_host(LifePage(repository: repo)));
  await tester.pump();
  await tester.pump(const Duration(milliseconds: 50));
}

ModuleCard _card(WidgetTester tester, String title) =>
    tester.widget<ModuleCard>(find.widgetWithText(ModuleCard, title));

void main() {
  testWidgets('test_life_page_module_grid_has_vehicle_card', (tester) async {
    final repo = _FakeLifeRepository();
    await _pumpPage(tester, repo);

    for (final title in const [
      '记账',
      '备忘录',
      '任务',
      '日历',
      '旅行',
      '健康',
      '车辆',
      '相册',
    ]) {
      expect(find.widgetWithText(ModuleCard, title), findsOneWidget, reason: title);
    }
    expect(find.byType(ModuleCard), findsNWidgets(11));
  });

  testWidgets('test_life_page_car_summary_is_real_amount', (tester) async {
    final repo = _FakeLifeRepository(carMinor: 61200);
    await _pumpPage(tester, repo);

    expect(find.text('本月养车 ¥612'), findsOneWidget);
  });

  testWidgets('test_life_page_car_summary_empty_state_is_honest',
      (tester) async {
    final repo = _FakeLifeRepository(carMinor: 0);
    await _pumpPage(tester, repo);

    expect(find.text('还没有养车记录'), findsOneWidget);
    expect(find.text('本月养车 ¥0'), findsNothing);
  });

  testWidgets('test_life_page_car_summary_failure_only_degrades_its_card',
      (tester) async {
    final repo = _FakeLifeRepository(carFails: true);
    await _pumpPage(tester, repo);

    expect(find.text('暂时取不到，点下方重试'), findsOneWidget);
    expect(find.text('本月支出 ¥612.00'), findsOneWidget);
    expect(find.text('1 条备忘'), findsOneWidget);
  });

  testWidgets('test_life_page_car_card_navigates_to_car', (tester) async {
    final repo = _FakeLifeRepository();
    await _pumpPage(tester, repo);

    expect(_card(tester, '车辆').onTap, isNotNull);
  });

  testWidgets('test_life_page_calendar_travel_cards_are_not_tappable',
      (tester) async {
    final repo = _FakeLifeRepository();
    await _pumpPage(tester, repo);

    expect(_card(tester, '日历').onTap, isNull);
    expect(_card(tester, '旅行').onTap, isNull);
    expect(_card(tester, '日历').summary, '未接入');
    expect(_card(tester, '旅行').summary, '未接入');
    expect(_card(tester, '相册').onTap, isNotNull, reason: 'APP-040：相册卡可点入 /album');
    expect(_card(tester, '相册').summary, '仅本机 · 需授权',
        reason: '无 provider 更新时呈诚实授权引导态');
  });

  testWidgets('test_life_page_existing_summaries_unchanged', (tester) async {
    final repo = _FakeLifeRepository();
    await _pumpPage(tester, repo);

    expect(_card(tester, '记账').summary, '本月支出 ¥612.00');
    expect(_card(tester, '备忘录').summary, '1 条备忘');
    expect(_card(tester, '任务').summary, '还有 2 项待办');
    expect(_card(tester, '健康').summary, '即将接入');
  });

  testWidgets('test_life_page_task_failure_degrades_only_its_cards',
      (tester) async {
    final repo = _FakeLifeRepository(tasksFail: true);
    await _pumpPage(tester, repo);

    expect(_card(tester, '备忘录').summary, '暂时取不到，点下方重试');
    expect(_card(tester, '任务').summary, '暂时取不到，点下方重试');
    expect(_card(tester, '车辆').summary, '本月养车 ¥612');
    expect(_card(tester, '记账').summary, '本月支出 ¥612.00');
  });

  test('test_life_page_never_renders_fabricated_module_summaries', () {
    final content = File(
      'lib/features/life/presentation/life_page.dart',
    ).readAsStringSync();
    for (final forbidden in const [
      '方案对齐',
      '行程规划中',
      '15:00',
      '十一',
    ]) {
      expect(content.contains(forbidden), isFalse, reason: forbidden);
    }
    expect(content.contains('features/ledger'), isFalse);
    expect(content.contains('features/car'), isFalse);
  });

  testWidgets('test_life_page_golden', (tester) async {
    final repo = _FakeLifeRepository();
    await _pumpPage(tester, repo);
    await expectLater(
      find.byType(Scaffold).first,
      matchesGoldenFile('goldens/life_page_modules.png'),
    );
  });
}
