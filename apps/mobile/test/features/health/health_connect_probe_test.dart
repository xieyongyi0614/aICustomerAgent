import 'package:flutter_test/flutter_test.dart';
import 'package:health/health.dart';
import 'package:mobile/features/health/data/health_connect_probe.dart';
import 'package:mocktail/mocktail.dart';

class _MockHealth extends Mock implements Health {}

HealthDataPoint _point({
  required HealthDataType type,
  required num value,
  required DateTime end,
  String sourceId = miFitnessPackage,
}) {
  return HealthDataPoint(
    uuid: 'u-$type-$value-${end.millisecondsSinceEpoch}-$sourceId',
    value: NumericHealthValue(numericValue: value),
    type: type,
    unit: dataTypeToUnit[type]!,
    dateFrom: end.subtract(const Duration(minutes: 1)),
    dateTo: end,
    sourcePlatform: HealthPlatformType.googleHealthConnect,
    sourceDeviceId: '',
    sourceId: sourceId,
    sourceName: sourceId,
  );
}

HealthDataType _specType(ProbeTypeSpec spec) => spec.type;

void main() {
  late _MockHealth health;
  late HealthConnectProbe probe;

  setUp(() {
    health = _MockHealth();
    probe = HealthConnectProbe(health: health);
    when(() => health.isHealthConnectAvailable()).thenAnswer((_) async => true);
    when(() => health.hasPermissions(any())).thenAnswer((_) async => true);
    when(
      () => health.getHealthDataFromTypes(
        types: any(named: 'types'),
        startTime: any(named: 'startTime'),
        endTime: any(named: 'endTime'),
      ),
    ).thenAnswer((_) async => <HealthDataPoint>[]);
  });

  group('probeTypeSpecs', () {
    test('每个采集类型都在 Health Connect（Android）支持清单内', () {
      for (final spec in probeTypeSpecs) {
        expect(dataTypeKeysAndroid, contains(spec.type), reason: spec.label);
      }
    });

    test('调研基线字段全部被覆盖（VO2_MAX 除外：health 包未暴露）', () {
      final types = probeTypeSpecs.map(_specType).toSet();
      expect(types, containsAll(<HealthDataType>[
        HealthDataType.STEPS,
        HealthDataType.DISTANCE_DELTA,
        HealthDataType.HEART_RATE,
        HealthDataType.BLOOD_OXYGEN,
        HealthDataType.HEART_RATE_VARIABILITY_RMSSD,
        HealthDataType.RESPIRATORY_RATE,
        HealthDataType.SLEEP_SESSION,
        HealthDataType.WEIGHT,
        HealthDataType.WORKOUT,
      ]));
    });

    test('权限常量与 Manifest 声明形态一致（android.permission.health.READ_*）', () {
      for (final spec in probeTypeSpecs) {
        expect(
          spec.permission,
          matches(RegExp(r'^android\.permission\.health\.READ_[A-Z_]+$')),
          reason: spec.label,
        );
      }
    });
  });

  group('readSnapshot', () {
    test('按类型聚合条数、最新数据点与来源集合', () async {
      final base = DateTime(2026, 9, 29, 10);
      when(
        () => health.getHealthDataFromTypes(
          types: any(named: 'types'),
          startTime: any(named: 'startTime'),
          endTime: any(named: 'endTime'),
        ),
      ).thenAnswer((invocation) async {
        final types =
            invocation.namedArguments[#types] as List<HealthDataType>;
        return switch (types.single) {
          HealthDataType.STEPS => <HealthDataPoint>[
              _point(type: HealthDataType.STEPS, value: 100, end: base),
              _point(
                type: HealthDataType.STEPS,
                value: 300,
                end: base.add(const Duration(hours: 2)),
                sourceId: 'com.google.android.apps.fitness',
              ),
              _point(
                type: HealthDataType.STEPS,
                value: 200,
                end: base.add(const Duration(hours: 1)),
              ),
            ],
          HealthDataType.HEART_RATE => <HealthDataPoint>[
              _point(
                type: HealthDataType.HEART_RATE,
                value: 72,
                end: base.add(const Duration(hours: 3)),
              ),
            ],
          _ => <HealthDataPoint>[],
        };
      });

      final snapshot = await probe.readSnapshot();

      final steps =
          snapshot.rows.singleWhere((row) => row.spec.type == HealthDataType.STEPS);
      expect(steps.count, 3);
      expect((steps.latest!.value as NumericHealthValue).numericValue, 300);
      expect(steps.sourceIds, contains(miFitnessPackage));
      expect(steps.sourceIds.length, 2);

      final heart = snapshot.rows
          .singleWhere((row) => row.spec.type == HealthDataType.HEART_RATE);
      expect(heart.count, 1);
      expect(heart.latestValueText, '72');

      final weight = snapshot.rows
          .singleWhere((row) => row.spec.type == HealthDataType.WEIGHT);
      expect(weight.hasData, isFalse);
      expect(weight.latestValueText, '—');
      expect(snapshot.miFitnessWritten, isTrue);
      expect(snapshot.sourceIds.length, 2);
    });

    test('未授权的类型不发起读取且标记未授权', () async {
      when(() => health.hasPermissions([HealthDataType.WEIGHT]))
          .thenAnswer((_) async => false);

      final snapshot = await probe.readSnapshot();

      final weight = snapshot.rows
          .singleWhere((row) => row.spec.type == HealthDataType.WEIGHT);
      expect(weight.granted, isFalse);
      expect(weight.count, 0);
      verifyNever(
        () => health.getHealthDataFromTypes(
          types: [HealthDataType.WEIGHT],
          startTime: any(named: 'startTime'),
          endTime: any(named: 'endTime'),
        ),
      );
    });

    test('单个类型读取异常被隔离在该行，不影响其余类型', () async {
      when(
        () => health.getHealthDataFromTypes(
          types: [HealthDataType.HEART_RATE],
          startTime: any(named: 'startTime'),
          endTime: any(named: 'endTime'),
        ),
      ).thenThrow(Exception('type not supported'));

      final snapshot = await probe.readSnapshot();

      final heart = snapshot.rows
          .singleWhere((row) => row.spec.type == HealthDataType.HEART_RATE);
      expect(heart.error, isNotNull);
      expect(heart.count, 0);
      expect(snapshot.rows.every((row) => row.spec.type == HealthDataType.HEART_RATE || row.error == null), isTrue);
    });

    test('Health Connect 不可用时返回全行不可用快照', () async {
      when(() => health.isHealthConnectAvailable()).thenAnswer((_) async => false);

      final snapshot = await probe.readSnapshot();

      expect(snapshot.healthConnectAvailable, isFalse);
      expect(snapshot.rows, hasLength(probeTypeSpecs.length));
      expect(snapshot.rows.every((row) => !row.granted && row.error != null), isTrue);
      verifyNever(() => health.hasPermissions(any()));
    });
  });

  group('P1 判定', () {
    test('来源含 Mi Fitness 包名时给出「写入成立」证据', () async {
      when(
        () => health.getHealthDataFromTypes(
          types: any(named: 'types'),
          startTime: any(named: 'startTime'),
          endTime: any(named: 'endTime'),
        ),
      ).thenAnswer((invocation) async {
        final types =
            invocation.namedArguments[#types] as List<HealthDataType>;
        return types.single == HealthDataType.STEPS
            ? <HealthDataPoint>[
                _point(type: HealthDataType.STEPS, value: 500, end: DateTime.now()),
              ]
            : <HealthDataPoint>[];
      });

      final snapshot = await probe.readSnapshot();

      expect(snapshot.p1Evidence, contains('Mi Fitness'));
      expect(snapshot.p1Evidence, contains(miFitnessPackage));
      expect(snapshot.p1Evidence, contains('步数'));
    });

    test('已授权但无任何数据时提示核对同步开关', () async {
      final snapshot = await probe.readSnapshot();

      expect(snapshot.miFitnessWritten, isFalse);
      expect(snapshot.hasAnyData, isFalse);
      expect(snapshot.p1Evidence, contains('未读到任何数据'));
    });
  });

  group('latencyBucket', () {
    test('按 PLT-001 §4.1.4 分档', () {
      expect(latencyBucket(const Duration(minutes: 4)), contains('实时'));
      expect(latencyBucket(const Duration(minutes: 5)), contains('实时'));
      expect(latencyBucket(const Duration(minutes: 6)), contains('近实时'));
      expect(latencyBucket(const Duration(minutes: 59)), contains('近实时'));
      expect(latencyBucket(const Duration(hours: 2)), contains('延迟'));
    });
  });

  group('sampleLatest', () {
    test('取最近一条数据并计算数据龄与档位', () async {
      final recordEnd = DateTime.now().subtract(const Duration(minutes: 12));
      when(
        () => health.getHealthDataFromTypes(
          types: any(named: 'types'),
          startTime: any(named: 'startTime'),
          endTime: any(named: 'endTime'),
        ),
      ).thenAnswer((_) async => <HealthDataPoint>[
            _point(type: HealthDataType.STEPS, value: 30, end: recordEnd),
            _point(
              type: HealthDataType.STEPS,
              value: 10,
              end: recordEnd.subtract(const Duration(hours: 1)),
            ),
          ]);

      final spec =
          probeTypeSpecs.singleWhere((s) => s.type == HealthDataType.STEPS);
      final sample = await probe.sampleLatest(spec);

      expect(sample, isNotNull);
      expect(sample!.recordEnd, recordEnd);
      expect(sample.age.inMinutes, inInclusiveRange(11, 13));
      expect(sample.bucket, contains('近实时'));
      expect(sample.valueText, '30');
    });

    test('窗口内无数据返回 null', () async {
      final spec =
          probeTypeSpecs.singleWhere((s) => s.type == HealthDataType.STEPS);
      expect(await probe.sampleLatest(spec), isNull);
    });
  });

  group('probeReportText', () {
    test('报告含 P1/P2/P3 段、来源、环境占位与医疗免责', () async {
      when(
        () => health.getHealthDataFromTypes(
          types: any(named: 'types'),
          startTime: any(named: 'startTime'),
          endTime: any(named: 'endTime'),
        ),
      ).thenAnswer((invocation) async {
        final types =
            invocation.namedArguments[#types] as List<HealthDataType>;
        return types.single == HealthDataType.STEPS
            ? <HealthDataPoint>[
                _point(type: HealthDataType.STEPS, value: 42, end: DateTime.now()),
              ]
            : <HealthDataPoint>[];
      });

      final snapshot = await probe.readSnapshot();
      final spec =
          probeTypeSpecs.singleWhere((s) => s.type == HealthDataType.STEPS);
      final sample = await probe.sampleLatest(spec);

      final report = probeReportText(snapshot, [?sample]);

      expect(report, contains('## P1'));
      expect(report, contains('## P2'));
      expect(report, contains('## P3'));
      expect(report, contains('| 步数 | STEPS |'));
      expect(report, contains(miFitnessPackage));
      expect(report, contains('【待填】'));
      expect(report, contains('非医疗建议，请咨询医生'));
    });

    test('无采样时 P3 段提示采样方法而非空表', () async {
      final snapshot = await probe.readSnapshot();
      expect(probeReportText(snapshot, const []), contains('未采样'));
    });
  });
}
