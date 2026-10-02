import 'package:flutter/material.dart';
import 'package:go_router/go_router.dart';

import '../../../app/theme/theme_context.dart';
import '../../../design_system/components/components.dart';
import '../data/ledger_repository.dart';
import 'ledger_category_visuals.dart';

/// B5 #ledger 账本：深色总览 + AI 观察 + 待确认 + 单入口 + 分类 + 账单。
///
/// 「待确认」是账本页的灵魂（`components.md` B5）：AI 记账不是全自动黑盒，
/// 拿不准的必须放在这里交给用户；34 只做「同步从哪来 / AI 学会了什么」。
class LedgerPage extends StatefulWidget {
  const LedgerPage({
    super.key,
    this.debugSummary,
    this.debugEntries,
    this.debugPending,
    this.repository,
  });

  final LedgerSummaryData? debugSummary;
  final List<LedgerEntryData>? debugEntries;
  final List<LedgerPendingData>? debugPending;
  final LedgerRepository? repository;

  @override
  State<LedgerPage> createState() => _LedgerPageState();
}

class _LedgerPageState extends State<LedgerPage> {
  late final LedgerRepository _repo = widget.repository ?? LedgerRepository();
  LedgerSummaryData? _summary;
  List<LedgerEntryData> _entries = [];
  List<LedgerPendingData> _pending = const [];
  Map<String, String> _categoryNames = const {};
  int? _autoCount;
  bool _loading = true;
  bool _actionFailed = false;
  Object? _error;

  @override
  void initState() {
    super.initState();
    if (widget.debugSummary != null) {
      _summary = widget.debugSummary;
      _entries = widget.debugEntries ?? const [];
      _pending = widget.debugPending ?? const [];
      _loading = false;
      _loadCategoryNames();
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
      final pending = await _loadPending();
      if (!mounted) return;
      setState(() {
        _summary = summary;
        _entries = entries;
        _autoCount = autoCount;
        _pending = pending;
        _actionFailed = false;
        _loading = false;
      });
      await _loadCategoryNames();
    } catch (e) {
      if (!mounted) return;
      setState(() {
        _error = e;
        _loading = false;
      });
    }
  }

  /// 账单行语义色需要 id → 名称解析（DA-27）；取不到时回落 money 基线，
  /// 只降级颜色，不影响整页。
  Future<void> _loadCategoryNames() async {
    try {
      final rows = await _repo.fetchCategories();
      if (!mounted) return;
      setState(() {
        _categoryNames = {for (final row in rows) row.id: row.name};
      });
    } catch (_) {
      if (!mounted) return;
      setState(() => _categoryNames = const {});
    }
  }

