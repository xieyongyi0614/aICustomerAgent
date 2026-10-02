import 'package:flutter/material.dart';
import 'package:go_router/go_router.dart';

import '../../../app/theme/theme_context.dart';
import '../../../design_system/components/components.dart';
import '../data/car_repository.dart';
import '../domain/car_models.dart';

/// B12 #car 车辆：车贷进度 → 电车状态 → 养车支出 → 提醒 → 最近记录。
class CarPage extends StatefulWidget {
  const CarPage({super.key, this.repository, this.debugOverview});

  final CarRepository? repository;
  final CarOverviewData? debugOverview;

  @override
  State<CarPage> createState() => _CarPageState();
}

class _CarPageState extends State<CarPage> {
  late final CarRepository _repo = widget.repository ?? CarRepository();
  CarOverviewData? _overview;
  bool _loading = true;
  Object? _error;

  @override
  void initState() {
    super.initState();
    if (widget.debugOverview != null) {
      _overview = widget.debugOverview;
      _loading = false;
      return;
    }
    _load();
  }

  Future<void> _load() async {
    setState(() {
      _loading = true;
      _error = null;
    });
    try {
      final overview = await _repo.fetchOverview();
      if (!mounted) return;
      setState(() {
        _overview = overview;
        _loading = false;
      });
    } catch (e) {
      if (!mounted) return;
      setState(() {
        _error = e;
        _loading = false;
      });
    }
  }

  Future<void> _push(String location) async {
    await context.push<bool>(location);
    if (!mounted) return;
    await _load();
  }

