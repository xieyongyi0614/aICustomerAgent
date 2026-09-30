import 'dart:async';
import 'dart:io';

import 'package:dio/dio.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:mobile/app/theme/app_theme.dart';
import 'package:mobile/design_system/components/components.dart';
import 'package:mobile/features/ledger/data/ledger_repository.dart';
import 'package:mobile/features/ledger/presentation/ledger_add_page.dart';

const _categories = [
  LedgerCategoryData(id: 'c-food', name: '餐饮', kind: 'expense'),
  LedgerCategoryData(id: 'c-traffic', name: '交通', kind: 'expense'),
  LedgerCategoryData(id: 'c-shop', name: '购物', kind: 'expense'),
  LedgerCategoryData(id: 'c-salary', name: '工资', kind: 'income'),
];

class _FakeLedgerRepository extends LedgerRepository {
  _FakeLedgerRepository({
    this.preview,
    this.previewFails = false,
    this.createFails = false,
  }) : super(dio: Dio());

  final LedgerPreviewData? preview;
  bool previewFails;
  bool createFails;
  Completer<void>? createGate;

  final List<String> requestedKinds = [];
  int previewCalls = 0;
  int createCalls = 0;
  final List<int> createdAmounts = [];
  final List<String?> createdCategories = [];
  final List<String> createdKeys = [];

  @override
  Future<List<LedgerCategoryData>> fetchCategories({String? kind}) async {
    requestedKinds.add(kind ?? '');
    return _categories.where((row) => kind == null || row.kind == kind).toList();
  }

  @override
  Future<LedgerPreviewData> classifyPreview(
    String note, {
    String kind = 'expense',
  }) async {
    previewCalls++;
    if (previewFails) throw Exception('preview down');
    return preview ??
        const LedgerPreviewData(
          matched: false,
          categoryName: '其他',
          reason: 'fallback',
          isFallback: true,
        );
  }

  @override
  Future<LedgerCreateResult> createEntry({
    required int amountMinor,
    required String direction,
    required String idempotencyKey,
    String? categoryId,
    DateTime? occurredAt,
    String? note,
  }) async {
    createCalls++;
    createdAmounts.add(amountMinor);
    createdCategories.add(categoryId);
    createdKeys.add(idempotencyKey);
    if (createGate != null) await createGate!.future;
    if (createFails) throw Exception('create down');
    return const LedgerCreateResult(id: 'ent-1');
  }
}

Widget _host(Widget child) => MaterialApp(theme: buildAppTheme(), home: child);

/// 33 页信息流长于一屏（8 段 + 键盘），把测试面拉到手机高屏，避免键盘/保存键落在视口外。
void _useTallSurface(WidgetTester tester) {
  tester.view.physicalSize = const Size(390, 1500);
  tester.view.devicePixelRatio = 1;
  addTearDown(tester.view.reset);
}

Future<void> _openEntryPage(WidgetTester tester, LedgerRepository repo) async {
  _useTallSurface(tester);
  await tester.pumpWidget(
    _host(
      Builder(
        builder: (context) => Scaffold(
          body: Center(
            child: TextButton(
              onPressed: () => Navigator.of(context).push(
                MaterialPageRoute<void>(
                  builder: (_) => LedgerAddPage(repository: repo),
                ),
              ),
              child: const Text('open'),
            ),
          ),
        ),
      ),
    ),
  );
  await tester.tap(find.text('open'));
  await tester.pump();
  await tester.pump(const Duration(milliseconds: 400));
}

Future<void> _typeAmount(WidgetTester tester, String digits) async {
  for (final key in digits.split('')) {
    await tester.tap(find.text(key));
    await tester.pump();
  }
}

Future<void> _typeNote(WidgetTester tester, String note) async {
  await tester.tap(find.text('备注'));
  await tester.pump();
  await tester.enterText(find.byType(TextField), note);
  await tester.pump(const Duration(milliseconds: 50));
}

