import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../../app/state/album_summary_provider.dart';
import '../../../app/theme/theme_context.dart';
import '../../../design_system/components/components.dart';
import '../data/life_repository.dart';
import 'capture_route.dart';

/// B4 #life：捕获条 → 模块宫格 → soon 占位。模块摘要为真实数据，无数据源模块显式降级。
class LifePage extends StatefulWidget {
  const LifePage({super.key, this.repository});

  final LifeRepository? repository;

  @override
  State<LifePage> createState() => _LifePageState();
}

class _LifePageState extends State<LifePage> {
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
  int get _taskCount => _tasks?.where((t) => t.kind != 'memo').length ?? 0;

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

  String get _taskSummary {
    if (_tasksFailed) return _unavailable;
    if (_tasks == null) return '…';
    return _taskCount == 0 ? '今天没有待办' : '还有 $_taskCount 项待办';
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
    return Scaffold(
      backgroundColor: colors.canvas,
      body: SafeArea(
        bottom: false,
        child: ListView(
          padding: context.spacing.screenPadding,
          children: [
            Text('生活', style: type.pageTitle),
            Text('说一句话，亚丝娜帮你归位',
                style: type.sub.copyWith(color: colors.ink2)),
            const SizedBox(height: 16),
            CaptureBar(
              onTap: () {
                showModalBottomSheet<void>(
                  context: context,
                  isScrollControlled: true,
                  builder: (_) => const CaptureRouteSheet(),
                );
              },
            ),
            const _SectionTitle(title: '生活模块', hint: 'Skill 化 · 可持续扩展'),
            const SizedBox(height: 10),
            _ModuleGrid(
              ledgerSummary: _ledgerSummary,
              memoSummary: _memoSummary,
              taskSummary: _taskSummary,
              carSummary: _carSummaryText,
            ),
            if (_anyFailed) ...[
              const SizedBox(height: 10),
              Align(
                alignment: Alignment.centerRight,
                child: ChipButton(label: '重试', ghost: true, onTap: _load),
              ),
            ],
            const SizedBox(height: 24),
            const _SectionTitle(title: '即将上线', hint: 'Skill 商店'),
            const SizedBox(height: 10),
            const _SoonGrid(),
            const SizedBox(height: 40),
          ],
        ),
      ),
    );
  }
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

class _ModuleGrid extends StatelessWidget {
  const _ModuleGrid({
    required this.ledgerSummary,
    required this.memoSummary,
    required this.taskSummary,
    required this.carSummary,
  });

  final String ledgerSummary;
  final String memoSummary;
  final String taskSummary;
  final String carSummary;

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
                icon: Icons.wallet,
                tileBg: colors.tileMoney,
                tileFg: colors.money,
                onTap: () => context.push<bool>('/ledger'),
              ),
            ),
            const SizedBox(width: 11),
            Expanded(
              child: ModuleCard(
                title: '备忘录',
                summary: memoSummary,
                icon: Icons.notes,
                tileBg: colors.tileAi,
                tileFg: colors.aiPrimary,
              ),
            ),
            const SizedBox(width: 11),
            Expanded(
              child: ModuleCard(
                title: '任务',
                summary: taskSummary,
                icon: Icons.checklist,
                tileBg: colors.tileHealth,
                tileFg: colors.health,
              ),
            ),
          ],
        ),
        const SizedBox(height: 11),
        Row(
          children: [
            Expanded(
              child: ModuleCard(
                title: '日历',
                summary: '未接入',
                icon: AppIcons.calendar,
                tileBg: colors.tileInfo,
                tileFg: colors.aiBlue,
              ),
            ),
            const SizedBox(width: 11),
            Expanded(
              child: ModuleCard(
                title: '旅行',
                summary: '未接入',
                icon: AppIcons.plane,
                tileBg: colors.tileTravel,
                tileFg: colors.aiCyan,
              ),
            ),
            const SizedBox(width: 11),
            Expanded(
              child: ModuleCard(
                title: '健康',
                summary: '即将接入',
                icon: Icons.favorite,
                tileBg: colors.tileHealth,
                tileFg: colors.health,
              ),
            ),
          ],
        ),
        const SizedBox(height: 11),
        Row(
          children: [
            Expanded(
              child: ModuleCard(
                title: '车辆',
                summary: carSummary,
                icon: AppIcons.car,
                tileBg: colors.tileInfo,
                tileFg: colors.aiBlue,
                onTap: () => context.push<bool>('/car'),
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
                    tileBg: colors.tileAi,
                    tileFg: colors.aiPrimary,
                    onTap: () => context.push<bool>('/album'),
                  );
                },
              ),
            ),
            const SizedBox(width: 11),
            Expanded(
              child: ModuleCard(
                title: '记忆',
                summary: '全部可见 · 可改可忘',
                icon: AppIcons.brain,
                tileBg: colors.tileAi,
                tileFg: colors.aiPrimary,
                onTap: () => context.push<bool>('/memory'),
              ),
            ),
          ],
        ),
      ],
    );
  }
}

class _SoonGrid extends StatelessWidget {
  const _SoonGrid();

  @override
  Widget build(BuildContext context) {
    return const Row(
      children: [
        Expanded(
          child: ModuleCard(
            title: '阅读',
            summary: 'V2 见',
            icon: Icons.menu_book,
            soon: true,
          ),
        ),
        SizedBox(width: 11),
        Expanded(
          child: ModuleCard(
            title: '习惯打卡',
            summary: 'V2 见',
            icon: Icons.repeat,
            soon: true,
          ),
        ),
        SizedBox(width: 11),
        Expanded(
          child: ModuleCard(
            title: '更多 Skill',
            summary: '持续扩展',
            icon: Icons.add_box,
            soon: true,
          ),
        ),
      ],
    );
  }
}
