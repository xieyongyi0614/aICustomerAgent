import 'package:dio/dio.dart';

import '../../../core/network/dio_client.dart';
import '../domain/car_models.dart';

/// 档案不变量违规（服务端 422）：表现层只认这个域异常，不引 dio。
class CarProfileValidationException implements Exception {
  const CarProfileValidationException(this.message);

  final String message;

  @override
  String toString() => message;
}

class CarRepository {
  CarRepository({Dio? dio}) : _dio = dio ?? createDio();

  static const profileValidationMessage = '这几项对不上：请检查里程、电池容量与保养周期';

  final Dio _dio;

  Future<CarOverviewData> fetchOverview() async {
    final resp = await _dio.get<Map<String, dynamic>>('/car/overview');
    final data = resp.data ?? const {};
    return CarOverviewData(
      profile: _profileSummary(data['profile'] as Map?),
      loan: _loan(data['loan'] as Map?),
      evMetrics: _evMetrics(data['ev_metrics'] as Map? ?? const {}),
      expenseBreakdown: _expenseLines(data['expense_breakdown'] as List?),
      expenseTotalMinor: data['expense_total_minor'] as int? ?? 0,
      expenseTotalText: data['expense_total_text'] as String? ?? '0.00',
      reminders: _reminders(data['reminders'] as List?),
      restrictionGuide: data['restriction_guide'] as String?,
      recentRecords: _recentRecords(data['recent_records'] as List?),
      degradedBlocks: [
        for (final block in (data['degraded_blocks'] as List?) ?? const [])
          block as String,
      ],
    );
  }

  Future<CarProfileData> fetchProfile() async {
    final resp = await _dio.get<Map<String, dynamic>>('/car/profile');
    return _profileData(resp.data ?? const {});
  }

  Future<CarProfileData> updateProfile(Map<String, dynamic> payload) async {
    try {
      final resp = await _dio.put<Map<String, dynamic>>(
        '/car/profile',
        data: payload,
      );
      return _profileData(resp.data ?? const {});
    } on DioException catch (e) {
      if (e.response?.statusCode == 422) {
        throw const CarProfileValidationException(profileValidationMessage);
      }
      rethrow;
    }
  }

  Future<CarEntryResult> createEntry({
    required String kind,
    required String idempotencyKey,
    int? amountMinor,
    String? note,
    int? odometerKm,
    String? place,
  }) async {
    final resp = await _dio.post<Map<String, dynamic>>(
      '/car/entries',
      data: {
        'kind': kind,
        'amount_minor': ?amountMinor,
        'note': ?note,
        'odometer_km': ?odometerKm,
        'place': ?place,
        'idempotency_key': idempotencyKey,
      },
    );
    final data = resp.data ?? const {};
    return CarEntryResult(
      kind: data['kind'] as String? ?? kind,
      categoryName: data['category_name'] as String? ?? '',
      hint: data['hint'] as String? ?? '',
      entryId: data['entry_id'] as String?,
      recordId: data['record_id'] as String?,
      odometerDeltaKm: data['odometer_delta_km'] as int?,
    );
  }

  Future<List<CarServiceRowData>> fetchServices({int limit = 20}) async {
    final resp = await _dio.get<Map<String, dynamic>>(
      '/car/services',
      queryParameters: {'limit': limit},
    );
    return _serviceRows(resp.data?['items'] as List?);
  }

  CarProfileSummary? _profileSummary(Map? raw) {
    if (raw == null) return null;
    return CarProfileSummary(
      model: raw['model'] as String?,
      plate: raw['plate'] as String?,
      odometerKm: raw['odometer_km'] as int? ?? 0,
    );
  }