  @override
  Widget build(BuildContext context) {
    final colors = context.colors;
    final type = context.typography;
    if (_loading && _overview == null) {
      return Scaffold(
        backgroundColor: colors.canvas,
        body: SafeArea(
          child: ListView(
            padding: const EdgeInsets.all(18),
            children: const [SkeletonCard(), SkeletonCard()],
          ),
        ),
      );
    }
    if (_error != null && _overview == null) {
      return Scaffold(
        backgroundColor: colors.canvas,
        body: SafeArea(child: ErrorState(onRetry: _load)),
      );
    }
    final overview = _overview!;
    final breakdownDegraded = overview.hasDegraded('expense_breakdown');
    final maxCost = overview.expenseBreakdown.fold<int>(
      0,
      (acc, line) => line.netMinor > acc ? line.netMinor : acc,
    );
    return Scaffold(
      backgroundColor: colors.canvas,
      body: SafeArea(
        child: RefreshIndicator(
          onRefresh: _load,
          child: ListView(
            padding: context.spacing.screenPadding.copyWith(bottom: 40),
            children: [
              BackLink(label: '生活'),
              if (overview.loan != null) ...[
                LoanCard(
                  label: '车贷 · 已还 ${overview.loan!.paidPeriods} / '
                      '${overview.loan!.totalPeriods} 期',
                  badgeText: _shortDate(overview.loan!.badgeText),
                  remainingText: '¥${overview.loan!.remainingText}',
                  subText: '月供 ¥${overview.loan!.monthlyText}',
                  progress: overview.loan!.paidRatio,
                  leftNote: '剩余待还',
                  rightNote: _shortDate(overview.loan!.settledNote) == null
                      ? null
                      : '${_shortDate(overview.loan!.settledNote)} 结清',
                ),
                const SizedBox(height: 14),
              ],
              AiCard(
                title: '亚丝娜的观察',
                child: Text(
                  _observation(overview),
                  style: type.body
                      .copyWith(color: colors.bodyOnCard, height: 1.65),
                ),
              ),
              const SizedBox(height: 20),
              _SectionTitle(title: '电车状态', hint: '本月'),
              const SizedBox(height: 10),
              Row(
                children: [
                  Expanded(
                    child: overview.evMetrics.chargeKwhMonth == null
                        ? MetricCard(
                            label: '本月充电费用 元',
                            value: _yuanText(
                              overview.evMetrics.chargeCostMinorMonth,
                            ),
                          )
                        : MetricCard(
                            label: '本月充电',
                            value: _kwhText(overview.evMetrics.chargeKwhMonth!),
                            unit: 'kWh',
                          ),
                  ),
                  const SizedBox(width: 9),
                  Expanded(
                    child: MetricCard(
                      label: '百公里电耗',
                      value: overview.evMetrics.kwhPer100km == null
                          ? '—'
                          : _kwhText(overview.evMetrics.kwhPer100km!),
                      unit: 'kWh',
                    ),
                  ),
                  const SizedBox(width: 9),
                  Expanded(
                    child: MetricCard(
                      label: '总里程',
                      value: overview.evMetrics.odometerKm == null
                          ? '—'
                          : _thousands(overview.evMetrics.odometerKm!),
                      unit: 'km',
                      note: '本月 +${overview.evMetrics.odometerDeltaMonth} km',
                    ),
                  ),
                ],
              ),
              const SizedBox(height: 8),
              Text(
                overview.evMetrics.note,
                style: type.caption.copyWith(color: colors.ink3),
              ),
              const SizedBox(height: 20),
              _SectionTitle(
                title: '本月养车支出',
                hint: breakdownDegraded
                    ? '暂时取不到'
                    : '合计 ¥${overview.expenseTotalText}',
              ),
              const SizedBox(height: 10),
              if (breakdownDegraded)
                Text('支出构成暂时取不到，下拉可重试',
                    style: type.body.copyWith(color: colors.ink2))
              else if (overview.expenseBreakdown.isEmpty)
                Text('本月还没有养车支出',
                    style: type.body.copyWith(color: colors.ink2))
              else
                for (var i = 0; i < overview.expenseBreakdown.length; i++)
                  CategoryBar(
                    label: overview.expenseBreakdown[i].categoryName,
                    amountLabel: '¥${overview.expenseBreakdown[i].netText}',
                    ratio: maxCost == 0
                        ? 0
                        : overview.expenseBreakdown[i].netMinor / maxCost,
                    gradient: _breakdownGradient(
                      overview.expenseBreakdown[i].categoryName,
                      i,
                    ),
                  ),
              const SizedBox(height: 20),
              _SectionTitle(title: '车辆提醒', hint: '我会提前告诉你'),
              const SizedBox(height: 6),
              if (overview.reminders.isEmpty)
                SettingGroup(
                  children: [
                    SettingRow(
                      title: '还没有可提醒的事项',
                      subtitle: overview.restrictionGuide ?? '补齐档案后我会替你盯着',
                      icon: AppIcons.timer,
                      showDivider: false,
                    ),
                  ],
                )
              else
                SettingGroup(
                  children: [
                    for (var i = 0; i < overview.reminders.length; i++)
                      SettingRow(
                        title: overview.reminders[i].title,
                        subtitle: overview.reminders[i].detail,
                        icon: _reminderIcon(overview.reminders[i].kind),
                        iconBg: overview.reminders[i].isSoon
                            ? colors.tileWarm
                            : colors.fillSubtle,
                        iconColor: overview.reminders[i].isSoon
                            ? colors.warm
                            : colors.ink2,
                        showDivider: i < overview.reminders.length - 1,
                      ),
                  ],
                ),
              if (overview.restrictionGuide != null) ...[
                const SizedBox(height: 8),
                Text(
                  overview.restrictionGuide!,
                  style: type.caption.copyWith(color: colors.ink3),
                ),
              ],
              const SizedBox(height: 12),
              _SectionTitle(title: '最近记录', hint: 'AI 自动分类'),
              const SizedBox(height: 6),
              if (overview.recentRecords.isEmpty)
                Text('还没有养车记录', style: type.body.copyWith(color: colors.ink2))
              else
                for (var i = 0; i < overview.recentRecords.length; i++)
                  TxRow(
                    title: overview.recentRecords[i].title,
                    subtitle: _recordSubtitle(overview.recentRecords[i]),
                    amountLabel: overview.recentRecords[i].isMileage
                        ? '${overview.recentRecords[i].odometerDeltaKm ?? 0} km'
                        : '-${_minorText(overview.recentRecords[i].netMinor!)}',
                    tileColor: _recordTile(colors, overview.recentRecords[i].kind),
                    iconColor: _recordForeground(
                      colors,
                      overview.recentRecords[i].kind,
                    ),
                    icon: _recordIcon(overview.recentRecords[i].kind),
                    showDivider: i < overview.recentRecords.length - 1,
                  ),
              const SizedBox(height: 20),
              EntryCard(
                title: '车辆档案',
                subtitle: overview.profile?.plate ?? '车型 · 车贷 · 保养周期',
                icon: AppIcons.fileText,
                accent: EntryAccent.ai,
                onTap: () => _push('/car/profile'),
              ),
              const SizedBox(height: 14),
              LedgerSaveButton(
                label: '＋ 记一笔养车费用',
                onPressed: () => _push('/car/add'),
              ),
            ],
          ),
        ),
      ),
    );
  }

