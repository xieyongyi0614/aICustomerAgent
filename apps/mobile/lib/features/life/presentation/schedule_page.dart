import 'package:flutter/material.dart';
import 'package:go_router/go_router.dart';
import 'package:intl/intl.dart';

import '../../../app/theme/theme_context.dart';
import '../../../design_system/components/components.dart';
import '../data/life_repository.dart';

const _weekdayLabels = ['一', '二', '三', '四', '五', '六', '日'];

/// B4b `#schedule` 日程（42）：迷你周日历 → AI 排法 → 今日时间线 → 即将到来。
///
/// 日程 = 日历 + 任务合一（2026-09-30 IA 裁决），复用任务域（`kind=task`）。
/// 无日期的待办不编造时间，落时间线末位并标「待排」。
class SchedulePage extends StatefulWidget {
  const SchedulePage({super.key, this.repository, this.showBackLink = true});

  final LifeRepository? repository;

  /// false = 作为「动态」Tab 根页渲染：不出现「‹ 生活」返回链接。
  final bool showBackLink;

  @override
  State<SchedulePage> createState() => _SchedulePageState();
}

class _SchedulePageState extends State<SchedulePage> {
  late final LifeRepository _repo = widget.repository ?? LifeRepository();
  List<LifeTaskItem>? _tasks;
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
      // DA-19：拉 open + done，时间线的删除线完成态由此而来。
      final tasks = await _repo.listTasks(status: 'all');
      if (!mounted) return;
      setState(() {
        _tasks = tasks.where((task) => task.kind != 'memo').toList();
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

  DateTime get _today {
    final now = DateTime.now();
    return DateTime(now.year, now.month, now.day);
  }

  /// 任务的落点日期：优先 `due_date`，其次 `remind_at`；都没有则未排期。
  DateTime? _dateOf(LifeTaskItem task) {
    final due = task.dueDateTime;
    if (due != null) return DateTime(due.year, due.month, due.day);
    final remind = task.remindDateTime;
    if (remind != null) return DateTime(remind.year, remind.month, remind.day);
    return null;
  }

  String _timeLabel(LifeTaskItem task) {
    final remind = task.remindDateTime;
    if (remind != null) return DateFormat('HH:mm').format(remind);
    final completed = task.completedDateTime;
    if (task.status != 'open' && completed != null) {
      return DateFormat('HH:mm').format(completed);
    }
    return _dateOf(task) == null ? '待排' : '全天';
  }

  List<LifeTaskItem> get _all => _tasks ?? const <LifeTaskItem>[];

  /// 已完成且属于今天：有当日日期，或无日期但今天完成（跨天旧完成项不上时间线）。
  bool _isTodayDone(LifeTaskItem task, DateTime today) {
    if (task.status == 'open') return false;
    final date = _dateOf(task);
    if (date != null) return date == today;
    final completed = task.completedDateTime;
    return completed != null &&
        DateTime(completed.year, completed.month, completed.day) == today;
  }

  List<LifeTaskItem> get _todayItems {
    final today = _today;
    final items = _all
        .where(
          (task) =>
              task.status == 'open'
              ? _dateOf(task) == today
              : _isTodayDone(task, today),
        )
        .toList();
    items.sort((a, b) {
      final ra = a.remindDateTime ?? (a.status != 'open' ? a.completedDateTime : null);
      final rb = b.remindDateTime ?? (b.status != 'open' ? b.completedDateTime : null);
      if (ra == null && rb == null) return 0;
      if (ra == null) return 1;
      if (rb == null) return -1;
      return ra.compareTo(rb);
    });
    return [...items, ..._all.where((task) => _dateOf(task) == null && task.status == 'open')];
  }

  List<LifeTaskItem> get _upcoming {
    final today = _today;
    final limit = today.add(const Duration(days: 14));
    final items = _all.where((task) {
      if (task.status != 'open') return false;
      final date = _dateOf(task);
      return date != null && date.isAfter(today) && !date.isAfter(limit);
    }).toList();
    items.sort((a, b) => _dateOf(a)!.compareTo(_dateOf(b)!));
    return items.take(5).toList();
  }

  List<WeekDay> get _week {
    final today = _today;
    final monday = today.subtract(Duration(days: today.weekday - 1));
    return [
      for (var i = 0; i < 7; i++) _weekDay(monday.add(Duration(days: i)), today),
    ];
  }

  WeekDay _weekDay(DateTime day, DateTime today) => WeekDay(
    weekdayLabel: _weekdayLabels[day.weekday - 1],
    dayNumber: day.day,
    isToday: day == today,
    eventCount: _all.where((task) => _dateOf(task) == day).length,
  );

  String get _todayHeading {
    final today = _today;
    return '今天 · ${today.month}月${today.day}日 周${_weekdayLabels[today.weekday - 1]}';
  }

  String get _aiConclusion {
    final items = _todayItems;
    if (items.isEmpty) {
      return '今天还没有排到事。想加一件，跟我说一句就行。';
    }
    final undated = items.where((task) => _dateOf(task) == null).length;
    final undatedPart = undated == 0
        ? ''
        : '另有 $undated 件还没定时间，告诉我什么时候做，我帮你排进去。';
    return '今天 ${items.length} 件事，我按你的精力节奏排好了——'
        '需要专注的放前面，跑外勤的往后挪。$undatedPart';
  }

  Future<void> _act(LifeTaskItem task) async {
    final colors = context.colors;
    final action = await showModalBottomSheet<String>(
      context: context,
      builder: (sheetContext) => SafeArea(
        child: Padding(
          padding: const EdgeInsets.fromLTRB(18, 16, 18, 20),
          child: Column(
            mainAxisSize: MainAxisSize.min,
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text(task.title, style: context.typography.sectionTitle),
              const SizedBox(height: 12),
              Row(
                children: [
                  ChipButton(
                    label: '标记完成',
                    onTap: () => Navigator.of(sheetContext).pop('complete'),
                  ),
                  const SizedBox(width: 8),
                  ChipButton(
                    label: '删除',
                    ghost: true,
                    onTap: () => Navigator.of(sheetContext).pop('delete'),
                  ),
                ],
              ),
              const SizedBox(height: 8),
              Text(
                '完成与删除都会同步到你的任务域',
                style: context.typography.caption.copyWith(color: colors.ink3),
              ),
            ],
          ),
        ),
      ),
    );
    if (action == null) return;
    try {
      if (action == 'complete') {
        await _repo.completeTask(task.id);
      } else {
        await _repo.deleteTask(task.id);
      }
    } catch (_) {
      if (!mounted) return;
      ScaffoldMessenger.of(context)
        ..hideCurrentSnackBar()
        ..showSnackBar(const SnackBar(content: Text('没保存上，检查网络后再试')));
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
    if (_tasks == null) {
      if (_loading) {
        return ListView(
          padding: context.spacing.screenPadding,
          children: const [SkeletonCard(), SkeletonCard()],
        );
      }
      return _error == null
          ? const EmptyState(message: '今天还没有排到事，跟我说一句就好')
          : ErrorState(message: StateCopy.serverError, onRetry: _load);
    }

    final todayItems = _todayItems;
    final upcoming = _upcoming;
    return ListView(
      padding: context.spacing.screenPadding,
      children: [
        Text('日程', style: type.pageTitle),
        Text(
          '会议与待办在一起，亚丝娜帮你排',
          style: type.sub.copyWith(color: colors.ink2),
        ),
        const SizedBox(height: 18),
        WeekStrip(days: _week),
        const SizedBox(height: 16),
        AiCard(
          title: '亚丝娜的排法',
          child: Text(
            _aiConclusion,
            style: type.body.copyWith(fontSize: 13.5, color: colors.bodyOnCard),
          ),
        ),
        Padding(
          padding: const EdgeInsets.only(top: 24, bottom: 11),
          child: Row(
            children: [
              Text(_todayHeading, style: type.sectionTitle),
              const Spacer(),
              Text('AI 已排序', style: type.caption.copyWith(color: colors.ink3)),
            ],
          ),
        ),
        if (todayItems.isEmpty)
          const EmptyState(message: '今天还没有排到事，跟我说一句就好')
        else
          ScheduleTimeline(
            items: [
              for (final task in todayItems)
                ScheduleTimelineItem(
                  timeLabel: _timeLabel(task),
                  title: task.title,
                  subtitle: task.note,
                  aiNote: task.orderReason,
                  badge: (task.tag ?? '').isEmpty ? null : task.tag,
                  done: task.status != 'open',
                ),
            ],
          ),
        Padding(
          padding: const EdgeInsets.only(top: 24, bottom: 11),
          child: Row(
            children: [
              Text('即将到来', style: type.sectionTitle),
              const Spacer(),
              Text('未来 14 天', style: type.caption.copyWith(color: colors.ink3)),
            ],
          ),
        ),
        if (upcoming.isEmpty)
          Text(
            '未来两周还没有安排',
            style: type.sub.copyWith(color: colors.ink3),
          )
        else
          for (final task in upcoming)
            NextCard(
              dateLabel: DateFormat('M.d').format(_dateOf(task)!),
              dateNote: '周${_weekdayLabels[_dateOf(task)!.weekday - 1]}',
              title: task.title,
              subtitle: task.orderReason ?? task.note,
              tint: colors.tileInfo,
              tintFg: colors.aiBlue,
              onTap: () => _act(task),
            ),
        const SizedBox(height: 40),
      ],
    );
  }
}
