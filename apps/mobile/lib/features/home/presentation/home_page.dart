import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../../app/theme/theme_context.dart';
import '../../../core/storage/prefs_store.dart';
import '../../../design_system/components/components.dart';
import '../../../design_system/orb/orb.dart';
import '../data/home_repository.dart';

/// B1 #home 十一段：先结论 → 后数据 → 再行动。
class HomePage extends ConsumerStatefulWidget {
  const HomePage({super.key, this.healthAuthorized = false, this.debugSummary});

  final bool healthAuthorized;

  /// 测试注入；生产路径为 null，走 /home/summary。
  final HomeSummaryData? debugSummary;

  @override
  ConsumerState<HomePage> createState() => _HomePageState();
}

class _HomePageState extends ConsumerState<HomePage> {
  final _repo = HomeRepository();
  HomeSummaryData? _data;
  String? _nickname;
  Object? _error;
  bool _loading = true;

  @override
  void initState() {
    super.initState();
    _loadIdentity();
    if (widget.debugSummary != null) {
      _data = widget.debugSummary;
      _loading = false;
      return;
    }
    _load();
  }

  /// 头像取用户首字（设计稿 `远`），不编造昵称。
  Future<void> _loadIdentity() async {
    try {
      final prefs = await PrefsStore.load();
      if (!mounted) return;
      setState(() => _nickname = prefs.nickname());
    } catch (_) {
      return;
    }
  }

  Future<void> _load() async {
    setState(() {
      _loading = true;
      _error = null;
    });
    try {
      final data = await _repo.fetchSummary();
      if (!mounted) return;
      setState(() {
        _data = data;
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

  @override
  Widget build(BuildContext context) {
    final colors = context.colors;
    if (_loading && _data == null) {
      return Scaffold(
        backgroundColor: colors.canvas,
        body: SafeArea(
          child: ListView(
            padding: EdgeInsets.all(18),
            children: [SkeletonCard(), SkeletonCard(), SkeletonCard()],
          ),
        ),
      );
    }
    if (_error != null && _data == null) {
      return Scaffold(
        backgroundColor: colors.canvas,
        body: SafeArea(
          child: ErrorState(
            message: StateCopy.serverError,
            onRetry: _load,
          ),
        ),
      );
    }
    final d = _data!;
    final healthAuthorized = d.healthAuthorized || widget.healthAuthorized;
    return Scaffold(
      backgroundColor: colors.canvas,
      body: SafeArea(
        bottom: false,
        child: RefreshIndicator(
          onRefresh: _load,
          child: ListView(
            padding: context.spacing.screenPadding,
            children: [
              _GreetingRow(
                dateLabel: d.dateLabel,
                greeting: d.greeting,
                initial: (_nickname == null || _nickname!.isEmpty)
                    ? '你'
                    : _nickname!.substring(0, 1),
              ),
              const SizedBox(height: 18),
              _HeroBlock(headline: d.headline, sub: d.sub, modeChip: d.modeChip),
              const SizedBox(height: 20),
              AiCard(
                title: d.insightTitle,
                actionLabel: d.insightAction,
                onAction: d.insightAction == null
                    ? null
                    : () => context.go('/briefing?type=morning'),
                child: Text(
                  d.insightNarrative.isEmpty ? '今天还没有新的总结' : d.insightNarrative,
                  style: context.typography.body.copyWith(
                    color: colors.bodyOnCard,
                    height: 1.65,
                  ),
                ),
              ),
              const SizedBox(height: 24),
              _SectionTitle(
                title: '今日状态',
                hint: healthAuthorized ? d.healthSource : null,
              ),
              const SizedBox(height: 10),
              if (healthAuthorized && d.healthMetrics.isNotEmpty)
                _HealthGrid(metrics: d.healthMetrics)
              else if (healthAuthorized)
                const _HealthSyncingEmpty()
              else
                _HealthAuthEmpty(hint: d.healthEmptyHint),
              const SizedBox(height: 24),
              _SectionTitle(title: '今日任务', hint: d.tasksHint),
              const SizedBox(height: 6),
              AppCard(
                listPadding: true,
                child: Column(
                  children: [
                    if (d.tasks.isEmpty)
                      const Padding(
                        padding: EdgeInsets.symmetric(vertical: 12),
                        child: Text('今天还没有任务'),
                      )
                    else
                      for (var i = 0; i < d.tasks.length; i++)
                        TaskRow(
                          title: d.tasks[i].title,
                          subtitle: d.tasks[i].subtitle,
                          tag: d.tasks[i].tag,
                          done: d.tasks[i].done,
                          showDivider: i < d.tasks.length - 1,
                        ),
                  ],
                ),
              ),
              const SizedBox(height: 24),
              _SectionTitle(
                title: '今日消费',
                trailingAction: '查看账本 ›',
                onTrailing: () => context.go('/ledger'),
              ),
              const SizedBox(height: 10),
              if (d.spend != null)
                SpendSummary(
                  amountLabel: d.spend!.amountLabel,
                  budgetLabel: d.spend!.budgetLabel,
                  progress: d.spend!.progress,
                  weekBars: d.spend!.weekBars,
                  conclusion: d.spend!.conclusion,
                ),
              const SizedBox(height: 20),
              AskPill(onSend: () => context.go('/chat')),
              const SizedBox(height: 40),
            ],
          ),
        ),
      ),
    );
  }
}

class _GreetingRow extends StatelessWidget {
  const _GreetingRow({
    required this.dateLabel,
    required this.greeting,
    required this.initial,
  });

  final String dateLabel;
  final String greeting;
  final String initial;

  @override
  Widget build(BuildContext context) {
    final colors = context.colors;
    final type = context.typography;
    return Row(
      children: [
        Expanded(
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text(dateLabel, style: type.caption.copyWith(color: colors.ink2)),
              Text(greeting, style: type.heroTitle.copyWith(fontSize: 17)),
            ],
          ),
        ),
        Container(
          width: 38,
          height: 38,
          alignment: Alignment.center,
          decoration: BoxDecoration(
            shape: BoxShape.circle,
            gradient: context.gradients.avatar,
          ),
          child: Text(
            initial,
            style: type.sectionTitle.copyWith(
              fontSize: 15,
              color: colors.avatarText,
            ),
          ),
        ),
      ],
    );
  }
}

class _HeroBlock extends StatelessWidget {
  const _HeroBlock({
    required this.headline,
    required this.sub,
    required this.modeChip,
  });

  final String headline;
  final String sub;
  final String modeChip;

  @override
  Widget build(BuildContext context) {
    final colors = context.colors;
    final type = context.typography;
    return Column(
      children: [
        const Center(child: Orb(size: OrbSize.lg)),
        const SizedBox(height: 12),
        Text(headline, textAlign: TextAlign.center, style: type.heroTitle),
        const SizedBox(height: 6),
        Text(sub,
            textAlign: TextAlign.center,
            style: type.body.copyWith(color: colors.ink2, fontSize: 13.5)),
        if (modeChip.isNotEmpty) ...[
          const SizedBox(height: 10),
          Center(
            child: ModeChip(label: modeChip),
          ),
        ],
      ],
    );
  }
}

class _SectionTitle extends StatelessWidget {
  const _SectionTitle({
    required this.title,
    this.hint,
    this.trailingAction,
    this.onTrailing,
  });

  final String title;
  final String? hint;
  final String? trailingAction;
  final VoidCallback? onTrailing;

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
        if (trailingAction != null)
          GestureDetector(
            onTap: onTrailing,
            child: Text(trailingAction!,
                style: type.caption.copyWith(color: colors.aiPrimary)),
          ),
      ],
    );
  }
}

