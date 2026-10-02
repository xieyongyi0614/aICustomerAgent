import 'dart:io';

import 'package:dio/dio.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:mobile/app/theme/app_theme.dart';
import 'package:mobile/design_system/components/components.dart';
import 'package:mobile/features/ledger/data/ledger_repository.dart';
import 'package:mobile/features/ledger/domain/bill_source_capability.dart';
import 'package:mobile/features/ledger/presentation/ledger_auto_page.dart';

const _pageSourcePath =
    'lib/features/ledger/presentation/ledger_auto_page.dart';
const _capabilitySourcePath =
    'lib/features/ledger/domain/bill_source_capability.dart';

class _FakeLedgerRepository extends LedgerRepository {
  _FakeLedgerRepository({
    this.summary = const LedgerAutoSummaryData(
      periodLabel: 'month',
      autoCount: 0,
      pendingCount: 0,
    ),
    this.rules = const [],
  }) : super(dio: Dio());

  final LedgerAutoSummaryData summary;
  final List<LedgerRuleData> rules;

  @override
  Future<LedgerAutoSummaryData> fetchAutoSummary() async => summary;

  @override
  Future<List<LedgerRuleData>> fetchRules() async => rules;
}

void _useTallSurface(WidgetTester tester) {
  tester.view.physicalSize = const Size(390, 1800);
  tester.view.devicePixelRatio = 1;
  addTearDown(tester.view.reset);
}

Future<void> _openPage(WidgetTester tester, LedgerRepository repo) async {
  _useTallSurface(tester);
  await tester.pumpWidget(
    MaterialApp(theme: buildAppTheme(), home: LedgerAutoPage(repository: repo)),
  );
  await tester.pump();
  await tester.pump(const Duration(milliseconds: 50));
}

List<String> _sectionTypes(WidgetTester tester) {
  final listView = tester.widget<ListView>(find.byType(ListView));
  final children =
      (listView.childrenDelegate as SliverChildListDelegate).children;
  return children.map((child) => child.runtimeType.toString()).toList();
}

