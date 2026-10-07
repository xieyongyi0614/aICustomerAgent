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
  const MemoPage({super.key, this.repository, this.showBackLink = true});

  final LifeRepository? repository;

  /// false = 作为「动态」Tab 根页渲染：不出现「‹ 生活」返回链接。
  final bool showBackLink;

  @override
  State<MemoPage> createState() => _MemoPageState();
}

class _MemoPageState extends State<MemoPage> {
  static const _untaggedGroup = '全部备忘';
  static const _otherGroup = '其他';

  /// 服务端给备忘的默认排序理由是通用占位（不是「被用到哪里」的关联回执），行内不重复渲染。
  static const _genericMemoReason = '备忘录 · AI 已整理';

  static const _dueSoonDays = 7;

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
    if (tagged.isEmpty) return [(_untaggedGroup, memos)];
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
      if (untagged.isNotEmpty) (_otherGroup, untagged),
    ];
  }

  /// 主题色对（前景 / 图标底）全部取自 token，不新增色值。
  List<(Color, Color)> _palette(AppColors colors) => [
    (colors.aiCyan, colors.tileTravel),
    (colors.aiBlue, colors.tileInfo),
    (colors.warm, colors.tileWarm),
    (colors.aiPrimary, colors.tileAi),
    (colors.money, colors.tileMoney),
  ];

  (Color, Color) _groupTint(int index, AppColors colors) {
    final palette = _palette(colors);
    return palette[index % palette.length];
  }

  IconData _groupIcon(String name) =>
      name == _untaggedGroup || name == _otherGroup
      ? AppIcons.fileText
      : AppIcons.tag;

  /// 来源行：记录时间 / 到期 / 提醒，只拼真实字段，缺项不占位。
  String? _sourceNote(LifeTaskItem memo) {
    final parts = <String>[];
    final created = memo.createdDateTime?.toLocal();
    if (created != null) parts.add('${DateFormat('M/d').format(created)} 记录');
    final due = memo.dueDateTime;
    if (due != null) parts.add('到期 ${DateFormat('M/d').format(due)}');
    final remind = memo.remindDateTime?.toLocal();
    if (remind != null) {
      parts.add('提醒 ${DateFormat('M/d HH:mm').format(remind)}');
    }
    return parts.isEmpty ? null : parts.join(' · ');
  }

  /// AI 关联回执：只渲染真正指向「被用到哪里」的理由。
  String? _aiNote(LifeTaskItem memo) {
    final reason = memo.orderReason;
    if (reason == null || reason.isEmpty || reason == _genericMemoReason) {
      return null;
    }
    return reason;
  }

  int _dueSoonCount(List<LifeTaskItem> memos) {
    final now = DateTime.now();
    final today = DateTime(now.year, now.month, now.day);
    final limit = today.add(const Duration(days: _dueSoonDays));
    return memos.where((memo) {
      final due = memo.dueDateTime;
      if (due == null) return false;
      final day = DateTime(due.year, due.month, due.day);
      return !day.isBefore(today) && !day.isAfter(limit);
    }).length;
  }

  String get _countText {
    final memos = _memos ?? const <LifeTaskItem>[];
    final groups = _groups.length;
    return groups > 1
        ? '${memos.length} 条 · $groups 个主题'
        : '${memos.length} 条';
  }

  String get _aiConclusion {
    final memos = _memos ?? const <LifeTaskItem>[];
    if (memos.isEmpty) {
      return '还没有备忘。随口说一句「帮我记…」，我就帮你收好，并记得它该在什么时候提醒你。';
    }
    final groups = _groups.length;
    final reminded = memos.where((memo) => memo.remindDateTime != null).length;
    final dueSoon = _dueSoonCount(memos);
    final parts = <String>['这 ${memos.length} 条备忘我收好了'];
    if (groups > 1) parts.add('按 $groups 个主题归好');
    if (reminded > 0) parts.add('$reminded 条设了提醒');
    if (dueSoon > 0) parts.add('$dueSoon 条 $_dueSoonDays 天内到期');
    return '${parts.join('，')}。长按任意一条就能删掉它。';
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
            if (widget.showBackLink)
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
          ? _emptyState(context, colors, type)
          : ErrorState(message: StateCopy.serverError, onRetry: _load);
    }

    return ListView(
      padding: context.spacing.screenPadding,
      children: [
        Row(
          crossAxisAlignment: CrossAxisAlignment.center,
          children: [
            Text('备忘录', style: type.pageTitle),
            const Spacer(),
            CountPill(text: _countText),
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
          _emptyState(context, colors, type)
        else
          ..._sections(context, colors, type, _groups),
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

  List<Widget> _sections(
    BuildContext context,
    AppColors colors,
    AppTypography type,
    List<(String, List<LifeTaskItem>)> groups,
  ) {
    final out = <Widget>[];
    for (var i = 0; i < groups.length; i++) {
      final (name, items) = groups[i];
      final (fg, bg) = _groupTint(i, colors);
      out.add(
        Padding(
          padding: const EdgeInsets.only(top: 24, bottom: 11),
          child: _GroupHeader(
            name: name,
            count: items.length,
            icon: _groupIcon(name),
            tintFg: fg,
            tintBg: bg,
          ),
        ),
      );
      out.add(
        AppCard(
          padding: const EdgeInsets.symmetric(vertical: 6, horizontal: 18),
          child: Column(
            children: [
              for (var j = 0; j < items.length; j++)
                MemoRow(
                  title: items[j].title,
                  dotColor: fg,
                  sourceNote: _sourceNote(items[j]),
                  aiNote: _aiNote(items[j]),
                  showDivider: j != items.length - 1,
                  onLongPress: () => _delete(items[j]),
                ),
            ],
          ),
        ),
      );
    }
    return out;
  }

  Widget _emptyState(
    BuildContext context,
    AppColors colors,
    AppTypography type,
  ) {
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 28),
      child: Column(
        children: [
          Container(
            width: 44,
            height: 44,
            decoration: BoxDecoration(
              color: colors.tileAi,
              borderRadius: BorderRadius.circular(context.radii.iconTile(44)),
            ),
            child: Icon(AppIcons.fileText, size: 20, color: colors.aiPrimary),
          ),
          const SizedBox(height: 14),
          Text(
            '还没有备忘，随口说一句我就帮你记',
            textAlign: TextAlign.center,
            style: type.body.copyWith(color: colors.ink2),
          ),
          const SizedBox(height: 16),
          ChipButton(label: '记一条', onTap: _openCapture),
        ],
      ),
    );
  }
}

/// B4a 主题分组头：图标方块（语义浅底）+ 主题名 + 条数。
///
/// 图标只区分「有主题 / 未归类」两类，不给 tag 猜语义（红线 11：不编造）。
class _GroupHeader extends StatelessWidget {
  const _GroupHeader({
    required this.name,
    required this.count,
    required this.icon,
    required this.tintFg,
    required this.tintBg,
  });

  final String name;
  final int count;
  final IconData icon;
  final Color tintFg;
  final Color tintBg;

  @override
  Widget build(BuildContext context) {
    final colors = context.colors;
    final type = context.typography;
    final radii = context.radii;
    return Row(
      children: [
        Container(
          width: 28,
          height: 28,
          decoration: BoxDecoration(
            color: tintBg,
            borderRadius: BorderRadius.circular(radii.iconTile(28)),
          ),
          child: Icon(icon, size: 15, color: tintFg),
        ),
        const SizedBox(width: 9),
        Text(name, style: type.sectionTitle),
        const Spacer(),
        Text('$count 条', style: type.caption.copyWith(color: colors.ink3)),
      ],
    );
  }
}
