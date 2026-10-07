import 'dart:convert';
import 'dart:io';

import 'package:dio/dio.dart';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:mobile/app/theme/app_theme.dart';
import 'package:mobile/design_system/components/components.dart';
import 'package:mobile/design_system/tokens/tokens.dart';
import 'package:mobile/features/car/data/car_model_catalog_repository.dart';
import 'package:mobile/features/car/data/car_repository.dart';
import 'package:mobile/features/car/domain/car_models.dart';
import 'package:mobile/features/car/presentation/car_profile_page.dart';

/// 车型目录用内存 bundle 注入：真实 assets 的读取是真实 IO，
/// 在 widget test 的 fake async 里会与 pump 抢时序，所以测试不依赖它。
const _catalogJson = '''
{
  "updated_at": "2026-10-07",
  "source": "test",
  "disclaimer": "test only",
  "models": [
    { "brand": "特斯拉", "series": "Model Y", "powertrain": "ev", "variants": [
      { "name": "后轮驱动版", "battery_kwh": 60.0 },
      { "name": "长续航全轮驱动版", "battery_kwh": 78.4 }
    ] },
    { "brand": "比亚迪", "series": "汉 EV", "powertrain": "ev", "variants": [
      { "name": "715km 尊贵型", "battery_kwh": 85.4 }
    ] },
    { "brand": "丰田", "series": "凯美瑞", "powertrain": "fuel" }
  ]
}
''';

class _MemoryBundle extends CachingAssetBundle {
  _MemoryBundle(this.json);

  final String json;

  @override
  Future<ByteData> load(String key) async =>
      ByteData.sublistView(Uint8List.fromList(utf8.encode(json)));
}

CarModelCatalogRepository _catalogRepo() =>
    CarModelCatalogRepository(bundle: _MemoryBundle(_catalogJson));

class _FakeCarRepository extends CarRepository {
  _FakeCarRepository({this.validationError = false}) : super(dio: Dio());

  bool validationError;
  int profileCalls = 0;
  int updateCalls = 0;
  String model = '比亚迪 汉 EV';
  final List<Map<String, dynamic>> payloads = [];

  @override
  Future<CarProfileData> fetchProfile() async {
    profileCalls++;
    return _profile(model);
  }

  @override
  Future<CarProfileData> updateProfile(Map<String, dynamic> payload) async {
    updateCalls++;
    payloads.add(payload);
    if (validationError) {
      throw const CarProfileValidationException(
        CarRepository.profileValidationMessage,
      );
    }
    model = payload['model'] as String? ?? model;
    return _profile(model);
  }
}

CarProfileData _profile(String model) => CarProfileData(
      identity: CarIdentityData(
        model: model,
        plate: '沪 A·D8F2K',
        trimNote: '715km 尊享型 · 2024 年 6 月上牌',
        batteryKwh: 85.4,
        ageText: '2 年 3 个月',
        odometerKm: 12480,
      ),
      files: const [
        CarFileData(
          key: 'insurance',
          label: '车辆保险',
          valueText: '2027-01-15 到期',
        ),
        CarFileData(key: 'inspection', label: '年检', valueText: '2027 年 04 月'),
        CarFileData(
          key: 'charger',
          label: '家用充电桩',
          valueText: '7 kW',
          detail: '家用 7 kW · 谷电',
        ),
        CarFileData(
          key: 'service_interval',
          label: '保养周期',
          valueText: '每 10,000 km 或 12 个月',
        ),
      ],
      loan: const CarLoanData(
        remainingText: '69300.00',
        monthlyText: '3850.00',
        paidPeriods: 18,
        totalPeriods: 36,
        paidRatio: 0.5,
      ),
      services: const [
        CarServiceRowData(
          id: 's-1',
          title: '小保养 · 机油机滤',
          upcoming: false,
          place: '华迪 4S 店',
          occurredAt: '2026-08-16T09:00:00',
          amountMinor: 20000,
          amountText: '200.00',
          odometerKm: 10380,
        ),
        CarServiceRowData(
          id: 's-2',
          title: '首保',
          upcoming: false,
          place: '厂家赠送',
          occurredAt: '2026-03-02T09:00:00',
          odometerKm: 5000,
        ),
        CarServiceRowData(
          id: 'car-next-service',
          title: '下一次保养',
          upcoming: true,
          dueKm: 13500,
        ),
      ],
      reminders: const [
        CarReminderData(
          kind: 'service',
          title: '下次保养',
          detail: '还剩 1,020 km',
          level: 'soon',
        ),
      ],
      restrictionGuide: '还没配置限行城市、尾号与限行日，配置后我会提前提醒',
    );