void main() {
  testWidgets('test_ledger_add_renders_eight_sections_in_order',
      (tester) async {
    await _openEntryPage(tester, _FakeLedgerRepository());
    final listView = tester.widget<ListView>(find.byType(ListView));
    final children =
        (listView.childrenDelegate as SliverChildListDelegate).children;
    final types = children.map((child) => child.runtimeType.toString()).toList();
    const expected = [
      'BackLink',
      'LedgerSeg',
      'LedgerAmount',
      'LedgerKindGrid',
      'LedgerFormRows',
      'AiCard',
      'LedgerPad',
      'LedgerSaveButton',
    ];
    final indices = [for (final name in expected) types.indexOf(name)];
    expect(indices.contains(-1), isFalse, reason: '$types');
    final sorted = [...indices]..sort();
    expect(indices, sorted, reason: '$types');
  });

  testWidgets('test_ledger_add_seg_income_reloads_categories_with_kind',
      (tester) async {
    final repo = _FakeLedgerRepository();
    await _openEntryPage(tester, repo);
    expect(repo.requestedKinds, ['expense']);
    await tester.tap(find.text('收入'));
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 50));
    expect(repo.requestedKinds, ['expense', 'income']);
    expect(find.text('工资'), findsOneWidget);
  });

  testWidgets('test_ledger_add_amount_submits_integer_minor', (tester) async {
    final repo = _FakeLedgerRepository();
    await _openEntryPage(tester, repo);
    await _typeAmount(tester, '35');
    await tester.tap(find.text('保存这一笔'));
    await tester.pump();
    expect(repo.createdAmounts, [3500]);
    expect(repo.createdAmounts.single, isA<int>());
  });

  testWidgets('test_ledger_add_note_preview_is_debounced', (tester) async {
    final repo = _FakeLedgerRepository();
    await _openEntryPage(tester, repo);
    await tester.tap(find.text('备注'));
    await tester.pump();
    for (final text in const ['一', '一碗', '一碗拉', '一碗拉面', '一碗拉面 35']) {
      await tester.enterText(find.byType(TextField), text);
      await tester.pump(const Duration(milliseconds: 50));
    }
    await tester.pump(const Duration(milliseconds: 400));
    expect(repo.previewCalls, 1);
  });

  testWidgets('test_ledger_add_preview_failure_is_silent', (tester) async {
    final repo = _FakeLedgerRepository(previewFails: true);
    await _openEntryPage(tester, repo);
    await _typeNote(tester, '一碗拉面 35');
    await tester.pump(const Duration(milliseconds: 400));
    expect(find.byType(ErrorState), findsNothing);
    expect(
      find.text('写下备注，我会帮你自动匹配分类，下次同类消费直接记住'),
      findsOneWidget,
    );
    expect(tester.takeException(), isNull);
  });

  testWidgets(
      'test_ledger_add_preview_reports_match_without_selecting_category',
      (tester) async {
    final repo = _FakeLedgerRepository(
      preview: const LedgerPreviewData(
        matched: true,
        categoryName: '餐饮',
        reason: 'alias',
        isFallback: false,
        categoryId: 'c-food',
      ),
    );
    await _openEntryPage(tester, repo);
    await _typeNote(tester, '一碗拉面');
    await tester.pump(const Duration(milliseconds: 400));
    expect(find.text('我的判断：餐饮，下次同类消费直接记住'), findsOneWidget);
    final grid = tester.widget<LedgerKindGrid>(find.byType(LedgerKindGrid));
    expect(grid.selectedKey, isNull);
  });

  testWidgets('test_ledger_add_save_is_disabled_while_pending', (tester) async {
    final repo = _FakeLedgerRepository()..createGate = Completer<void>();
    await _openEntryPage(tester, repo);
    await _typeAmount(tester, '35');
    for (var i = 0; i < 3; i++) {
      await tester.tap(find.text('保存这一笔'));
      await tester.pump();
    }
    expect(repo.createCalls, 1);
    repo.createGate!.complete();
    await tester.pump();
  });

  testWidgets('test_ledger_add_save_keeps_same_idempotency_key_on_retry',
      (tester) async {
    final repo = _FakeLedgerRepository(createFails: true);
    await _openEntryPage(tester, repo);
    await _typeAmount(tester, '35');
    await tester.tap(find.text('保存这一笔'));
    await tester.pump();
    repo.createFails = false;
    await tester.tap(find.text('再试一次'));
    await tester.pump();
    expect(repo.createdKeys.length, 2);
    expect(repo.createdKeys.first, repo.createdKeys.last);
  });

  testWidgets('test_ledger_add_save_failure_shows_retry', (tester) async {
    final repo = _FakeLedgerRepository(createFails: true);
    await _openEntryPage(tester, repo);
    await _typeAmount(tester, '35');
    await tester.tap(find.text('保存这一笔'));
    await tester.pump();
    expect(find.byType(LedgerAddPage), findsOneWidget);
    expect(find.text('再试一次'), findsOneWidget);
    expect(find.text('保存这一笔'), findsOneWidget);
  });

  testWidgets('test_ledger_add_save_pops_on_success', (tester) async {
    _useTallSurface(tester);
    final repo = _FakeLedgerRepository();
    bool? popped;
    await tester.pumpWidget(
      _host(
        Builder(
          builder: (context) => Scaffold(
            body: Center(
              child: TextButton(
                onPressed: () async {
                  popped = await Navigator.of(context).push<bool>(
                    MaterialPageRoute<bool>(
                      builder: (_) => LedgerAddPage(repository: repo),
                    ),
                  );
                },
                child: const Text('open'),
              ),
            ),
          ),
        ),
      ),
    );
    await tester.tap(find.text('open'));
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 400));
    await _typeAmount(tester, '35');
    await tester.tap(find.text('保存这一笔'));
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 400));
    await tester.pump(const Duration(milliseconds: 400));
    expect(popped, isTrue);
    expect(find.byType(LedgerAddPage), findsNothing);
  });

  testWidgets('test_ledger_add_selected_category_is_submitted', (tester) async {
    final repo = _FakeLedgerRepository();
    await _openEntryPage(tester, repo);
    await tester.tap(find.text('餐饮'));
    await tester.pump();
    await _typeAmount(tester, '35');
    await tester.tap(find.text('保存这一笔'));
    await tester.pump();
    expect(repo.createdCategories, ['c-food']);
  });

  test('test_ledger_add_never_imports_dio', () {
    final source =
        File('lib/features/ledger/presentation/ledger_add_page.dart')
            .readAsStringSync();
    expect(source.contains('package:dio'), isFalse);
  });

  testWidgets('test_ledger_add_golden', (tester) async {
    _useTallSurface(tester);
    final repo = _FakeLedgerRepository();
    await tester.pumpWidget(_host(LedgerAddPage(repository: repo)));
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 50));
    await _typeAmount(tester, '35');
    await tester.pump(const Duration(milliseconds: 16));
    await expectLater(
      find.byType(Scaffold),
      matchesGoldenFile('goldens/ledger_add.png'),
    );
  });
}
