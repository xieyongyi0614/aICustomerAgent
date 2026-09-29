import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:mobile/app/theme/app_theme.dart';
import 'package:mobile/features/briefing/data/briefing_repository.dart';
import 'package:mobile/features/briefing/data/location_service.dart';
import 'package:mobile/features/briefing/presentation/briefing_page.dart';

BriefContentData _content() => const BriefContentData(
      type: 'morning',
      greeting: '08:00 · 早间简报',
      title: '早上好，今天交给我吧',
      orbNote: '今天晴，21°',
      cards: [
        BriefCardData(title: '天气', body: '21° 晴', note: '今日 15°~27° · 降水 10%'),
        BriefCardData(title: '任务', body: '2 项 · 已按你的节奏排好', note: '先从压力最小的一件开始'),
      ],
      cta: '开始今天',
    );

class _RecordingRepo extends BriefingRepository {
  _RecordingRepo({this.savedCity});

  final String? savedCity;
  final List<double?> fetchedLats = [];
  final List<String?> savedCities = [];

  @override
  Future<BriefContentData?> cachedBrief(String type) async => null;

  @override
  Future<BriefContentData> fetchBrief(
    String type, {
    double? lat,
    double? lon,
  }) async {
    fetchedLats.add(lat);
    return _content();
  }

  @override
  Future<BriefPrefsData> fetchPrefs() async => BriefPrefsData(city: savedCity);

  @override
  Future<BriefPrefsData> savePrefs({
    String? morningAt,
    String? eveningAt,
    String? city,
  }) async {
    savedCities.add(city);
    return BriefPrefsData(city: city);
  }
}

class _FixedLocation extends LocationService {
  int calls = 0;

  @override
  Future<CoordPair?> getCurrentCoords({
    Duration timeLimit = const Duration(seconds: 5),
  }) async {
    calls += 1;
    return const CoordPair(lat: 39.9042, lon: 116.4074);
  }
}

class _DeniedLocation extends LocationService {
  int calls = 0;

  @override
  Future<CoordPair?> getCurrentCoords({
    Duration timeLimit = const Duration(seconds: 5),
  }) async {
    calls += 1;
    return null;
  }
}

Future<void> _pump(
  WidgetTester tester,
  BriefingRepository repo,
  LocationService location,
) async {
  await tester.pumpWidget(
    MaterialApp(
      theme: buildAppTheme(),
      home: BriefingPage(
        type: 'morning',
        repository: repo,
        location: location,
      ),
    ),
  );
  // Orb 呼吸（4.2s 循环）永不停止，禁止 pumpAndSettle；定量 pump 冲刷异步链。
  for (var i = 0; i < 5; i++) {
    await tester.pump(const Duration(milliseconds: 120));
  }
}

/// 定量 pump 的测试内副本（避免测试依赖页面私有常量）。
Future<void> _flush(WidgetTester tester) async {
  for (var i = 0; i < 5; i++) {
    await tester.pump(const Duration(milliseconds: 120));
  }
}

void main() {
  testWidgets('renders server contract copy and cards without fabricating', (
    tester,
  ) async {
    final repo = _RecordingRepo(savedCity: null);
    await _pump(tester, repo, _DeniedLocation());

    expect(find.text('08:00 · 早间简报'), findsOneWidget);
    expect(find.text('早上好，今天交给我吧'), findsOneWidget);
    expect(find.text('今天晴，21°'), findsOneWidget);
    expect(find.text('21° 晴'), findsOneWidget);
    expect(find.text('2 项 · 已按你的节奏排好'), findsOneWidget);
    expect(find.text('开始今天'), findsOneWidget);
    expect(find.text('离线内容'), findsNothing);

    final weatherCard = tester.getTopLeft(find.text('21° 晴'));
    final taskCard = tester.getTopLeft(find.text('2 项 · 已按你的节奏排好'));
    expect(weatherCard.dy, lessThan(taskCard.dy));
  });

  testWidgets('uses device coords when no city preference saved', (tester) async {
    final repo = _RecordingRepo(savedCity: null);
    final location = _FixedLocation();
    await _pump(tester, repo, location);

    expect(location.calls, 1);
    expect(repo.fetchedLats.single, 39.9042);
  });

  testWidgets('skips device coords when a city preference is saved', (
    tester,
  ) async {
    final repo = _RecordingRepo(savedCity: '上海');
    final location = _FixedLocation();
    await _pump(tester, repo, location);

    expect(location.calls, 0);
    expect(repo.fetchedLats.single, isNull);
  });

  testWidgets('denied location still renders brief without coords', (
    tester,
  ) async {
    final repo = _RecordingRepo(savedCity: null);
    final location = _DeniedLocation();
    await _pump(tester, repo, location);

    expect(location.calls, 1);
    expect(repo.fetchedLats.single, isNull);
    expect(find.text('开始今天'), findsOneWidget);
  });

  testWidgets('city entry saves a new city and refreshes', (tester) async {
    final repo = _RecordingRepo(savedCity: null);
    await _pump(tester, repo, _FixedLocation());

    await tester.tap(find.text('天气按实时定位 · 点按设置'));
    await _flush(tester);
    await tester.enterText(find.byType(TextField), '北京');
    await tester.tap(find.text('保存'));
    await _flush(tester);

    expect(repo.savedCities.single, '北京');
  });
}
