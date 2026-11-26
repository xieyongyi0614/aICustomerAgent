import 'dart:io';

import 'package:dio/dio.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:mobile/app/theme/app_theme.dart';
import 'package:mobile/design_system/components/components.dart';
import 'package:mobile/design_system/tokens/tokens.dart';
import 'package:mobile/features/life/data/life_repository.dart';
import 'package:mobile/features/life/presentation/memo_page.dart';

class _FakeLifeRepository extends LifeRepository {
  _FakeLifeRepository({this.tasks = const [], this.fails = false})
    : super(dio: Dio());

  final List<LifeTaskItem> tasks;
  final bool fails;
  int deleteCalls = 0;
  String? deletedId;

  @override
  Future<List<LifeTaskItem>> listOpenTasks() async {
    if (fails) throw Exception('tasks down');
    return tasks;
  }

  @override
  Future<void> deleteTask(String id) async {
    deleteCalls++;
    deletedId = id;
  }
}

Widget _host(Widget child) =>
    MaterialApp(theme: buildAppTheme(), home: child);

void _useTallSurface(WidgetTester tester) {
  tester.view.physicalSize = const Size(390, 1600);
  tester.view.devicePixelRatio = 1;
  addTearDown(tester.view.reset);
}

Future<void> _pump(WidgetTester tester, _FakeLifeRepository repo) async {
  _useTallSurface(tester);
  await tester.pumpWidget(_host(MemoPage(repository: repo)));
  await tester.pump();
  await tester.pump(const Duration(milliseconds: 50));
}