  /// 35 页分类条：语义色优先（充电=green / 停车=blue / 过路=purple /
  /// 洗车保养加油=money），未识别类名按位置四色轮转。
  LinearGradient _breakdownGradient(String categoryName, int index) {
    final gradients = context.gradients;
    if (categoryName.contains('充电')) return gradients.barGreen;
    if (categoryName.contains('停车')) return gradients.barBlue;
    if (categoryName.contains('过路')) return gradients.barPurple;
    if (categoryName.contains('洗车') ||
        categoryName.contains('保养') ||
        categoryName.contains('加油')) {
      return gradients.barMoney;
    }
    return switch (index % 4) {
      0 => gradients.barMoney,
      1 => gradients.barBlue,
      2 => gradients.barPurple,
      _ => gradients.barGreen,
    };
  }

  Color _recordTile(AppColors colors, String kind) => switch (kind) {
        'charge' => colors.tileHealth,
        'parking' => colors.tileInfo,
        'mileage' => colors.tileMoney,
        'toll' => colors.tileAi,
        _ => colors.tileWarm,
      };

  Color _recordForeground(AppColors colors, String kind) => switch (kind) {
        'charge' => colors.health,
        'parking' => colors.aiBlue,
        'mileage' => colors.money,
        'toll' => colors.aiPrimary,
        _ => colors.warm,
      };

  String _observation(CarOverviewData overview) {
    if (overview.expenseTotalMinor == 0 && overview.reminders.isEmpty) {
      return '还没有养车数据，记一笔充电或保养，我就能替你盯着了。';
    }
    final top = overview.expenseBreakdown.isEmpty
        ? null
        : overview.expenseBreakdown.first;
    final parts = <String>[
      '本月养车花了 ¥${overview.expenseTotalText}',
      if (top != null) '其中${top.categoryName}最多（¥${top.netText}）',
    ];
    if (overview.reminders.isNotEmpty) {
      parts.add('有 ${overview.reminders.length} 件事我会提前提醒你');
    }
    return '${parts.join('，')}。';
  }

  IconData _reminderIcon(String kind) => switch (kind) {
        'insurance' => AppIcons.shield,
        'inspection' => AppIcons.calendar,
        'restriction' => AppIcons.parking,
        _ => AppIcons.wrench,
      };

  IconData _recordIcon(String kind) => switch (kind) {
        'charge' => AppIcons.zap,
        'fuel' => AppIcons.fuel,
        'parking' => AppIcons.parking,
        'toll' => AppIcons.ticket,
        'service' => AppIcons.wrench,
        'mileage' => AppIcons.gauge,
        _ => AppIcons.car,
      };

  String? _recordSubtitle(CarRecentRecordData record) {
    if (record.isMileage) return record.subtitle ?? _shortDate(record.occurredAt);
    final when = _shortDate(record.occurredAt);
    if (record.subtitle == null) return when;
    return '${record.subtitle} · $when';
  }
}

String? _shortDate(String? iso) {
  if (iso == null || iso.length < 16) return null;
  return iso.substring(5, 16).replaceFirst('T', ' ');
}

String _minorText(int minor) => (minor / 100).toStringAsFixed(2);

String _yuanText(int minor) => (minor / 100).round().toString();

String _kwhText(double kwh) =>
    kwh % 1 == 0 ? kwh.toStringAsFixed(0) : kwh.toStringAsFixed(1);

String _thousands(int value) {
  final digits = value.toString();
  final buffer = StringBuffer();
  for (var i = 0; i < digits.length; i++) {
    if (i > 0 && (digits.length - i) % 3 == 0) buffer.write(',');
    buffer.write(digits[i]);
  }
  return buffer.toString();
}

class _SectionTitle extends StatelessWidget {
  const _SectionTitle({required this.title, this.hint});

  final String title;
  final String? hint;

  @override
  Widget build(BuildContext context) {
    final colors = context.colors;
    final type = context.typography;
    return Row(
      children: [
        Text(title, style: type.sectionTitle),
        const Spacer(),
        if (hint != null)
          Text(hint!, style: type.caption.copyWith(color: colors.ink3)),
      ],
    );
  }
}
