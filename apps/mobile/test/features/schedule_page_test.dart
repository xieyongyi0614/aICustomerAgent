import 'dart:io';

import 'package:dio/dio.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:intl/intl.dart';
import 'package:mobile/app/theme/app_theme.dart';
import 'package:mobile/design_system/components/components.dart';
import 'package:mobile/features/life/data/life_repository.dart';
import 'package:mobile/features/life/presentation/schedule_page.dart';

class _FakeLifeRepository extends LifeRepository {
  _FakeLifeRepository({this.tasks = const [], this.fails = false})
    : super(dio: Dio());

  final List<LifeTaskItem> tasks;
  final bool fails;
  int completeCalls = 0;
  int deleteCalls = 0;

  @override
  Future<List<LifeTaskItem>> listTasks({String status = 'open'}) async {
    if (fails) throw Exception('tasks down');
    if (status == 'open') {
      return tasks.where((task) => task.status == 'open').toList();
    }
    return tasks;
  }

  @override
  Future<void> completeTask(String id) async {
    completeCalls++;
  }

  @override
  Future<void> deleteTask(String id) async {
    deleteCalls++;
  }
}

Widget _host(Widget child) =>
    MaterialApp(theme: buildAppTheme(), home: child);

void _useTallSurface(WidgetTester tester) {
  tester.view.physicalSize = const Size(390, 1800);
  tester.view.devicePixelRatio = 1;
  addTearDown(tester.view.reset);
}

Future<void> _pump(WidgetTester tester, _FakeLifeRepository repo) async {
  _useTallSurface(tester);
  await tester.pumpWidget(_host(SchedulePage(repository: repo)));
  await tester.pump();
  await tester.pump(const Duration(milliseconds: 50));
}

DateTime get _today {
  final now = DateTime.now();
  return DateTime(now.year, now.month, now.day);
}