void main() {
  testWidgets('test_memo_page_lists_only_memos_grouped_by_tag',
      (tester) async {
    final repo = _FakeLifeRepository(
      tasks: const [
        LifeTaskItem(
          id: 'm-1',
          title: '护照明年 3 月到期',
          kind: 'memo',
          status: 'open',
          tag: '生活',
        ),
        LifeTaskItem(
          id: 'm-2',
          title: '带无人机，查限飞区',
          kind: 'memo',
          status: 'open',
          tag: '旅行灵感',
        ),
        LifeTaskItem(id: 't-1', title: '交水费', kind: 'task', status: 'open'),
      ],
    );
    await _pump(tester, repo);

    expect(find.text('备忘录'), findsOneWidget);
    expect(find.text('随手说，亚丝娜帮你归好类'), findsOneWidget);
    expect(find.text('2 条 · 2 个主题'), findsOneWidget);
    expect(find.text('护照明年 3 月到期'), findsOneWidget);
    expect(find.text('带无人机，查限飞区'), findsOneWidget);
    expect(find.text('交水费'), findsNothing, reason: '备忘录页不展示 kind=task');
    expect(
      find.descendant(of: find.byType(BackLink), matching: find.text('生活')),
      findsOneWidget,
      reason: '「生活」同时是分组名，返回链断言须限定在 BackLink 内',
    );
    expect(find.text('旅行灵感'), findsOneWidget);
    expect(find.text('亚丝娜整理中'), findsOneWidget);
    expect(find.byType(MemoRow), findsNWidgets(2));
  });

  testWidgets('test_memo_page_untagged_memos_land_in_one_section',
      (tester) async {
    final repo = _FakeLifeRepository(
      tasks: const [
        LifeTaskItem(id: 'm-1', title: '买牛奶', kind: 'memo', status: 'open'),
        LifeTaskItem(id: 'm-2', title: '修台灯', kind: 'memo', status: 'open'),
      ],
    );
    await _pump(tester, repo);

    expect(find.text('全部备忘'), findsOneWidget);
    expect(
      tester.widget<CountPill>(find.byType(CountPill)).text,
      '2 条',
      reason: '无 tag 时不编造主题数',
    );
    expect(find.byType(MemoRow), findsNWidgets(2));
  });

  testWidgets('test_memo_page_empty_state_is_honest', (tester) async {
    final repo = _FakeLifeRepository();
    await _pump(tester, repo);

    expect(find.text('还没有备忘，随口说一句我就帮你记'), findsOneWidget);
    expect(find.byType(MemoRow), findsNothing);
    expect(tester.widget<CountPill>(find.byType(CountPill)).text, '0 条');
  });

  testWidgets('test_memo_page_failure_shows_retry', (tester) async {
    final repo = _FakeLifeRepository(fails: true);
    await _pump(tester, repo);

    expect(find.byType(ErrorState), findsOneWidget);
    expect(find.byType(MemoRow), findsNothing);
  });

  testWidgets('test_memo_page_long_press_deletes_a_memo', (tester) async {
    final repo = _FakeLifeRepository(
      tasks: const [
        LifeTaskItem(id: 'm-9', title: '健身房年卡续费', kind: 'memo', status: 'open'),
      ],
    );
    await _pump(tester, repo);

    await tester.longPress(find.byType(MemoRow));
    await tester.pumpAndSettle();
    expect(find.text('删掉这条备忘'), findsOneWidget);

    await tester.tap(find.text('删掉它'));
    await tester.pumpAndSettle();
    expect(repo.deleteCalls, 1);
    expect(repo.deletedId, 'm-9');
  });

  testWidgets('test_memo_page_renders_reminder_and_ai_receipt', (tester) async {
    final repo = _FakeLifeRepository(
      tasks: const [
        LifeTaskItem(
          id: 'm-1',
          title: '更新基线文档',
          kind: 'memo',
          status: 'open',
          dueDate: '2026-03-01',
          orderReason: '已排进今日任务',
        ),
      ],
    );
    await _pump(tester, repo);

    expect(find.textContaining('到期 3/1'), findsOneWidget);
    expect(find.textContaining('已排进今日任务'), findsOneWidget);
  });

  testWidgets('test_memo_page_row_carries_recorded_date', (tester) async {
    final repo = _FakeLifeRepository(
      tasks: const [
        LifeTaskItem(
          id: 'm-1',
          title: '护照明年 3 月到期',
          kind: 'memo',
          status: 'open',
          tag: '生活',
          createdAt: '2026-09-21T02:00:00+00:00',
        ),
      ],
    );
    await _pump(tester, repo);

    expect(find.textContaining('记录'), findsOneWidget);
    expect(find.byType(MemoRow), findsOneWidget);
  });

  testWidgets('test_memo_page_skips_generic_memo_reason', (tester) async {
    final repo = _FakeLifeRepository(
      tasks: const [
        LifeTaskItem(
          id: 'm-1',
          title: '洗衣液买无香型',
          kind: 'memo',
          status: 'open',
          tag: '生活',
          orderReason: '备忘录 · AI 已整理',
        ),
      ],
    );
    await _pump(tester, repo);

    expect(
      find.textContaining('AI 已整理'),
      findsNothing,
      reason: '通用排序理由不是「被用到哪里」，行内不重复渲染',
    );
  });

  testWidgets('test_memo_page_group_header_shows_icon_and_count',
      (tester) async {
    final repo = _FakeLifeRepository(
      tasks: const [
        LifeTaskItem(
          id: 'm-1',
          title: '带无人机，查限飞区',
          kind: 'memo',
          status: 'open',
          tag: '旅行灵感',
        ),
        LifeTaskItem(
          id: 'm-2',
          title: '老妈想要的鲜花饼牌子',
          kind: 'memo',
          status: 'open',
          tag: '旅行灵感',
        ),
        LifeTaskItem(
          id: 'm-3',
          title: '季度 OKR 草稿',
          kind: 'memo',
          status: 'open',
          tag: '工作',
        ),
      ],
    );
    await _pump(tester, repo);

    expect(find.text('旅行灵感'), findsOneWidget);
    expect(find.text('2 条'), findsOneWidget, reason: '分组头条数');
    expect(find.text('工作'), findsOneWidget);
    expect(find.text('1 条'), findsOneWidget);
    expect(find.byIcon(AppIcons.tag), findsNWidgets(2), reason: '两个主题各一枚图标');
    expect(tester.widget<CountPill>(find.byType(CountPill)).text, '3 条 · 2 个主题');
  });

  test('test_memo_page_never_renders_fabricated_memo_content', () {
    final source = File(
      'lib/features/life/presentation/memo_page.dart',
    ).readAsStringSync();
    for (final forbidden in const [
      '嘉华',
      '鲜花饼',
      '洱海',
      '大理',
      '健身房年卡',
      '无人机',
    ]) {
      expect(source.contains(forbidden), isFalse, reason: forbidden);
    }
    expect(source.contains('features/ledger'), isFalse);
    expect(source.contains('features/car'), isFalse);
  });
}
