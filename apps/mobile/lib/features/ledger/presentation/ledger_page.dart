import 'package:flutter/material.dart';
import 'package:go_router/go_router.dart';

import '../../../app/theme/theme_context.dart';
import '../../../design_system/components/components.dart';
import '../data/ledger_repository.dart';

/// B5 #ledger 账本：深色总览 + AI 观察 + 分类 + 账单。
class LedgerPage extends StatefulWidget {
  const LedgerPage({
    super.key,
    this.debugSummary,
    this.debugEntries,
    this.repository,
  });

  final LedgerSummaryData? debugSummary;
  final List<LedgerEntryData>? debugEntries;
  final LedgerRepository? repository;

  @override
  State<LedgerPage> createState() => _LedgerPageState();
}

class _LedgerPageState extends State<LedgerPage> {
  late final LedgerRepository _repo = widget.repository ?? LedgerRepository();
  LedgerSummaryData? _summary;
  List<LedgerEntryData> _entries = [];
  int? _autoCount;
  bool _loading = true;
  Object? _error;

  @override
  void initState() {
    super.initState();
    if (widget.debugSummary != null) {
      _summary = widget.debugSummary;
      _entries = widget.debugEntries ?? const [];
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
      final summary = await _repo.fetchSummary();
      final entries = await _repo.fetchEntries();
      final autoCount = await _loadAutoCount();
      if (!mounted) return;
      setState(() {
        _summary = summary;
        _entries = entries;
        _autoCount = autoCount;
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

  Future<int?> _loadAutoCount() async {
    try {
      final summary = await _repo.fetchAutoSummary();
      return summary.autoCount;
    } catch (_) {
      return null;
    }
  }

  String get _autoSubtitle {
    final count = _autoCount;
    if (count == null) return '看看 AI 记了什么';
    if (count == 0) return '本月还没有自动记账';
    return '本月已自动记 $count 笔';
  }

  Future<void> _openEntry(String location) async {
    await context.push<bool>(location);
    if (!mounted) return;
    await _load();
  }

  @override
  Widget build(BuildContext context) {
    final colors = context.colors;
    if (_loading && _summary == null) {
      return Scaffold(
        backgroundColor: colors.canvas,
        body: SafeArea(
          child: ListView(
            padding: EdgeInsets.all(18),
            children: [SkeletonCard(), SkeletonCard()],
          ),
        ),
      );
    }
    if (_error != null && _summary == null) {
      return Scaffold(
        backgroundColor: colors.canvas,
        body: SafeArea(child: ErrorState(onRetry: _load)),
      );
    }
    final s = _summary!;
    final type = context.typography;
    final gradients = context.gradients;
    final maxExpense = s.byCategory
        .map((e) => e.expenseMinor)
        .fold<int>(0, (a, b) => b > a ? b : a);
    return Scaffold(
      backgroundColor: colors.canvas,
      body: SafeArea(
        child: RefreshIndicator(
          onRefresh: _load,
          child: ListView(
            padding: context.spacing.screenPadding.copyWith(bottom: 40),
            children: [
              BackLink(
                label: '‹ 生活',
                onTap: () => Navigator.of(context).maybePop(),
              ),
              Container(
                padding: const EdgeInsets.all(18),
                decoration: BoxDecoration(
                  gradient: gradients.deepSummary,
                  borderRadius: context.radii.rLg,
                  boxShadow: context.elevation.deep,
                ),
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(s.periodLabel,
                        style: type.caption
                            .copyWith(color: colors.onDeepSecondary)),
                    const SizedBox(height: 6),
                    Text('¥${s.expenseText}',
                        style: type.numeric(type.display)
                            .copyWith(color: colors.onDeepPrimary)),
                    const SizedBox(height: 6),
                    if (s.comparisonLabel != null)
                      Container(
                        padding: const EdgeInsets.symmetric(
                            vertical: 3, horizontal: 8),
                        decoration: BoxDecoration(
                          color: colors.health.withValues(alpha: 0.18),
                          borderRadius: context.radii.rFull,
                        ),
                        child: Text(s.comparisonLabel!,
                            style:
                                type.caption.copyWith(color: colors.health)),
                      ),
                  ],
                ),
              ),
              const SizedBox(height: 14),
              AiCard(
                title: '亚丝娜的观察',
                child: Text(
                  s.entryCount == 0
                      ? '这段时间还没有记账，说一句「午饭 35 元」就能记上。'
                      : '本期共 ${s.entryCount} 笔。收入 ${s.incomeText}，结余 ${s.netText}。',
                  style: type.body
                      .copyWith(color: colors.bodyOnCard, height: 1.65),
                ),
              ),
              const SizedBox(height: 12),
              Row(
                children: [
                  Expanded(
                    child: EntryCard(
                      title: '手动记一笔',
                      subtitle: '金额 + 分类，备注我帮你填',
                      icon: AppIcons.wallet,
                      accent: EntryAccent.money,
                      onTap: () => _openEntry('/ledger/add'),
                    ),
                  ),
                  const SizedBox(width: 11),
                  Expanded(
                    child: EntryCard(
                      title: 'AI 自动记账',
                      subtitle: _autoSubtitle,
                      icon: AppIcons.sparkles,
                      accent: EntryAccent.ai,
                      onTap: () => _openEntry('/ledger/auto'),
                    ),
                  ),
                ],
              ),
              const SizedBox(height: 20),
              _SectionTitle(title: '分类支出', hint: s.periodLabel),
              const SizedBox(height: 10),
              if (s.byCategory.isEmpty)
                Text('还没有分类数据', style: type.body.copyWith(color: colors.ink2))
              else
                for (final c in s.byCategory.take(6))
                  CategoryBar(
                    label: c.categoryId ?? '未分类',
                    amountLabel: '¥${(c.expenseMinor / 100).toStringAsFixed(0)}',
                    ratio: maxExpense == 0
                        ? 0
                        : c.expenseMinor / maxExpense,
                    gradient: gradients.barMoney,
                  ),
              const SizedBox(height: 14),
              _SectionTitle(title: '最近账单', hint: 'AI 自动分类'),
              const SizedBox(height: 6),
              if (_entries.isEmpty)
                Text('还没有账单', style: type.body.copyWith(color: colors.ink2))
              else
                for (var i = 0; i < _entries.length; i++)
                  TxRow(
                    title: _entries[i].merchant ??
                        _entries[i].note ??
                        '一笔账',
                    amountLabel: _entries[i].direction == 'income'
                        ? '+${_entries[i].amountText}'
                        : '-${_entries[i].amountText}',
                    tileColor: colors.tileMoney,
                    iconColor: colors.money,
                    icon: Icons.receipt_long,
                    subtitle: _entries[i].occurredAt,
                    showDivider: i < _entries.length - 1,
                  ),
            ],
          ),
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