void main() {
  testWidgets('test_schedule_page_shows_week_ai_timeline_and_upcoming',
      (tester) async {
    final today = _today;
    final at15 = DateTime(today.year, today.month, today.day, 15);
    final in3Days = today.add(const Duration(days: 3));
    final repo = _FakeLifeRepository(
      tasks: [
        LifeTaskItem(
          id: 't-1',
          title: '产品方案对齐',
          kind: 'task',
          status: 'open',
          remindAt: at15.toIso8601String(),
          tag: '工作',
          orderReason: '纪要模板已备好',
        ),
        LifeTaskItem(id: 't-2', title: '给妈妈回电话', kind: 'task', status: 'open'),
        LifeTaskItem(
          id: 't-3',
          title: '车贷还款日',
          kind: 'task',
          status: 'open',
          dueDate: DateFormat('yyyy-MM-dd').format(in3Days),
        ),
        LifeTaskItem(id: 'm-1', title: '买牛奶', kind: 'memo', status: 'open'),
      ],
    );
    await _pump(tester, repo);

    expect(find.text('日程'), findsOneWidget);
    expect(find.text('会议与待办在一起，亚丝娜帮你排'), findsOneWidget);
    expect(find.byType(WeekStrip), findsOneWidget);
    expect(find.text('亚丝娜的排法'), findsOneWidget);
    expect(find.text('AI 已排序'), findsOneWidget);

    expect(find.text('15:00'), findsOneWidget);
    expect(find.text('产品方案对齐'), findsOneWidget);
    expect(find.text('工作'), findsOneWidget);
    expect(find.textContaining('纪要模板已备好'), findsOneWidget);
    expect(find.text('待排'), findsOneWidget, reason: '无日期待办不编造时间');
    expect(find.text('给妈妈回电话'), findsOneWidget);
    expect(find.text('买牛奶'), findsNothing, reason: '日程页不展示 kind=memo');

    expect(find.text('即将到来'), findsOneWidget);
    expect(find.byType(NextCard), findsOneWidget);
    expect(find.text('车贷还款日'), findsOneWidget);
  });

  testWidgets('test_schedule_page_empty_state_is_honest', (tester) async {
    final repo = _FakeLifeRepository();
    await _pump(tester, repo);

    expect(find.text('今天还没有排到事，跟我说一句就好'), findsOneWidget);
    expect(find.text('未来两周还没有安排'), findsOneWidget);
    expect(find.byType(NextCard), findsNothing);
  });

  testWidgets('test_schedule_page_failure_shows_retry', (tester) async {
    final repo = _FakeLifeRepository(fails: true);
    await _pump(tester, repo);

    expect(find.byType(ErrorState), findsOneWidget);
  });

  testWidgets('test_schedule_page_next_card_offers_complete_and_delete',
      (tester) async {
    final in3Days = _today.add(const Duration(days: 3));
    final repo = _FakeLifeRepository(
      tasks: [
        LifeTaskItem(
          id: 't-3',
          title: '车贷还款日',
          kind: 'task',
          status: 'open',
          dueDate: DateFormat('yyyy-MM-dd').format(in3Days),
        ),
      ],
    );
    await _pump(tester, repo);

    await tester.tap(find.byType(NextCard));
    await tester.pumpAndSettle();
    expect(find.text('标记完成'), findsOneWidget);

    await tester.tap(find.text('标记完成'));
    await tester.pumpAndSettle();
    expect(repo.completeCalls, 1);
  });

  testWidgets('test_schedule_page_done_task_is_struck_through', (tester) async {
    final today = _today;
    final at9 = DateTime(today.year, today.month, today.day, 9, 30);
    final repo = _FakeLifeRepository(
      tasks: [
        LifeTaskItem(
          id: 't-1',
          title: '回复导师邮件',
          kind: 'task',
          status: 'done',
          remindAt: at9.toIso8601String(),
        ),
      ],
    );
    await _pump(tester, repo);

    final title = tester.widget<Text>(find.text('回复导师邮件'));
    expect(title.style?.decoration, TextDecoration.lineThrough);
  });

  testWidgets('test_schedule_page_done_without_remind_uses_completed_time',
      (tester) async {
    final today = _today;
    final completedAt = DateTime(today.year, today.month, today.day, 11, 5);
    final repo = _FakeLifeRepository(
      tasks: [
        LifeTaskItem(
          id: 't-1',
          title: '回复导师邮件',
          kind: 'task',
          status: 'done',
          completedAt: completedAt.toIso8601String(),
        ),
      ],
    );
    await _pump(tester, repo);

    expect(find.text('11:05'), findsOneWidget);
    expect(find.text('回复导师邮件'), findsOneWidget);
  });

  testWidgets('test_schedule_page_old_done_task_stays_off_timeline',
      (tester) async {
    final yesterday = _today.subtract(const Duration(days: 1));
    final repo = _FakeLifeRepository(
      tasks: [
        LifeTaskItem(
          id: 't-1',
          title: '昨天的已完成事项',
          kind: 'task',
          status: 'done',
          dueDate: DateFormat('yyyy-MM-dd').format(yesterday),
        ),
      ],
    );
    await _pump(tester, repo);

    expect(find.text('昨天的已完成事项'), findsNothing);
    expect(find.text('今天还没有排到事，跟我说一句就好'), findsOneWidget);
  });

  test('test_schedule_page_never_renders_fabricated_schedule_content', () {
    final source = File(
      'lib/features/life/presentation/schedule_page.dart',
    ).readAsStringSync();
    for (final forbidden in const [
      '大理',
      '产品方案对齐',
      '导师邮件',
      '会议室 B',
      '车贷还款日',
      '洱海',
    ]) {
      expect(source.contains(forbidden), isFalse, reason: forbidden);
    }
    expect(source.contains('features/ledger'), isFalse);
    expect(source.contains('features/car'), isFalse);
  });
}
