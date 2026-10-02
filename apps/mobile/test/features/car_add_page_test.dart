import 'dart:async';

import 'package:dio/dio.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:mobile/app/theme/app_theme.dart';
import 'package:mobile/design_system/components/components.dart';
import 'package:mobile/features/car/data/car_repository.dart';
import 'package:mobile/features/car/domain/car_models.dart';
import 'package:mobile/features/car/presentation/car_add_page.dart';

class _FakeCarRepository extends CarRepository {
  _FakeCarRepository({this.createFails = false}) : super(dio: Dio());

  bool createFails;
  Completer<void>? createGate;
  int createCalls = 0;
  final List<String> kinds = [];
  final List<int?> amounts = [];
  final List<String?> notes = [];
  final List<int?> odometers = [];
  final List<String?> places = [];
  final List<String> keys = [];

  @override
  Future<CarProfileData> fetchProfile() async => const CarProfileData(
        files: [],
        services: [],
        reminders: [],
        identity: CarIdentityData(odometerKm: 12400),
      );

  @override
  Future<CarEntryResult> createEntry({
    required String kind,
    required String idempotencyKey,
    int? amountMinor,
    String? note,
    int? odometerKm,
    String? place,
  }) async {
    createCalls++;
    kinds.add(kind);
    amounts.add(amountMinor);
    notes.add(note);
    odometers.add(odometerKm);
    places.add(place);
    keys.add(idempotencyKey);
    if (createGate != null) await createGate!.future;
    if (createFails) throw Exception('create down');
    return CarEntryResult(
      kind: kind,
      categoryName: '充电',
      hint: carLinkageHintFallback,
      entryId: 'ent-1',
    );
  }
}

Widget _host(Widget child) => MaterialApp(theme: buildAppTheme(), home: child);

void _useTallSurface(WidgetTester tester) {
  tester.view.physicalSize = const Size(390, 2200);
  tester.view.devicePixelRatio = 1;
  addTearDown(tester.view.reset);
}

Future<void> _pumpPage(
  WidgetTester tester,
  _FakeCarRepository repo, {
  String? linkageHint,
}) async {
  _useTallSurface(tester);
  await tester.pumpWidget(
    _host(CarAddPage(repository: repo, linkageHint: linkageHint)),
  );
  await tester.pump();
  await tester.pump(const Duration(milliseconds: 50));
}

Future<void> _typeAmount(WidgetTester tester, String digits) async {
  for (final key in digits.split('')) {
    await tester.tap(find.text(key).last);
    await tester.pump();
  }
}

Future<void> _selectKind(WidgetTester tester, String key) async {
  final finder = find.byKey(TypeScroll.itemKey(key));
  await tester.ensureVisible(finder);
  await tester.pump();
  await tester.tap(finder);
  await tester.pump(const Duration(milliseconds: 16));
}