void main() {
  testWidgets('test_ledger_auto_sections_render_in_order', (tester) async {
    final repo = _FakeLedgerRepository(
      summary: const LedgerAutoSummaryData(
        periodLabel: 'month',
        autoCount: 42,
        pendingCount: 1,
      ),
      rules: const [LedgerRuleData(keyword: '奶茶', categoryName: '饮品')],
    );
    await _openPage(tester, repo);
    final types = _sectionTypes(tester);
    const topLevel = ['BackLink', 'AiCard', 'SettingGroup', 'PrivacyNote'];
    final indices = [for (final name in topLevel) types.indexOf(name)];
    expect(indices.contains(-1), isFalse, reason: '$types');
    expect(indices, [...indices]..sort(), reason: '$types');

    double topOf(Finder finder) => tester.getTopLeft(finder).dy;
    expect(
      topOf(find.byType(AiCard)),
      lessThan(topOf(find.byType(SettingGroup))),
    );
    expect(
      topOf(find.byType(SettingGroup)),
      lessThan(topOf(find.byType(LedgerRuleRow).first)),
    );
    expect(
      topOf(find.byType(LedgerRuleRow).first),
      lessThan(topOf(find.byType(PrivacyNote))),
    );
  });

  testWidgets('test_ledger_auto_hides_accuracy_card_when_absent',
      (tester) async {
    final repo = _FakeLedgerRepository(
      summary: const LedgerAutoSummaryData(
        periodLabel: 'month',
        autoCount: 12,
        pendingCount: 2,
      ),
    );
    await _openPage(tester, repo);
    expect(find.byType(LedgerStatCard), findsOneWidget);
    expect(find.text('分类准确率'), findsNothing);
    expect(find.text('学会的规则'), findsNothing);
  });

  testWidgets('test_ledger_auto_stats_are_auto_accuracy_and_rules',
      (tester) async {
    final repo = _FakeLedgerRepository(
      summary: const LedgerAutoSummaryData(
        periodLabel: 'month',
        autoCount: 12,
        pendingCount: 2,
        accuracy: 0.92,
      ),
      rules: const [
        LedgerRuleData(keyword: '瑞幸', categoryName: '餐饮'),
        LedgerRuleData(keyword: '滴滴', categoryName: '交通'),
        LedgerRuleData(keyword: '盒马', categoryName: '购物'),
      ],
    );
    await _openPage(tester, repo);
    expect(find.byType(LedgerStatCard), findsNWidgets(3));
    expect(find.text('分类准确率'), findsOneWidget);
    expect(find.text('92'), findsOneWidget);
    expect(find.text('学会的规则'), findsOneWidget);
    expect(find.text('3'), findsOneWidget);
    expect(find.text('来自你的 3 次修正'), findsOneWidget);
  });

  testWidgets('test_ledger_auto_has_no_pending_block', (tester) async {
    final repo = _FakeLedgerRepository(
      summary: const LedgerAutoSummaryData(
        periodLabel: 'month',
        autoCount: 3,
        pendingCount: 2,
      ),
    );
    await _openPage(tester, repo);
    expect(
      find.text('需要你的确认'),
      findsNothing,
      reason: '待确认只出现在账本首页（31），本页是二级管理页',
    );
    expect(find.byType(LedgerConfirmRow), findsNothing);
    expect(find.text('待你确认'), findsNothing);
    expect(find.byType(LedgerStatCard), findsOneWidget);
  });

  testWidgets('test_ledger_auto_conclusion_points_to_ledger_home',
      (tester) async {
    final repo = _FakeLedgerRepository(
      summary: const LedgerAutoSummaryData(
        periodLabel: 'month',
        autoCount: 42,
        pendingCount: 2,
        accuracy: 0.96,
      ),
    );
    await _openPage(tester, repo);
    expect(
      find.text(
        '本月我自动记了 42 笔 · 分类准确率 96% · 2 笔拿不准的已放在账本首页等你确认。',
      ),
      findsOneWidget,
    );
  });

  test('test_ledger_auto_never_renders_sync_counts', () {
    final source =
        File(_pageSourcePath).readAsStringSync() +
        File(_capabilitySourcePath).readAsStringSync();
    expect(source.contains('已连接'), isFalse);
    expect(source.contains('今天同步'), isFalse);
    expect(RegExp(r'同步\s*\d+\s*笔').hasMatch(source), isFalse);
  });

  test('test_ledger_auto_source_rows_are_static_and_include_reasons', () {
    final unavailable =
        billSourceCapabilities.where((row) => !row.available).toList();
    expect(unavailable, hasLength(3));
    for (final row in unavailable) {
      expect(row.state, '未接入');
      expect(row.reason.trim(), isNotEmpty);
    }
    final voice =
        billSourceCapabilities.firstWhere((row) => row.available);
    expect(voice.state, '一直开着');
  });

  testWidgets('test_ledger_auto_source_block_renders_states', (tester) async {
    final repo = _FakeLedgerRepository();
    await _openPage(tester, repo);
    expect(find.text('未接入'), findsNWidgets(3));
    expect(find.text('一直开着'), findsOneWidget);
    expect(find.text('语音记账'), findsOneWidget);
  });

  testWidgets('test_ledger_auto_rule_row_hides_source_when_learned_from_absent',
      (tester) async {
    final repo = _FakeLedgerRepository(
      rules: const [LedgerRuleData(keyword: '奶茶', categoryName: '饮品')],
    );
    await _openPage(tester, repo);
    final row = tester.widget<LedgerRuleRow>(find.byType(LedgerRuleRow));
    expect(row.sourceNote, isNull);
    expect(find.text('奶茶'), findsOneWidget);
    expect(find.text('饮品'), findsOneWidget);
  });

  testWidgets('test_ledger_auto_rules_empty_state_is_honest', (tester) async {
    final repo = _FakeLedgerRepository();
    await _openPage(tester, repo);
    expect(find.text('还没有学会新的规则。改一次分类，我就记住。'), findsOneWidget);
  });

  test('test_ledger_auto_privacy_note_does_not_claim_sync_control', () {
    final source = File(_pageSourcePath).readAsStringSync();
    expect(source.contains('关闭同步'), isFalse);
    expect(source.contains('停止读取'), isFalse);
  });

  test('test_ledger_auto_never_imports_dio', () {
    final source = File(_pageSourcePath).readAsStringSync();
    expect(source.contains('package:dio'), isFalse);
  });

  testWidgets('test_ledger_auto_golden', (tester) async {
    final repo = _FakeLedgerRepository(
      summary: const LedgerAutoSummaryData(
        periodLabel: 'month',
        autoCount: 42,
        pendingCount: 1,
        accuracy: 0.92,
      ),
      rules: const [
        LedgerRuleData(keyword: '奶茶', categoryName: '饮品'),
        LedgerRuleData(keyword: '充电桩', categoryName: '交通 / 加油'),
      ],
    );
    await _openPage(tester, repo);
    await expectLater(
      find.byType(Scaffold),
      matchesGoldenFile('goldens/ledger_auto.png'),
    );
  });

  testWidgets('test_ledger_auto_no_accuracy_golden', (tester) async {
    final repo = _FakeLedgerRepository(
      summary: const LedgerAutoSummaryData(
        periodLabel: 'month',
        autoCount: 12,
        pendingCount: 2,
      ),
      rules: const [LedgerRuleData(keyword: '奶茶', categoryName: '饮品')],
    );
    await _openPage(tester, repo);
    await expectLater(
      find.byType(Scaffold),
      matchesGoldenFile('goldens/ledger_auto_no_accuracy.png'),
    );
  });
}
