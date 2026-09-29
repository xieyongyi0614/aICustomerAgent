import 'package:health/health.dart';

/// PLT-001 手环实机验证探针（数据层）：
/// 采集 Mi Fitness → Health Connect 的写入证据（P1）、可读字段（P2）与同步延迟（P3）。
/// 交付面是「证据 + 报告草稿」，不是产品读数链路（那是 APP-023）。
class ProbeTypeSpec {
  const ProbeTypeSpec({
    required this.label,
    required this.type,
    required this.unitHint,
    required this.permission,
  });

  final String label;
  final HealthDataType type;
  final String unitHint;
  final String permission;
}

/// 字段基线 = research/personal-ai-butler-miband/REPORT.md §2.3 的 Health Connect
/// 可读类型清单 + Health Connect 侧补充列（消耗 / 楼层 / 活动强度）。
/// HRV 在 Health Connect 仅 RMSSD 口径（SDNN 为 iOS 专属）；
/// VO2_MAX 属调研基线但 health 包未暴露，探针侧按「实测缺失」处理，不在采集列。
const probeTypeSpecs = <ProbeTypeSpec>[
  ProbeTypeSpec(
    label: '步数',
    type: HealthDataType.STEPS,
    unitHint: 'count',
    permission: 'android.permission.health.READ_STEPS',
  ),
  ProbeTypeSpec(
    label: '距离',
    type: HealthDataType.DISTANCE_DELTA,
    unitHint: 'm',
    permission: 'android.permission.health.READ_DISTANCE',
  ),
  ProbeTypeSpec(
    label: '心率',
    type: HealthDataType.HEART_RATE,
    unitHint: 'bpm',
    permission: 'android.permission.health.READ_HEART_RATE',
  ),
  ProbeTypeSpec(
    label: '静息心率',
    type: HealthDataType.RESTING_HEART_RATE,
    unitHint: 'bpm',
    permission: 'android.permission.health.READ_RESTING_HEART_RATE',
  ),
  ProbeTypeSpec(
    label: '血氧 SpO2',
    type: HealthDataType.BLOOD_OXYGEN,
    unitHint: '%',
    permission: 'android.permission.health.READ_OXYGEN_SATURATION',
  ),
  ProbeTypeSpec(
    label: '心率变异性 HRV（RMSSD）',
    type: HealthDataType.HEART_RATE_VARIABILITY_RMSSD,
    unitHint: 'ms',
    permission: 'android.permission.health.READ_HEART_RATE_VARIABILITY',
  ),
  ProbeTypeSpec(
    label: '呼吸频率',
    type: HealthDataType.RESPIRATORY_RATE,
    unitHint: 'breaths/min',
    permission: 'android.permission.health.READ_RESPIRATORY_RATE',
  ),
  ProbeTypeSpec(
    label: '体温',
    type: HealthDataType.BODY_TEMPERATURE,
    unitHint: '°C',
    permission: 'android.permission.health.READ_BODY_TEMPERATURE',
  ),
  ProbeTypeSpec(
    label: '皮温（Health Connect）',
    type: HealthDataType.SKIN_TEMPERATURE,
    unitHint: '°C',
    permission: 'android.permission.health.READ_SKIN_TEMPERATURE',
  ),
  ProbeTypeSpec(
    label: '睡眠段',
    type: HealthDataType.SLEEP_SESSION,
    unitHint: 'min',
    permission: 'android.permission.health.READ_SLEEP',
  ),
  ProbeTypeSpec(
    label: '睡眠分期·深睡',
    type: HealthDataType.SLEEP_DEEP,
    unitHint: 'min',
    permission: 'android.permission.health.READ_SLEEP',
  ),
  ProbeTypeSpec(
    label: '睡眠分期·浅睡',
    type: HealthDataType.SLEEP_LIGHT,
    unitHint: 'min',
    permission: 'android.permission.health.READ_SLEEP',
  ),
  ProbeTypeSpec(
    label: '睡眠分期·REM',
    type: HealthDataType.SLEEP_REM,
    unitHint: 'min',
    permission: 'android.permission.health.READ_SLEEP',
  ),
  ProbeTypeSpec(
    label: '体重',
    type: HealthDataType.WEIGHT,
    unitHint: 'kg',
    permission: 'android.permission.health.READ_WEIGHT',
  ),
  ProbeTypeSpec(
    label: '运动记录',
    type: HealthDataType.WORKOUT,
    unitHint: 'session',
    permission: 'android.permission.health.READ_EXERCISE',
  ),
  ProbeTypeSpec(
    label: '活动消耗',
    type: HealthDataType.TOTAL_CALORIES_BURNED,
    unitHint: 'kcal',
    permission: 'android.permission.health.READ_TOTAL_CALORIES_BURNED',
  ),
  ProbeTypeSpec(
    label: '爬楼层数',
    type: HealthDataType.FLIGHTS_CLIMBED,
    unitHint: 'count',
    permission: 'android.permission.health.READ_FLOORS_CLIMBED',
  ),
  ProbeTypeSpec(
    label: '活动强度',
    type: HealthDataType.ACTIVITY_INTENSITY,
    unitHint: 'min',
    permission: 'android.permission.health.READ_ACTIVITY_INTENSITY',
  ),
];

