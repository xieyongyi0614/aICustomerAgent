import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../../app/state/album_summary_provider.dart';
import '../../../app/state/dynamic_tab.dart';
import '../../../app/theme/theme_context.dart';
import '../../../design_system/components/components.dart';
import '../data/life_repository.dart';
import 'dynamic_module_sheet.dart';

/// B4 #life：生活工具箱 —— 六格模块宫格；长按模块卡可把它设为「动态」位。
/// 模块摘要为真实数据，无数据源模块显式降级。
class LifePage extends ConsumerStatefulWidget {
  const LifePage({super.key, this.repository});

  final LifeRepository? repository;

  @override
  ConsumerState<LifePage> createState() => _LifePageState();
}

class _LifePageState extends ConsumerState<LifePage> {
  late final LifeRepository _repo = widget.repository ?? LifeRepository();
  List<LifeTaskItem>? _tasks;
  String? _expenseText;
  LifeCarSummary? _carSummary;
  bool _tasksFailed = false;
  bool _ledgerFailed = false;
  bool _carFailed = false;

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    setState(() {
      _tasks = null;
      _expenseText = null;
      _carSummary = null;
      _tasksFailed = false;
      _ledgerFailed = false;
      _carFailed = false;
    });
    List<LifeTaskItem>? tasks;
    String? expense;
    LifeCarSummary? car;
    try {
      tasks = await _repo.listOpenTasks();
    } catch (_) {
      tasks = null;
    }
    try {
      expense = await _repo.monthExpenseText();
    } catch (_) {
      expense = null;
    }
    try {
      car = await _repo.monthCarExpense();
    } catch (_) {
      car = null;
    }
    if (!mounted) return;
    setState(() {
      _tasks = tasks;
      _tasksFailed = tasks == null;
      _expenseText = expense;
      _ledgerFailed = expense == null;
      _carSummary = car;
      _carFailed = car == null;
    });
  }

  int get _memoCount => _tasks?.where((t) => t.kind == 'memo').length ?? 0;

  /// 日程格只算「今天」与「还没定时间」的待办；未来两周的留给日程页「即将到来」。
  List<LifeTaskItem> get _todayTasks {
    final now = DateTime.now();
    final day = DateTime(now.year, now.month, now.day);
    return [
      for (final task in _tasks ?? const <LifeTaskItem>[])
        if (task.kind != 'memo' && _isTodayOrUndated(task, day)) task,
    ];
  }

  bool _isTodayOrUndated(LifeTaskItem task, DateTime day) {
    final anchor = task.dueDateTime ?? task.remindDateTime;
    if (anchor == null) return true;
    return DateTime(anchor.year, anchor.month, anchor.day) == day;
  }

  static const _unavailable = '暂时取不到，点下方重试';

  String get _ledgerSummary {
    if (_ledgerFailed) return _unavailable;
    final expense = _expenseText;
    if (expense == null) return '…';
    final value = double.tryParse(expense) ?? 0;
    return value <= 0 ? '本月还没有支出' : '本月支出 ¥$expense';
  }

  String get _memoSummary {
    if (_tasksFailed) return _unavailable;
    if (_tasks == null) return '…';
    return _memoCount == 0 ? '还没有备忘' : '$_memoCount 条备忘';
  }

  String get _scheduleSummary {
    if (_tasksFailed) return _unavailable;
    if (_tasks == null) return '…';
    final items = _todayTasks;
    if (items.isEmpty) return '今天没有待办';
    final ordered = items.any((task) => (task.orderReason ?? '').isNotEmpty);
    return ordered ? '今日 ${items.length} 项 · AI 已排' : '今日 ${items.length} 项';
  }

  String get _carSummaryText {
    if (_carFailed) return _unavailable;
    final car = _carSummary;
    if (car == null) return '…';
    return car.isEmpty ? '还没有养车记录' : '本月养车 ¥${car.text}';
  }

  bool get _anyFailed => _tasksFailed || _ledgerFailed || _carFailed;

  @override
  Widget build(BuildContext context) {
    final colors = context.colors;
    final type = context.typography;
    final dynamicModule = ref.watch(dynamicModuleProvider);
    return Scaffold(
      backgroundColor: colors.canvas,
      body: SafeArea(
        bottom: false,
        child: ListView(
          padding: context.spacing.screenPadding,
          children: [
            Text('生活', style: type.pageTitle),
            Text('你的生活工具箱',
                style: type.sub.copyWith(color: colors.ink2)),
            const SizedBox(height: 6),
            Text('长按模块可设为动态',
                style: type.caption.copyWith(color: colors.ink3)),
            const SizedBox(height: 16),
            _ModuleGrid(
              ledgerSummary: _ledgerSummary,
              memoSummary: _memoSummary,
              scheduleSummary: _scheduleSummary,
              carSummary: _carSummaryText,
              dynamicModule: dynamicModule,
              onRequestDynamic: _openDynamicModuleSheet,
            ),
            if (_anyFailed) ...[
              const SizedBox(height: 10),
              Align(
                alignment: Alignment.centerRight,
                child: ChipButton(label: '重试', ghost: true, onTap: _load),
              ),
            ],
            const SizedBox(height: 40),
          ],
        ),
      ),
    );
  }

  void _openDynamicModuleSheet() {
    showModalBottomSheet<void>(
      context: context,
      isScrollControlled: true,
      builder: (_) => const DynamicModuleSheet(),
    );
  }
}