Widget _host(Widget child) => MaterialApp(theme: buildAppTheme(), home: child);

void _useTallSurface(WidgetTester tester) {
  tester.view.physicalSize = const Size(390, 2200);
  tester.view.devicePixelRatio = 1;
  addTearDown(tester.view.reset);
}

Future<void> _pumpPage(WidgetTester tester, _FakeCarRepository repo) async {
  _useTallSurface(tester);
  await tester.pumpWidget(
    _host(
      CarProfilePage(repository: repo, catalogRepository: _catalogRepo()),
    ),
  );
  await tester.pump();
  await tester.pump(const Duration(milliseconds: 50));
}

void main() {
  testWidgets('test_car_profile_renders_sections', (tester) async {
    final repo = _FakeCarRepository();
    await _pumpPage(tester, repo);

    expect(find.text('我的车'), findsOneWidget);
    expect(find.text('比亚迪 汉 EV'), findsOneWidget);
    expect(find.text('沪 A·D8F2K'), findsOneWidget);
    expect(find.text('车辆档案'), findsOneWidget);
    expect(find.text('车辆保险'), findsOneWidget);
    expect(find.text('2027-01-15 到期'), findsOneWidget);
    expect(find.text('保养记录'), findsOneWidget);
    expect(find.text('2 次'), findsOneWidget);
    expect(find.text('看本月养车账 →'), findsOneWidget);
    expect(find.byType(Timeline), findsOneWidget);
  });

  testWidgets('test_car_profile_subtitle_follows_d13_not_local_claim',
      (tester) async {
    final repo = _FakeCarRepository();
    await _pumpPage(tester, repo);

    final rendered = tester
        .widgetList<Text>(find.byType(Text))
        .map((widget) => widget.data ?? '')
        .join('|');
    expect(rendered.contains('都在本机'), isFalse);
    expect(rendered.contains('可随时查看、修改、删除'), isTrue);
  });

  testWidgets('test_car_profile_timeline_last_row_is_upcoming', (tester) async {
    final repo = _FakeCarRepository();
    await _pumpPage(tester, repo);

    final value = tester.widget<Text>(find.byKey(Timeline.valueKey(2)));
    expect(value.data, '13500 km');
    expect(value.style!.color, AppColors.light.inkOnSoon);
    expect(value.style!.fontSize, 12);
    expect(value.style!.fontWeight, FontWeight.w600);
    final row = tester.widget<Container>(find.byKey(Timeline.rowKey(2)));
    expect(row.decoration, isNull);
  });

  testWidgets('test_car_profile_timeline_free_row_shows_text_not_zero',
      (tester) async {
    final repo = _FakeCarRepository();
    await _pumpPage(tester, repo);

    expect(find.text('免费'), findsOneWidget);
    expect(find.text('¥0'), findsNothing);
    expect(find.text('¥0.00'), findsNothing);
  });

  testWidgets('test_car_profile_edit_rejects_invalid_invariant',
      (tester) async {
    final repo = _FakeCarRepository(validationError: true);
    await _pumpPage(tester, repo);

    await tester.tap(find.text('改档案'));
    await tester.pump();
    await tester.tap(find.text('保存档案'));
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 50));

    expect(find.text(CarRepository.profileValidationMessage), findsOneWidget);
    expect(find.byType(CarProfilePage), findsOneWidget);
    expect(repo.updateCalls, 1);
  });

  testWidgets('test_car_profile_reloads_after_edit', (tester) async {
    final repo = _FakeCarRepository();
    await _pumpPage(tester, repo);

    await tester.tap(find.text('改档案'));
    await tester.pump();
    await tester.tap(find.byKey(const ValueKey('car-profile-field-model')));
    await tester.pumpAndSettle();
    await tester.enterText(find.byKey(pickerSearchKey), '汉 EV 冠军版');
    await tester.pump();
    await tester.tap(find.text('用「汉 EV 冠军版」'));
    await tester.pumpAndSettle();

    await tester.tap(find.text('保存档案'));
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 50));

    expect(repo.payloads.single['model'], '汉 EV 冠军版');
    expect(repo.profileCalls, 2);
    expect(find.text('汉 EV 冠军版'), findsOneWidget);
    expect(find.text('改档案'), findsOneWidget);
  });

  testWidgets('test_car_profile_edit_action_is_a_full_width_button',
      (tester) async {
    final repo = _FakeCarRepository();
    await _pumpPage(tester, repo);

    final entry = tester.getSize(find.widgetWithText(LedgerSaveButton, '改档案'));
    expect(entry.width, greaterThan(200), reason: '改档案是整行按钮，不再是小 chip');
    expect(entry.height, greaterThanOrEqualTo(44),
        reason: '点按区不小于 44');
  });

  testWidgets('test_car_profile_without_identity_offers_fill_entry',
      (tester) async {
    _useTallSurface(tester);
    await tester.pumpWidget(
      _host(
        const CarProfilePage(
          debugProfile: CarProfileData(
            files: [],
            services: [],
            reminders: [],
          ),
        ),
      ),
    );
    await tester.pump();

    expect(find.text('还没有车辆档案，填一次我就替你记着'), findsOneWidget);
    expect(find.text('填写车辆档案'), findsOneWidget);
    expect(find.text('改档案'), findsNothing);
  });

  testWidgets('test_car_profile_edit_actions_keep_row_height', (tester) async {
    final repo = _FakeCarRepository();
    await _pumpPage(tester, repo);
    await tester.tap(find.text('改档案'));
    await tester.pump();

    final cancel = tester.getSize(find.widgetWithText(LedgerSaveButton, '取消'));
    final save = tester.getSize(find.widgetWithText(LedgerSaveButton, '保存档案'));
    expect(cancel.height, closeTo(save.height, 0.5));
    expect(cancel.width, save.width);
  });

  testWidgets('test_car_profile_model_row_picks_from_catalog', (tester) async {
    final repo = _FakeCarRepository();
    await _pumpPage(tester, repo);
    await tester.tap(find.text('改档案'));
    await tester.pump();

    await tester.tap(find.byKey(const ValueKey('car-profile-field-model')));
    await tester.pumpAndSettle();
    expect(find.text('选车型'), findsOneWidget);

    await tester.enterText(find.byKey(pickerSearchKey), '特斯拉');
    await tester.pump();
    expect(find.text('Model Y'), findsOneWidget);
    expect(find.text('汉 EV'), findsNothing, reason: '搜索按品牌过滤掉其它品牌');
    await tester.tap(find.text('Model Y'));
    await tester.pumpAndSettle();

    expect(find.text('选「Model Y」的版本'), findsOneWidget);
    await tester.tap(find.text('后轮驱动版'));
    await tester.pumpAndSettle();

    expect(find.text('特斯拉 Model Y'), findsOneWidget);
    expect(
      tester
          .widgetList<TextField>(find.byType(TextField))
          .any((field) => field.controller?.text == '60'),
      isTrue,
      reason: '选中版本后按参考值预填电池容量',
    );
    expect(find.text('已按「后轮驱动版」预填 60 kWh，参考值可改。'), findsOneWidget);
  });

  testWidgets('test_car_profile_date_row_uses_date_wheel', (tester) async {
    final repo = _FakeCarRepository();
    await _pumpPage(tester, repo);
    await tester.tap(find.text('改档案'));
    await tester.pump();

    await tester.tap(find.byKey(const ValueKey('car-profile-field-保险到期')));
    await tester.pumpAndSettle();
    expect(find.byType(WheelColumn), findsNWidgets(3));

    await tester.tap(find.text('完成'));
    await tester.pumpAndSettle();

    expect(find.text('2027-01-15'), findsOneWidget);
  });

  test('test_car_profile_source_has_no_local_claim_or_dio', () {
    final content = File(
      'lib/features/car/presentation/car_profile_page.dart',
    ).readAsStringSync();
    expect(content.contains('都在本机'), isFalse);
    expect(content.contains('package:dio'), isFalse);
    expect(content.contains('features/ledger'), isFalse);
  });

  testWidgets('test_car_profile_golden', (tester) async {
    final repo = _FakeCarRepository();
    await _pumpPage(tester, repo);
    await expectLater(
      find.byType(Scaffold).first,
      matchesGoldenFile('goldens/car_profile.png'),
    );
  });
}