const miFitnessPackage = 'com.xiaomi.wearable';

const _sourceDisplayNames = <String, String>{
  miFitnessPackage: 'Mi Fitness（小米运动健康）',
  'nodomain.freeyourgadget.gadgetbridge': 'Gadgetbridge',
  'com.huami.watch.hmwatchmanager': 'Zepp Life',
  'com.google.android.apps.fitness': 'Google Fit',
};

String sourceDisplayName(String sourceId) =>
    _sourceDisplayNames[sourceId] ?? sourceId;

class ProbeRow {
  const ProbeRow({
    required this.spec,
    required this.granted,
    this.count = 0,
    this.latest,
    this.sourceIds = const <String>{},
    this.error,
  });

  final ProbeTypeSpec spec;
  final bool granted;
  final int count;
  final HealthDataPoint? latest;
  final Set<String> sourceIds;
  final String? error;

  bool get hasData => count > 0 && latest != null;

  String get latestValueText {
    final value = latest?.value;
    if (value is! NumericHealthValue) return value?.toString() ?? '—';
    final n = value.numericValue;
    return n % 1 == 0 ? n.toInt().toString() : n.toStringAsFixed(2);
  }
}

class ProbeSnapshot {
  const ProbeSnapshot({
    required this.rows,
    required this.generatedAt,
    required this.windowDays,
    required this.healthConnectAvailable,
  });

  final List<ProbeRow> rows;
  final DateTime generatedAt;
  final int windowDays;
  final bool healthConnectAvailable;

  Set<String> get sourceIds =>
      rows.expand((row) => row.sourceIds).toSet();

  bool get miFitnessWritten => sourceIds.contains(miFitnessPackage);

  bool get hasAnyData => rows.any((row) => row.hasData);

  List<ProbeRow> get miFitnessRows =>
      rows.where((row) => row.sourceIds.contains(miFitnessPackage)).toList();

  /// P1 的探针侧证据；最终判定仍须到 Health Connect「数据来源」人工复核。
  String get p1Evidence {
    if (miFitnessWritten) {
      final fields = miFitnessRows.map((row) => row.spec.label).join('、');
      return '检测到 Mi Fitness（$miFitnessPackage）写入的字段：$fields。'
          '原生写入证据成立，请再到 Health Connect「数据来源」人工复核。';
    }
    if (hasAnyData) {
      final others = sourceIds.map(sourceDisplayName).join('、');
      return '窗口内有数据但来源为：$others，未见 $miFitnessPackage。'
          '请确认 Mi Fitness 内「同步到健康平台」开关与区域版本。';
    }
    if (rows.any((row) => row.granted)) {
      return '已授权但窗口内未读到任何数据。请检查手环佩戴、Mi Fitness 同步开关，'
          '并在 Health Connect「数据来源」核对是否出现 Mi Fitness。';
    }
    return '未获得读权限或 Health Connect 不可用。请先完成授权再读。';
  }
}

class LatencySample {
  const LatencySample({
    required this.takenAt,
    required this.spec,
    required this.recordEnd,
    required this.valueText,
  });

  final DateTime takenAt;
  final ProbeTypeSpec spec;
  final DateTime recordEnd;
  final String valueText;

  Duration get age => takenAt.difference(recordEnd);

  String get bucket => latencyBucket(age);
}

/// PLT-001 §4.1.4 延迟分档；「仅手动触发」由人工判读（页面上每次都需手点才会出现）。
String latencyBucket(Duration age) {
  if (age <= const Duration(minutes: 5)) return '实时（≤5min）';
  if (age <= const Duration(hours: 1)) return '近实时（≤1h）';
  return '延迟（>1h）';
}

class HealthConnectProbe {
  HealthConnectProbe({Health? health}) : _health = health ?? Health();

  final Health _health;

  Future<bool> healthConnectAvailable() =>
      _health.isHealthConnectAvailable();

  Future<void> installHealthConnect() => _health.installHealthConnect();

  Future<bool> requestAuthorization() => _health.requestAuthorization(
        probeTypeSpecs.map((spec) => spec.type).toList(),
      );

  Future<Map<HealthDataType, bool>> grantedByType() async {
    final grants = <HealthDataType, bool>{};
    for (final spec in probeTypeSpecs) {
      grants[spec.type] = await _health.hasPermissions([spec.type]) ?? false;
    }
    return grants;
  }