void main() {
  testWidgets('test_car_add_renders_sections_in_order', (tester) async {
    final repo = _FakeCarRepository();
    await _pumpPage(tester, repo);

    expect(find.text('车辆'), findsOneWidget);
    expect(find.byType(TypeScroll), findsOneWidget);
    expect(find.byType(LedgerAmount), findsOneWidget);
    expect(find.text('亚丝娜的提示'), findsOneWidget);
    expect(find.text('保存记录'), findsOneWidget);
    expect(find.textContaining('不用重复记'), findsOneWidget);
  });

  testWidgets('test_car_add_mileage_hides_amount_section', (tester) async {
    final repo = _FakeCarRepository();
    await _pumpPage(tester, repo);
    await _selectKind(tester, 'mileage');

    expect(find.byType(LedgerAmount), findsNothing);
    expect(find.byType(LedgerPad), findsNothing);
    expect(find.text('保存里程'), findsOneWidget);
    expect(find.text('总里程'), findsOneWidget);
    expect(find.text('12400 km'), findsOneWidget);

    await tester.enterText(find.byType(TextField).first, '80');
    await tester.pump();
    expect(find.text('12480 km'), findsOneWidget);

    await _tapSave(tester);
    expect(repo.kinds, ['mileage']);
    expect(repo.amounts, [null]);
    expect(repo.odometers, [12480]);
  });

  testWidgets('test_car_add_form_fields_switch_per_kind', (tester) async {
    final repo = _FakeCarRepository();
    await _pumpPage(tester, repo);

    expect(find.text('充电度数'), findsOneWidget);
    expect(find.text('充电站'), findsOneWidget);
    expect(find.text('当前里程'), findsOneWidget);

    await _selectKind(tester, 'parking');
    expect(find.text('地点'), findsOneWidget);
    expect(find.text('充电度数'), findsNothing);

    await _selectKind(tester, 'service');
    expect(find.text('保养项目'), findsOneWidget);
    expect(find.text('门店'), findsOneWidget);
  });

  testWidgets('test_car_add_charge_requires_kwh', (tester) async {
    final repo = _FakeCarRepository();
    await _pumpPage(tester, repo);
    await _typeAmount(tester, '42');
    await _tapSave(tester);

    expect(find.text('充电需要填度数'), findsOneWidget);
    expect(repo.createCalls, 0);
  });

  testWidgets('test_car_add_amount_submits_integer_minor', (tester) async {
    final repo = _FakeCarRepository();
    await _pumpPage(tester, repo);
    await _typeAmount(tester, '42.5');
    await tester.enterText(find.byType(TextField).first, '34.2');
    await _tapSave(tester);

    expect(repo.amounts, [4250]);
    expect(repo.notes.single, contains('34.2 kWh'));
  });

  testWidgets('test_car_add_save_is_disabled_while_pending', (tester) async {
    final repo = _FakeCarRepository()..createGate = Completer<void>();
    await _pumpPage(tester, repo);
    await _typeAmount(tester, '42');
    await tester.enterText(find.byType(TextField).first, '34.2');

    await tester.tap(find.text('保存记录'));
    await tester.pump();
    await tester.tap(find.text('保存记录'));
    await tester.pump();
    await tester.tap(find.text('保存记录'));
    await tester.pump();

    expect(repo.createCalls, 1);
    repo.createGate!.complete();
  });

  testWidgets('test_car_add_linkage_note_uses_server_hint', (tester) async {
    final repo = _FakeCarRepository();
    await _pumpPage(tester, repo, linkageHint: '服务端下发的联动口径');

    expect(find.text('服务端下发的联动口径'), findsOneWidget);
    expect(find.textContaining('不用重复记'), findsNothing);
  });

  testWidgets('test_car_add_linkage_note_fallback_is_honest', (tester) async {
    final repo = _FakeCarRepository();
    await _pumpPage(tester, repo);

    expect(find.text(carLinkageHintFallback), findsOneWidget);
    expect(carLinkageHintFallback.contains('不用重复记'), isTrue);
    expect(RegExp(r'\d').hasMatch(carLinkageHintFallback), isFalse);
  });

  testWidgets('test_car_add_ai_hint_absent_when_no_server_hint',
      (tester) async {
    final repo = _FakeCarRepository();
    await _pumpPage(tester, repo);

    final hint = tester.widget<Text>(find.textContaining('谷电')).data!;
    expect(RegExp(r'\d').hasMatch(hint), isFalse);
  });

  testWidgets('test_car_add_save_failure_does_not_pop', (tester) async {
    final repo = _FakeCarRepository(createFails: true);
    await _pumpPage(tester, repo);
    await _typeAmount(tester, '42');
    await tester.enterText(find.byType(TextField).first, '34.2');
    await _tapSave(tester);

    expect(find.byType(CarAddPage), findsOneWidget);
    expect(find.text(StateCopy.networkError), findsOneWidget);

    repo.createFails = false;
    await tester.tap(find.text(StateCopy.retryAction));
    await tester.pump();
    expect(repo.keys.toSet().length, 1);
  });

  testWidgets('test_car_add_golden', (tester) async {
    final repo = _FakeCarRepository();
    await _pumpPage(tester, repo);
    await _typeAmount(tester, '42');
    await tester.enterText(find.byType(TextField).first, '34.2');
    await expectLater(
      find.byType(Scaffold).first,
      matchesGoldenFile('goldens/car_add.png'),
    );
  });
}

Future<void> _tapSave(WidgetTester tester) async {
  final button = find.textContaining('保存');
  await tester.tap(button.last);
  await tester.pump();
  await tester.pump(const Duration(milliseconds: 50));
}
