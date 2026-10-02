import 'package:flutter/material.dart';
import 'package:go_router/go_router.dart';
import 'package:intl/intl.dart';

import '../../../app/theme/theme_context.dart';
import '../../../design_system/components/components.dart';
import '../data/life_repository.dart';
import 'capture_route.dart';

/// B4a `#memo` 备忘录（41）：AI 归类结论 → 主题分组清单 → 隐私口径。
///
/// V1 复用任务域（`kind=memo`，APP-022 降级裁决：不建独立备忘录域）。
/// 无 tag 的备忘不编造主题，统一落「全部备忘」。
class MemoPage extends StatefulWidget {
  const MemoPage({super.key, this.repository});

  final LifeRepository? repository;

  @override
  State<MemoPage> createState() => _MemoPageState();
}

class _MemoPageState extends State<MemoPage> {
  late final LifeRepository _repo = widget.repository ?? LifeRepository();
  List<LifeTaskItem>? _memos;
  Object? _error;
  bool _loading = true;

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
      final tasks = await _repo.listOpenTasks();
      if (!mounted) return;
      setState(() {
        _memos = tasks.where((task) => task.kind == 'memo').toList();
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

  List<(String, List<LifeTaskItem>)> get _groups {
    final memos = _memos ?? const <LifeTaskItem>[];
    if (memos.isEmpty) return const [];
    final tagged = memos.where((memo) => (memo.tag ?? '').isNotEmpty);
    if (tagged.isEmpty) return [('全部备忘', memos)];
    final byTag = <String, List<LifeTaskItem>>{};
    final untagged = <LifeTaskItem>[];
    for (final memo in memos) {
      final tag = memo.tag ?? '';
      if (tag.isEmpty) {
        untagged.add(memo);
      } else {
        byTag.putIfAbsent(tag, () => <LifeTaskItem>[]).add(memo);
      }
    }
    return [
      for (final entry in byTag.entries) (entry.key, entry.value),
      if (untagged.isNotEmpty) ('其他', untagged),
    ];
  }

  Color _dotColor(int index) {
    final colors = context.colors;
    const paletteLength = 5;
    return switch (index % paletteLength) {
      0 => colors.aiCyan,
      1 => colors.aiBlue,
      2 => colors.warm,
      3 => colors.aiPrimary,
      _ => colors.money,
    };
  }

  String? _sourceNote(LifeTaskItem memo) {
    final parts = <String>[];
    final due = memo.dueDateTime;
    if (due != null) parts.add('到期 ${DateFormat('M/d').format(due)}');
    final remind = memo.remindDateTime;
    if (remind != null) {
      parts.add('提醒 ${DateFormat('M/d HH:mm').format(remind)}');
    }
    return parts.isEmpty ? null : parts.join(' · ');
  }

  Future<void> _openCapture() async {
    await showModalBottomSheet<void>(
      context: context,
      isScrollControlled: true,
      builder: (_) => const CaptureRouteSheet(),
    );
    if (!mounted) return;
    await _load();
  }

  Future<void> _delete(LifeTaskItem memo) async {
    final colors = context.colors;
    final confirmed = await showDialog<bool>(
      context: context,
      builder: (dialogContext) => AlertDialog(
        title: const Text('删掉这条备忘'),
        content: Text('「${memo.title}」删掉后不会再出现，也不会再用来提醒你。'),
        actions: [
          TextButton(
            onPressed: () => Navigator.of(dialogContext).pop(false),
            child: const Text('先留着'),
          ),
          TextButton(
            onPressed: () => Navigator.of(dialogContext).pop(true),
            child: Text('删掉它', style: TextStyle(color: colors.danger)),
          ),
        ],
      ),
    );
    if (confirmed != true) return;
    try {
      await _repo.deleteTask(memo.id);
    } catch (_) {
      if (!mounted) return;
      ScaffoldMessenger.of(context)
        ..hideCurrentSnackBar()
        ..showSnackBar(const SnackBar(content: Text('没删掉，检查网络后再试')));
      return;
    }
    if (!mounted) return;
    await _load();
  }

  String get _aiConclusion {
    final memos = _memos ?? const <LifeTaskItem>[];
    if (memos.isEmpty) {
      return '还没有备忘。随口说一句「帮我记…」，我就帮你收好，并记得它该在什么时候提醒你。';
    }
    final tagCount = _groups.length;
    final themePart = tagCount > 1 ? '，按 $tagCount 个主题归好' : '';
    return '这 ${memos.length} 条备忘我帮你收着$themePart。'
        '归类依据你随时可以问我，长按任意一条就能改或删。';
  }

  @override
  Widget build(BuildContext context) {
    final colors = context.colors;
    final type = context.typography;
    return Scaffold(
      backgroundColor: colors.canvas,
      body: SafeArea(
        bottom: false,
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            Padding(
              padding: const EdgeInsets.fromLTRB(18, 12, 18, 0),
              child: BackLink(
                label: '生活',
                onTap: () => context.go('/life'),
              ),
            ),
            Expanded(child: _body(context, colors, type)),
          ],
        ),
      ),
    );
  }