  Future<ProbeSnapshot> readSnapshot({int windowDays = 7}) async {
    final generatedAt = DateTime.now();
    final available = await healthConnectAvailable();
    if (!available) {
      return ProbeSnapshot(
        rows: probeTypeSpecs
            .map((spec) => ProbeRow(
                  spec: spec,
                  granted: false,
                  error: 'Health Connect 不可用',
                ))
            .toList(),
        generatedAt: generatedAt,
        windowDays: windowDays,
        healthConnectAvailable: false,
      );
    }
    final grants = await grantedByType();
    final end = generatedAt;
    final start = end.subtract(Duration(days: windowDays));
    final rows = <ProbeRow>[];
    for (final spec in probeTypeSpecs) {
      if (grants[spec.type] != true) {
        rows.add(ProbeRow(spec: spec, granted: false));
        continue;
      }
      try {
        final points = await _health.getHealthDataFromTypes(
          types: [spec.type],
          startTime: start,
          endTime: end,
        );
        points.sort((a, b) => a.dateTo.compareTo(b.dateTo));
        rows.add(ProbeRow(
          spec: spec,
          granted: true,
          count: points.length,
          latest: points.isEmpty ? null : points.last,
          sourceIds: points.map((point) => point.sourceId).toSet(),
        ));
      } catch (error) {
        rows.add(ProbeRow(spec: spec, granted: true, error: error.toString()));
      }
    }
    return ProbeSnapshot(
      rows: rows,
      generatedAt: generatedAt,
      windowDays: windowDays,
      healthConnectAvailable: true,
    );
  }

  Future<LatencySample?> sampleLatest(ProbeTypeSpec spec) async {
    final takenAt = DateTime.now();
    final points = await _health.getHealthDataFromTypes(
      types: [spec.type],
      startTime: takenAt.subtract(const Duration(days: 1)),
      endTime: takenAt,
    );
    if (points.isEmpty) return null;
    points.sort((a, b) => a.dateTo.compareTo(b.dateTo));
    final latest = points.last;
    final value = latest.value;
    final valueText = value is NumericHealthValue
        ? value.numericValue.toString()
        : value.toString();
    return LatencySample(
      takenAt: takenAt,
      spec: spec,
      recordEnd: latest.dateTo,
      valueText: valueText,
    );
  }
}

String _formatTime(DateTime time) {
  String two(int v) => v.toString().padLeft(2, '0');
  return '${two(time.month)}-${two(time.day)} ${two(time.hour)}:${two(time.minute)}';
}

/// 生成 PLT-001 报告草稿（探针可自动采集部分）；环境字段与 P3 的
/// 「数据产生时刻」留【待填】由人工补记。
String probeReportText(
  ProbeSnapshot snapshot,
  List<LatencySample> latencySamples,
) {
  final buffer = StringBuffer()
    ..writeln('# PLT-001 探针采集草稿')
    ..writeln()
    ..writeln('- 生成时刻：${snapshot.generatedAt.toIso8601String()}')
    ..writeln('- 读取窗口：近 ${snapshot.windowDays} 天')
    ..writeln('- Health Connect 可用：${snapshot.healthConnectAvailable ? '是' : '否'}')
    ..writeln('- 数据来源：${snapshot.sourceIds.isEmpty ? '无' : snapshot.sourceIds.map(sourceDisplayName).join('、')}')
    ..writeln()
    ..writeln('## P1 原生写入（探针证据）')
    ..writeln()
    ..writeln(snapshot.p1Evidence)
    ..writeln()
    ..writeln('## P2 字段清单')
    ..writeln()
    ..writeln('| 字段 | HealthDataType | 授权 | 条数 | 最新值 | 最新时刻 | 来源 |')
    ..writeln('|---|---|---|---|---|---|---|');
  for (final row in snapshot.rows) {
    buffer.writeln(
      '| ${row.spec.label} | ${row.spec.type.name} | ${row.granted ? '是' : '否'} '
      '| ${row.count} | ${row.hasData ? row.latestValueText : '—'} '
      '| ${row.latest != null ? _formatTime(row.latest!.dateTo) : '—'} '
      '| ${row.sourceIds.isEmpty ? '—' : row.sourceIds.map(sourceDisplayName).join('、')} |',
    );
  }
  buffer
    ..writeln()
    ..writeln('## P3 延迟采样')
    ..writeln();
  if (latencySamples.isEmpty) {
    buffer.writeln('（未采样。在探针页选定类目后点「延迟采样」，产生数据后对照手环补记产生时刻。）');
  } else {
    buffer
      ..writeln('| 数据类目 | 记录结束时刻 | 采样时刻 | 数据龄 | 档位 |')
      ..writeln('|---|---|---|---|---|');
    for (final sample in latencySamples) {
      buffer.writeln(
        '| ${sample.spec.label} | ${_formatTime(sample.recordEnd)} '
        '| ${_formatTime(sample.takenAt)} | ${sample.age.inMinutes}min '
        '| ${sample.bucket} |',
      );
    }
  }
  buffer
    ..writeln()
    ..writeln('## 环境（人工补记，PLT-001 §4.1.2）')
    ..writeln()
    ..writeln('- 手环：小米手环 9 Pro（固件【待填】）')
    ..writeln('- 手机型号：【待填】')
    ..writeln('- Android 版本（含补丁）：【待填】')
    ..writeln('- Mi Fitness 版本与商店来源：【待填】')
    ..writeln('- 区域版本：【待填：国内版 / 国际版】')
    ..writeln('- Health Connect 版本：【待填】')
    ..writeln()
    ..writeln('> 非医疗建议，请咨询医生');
  return buffer.toString();
}
