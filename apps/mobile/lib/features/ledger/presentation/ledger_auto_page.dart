import 'package:flutter/material.dart';

import '../../../app/theme/theme_context.dart';
import '../../../design_system/components/components.dart';
import '../data/ledger_repository.dart';
import '../domain/bill_source_capability.dart';

/// B11 #ledgerAuto AI 自动记账：真实统计 + 待确认 + 来源能力 + 已学规则。
///
/// 决策 D14：来源区块是**静态能力声明**，不含任何同步计数；`accuracy` 无来源时整卡不渲染。
class LedgerAutoPage extends StatefulWidget {
  const LedgerAutoPage({super.key, this.repository});

  final LedgerRepository? repository;

  @override
  State<LedgerAutoPage> createState() => _LedgerAutoPageState();
}

class _LedgerAutoPageState extends State<LedgerAutoPage> {
  late final LedgerRepository _repo = widget.repository ?? LedgerRepository();

  bool _loading = true;
  Object? _error;
  LedgerAutoSummaryData? _summary;
  List<LedgerPendingData> _pending = const [];
  List<LedgerRuleData> _rules = const [];
  bool _actionFailed = false;

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    setState(() {
      _loading = true;
      _error = null;
    });
    try {
      final summary = await _repo.fetchAutoSummary();
      final pending = await _repo.fetchPending();
      final rules = await _repo.fetchRules();
      if (!mounted) return;
      setState(() {
        _summary = summary;
        _pending = pending;
        _rules = rules;
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
      final summary = await _repo.fetchAutoSummary();
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

  @override
  Widget build(BuildContext context) {
    final colors = context.colors;
    if (_loading) {
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
    if (_error != null) {
      return Scaffold(
        backgroundColor: colors.canvas,
        body: SafeArea(child: ErrorState(onRetry: _load)),
      );
    }
    final summary = _summary!;
    return Scaffold(
      backgroundColor: colors.canvas,
      body: SafeArea(
        bottom: false,
        child: ListView(
          padding: context.spacing.screenPadding,
          children: [
            BackLink(label: '‹ 记账'),
            const SizedBox(height: 14),
            AiCard(
              title: 'AI 自动记账',
              child: Text(
                _conclusion(summary),
                style: context.typography.body.copyWith(color: colors.ink2),
              ),
            ),
            const SizedBox(height: 12),
            _stats(summary),
            if (_actionFailed) ...[
              const SizedBox(height: 12),
              _actionFailure(),
            ],
            const SizedBox(height: 18),
            _SectionTitle('需要你的确认', hint: '确认后我会记住'),
            _pendingBlock(),
            const SizedBox(height: 18),
            _SectionTitle('自动同步来源', hint: '随时可关'),
            _sourceBlock(),
            const SizedBox(height: 18),
            _SectionTitle(
              '我学会的规则',
              hint: _rules.isEmpty ? '来自你的分类修正' : '来自你的 ${_rules.length} 次修正',
            ),
            _rulesBlock(),
            PrivacyNote(
              child: Text(
                '账单数据只用于帮你记账与生成消费观察；'
                '目前我不会读取任何第三方账单，语音记账只在你主动说话时发生。',
                style: context.typography.caption
                    .copyWith(fontWeight: FontWeight.w400),
              ),
            ),
            const SizedBox(height: 24),
          ],
        ),
      ),
    );
  }

  String _conclusion(LedgerAutoSummaryData summary) {
    if (summary.pendingCount > 0) {
      return '本月我自动记了 ${summary.autoCount} 笔，'
          '有 ${summary.pendingCount} 笔拿不准，等你确认。';
    }
    return '本月我自动记了 ${summary.autoCount} 笔，没有拿不准的账单。';
  }

  Widget _stats(LedgerAutoSummaryData summary) {
    final cards = <Widget>[
      LedgerStatCard(
        value: '${summary.autoCount}',
        unit: '笔',
        label: '本月自动记账',
      ),
      if (summary.accuracy != null)
        LedgerStatCard(
          value: '${(summary.accuracy! * 100).round()}',
          unit: '%',
          label: '分类准确率',
        ),
      if (_rules.isNotEmpty)
        LedgerStatCard(
          value: '${_rules.length}',
          unit: '条',
          label: '学会的规则',
        ),
    ];
    return Row(
      children: [
        for (var index = 0; index < cards.length; index++) ...[
          if (index > 0) const SizedBox(width: 9),
          Expanded(child: cards[index]),
        ],
      ],
    );
  }

  Widget _pendingBlock() {
    final colors = context.colors;
    if (_pending.isEmpty) {
      return Text(
        '这个月没有拿不准的账单',
        style: context.typography.body.copyWith(color: colors.ink2),
      );
    }
    return Container(
      padding: const EdgeInsets.symmetric(vertical: 4, horizontal: 18),
      decoration: BoxDecoration(
        color: colors.surface,
        borderRadius: context.radii.rLg,
      ),
      child: Column(
        children: [
          for (var index = 0; index < _pending.length; index++)
            _pendingRow(_pending[index], index < _pending.length - 1),
        ],
      ),
    );
  }

  Widget _pendingRow(LedgerPendingData item, bool showDivider) {
    return LedgerConfirmRow(
      title: _rowTitle(item),
      judgment: '我的判断：${_judgment(item)}',
      showDivider: showDivider,
      actions: _actions(item),
    );
  }

  List<LedgerConfirmAction> _actions(LedgerPendingData item) {
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

  String _rowTitle(LedgerPendingData item) {
    final parts = <String>[
      if (item.merchantHint != null && item.merchantHint!.isNotEmpty)
        item.merchantHint!,
      if (item.amountText.isNotEmpty) '¥${item.amountText}',
    ];
    return parts.isEmpty ? item.question : parts.join(' · ');
  }

  String _judgment(LedgerPendingData item) {
    final parts = <String>[
      if (item.categoryHint != null && item.categoryHint!.isNotEmpty)
        item.categoryHint!,
      if (item.direction != null && item.direction!.isNotEmpty)
        item.direction!,
    ];
    return parts.isEmpty ? '待你补充' : parts.join(' · ');
  }

  Widget _sourceBlock() {
    final colors = context.colors;
    final type = context.typography;
    return SettingGroup(
      children: [
        for (var index = 0; index < billSourceCapabilities.length; index++)
          SettingRow(
            title: billSourceCapabilities[index].title,
            subtitle: billSourceCapabilities[index].reason,
            trailing: Text(
              billSourceCapabilities[index].state,
              style: type.caption.copyWith(
                color: billSourceCapabilities[index].available
                    ? colors.health
                    : colors.ink3,
              ),
            ),
            icon: billSourceCapabilities[index].available
                ? AppIcons.mic
                : AppIcons.lock,
            showDivider: index < billSourceCapabilities.length - 1,
          ),
      ],
    );
  }

  Widget _rulesBlock() {
    final colors = context.colors;
    if (_rules.isEmpty) {
      return Text(
        '还没有学会新的规则。改一次分类，我就记住。',
        style: context.typography.body.copyWith(color: colors.ink2),
      );
    }
    return Container(
      padding: const EdgeInsets.symmetric(vertical: 4, horizontal: 18),
      decoration: BoxDecoration(
        color: colors.surface,
        borderRadius: context.radii.rLg,
      ),
      child: Column(
        children: [
          for (final rule in _rules)
            LedgerRuleRow(
              keyword: rule.keyword,
              target: rule.categoryName,
              sourceNote: rule.sourceNote,
            ),
        ],
      ),
    );
  }

  Widget _actionFailure() {
    final colors = context.colors;
    return Text(
      '刚才那一步没成功，我把列表恢复了，你再试一次',
      style: context.typography.caption.copyWith(
        color: colors.danger,
        fontWeight: FontWeight.w400,
      ),
    );
  }
}

class _SectionTitle extends StatelessWidget {
  const _SectionTitle(this.text, {this.hint});

  final String text;
  final String? hint;

  @override
  Widget build(BuildContext context) {
    final colors = context.colors;
    final type = context.typography;
    return Padding(
      padding: const EdgeInsets.only(bottom: 10),
      child: Row(
        children: [
          Text(text, style: type.sectionTitle.copyWith(color: colors.ink)),
          const Spacer(),
          if (hint != null)
            Text(
              hint!,
              style: type.caption.copyWith(
                color: colors.ink3,
                fontWeight: FontWeight.w400,
              ),
            ),
        ],
      ),
    );
  }
}
