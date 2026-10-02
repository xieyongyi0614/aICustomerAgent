import 'dart:io';

import 'package:dio/dio.dart';
import 'package:flutter/gestures.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:mobile/app/theme/app_theme.dart';
import 'package:mobile/design_system/components/components.dart';
import 'package:mobile/app/state/album_summary_provider.dart';
import 'package:mobile/design_system/orb/orb.dart';
import 'package:mobile/features/life/data/life_repository.dart';
import 'package:mobile/features/life/presentation/life_page.dart';

class _AuthorizedAlbumNotifier extends AlbumSummaryNotifier {
  @override
  AlbumSummary? build() =>
      const AlbumSummary(authorized: true, totalCount: 2847);
}

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
  testWidgets('test_life_page_module_grid_has_six_modules', (tester) async {
    final repo = _FakeLifeRepository();
    await _pumpPage(tester, repo);

    for (final title in const [
      '记账',
      '备忘录',
      '日程',
      '健康',
      '车辆',
      '相册',
    ]) {
      expect(find.widgetWithText(ModuleCard, title), findsOneWidget, reason: title);
    }
    // 宫格 6（3×2）；「即将上线」占位区已于 2026-10-03 移除
    expect(find.byType(ModuleCard), findsNWidgets(6));
    for (final removed in const ['任务', '日历', '旅行', '记忆']) {
      expect(find.widgetWithText(ModuleCard, removed), findsNothing,
          reason: '$removed 已按 2026-09-30 IA 裁决移出宫格');
    }
  });

  testWidgets('test_life_page_car_summary_is_real_amount', (tester) async {
    final repo = _FakeLifeRepository(carMinor: 61200);
    await _pumpPage(tester, repo);

    expect(find.text('本月 ¥612'), findsOneWidget);
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
    expect(find.text('本月 ¥612.00'), findsOneWidget);
    expect(find.text('1 条备忘'), findsOneWidget);
  });

  testWidgets('test_life_page_car_card_navigates_to_car', (tester) async {
    final repo = _FakeLifeRepository();
    await _pumpPage(tester, repo);

    expect(_card(tester, '车辆').onTap, isNotNull);
  });

  testWidgets('test_life_page_ledger_card_navigates_to_ledger', (tester) async {
    final repo = _FakeLifeRepository();
    await _pumpPage(tester, repo);

    expect(_card(tester, '记账').onTap, isNotNull,
        reason: 'B4：记账模块 → 账本页（31）');
  });

  testWidgets('test_life_page_module_grid_has_no_dangling_entry', (tester) async {
    final repo = _FakeLifeRepository();
    await _pumpPage(tester, repo);

    for (final title in const ['记账', '备忘录', '日程', '健康', '车辆', '相册']) {
      expect(_card(tester, title).onTap, isNotNull,
          reason: '红线 10：宫格不允许悬空入口（$title 必须有真实页面）');
    }
    expect(_card(tester, '备忘录').summary, '1 条备忘');
    expect(_card(tester, '日程').summary, '今日 2 项');
    expect(_card(tester, '相册').onTap, isNotNull, reason: 'APP-040：相册卡可点入 /album');
    expect(_card(tester, '相册').summary, '仅本机 · 需授权',
        reason: '无 provider 更新时呈诚实授权引导态');
  });

  testWidgets('test_life_page_existing_summaries_unchanged', (tester) async {
    final repo = _FakeLifeRepository();
    await _pumpPage(tester, repo);

    expect(_card(tester, '记账').summary, '本月 ¥612.00');
    expect(_card(tester, '备忘录').summary, '1 条备忘');
    expect(_card(tester, '日程').summary, '今日 2 项');
    expect(_card(tester, '健康').summary, '趋势参考 · 非诊断');
  });

  testWidgets('test_life_page_task_failure_degrades_only_its_cards',
      (tester) async {
    final repo = _FakeLifeRepository(tasksFail: true);
    await _pumpPage(tester, repo);

    expect(_card(tester, '备忘录').summary, '暂时取不到，点下方重试');
    expect(_card(tester, '日程').summary, '暂时取不到，点下方重试');
    expect(_card(tester, '车辆').summary, '本月 ¥612');
    expect(_card(tester, '记账').summary, '本月 ¥612.00');
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

  testWidgets('test_life_page_drops_skill_copy_and_soon_grid', (tester) async {
    final repo = _FakeLifeRepository();
    await _pumpPage(tester, repo);

    expect(find.text('今天的生活，亚丝娜帮你看着呢'), findsOneWidget);
    expect(find.text('长按卡片拖动重排 · 第一格就是底部导航的「动态」'), findsOneWidget);
    expect(find.text('你的生活工具箱'), findsNothing,
        reason: '2026-10-03 设计稿改版：标题区换成 Hero（日期 / 问候 / 副标题）');
    for (final removed in const [
      '说一句话，亚丝娜帮你归位',
      'Skill 化 · 可持续扩展',
      '即将上线',
      'Skill 商店',
      '更多 Skill',
      '设为动态',
    ]) {
      expect(find.text(removed), findsNothing, reason: removed);
    }
  });

  testWidgets('test_life_page_drag_to_first_slot_promotes_module',
      (tester) async {
    final repo = _FakeLifeRepository();
    await _pumpPage(tester, repo);

    expect(_card(tester, '记账').active, isTrue, reason: '默认动态位是记账');

    final gesture = await tester.startGesture(
      tester.getCenter(find.widgetWithText(ModuleCard, '车辆')),
    );
    await tester.pump(kLongPressTimeout + const Duration(milliseconds: 50));
    await gesture.moveTo(
      tester.getCenter(find.widgetWithText(ModuleCard, '记账')),
    );
    await tester.pump();
    await gesture.up();
    // Hero 的 Orb 是常驻呼吸动画，不能 pumpAndSettle；落位补间 240ms。
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 300));

    expect(_card(tester, '车辆').active, isTrue,
        reason: '拖到首位的模块成为动态位');
    expect(_card(tester, '记账').active, isFalse);
  });

  testWidgets('test_life_page_marks_current_dynamic_module', (tester) async {
    final repo = _FakeLifeRepository();
    await _pumpPage(tester, repo);

    expect(_card(tester, '记账').active, isTrue, reason: '默认动态位是记账');
    expect(_card(tester, '车辆').active, isFalse);
  });

  testWidgets('test_life_page_hero_and_ai_summary_render', (tester) async {
    final repo = _FakeLifeRepository();
    await _pumpPage(tester, repo);

    expect(find.byType(Orb), findsOneWidget, reason: 'Hero 右侧是 AI 存在标记');
    expect(find.text('今天的生活，亚丝娜帮你看着呢'), findsOneWidget);
    expect(find.text('亚丝娜的生活小结'), findsOneWidget);
    expect(find.text('查看今日日程'), findsOneWidget);
    expect(find.text('去相册看看'), findsOneWidget);
    expect(find.text('生活模块'), findsOneWidget);
    expect(find.text('6 个 · 都在帮你跑'), findsOneWidget);
  });

  testWidgets('test_life_page_ai_summary_lists_only_real_facts',
      (tester) async {
    final repo = _FakeLifeRepository();
    await _pumpPage(tester, repo);

    expect(find.textContaining('今天有 2 项日程'), findsOneWidget);
    expect(find.textContaining('本月支出 ¥612.00'), findsOneWidget);
    expect(find.textContaining('养车 ¥612'), findsOneWidget);
    expect(find.textContaining('76 张'), findsNothing,
        reason: '红线 11：可清理张数客户端拿不到，不得编造');
  });

  testWidgets('test_life_page_trends_use_real_data_or_say_not_wired',
      (tester) async {
    final repo = _FakeLifeRepository();
    await _pumpPage(tester, repo);

    expect(_card(tester, '日程').trend, '交水费',
        reason: '日程 trend 用今天首条待办，不编造时间');
    expect(_card(tester, '记账').trend, '环比尚未接入');
    expect(_card(tester, '备忘录').trend, '主题归类尚未接入');
    expect(_card(tester, '健康').trend, '尚未接入健康数据');
    expect(_card(tester, '车辆').trend, isNull,
        reason: '没有限行提醒时不出这一行，不写示例日期');
  });

  testWidgets('test_life_page_album_trend_keeps_local_only_claim',
      (tester) async {
    _useTallSurface(tester);
    await tester.pumpWidget(
      ProviderScope(
        overrides: [
          albumSummaryProvider.overrideWith(_AuthorizedAlbumNotifier.new),
        ],
        child: MaterialApp(
          theme: buildAppTheme(),
          home: LifePage(repository: _FakeLifeRepository()),
        ),
      ),
    );
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 50));

    expect(_card(tester, '相册').summary, '2847 张 · 仅本机');
    expect(_card(tester, '相册').trend, '整理建议尚未接入',
        reason: '红线 9：相册口径带「仅本机」；红线 11：整理建议未接入就说未接入');
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
