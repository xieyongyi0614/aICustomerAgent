import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../../app/theme/theme_context.dart';
import '../../../core/location/location_service.dart';
import '../../../core/storage/prefs_store.dart';
import '../../../design_system/components/components.dart';
import '../../../design_system/orb/orb.dart';
import '../data/home_repository.dart';

/// B1 #home 十一段：先结论 → 后数据 → 再行动。
class HomePage extends ConsumerStatefulWidget {
  const HomePage({super.key, this.debugSummary});

  /// 测试注入；生产路径为 null，走 /home/summary。
  final HomeSummaryData? debugSummary;

  @override
  ConsumerState<HomePage> createState() => _HomePageState();
}

class _HomePageState extends ConsumerState<HomePage> {
  final _repo = HomeRepository();
  final _location = const LocationService();
  HomeSummaryData? _data;
  String? _nickname;
  Object? _error;
  bool _loading = true;
  bool _insightRefreshing = false;

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
      return;
    }
    unawaited(_refreshInsightWithLocation());
  }

  /// 两段式补刷：定位到位后只刷新 AI 卡（服务端按坐标重算，端上不拼装）。
  /// 未授权不弹窗（requestIfDenied: false），冷启动不被权限弹窗卡住；
  /// 定位取不到或补刷失败都保持首轮内容。
  Future<void> _refreshInsightWithLocation() async {
    if (_insightRefreshing) return;
    _insightRefreshing = true;
    try {
      final coords = await _location.getCurrentCoords(requestIfDenied: false);
      if (coords == null || !mounted || _data == null) return;
      final data = await _repo.fetchSummary(lat: coords.lat, lon: coords.lon);
      if (!mounted || _data == null) return;
      setState(() {
        _data = _data!.withInsight(
          insightTitle: data.insightTitle,
          insightNarrative: data.insightNarrative,
          insightAction: data.insightAction,
        );
      });
    } catch (_) {
      // 补刷失败保持首轮内容，不打断页面
    } finally {
      _insightRefreshing = false;
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
                title: '今日任务',
                hint: d.tasksHint.isEmpty ? null : '${d.tasksHint} ›',
                onHintTap: d.tasksHint.isEmpty
                    ? null
                    : () => context.push('/schedule', extra: '首页'),
              ),
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
                title: '最近消费',
                trailingAction: '查看账本 ›',
                onTrailing: () => context.push('/ledger', extra: '首页'),
              ),
              const SizedBox(height: 10),
              if (d.spend != null)
                SpendSummary(
                  amountLabel: d.spend!.amountLabel,
                  noteLabel: d.spend!.noteLabel,
                  progress: d.spend!.progress,
                  weekBars: d.spend!.weekBars,
                  weekLabels: d.spend!.weekLabels,
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
    this.onHintTap,
    this.trailingAction,
    this.onTrailing,
  });

  final String title;
  final String? hint;
  final VoidCallback? onHintTap;
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
          GestureDetector(
            onTap: onHintTap,
            child: Text(hint!, style: type.caption.copyWith(color: colors.ink3)),
          ),
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