  Widget _body(
    BuildContext context,
    AppColors colors,
    AppTypography type,
  ) {
    final memos = _memos;
    if (memos == null) {
      if (_loading) {
        return ListView(
          padding: context.spacing.screenPadding,
          children: const [SkeletonCard(), SkeletonCard()],
        );
      }
      return _error == null
          ? EmptyState(
              message: '还没有备忘，随口说一句我就帮你记',
              actionLabel: '记一条',
              onAction: _openCapture,
            )
          : ErrorState(message: StateCopy.serverError, onRetry: _load);
    }

    final groups = _groups;
    return ListView(
      padding: context.spacing.screenPadding,
      children: [
        Row(
          crossAxisAlignment: CrossAxisAlignment.center,
          children: [
            Text('备忘录', style: type.pageTitle),
            const Spacer(),
            CountPill(
              text: groups.length > 1
                  ? '${memos.length} 条 · ${groups.length} 个主题'
                  : '${memos.length} 条',
            ),
          ],
        ),
        const SizedBox(height: 4),
        Text('随手说，亚丝娜帮你归好类', style: type.sub.copyWith(color: colors.ink2)),
        const SizedBox(height: 16),
        CaptureBar(
          hint: '「帮我记：护照明年 3 月到期」…',
          onTap: _openCapture,
        ),
        AiCard(
          title: '亚丝娜整理中',
          child: Text(
            _aiConclusion,
            style: type.body.copyWith(fontSize: 13.5, color: colors.bodyOnCard),
          ),
        ),
        const SizedBox(height: 4),
        if (memos.isEmpty)
          const EmptyState(message: '还没有备忘，随口说一句我就帮你记')
        else
          for (var i = 0; i < groups.length; i++) ...[
            Padding(
              padding: const EdgeInsets.only(top: 24, bottom: 11),
              child: Row(
                children: [
                  Text(groups[i].$1, style: type.sectionTitle),
                  const Spacer(),
                  Text(
                    '${groups[i].$2.length} 条',
                    style: type.caption.copyWith(color: colors.ink3),
                  ),
                ],
              ),
            ),
            AppCard(
              padding: const EdgeInsets.symmetric(vertical: 6, horizontal: 18),
              child: Column(
                children: [
                  for (var j = 0; j < groups[i].$2.length; j++)
                    MemoRow(
                      title: groups[i].$2[j].title,
                      dotColor: _dotColor(i),
                      sourceNote: _sourceNote(groups[i].$2[j]),
                      aiNote: groups[i].$2[j].orderReason,
                      done: groups[i].$2[j].status != 'open',
                      showDivider: j != groups[i].$2.length - 1,
                      onLongPress: () => _delete(groups[i].$2[j]),
                    ),
                ],
              ),
            ),
          ],
        PrivacyNote(
          child: Text(
            '备忘只用于帮你整理和提醒，归类的依据你随时可以问亚丝娜；'
            '任何一条都可以长按删除，删了就不会再用。',
          ),
        ),
        const SizedBox(height: 40),
      ],
    );
  }
}
