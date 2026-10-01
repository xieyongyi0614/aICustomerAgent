/// 联动口径兜底文案：服务端未下发 hint 时使用，语义与 `API-020` 的下发文案一致。
const carLinkageHintFallback = '这笔费用会同时计入「生活 · 记账」的养车分类，不用重复记';

class CarLoanData {
  const CarLoanData({
    required this.remainingText,
    required this.monthlyText,
    required this.paidPeriods,
    required this.totalPeriods,
    required this.paidRatio,
    this.badgeText,
    this.settledNote,
  });

  final String remainingText;
  final String monthlyText;
  final int paidPeriods;
  final int totalPeriods;
  final double paidRatio;
  final String? badgeText;
  final String? settledNote;
}

class CarProfileSummary {
  const CarProfileSummary({
    this.model,
    this.plate,
    required this.odometerKm,
  });

  final String? model;
  final String? plate;
  final int odometerKm;
}

class CarExpenseLineData {
  const CarExpenseLineData({
    required this.categoryName,
    required this.netMinor,
    required this.netText,
    required this.count,
  });

  final String categoryName;
  final int netMinor;
  final String netText;
  final int count;
}

class CarRecentRecordData {
  const CarRecentRecordData({
    required this.kind,
    required this.title,
    required this.occurredAt,
    required this.source,
    this.subtitle,
    this.netMinor,
    this.odometerDeltaKm,
  });

  final String kind;
  final String title;
  final String occurredAt;
  final String source;
  final String? subtitle;
  final int? netMinor;
  final int? odometerDeltaKm;

  bool get isMileage => netMinor == null;
}

class CarReminderData {
  const CarReminderData({
    required this.kind,
    required this.title,
    required this.detail,
    required this.level,
  });

  final String kind;
  final String title;
  final String detail;
  final String level;

  bool get isSoon => level == 'soon';
}

class CarEvMetricsData {
  const CarEvMetricsData({
    required this.odometerKm,
    required this.odometerDeltaMonth,
    required this.chargeCostMinorMonth,
    required this.chargeCostTextMonth,
    required this.chargeCountMonth,
    required this.basis,
    required this.note,
  });

  final int? odometerKm;
  final int odometerDeltaMonth;
  final int chargeCostMinorMonth;
  final String chargeCostTextMonth;
  final int chargeCountMonth;
  final String basis;
  final String note;
}

class CarOverviewData {
  const CarOverviewData({
    required this.evMetrics,
    required this.expenseBreakdown,
    required this.expenseTotalMinor,
    required this.expenseTotalText,
    required this.reminders,
    required this.recentRecords,
    required this.degradedBlocks,
    this.profile,
    this.loan,
    this.restrictionGuide,
  });

  final CarProfileSummary? profile;
  final CarLoanData? loan;
  final CarEvMetricsData evMetrics;
  final List<CarExpenseLineData> expenseBreakdown;
  final int expenseTotalMinor;
  final String expenseTotalText;
  final List<CarReminderData> reminders;
  final String? restrictionGuide;
  final List<CarRecentRecordData> recentRecords;
  final List<String> degradedBlocks;

  bool hasDegraded(String block) => degradedBlocks.contains(block);
}

class CarIdentityData {
  const CarIdentityData({
    this.model,
    this.plate,
    this.trimNote,
    this.batteryKwh,
    this.ageText,
    this.odometerKm,
  });

  final String? model;
  final String? plate;
  final String? trimNote;
  final double? batteryKwh;
  final String? ageText;
  final int? odometerKm;
}

class CarFileData {
  const CarFileData({
    required this.key,
    required this.label,
    required this.valueText,
    this.detail,
  });

  final String key;
  final String label;
  final String valueText;
  final String? detail;
}

class CarServiceRowData {
  const CarServiceRowData({
    required this.id,
    required this.title,
    required this.upcoming,
    this.place,
    this.occurredAt,
    this.amountMinor,
    this.amountText,
    this.odometerKm,
    this.dueKm,
  });

  final String id;
  final String title;
  final bool upcoming;
  final String? place;
  final String? occurredAt;
  final int? amountMinor;
  final String? amountText;
  final int? odometerKm;
  final int? dueKm;
}

class CarProfileData {
  const CarProfileData({
    required this.files,
    required this.services,
    required this.reminders,
    this.identity,
    this.loan,
    this.restrictionGuide,
  });

  final CarIdentityData? identity;
  final List<CarFileData> files;
  final CarLoanData? loan;
  final List<CarServiceRowData> services;
  final List<CarReminderData> reminders;
  final String? restrictionGuide;
}

class CarEntryResult {
  const CarEntryResult({
    required this.kind,
    required this.categoryName,
    required this.hint,
    this.entryId,
    this.recordId,
    this.odometerDeltaKm,
  });

  final String kind;
  final String categoryName;
  final String hint;
  final String? entryId;
  final String? recordId;
  final int? odometerDeltaKm;
}