  CarLoanData? _loan(Map? raw) {
    if (raw == null) return null;
    return CarLoanData(
      remainingText: raw['remaining_text'] as String? ?? '0.00',
      monthlyText: raw['monthly_text'] as String? ?? '0.00',
      paidPeriods: raw['paid_periods'] as int? ?? 0,
      totalPeriods: raw['total_periods'] as int? ?? 0,
      paidRatio: (raw['paid_ratio'] as num?)?.toDouble() ?? 0,
      badgeText: raw['next_due_at'] as String?,
      settledNote: raw['settled_at'] as String?,
    );
  }

  CarEvMetricsData _evMetrics(Map raw) => CarEvMetricsData(
        odometerKm: raw['odometer_km'] as int?,
        odometerDeltaMonth: raw['odometer_delta_month'] as int? ?? 0,
        chargeCostMinorMonth: raw['charge_cost_minor_month'] as int? ?? 0,
        chargeCostTextMonth: raw['charge_cost_text_month'] as String? ?? '0.00',
        chargeCountMonth: raw['charge_count_month'] as int? ?? 0,
        basis: raw['basis'] as String? ?? '',
        note: raw['note'] as String? ?? '',
      );

  List<CarExpenseLineData> _expenseLines(List? items) => [
        for (final raw in items ?? const [])
          CarExpenseLineData(
            categoryName: (raw as Map)['category_name'] as String? ?? '',
            netMinor: raw['net_minor'] as int? ?? 0,
            netText: raw['net_text'] as String? ?? '0.00',
            count: raw['count'] as int? ?? 0,
          ),
      ];

  List<CarReminderData> _reminders(List? items) => [
        for (final raw in items ?? const [])
          CarReminderData(
            kind: (raw as Map)['kind'] as String? ?? '',
            title: raw['title'] as String? ?? '',
            detail: raw['detail'] as String? ?? '',
            level: raw['level'] as String? ?? 'normal',
          ),
      ];

  List<CarRecentRecordData> _recentRecords(List? items) => [
        for (final raw in items ?? const [])
          CarRecentRecordData(
            kind: (raw as Map)['kind'] as String? ?? '',
            title: raw['title'] as String? ?? '',
            subtitle: raw['subtitle'] as String?,
            netMinor: raw['net_minor'] as int?,
            odometerDeltaKm: raw['odometer_delta_km'] as int?,
            occurredAt: raw['occurred_at'] as String? ?? '',
            source: raw['source'] as String? ?? '',
          ),
      ];

  List<CarServiceRowData> _serviceRows(List? items) => [
        for (final raw in items ?? const [])
          CarServiceRowData(
            id: (raw as Map)['id'] as String? ?? '',
            title: raw['title'] as String? ?? '',
            place: raw['place'] as String?,
            occurredAt: raw['occurred_at'] as String?,
            amountMinor: raw['amount_minor'] as int?,
            amountText: raw['amount_text'] as String?,
            odometerKm: raw['odometer_km'] as int?,
            upcoming: raw['upcoming'] as bool? ?? false,
            dueKm: raw['due_km'] as int?,
          ),
      ];

  CarProfileData _profileData(Map data) {
    final identityRaw = data['identity'] as Map?;
    return CarProfileData(
      identity: identityRaw == null
          ? null
          : CarIdentityData(
              model: identityRaw['model'] as String?,
              plate: identityRaw['plate'] as String?,
              trimNote: identityRaw['trim_note'] as String?,
              batteryKwh: (identityRaw['battery_kwh'] as num?)?.toDouble(),
              ageText: identityRaw['age_text'] as String?,
              odometerKm: identityRaw['odometer_km'] as int?,
            ),
      files: [
        for (final raw in (data['files'] as List?) ?? const [])
          CarFileData(
            key: (raw as Map)['key'] as String? ?? '',
            label: raw['label'] as String? ?? '',
            detail: raw['detail'] as String?,
            valueText: raw['value_text'] as String? ?? '',
          ),
      ],
      loan: _loan(data['loan'] as Map?),
      services: _serviceRows(data['services'] as List?),
      reminders: _reminders(data['reminders'] as List?),
      restrictionGuide: data['restriction_guide'] as String?,
    );
  }
}