class _HealthGrid extends StatelessWidget {
  const _HealthGrid({required this.metrics});

  final List<HomeHealthMetric> metrics;

  @override
  Widget build(BuildContext context) {
    return Row(
      children: [
        for (var i = 0; i < metrics.length; i++) ...[
          if (i > 0) const SizedBox(width: 10),
          Expanded(
            child: MetricCard(
              label: metrics[i].label,
              value: metrics[i].value,
              unit: metrics[i].unit,
              note: metrics[i].note,
            ),
          ),
        ],
      ],
    );
  }
}

/// 已授权但当日还没有同步到数据：诚实空态，不出任何数值。
class _HealthSyncingEmpty extends StatelessWidget {
  const _HealthSyncingEmpty();

  @override
  Widget build(BuildContext context) {
    final colors = context.colors;
    final type = context.typography;
    return AppCard(
      child: Text(
        '已连接设备，今天的健康数据还没同步过来',
        textAlign: TextAlign.center,
        style: type.body.copyWith(color: colors.ink2),
      ),
    );
  }
}

/// 空态 + 引导授权：零数值、零留白（决策 D1）。
class _HealthAuthEmpty extends StatelessWidget {
  const _HealthAuthEmpty({this.hint});

  final String? hint;

  @override
  Widget build(BuildContext context) {
    final colors = context.colors;
    final type = context.typography;
    return AppCard(
      child: Column(
        children: [
          Text('还没有健康数据',
              style: type.rowTitle.copyWith(color: colors.ink)),
          const SizedBox(height: 8),
          Text(
            hint ?? '连接手环后，这里会显示睡眠、心率和步数',
            textAlign: TextAlign.center,
            style: type.body.copyWith(color: colors.ink2),
          ),
          const SizedBox(height: 14),
          ChipButton(
            label: '去授权健康数据',
            onTap: () => context.go('/health/consent'),
          ),
        ],
      ),
    );
  }
}