  /// 待确认是账本页的增强块，取不到时只隐藏该块，不把整页打成错误态。
  Future<List<LedgerPendingData>> _loadPending() async {
    try {
      return await _repo.fetchPending();
    } catch (_) {
      return const [];
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

  /// sync-link 文案体现 AI 动态（A31），不写静态说明。
  String get _syncLabel {
    final count = _autoCount;
    if (count == null) return '同步与 AI 规则';
    if (count == 0) return '本月还没有自动记账 · 同步与 AI 规则';
    return '本月已自动记 $count 笔 · 同步与 AI 规则';
  }

  Future<void> _openEntry(String location) async {
    await context.push<bool>(location);
    if (!mounted) return;
    await _load();
  }

  /// 待确认行：先乐观移除，失败则回滚并把失败显性化。
  Future<void> _resolve(
    LedgerPendingData item, {
    String? categoryName,
    String? direction,
  }) async {
    final snapshot = List<LedgerPendingData>.from(_pending);
    setState(() {
      _pending = [
        for (final row in _pending)
          if (row.pendingKey != item.pendingKey) row,
      ];
      _actionFailed = false;
    });
    try {
      await _repo.confirmPending(
        item.pendingKey,
        categoryName: categoryName,
        direction: direction,
      );
      await _refreshSummary();
    } catch (_) {
      if (!mounted) return;
      setState(() {
        _pending = snapshot;
        _actionFailed = true;
      });
    }
  }

  Future<void> _ignore(LedgerPendingData item) async {
    final snapshot = List<LedgerPendingData>.from(_pending);
    setState(() {
      _pending = [
        for (final row in _pending)
          if (row.pendingKey != item.pendingKey) row,
      ];
      _actionFailed = false;
    });
    try {
      await _repo.ignorePending(item.pendingKey);
      await _refreshSummary();
    } catch (_) {
      if (!mounted) return;
      setState(() {
        _pending = snapshot;
        _actionFailed = true;
      });
    }
  }

  Future<void> _refreshSummary() async {
    try {
      final summary = await _repo.fetchSummary();
      if (!mounted) return;
      setState(() => _summary = summary);
    } catch (_) {
      return;
    }
  }

  Future<void> _revise(LedgerPendingData item) async {
    final chosen = await showModalBottomSheet<String>(
      context: context,
      backgroundColor: context.colors.surface,
      shape: RoundedRectangleBorder(
        borderRadius: BorderRadius.vertical(
          top: Radius.circular(context.radii.lg),
        ),
      ),
      builder: (sheetContext) => SafeArea(
        child: Padding(
          padding: EdgeInsets.all(context.spacing.cardPadding),
          child: Column(
            mainAxisSize: MainAxisSize.min,
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text(
                '改成哪一类',
                style: context.typography.sectionTitle
                    .copyWith(color: context.colors.ink),
              ),
              const SizedBox(height: 14),
              Wrap(
                spacing: 8,
                runSpacing: 8,
                children: [
                  for (final candidate in item.candidates)
                    ChipButton(
                      label: candidate.label,
                      onTap: () =>
                          Navigator.of(sheetContext).pop(candidate.label),
                    ),
                ],
              ),
            ],
          ),
        ),
      ),
    );
    if (chosen == null || !mounted) return;
    await _resolve(item, categoryName: chosen);
  }

  Widget _pendingBlock() {
    final colors = context.colors;
    return Container(
      padding: const EdgeInsets.symmetric(vertical: 4, horizontal: 18),
      decoration: BoxDecoration(
        color: colors.surface,
        borderRadius: context.radii.rLg,
      ),
      child: Column(
        children: [
          for (var index = 0; index < _pending.length; index++)
            LedgerConfirmRow(
              title: _pendingTitle(_pending[index]),
              judgment: '我的判断：${_pendingJudgment(_pending[index])}',
              showDivider: index < _pending.length - 1,
              actions: _pendingActions(_pending[index]),
            ),
        ],
      ),
    );
  }

  List<LedgerConfirmAction> _pendingActions(LedgerPendingData item) {
    if (item.reason == 'direction_ambiguous') {
      return [
        LedgerConfirmAction(
          label: '记为支出',
          kind: LedgerActionKind.primary,
          onTap: () => _resolve(item, direction: 'expense'),
        ),
        LedgerConfirmAction(
          label: '记为收入',
          onTap: () => _resolve(item, direction: 'income'),
        ),
      ];
    }
    if (item.reason == 'category_ambiguous') {
      return [
        for (final candidate in item.candidates.take(3))
          LedgerConfirmAction(
            label: candidate.label,
            onTap: () => _resolve(item, categoryName: candidate.label),
          ),
        LedgerConfirmAction(label: '忽略', onTap: () => _ignore(item)),
      ];
    }
    return [
      LedgerConfirmAction(
        label: '确认',
        kind: LedgerActionKind.primary,
        onTap: () => _resolve(item),
      ),
      if (item.candidates.isNotEmpty)
        LedgerConfirmAction(label: '修改', onTap: () => _revise(item)),
      LedgerConfirmAction(label: '忽略', onTap: () => _ignore(item)),
    ];
  }

  String _pendingTitle(LedgerPendingData item) {
    final parts = <String>[
      if (item.merchantHint != null && item.merchantHint!.isNotEmpty)
        item.merchantHint!,
      if (item.amountText.isNotEmpty) '¥${item.amountText}',
    ];
    return parts.isEmpty ? item.question : parts.join(' · ');
  }

  /// `direction` 是后端枚举，必须转成用户看得懂的中文，不能原样抛出去。
  String _pendingJudgment(LedgerPendingData item) {
    final parts = <String>[
      if (item.categoryHint != null && item.categoryHint!.isNotEmpty)
        item.categoryHint!,
      if (item.direction == 'expense') '支出',
      if (item.direction == 'income') '收入',
    ];
    return parts.isEmpty ? '待你补充' : parts.join(' · ');
  }

  Widget _actionFailure() {
    final colors = context.colors;
    final type = context.typography;
    return Row(
      children: [
        Expanded(
          child: Text(
            '刚才那笔没处理成功，账单已放回列表',
            style: type.caption.copyWith(color: colors.danger),
          ),
        ),
        ChipButton(label: '重试', ghost: true, onTap: _load),
      ],
    );
  }

  LinearGradient _categoryGradient(int index) {
    final gradients = context.gradients;
    return switch (index % 4) {
      0 => gradients.barMoney,
      1 => gradients.barBlue,
      2 => gradients.barPurple,
      _ => gradients.barGreen,
    };
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
              BackLink(label: '生活'),
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
              if (_actionFailed) ...[
                _actionFailure(),
                const SizedBox(height: 8),
              ],
              if (_pending.isNotEmpty) ...[
                _SectionTitle(
                  title: '需要你的确认',
                  hint: '${_pending.length} 笔 · 确认后我会记住',
                ),
                const SizedBox(height: 6),
                _pendingBlock(),
                const SizedBox(height: 14),
              ],
              EntryCard(
                title: '记一笔',
                subtitle: '键盘输入，或直接说给亚丝娜',
                icon: AppIcons.pencil,
                accent: EntryAccent.money,
                onTap: () => _openEntry('/ledger/add'),
              ),
              SyncLink(
                label: _syncLabel,
                onTap: () => _openEntry('/ledger/auto'),
              ),
              const SizedBox(height: 20),
              _SectionTitle(title: '分类支出', hint: s.periodLabel),
              const SizedBox(height: 10),
              if (s.byCategory.isEmpty)
                Text('还没有分类数据', style: type.body.copyWith(color: colors.ink2))
              else
                for (final (index, c) in s.byCategory.take(6).indexed)
                  CategoryBar(
                    label: c.categoryId ?? '未分类',
                    amountLabel: '¥${(c.expenseMinor / 100).toStringAsFixed(0)}',
                    ratio: maxExpense == 0
                        ? 0
                        : c.expenseMinor / maxExpense,
                    gradient: _categoryGradient(index),
                  ),
              const SizedBox(height: 14),
              _SectionTitle(title: '最近账单', hint: 'AI 自动分类'),
              const SizedBox(height: 6),
              if (_entries.isEmpty)
                Text('还没有账单', style: type.body.copyWith(color: colors.ink2))
              else
                for (var i = 0; i < _entries.length; i++) _entryRow(i, colors),
            ],
          ),
        ),
      ),
    );
  }
  TxRow _entryRow(int index, AppColors colors) {
    final entry = _entries[index];
    final visuals = ledgerCategoryVisuals(
      colors,
      _categoryNames[entry.categoryId],
    );
    return TxRow(
      title: entry.merchant ?? entry.note ?? '一笔账',
      amountLabel: entry.direction == 'income'
          ? '+${entry.amountText}'
          : '-${entry.amountText}',
      tileColor: visuals.tile,
      iconColor: visuals.fg,
      icon: visuals.icon,
      subtitle: entry.occurredAt,
      showDivider: index < _entries.length - 1,
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