class _ModuleGrid extends StatelessWidget {
  const _ModuleGrid({
    required this.ledgerSummary,
    required this.memoSummary,
    required this.scheduleSummary,
    required this.carSummary,
    required this.dynamicModule,
    required this.onRequestDynamic,
  });

  final String ledgerSummary;
  final String memoSummary;
  final String scheduleSummary;
  final String carSummary;
  final LifeModule dynamicModule;
  final VoidCallback onRequestDynamic;

  @override
  Widget build(BuildContext context) {
    final colors = context.colors;
    return Column(
      children: [
        Row(
          children: [
            Expanded(
              child: ModuleCard(
                title: '记账',
                summary: ledgerSummary,
                icon: AppIcons.wallet,
                tileBg: colors.tileMoney,
                tileFg: colors.money,
                active: dynamicModule == LifeModule.ledger,
                onTap: () => context.push<bool>('/ledger'),
                onLongPress: onRequestDynamic,
              ),
            ),
            const SizedBox(width: 11),
            Expanded(
              child: ModuleCard(
                title: '备忘录',
                summary: memoSummary,
                icon: AppIcons.fileText,
                tileBg: colors.tileAi,
                tileFg: colors.aiPrimary,
                active: dynamicModule == LifeModule.memo,
                onTap: () => context.push<bool>('/memo'),
                onLongPress: onRequestDynamic,
              ),
            ),
            const SizedBox(width: 11),
            Expanded(
              child: ModuleCard(
                title: '日程',
                summary: scheduleSummary,
                icon: AppIcons.calendar,
                tileBg: colors.tileInfo,
                tileFg: colors.aiBlue,
                active: dynamicModule == LifeModule.schedule,
                onTap: () => context.push<bool>('/schedule'),
                onLongPress: onRequestDynamic,
              ),
            ),
          ],
        ),
        const SizedBox(height: 11),
        Row(
          children: [
            Expanded(
              child: ModuleCard(
                title: '健康',
                summary: '趋势参考 · 非诊断',
                icon: AppIcons.heart,
                tileBg: colors.tileHeart,
                tileFg: colors.heartFg,
                active: dynamicModule == LifeModule.health,
                onTap: () => context.push('/health'),
                onLongPress: onRequestDynamic,
              ),
            ),
            const SizedBox(width: 11),
            Expanded(
              child: ModuleCard(
                title: '车辆',
                summary: carSummary,
                icon: AppIcons.car,
                tileBg: colors.tileInfo,
                tileFg: colors.aiBlue,
                active: dynamicModule == LifeModule.car,
                onTap: () => context.push<bool>('/car'),
                onLongPress: onRequestDynamic,
              ),
            ),
            const SizedBox(width: 11),
            Expanded(
              child: Consumer(
                builder: (context, ref, _) {
                  final summary = ref.watch(albumSummaryProvider);
                  final authorized = summary?.authorized ?? false;
                  final count = summary?.totalCount;
                  final summaryText = !authorized
                      ? '仅本机 · 需授权'
                      : (count == null || count == 0)
                          ? '仅本机'
                          : '$count 张 · 仅本机';
                  return ModuleCard(
                    title: '相册',
                    summary: summaryText,
                    icon: AppIcons.image,
                    tileBg: colors.tileWarm,
                    tileFg: colors.warm,
                    active: dynamicModule == LifeModule.album,
                    onTap: () => context.push<bool>('/album'),
                    onLongPress: onRequestDynamic,
                  );
                },
              ),
            ),
          ],
        ),
      ],
    );
  }
}
