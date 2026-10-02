import 'package:flutter/material.dart';

import '../../../app/theme/theme_context.dart';
import '../../../design_system/components/components.dart';
import '../data/ledger_repository.dart';
import '../domain/bill_source_capability.dart';

/// B11 #ledgerAuto 同步与 AI 规则：AI 结论 + 统计三卡 + 同步来源 + 已学规则。
///
/// 本页是账本的**二级管理页**：只管「同步从哪来」与「AI 学会了什么」。
/// **「待确认」不在这里** —— 待确认账单只出现在账本首页（31）。
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
  List<LedgerRuleData> _rules = const [];

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
      final rules = await _repo.fetchRules();
      if (!mounted) return;
      setState(() {
        _summary = summary;
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
            BackLink(label: '记账'),
            const SizedBox(height: 14),
            AiCard(
              title: '本月 AI 自动记账',
              child: Text(
                _conclusion(summary),
                style: context.typography.body.copyWith(color: colors.ink2),
              ),
            ),
            const SizedBox(height: 12),
            _stats(summary),
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

  /// 结论要指明「待确认去哪了」—— 它不在本页，在账本首页（31）。
  String _conclusion(LedgerAutoSummaryData summary) {
    final parts = <String>['本月我自动记了 ${summary.autoCount} 笔'];
    if (summary.accuracy != null) {
      parts.add('分类准确率 ${(summary.accuracy! * 100).round()}%');
    }
    parts.add(
      summary.pendingCount > 0
          ? '${summary.pendingCount} 笔拿不准的已放在账本首页等你确认'
          : '没有拿不准的账单',
    );
    return '${parts.join(' · ')}。';
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
