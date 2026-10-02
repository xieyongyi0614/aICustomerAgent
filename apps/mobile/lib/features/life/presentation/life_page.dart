import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../../app/state/album_summary_provider.dart';
import '../../../app/state/dynamic_tab.dart';
import '../../../app/theme/theme_context.dart';
import '../../../core/storage/prefs_store.dart';
import '../../../design_system/components/components.dart';
import '../../../design_system/orb/orb.dart';
import '../data/life_repository.dart';

/// B4 #life：生活工具箱 —— Hero（日期 / 问候 / Orb）+ AI 生活小结 + 模块宫格（3 列）。
/// 长按拖动重排，第一格即底部导航的「动态」位；摘要与趋势只用真实数据，无数据源按红线 11 明示未接入。
class LifePage extends ConsumerStatefulWidget {
  const LifePage({super.key, this.repository});

  final LifeRepository? repository;

  @override
  ConsumerState<LifePage> createState() => _LifePageState();
}

class _LifePageState extends ConsumerState<LifePage> {
  static const _idleHint = '长按卡片拖动重排 · 第一格就是底部导航的「动态」';
  static const _draggingHint = '松手放到想放的位置 · 第一格会成为「动态」';

  late final LifeRepository _repo = widget.repository ?? LifeRepository();
  List<LifeTaskItem>? _tasks;
  String? _expenseText;
  LifeCarSummary? _carSummary;
  String? _nickname;
  bool _tasksFailed = false;
  bool _ledgerFailed = false;
  bool _carFailed = false;
  bool _dragging = false;

  @override
  void initState() {
    super.initState();
    _load();
    _loadNickname();
  }

  /// Hero 问候用本机称呼；没设过称呼时不带名字，不编造。
  Future<void> _loadNickname() async {
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

  /// 日程格只算「今天」与「还没定时间」的待办；未来两周的留给日程页「即将到来」。
  List<LifeTaskItem> get _todayTasks {
    final now = DateTime.now();
    final day = DateTime(now.year, now.month, now.day);
    return [
      for (final task in _tasks ?? const <LifeTaskItem>[])
        if (task.kind != 'memo' && _isTodayOrUndated(task, day)) task,
    ];
  }

  bool _isTodayOrUndated(LifeTaskItem task, DateTime day) {
    final anchor = task.dueDateTime ?? task.remindDateTime;
    if (anchor == null) return true;
    return DateTime(anchor.year, anchor.month, anchor.day) == day;
  }

  static const _unavailable = '暂时取不到，点下方重试';

  String get _ledgerSummary {
    if (_ledgerFailed) return _unavailable;
    final expense = _expenseText;
    if (expense == null) return '…';
    final value = double.tryParse(expense) ?? 0;
    return value <= 0 ? '本月还没有支出' : '本月 ¥$expense';
  }

  String get _memoSummary {
    if (_tasksFailed) return _unavailable;
    if (_tasks == null) return '…';
    return _memoCount == 0 ? '还没有备忘' : '$_memoCount 条备忘';
  }

  String get _scheduleSummary {
    if (_tasksFailed) return _unavailable;
    if (_tasks == null) return '…';
    final items = _todayTasks;
    return items.isEmpty ? '今天没有待办' : '今日 ${items.length} 项';
  }

  String get _carSummaryText {
    if (_carFailed) return _unavailable;
    final car = _carSummary;
    if (car == null) return '…';
    return car.isEmpty ? '还没有养车记录' : '本月 ¥${car.text}';
  }

  String _albumSummaryText(AlbumSummary? summary) {
    if (!(summary?.authorized ?? false)) return '仅本机 · 需授权';
    final count = summary?.totalCount;
    if (count == null || count == 0) return '仅本机';
    return '$count 张 · 仅本机';
  }

  bool get _anyFailed => _tasksFailed || _ledgerFailed || _carFailed;

  String get _dateLabel {
    final now = DateTime.now();
    const weekday = ['周一', '周二', '周三', '周四', '周五', '周六', '周日'];
    return '${now.month}月${now.day}日 · ${weekday[now.weekday - 1]}';
  }

  String get _greeting {
    final prefix = switch (DateTime.now().hour) {
      >= 5 && < 11 => '早上好',
      >= 11 && < 13 => '中午好',
      >= 13 && < 18 => '下午好',
      >= 18 && < 23 => '晚上好',
      _ => '夜深了',
    };
    final name = _nickname;
    return name == null || name.isEmpty ? prefix : '$prefix，$name';
  }

  String _hhmm(DateTime at) =>
      '${at.hour.toString().padLeft(2, '0')}:'
      '${at.minute.toString().padLeft(2, '0')}';

  LifeTaskItem? get _firstTodayTask {
    final items = _todayTasks;
    return items.isEmpty ? null : items.first;
  }

  /// 限行原文只取首段（`下周三 · 尾号 4 和 9 · 建议地铁通勤` → `下周三`），拼成「下周三限行 · 已提醒」。
  String _restrictionTrend(String detail) {
    final head = detail.split(' · ').first.trim();
    if (head.isEmpty) return '限行提醒 · 已提醒';
    return head.contains('限行') ? '$head · 已提醒' : '$head限行 · 已提醒';
  }

  // 环比、AI 归类、健康评分客户端都拿不到 —— 按红线 11 明示未接入，不编造结论。
  String? get _ledgerTrend {
    if (_ledgerFailed) return null;
    final expense = _expenseText;
    if (expense == null) return null;
    return (double.tryParse(expense) ?? 0) <= 0 ? null : '环比尚未接入';
  }

  String? get _memoTrend {
    if (_tasksFailed || _tasks == null || _memoCount == 0) return null;
    return '主题归类尚未接入';
  }

  String? get _scheduleTrend {
    if (_tasksFailed) return null;
    final first = _firstTodayTask;
    if (first == null) return null;
    final at = first.dueDateTime ?? first.remindDateTime;
    return at == null ? first.title : '${_hhmm(at)} ${first.title}';
  }

  String? get _carTrend {
    if (_carFailed) return null;
    final detail = _carSummary?.restrictionDetail;
    return detail == null ? null : _restrictionTrend(detail);
  }

  String? _albumTrend(AlbumSummary? summary) =>
      (summary?.authorized ?? false) ? '整理建议尚未接入' : null;

  String _lifeSummary(AlbumSummary? albumSummary) {
    final parts = <String>[];
    if (!_tasksFailed && _tasks != null) {
      final first = _firstTodayTask;
      if (first != null) {
        final at = first.dueDateTime ?? first.remindDateTime;
        parts.add(at == null
            ? '今天有 ${_todayTasks.length} 项日程，先看「${first.title}」'
            : '今天有 ${_todayTasks.length} 项日程，${_hhmm(at)} ${first.title}');
      }
    }
    if (!_ledgerFailed && _expenseText != null) {
      if ((double.tryParse(_expenseText!) ?? 0) > 0) {
        parts.add('本月支出 ¥$_expenseText');
      }
    }
    if (!_carFailed && _carSummary != null && !_carSummary!.isEmpty) {
      parts.add('养车 ¥${_carSummary!.text}');
    }
    final detail = _carFailed ? null : _carSummary?.restrictionDetail;
    if (detail != null) {
      parts.add('车辆${_restrictionTrend(detail).replaceAll(' · 已提醒', '')}，我记进提醒了');
    }
    if (albumSummary?.authorized == true) {
      final count = albumSummary?.totalCount;
      parts.add(count == null || count == 0
          ? '相册只在本机'
          : '相册 $count 张只在本机，整理建议还没接上');
    }
    if (parts.isEmpty) {
      return '还没接上你的日程和账本。记一笔，或加个待办，我就能替你看着了。';
    }
    return '${parts.join('；')}。';
  }

  _ModuleTile _tileFor(LifeModule module, AlbumSummary? albumSummary) {
    final colors = context.colors;
    return switch (module) {
      LifeModule.ledger => _ModuleTile(
          module: module,
          summary: _ledgerSummary,
          trend: _ledgerTrend,
          tileBg: colors.tileMoney,
          tileFg: colors.money,
        ),
      LifeModule.memo => _ModuleTile(
          module: module,
          summary: _memoSummary,
          trend: _memoTrend,
          tileBg: colors.tileAi,
          tileFg: colors.aiPrimary,
        ),
      LifeModule.schedule => _ModuleTile(
          module: module,
          summary: _scheduleSummary,
          trend: _scheduleTrend,
          trendColor: colors.aiBlue,
          tileBg: colors.tileInfo,
          tileFg: colors.aiBlue,
        ),
      LifeModule.health => _ModuleTile(
          module: module,
          summary: '趋势参考 · 非诊断',
          trend: '尚未接入健康数据',
          tileBg: colors.tileHeart,
          tileFg: colors.heartFg,
        ),
      LifeModule.car => _ModuleTile(
          module: module,
          summary: _carSummaryText,
          trend: _carTrend,
          trendColor: colors.warm,
          tileBg: colors.tileInfo,
          tileFg: colors.aiBlue,
        ),
      LifeModule.album => _ModuleTile(
          module: module,
          summary: _albumSummaryText(albumSummary),
          trend: _albumTrend(albumSummary),
          tileBg: colors.tileWarm,
          tileFg: colors.warm,
        ),
    };
  }

  Future<void> _reorder(int from, int to) async {
    await ref.read(lifeModuleOrderProvider.notifier).moveTo(from, to);
  }

  @override
  Widget build(BuildContext context) {
    final colors = context.colors;
    final type = context.typography;
    final order = ref.watch(lifeModuleOrderProvider);
    final albumSummary = ref.watch(albumSummaryProvider);
    final tiles = {
      for (final module in LifeModule.values) module: _tileFor(module, albumSummary),
    };

    return Scaffold(
      backgroundColor: colors.canvas,
      body: SafeArea(
        bottom: false,
        child: ListView(
          padding: context.spacing.screenPadding,
          children: [
            _LifeHero(
              dateLabel: _dateLabel,
              greeting: _greeting,
              sub: '今天的生活，亚丝娜帮你看着呢',
            ),
            const SizedBox(height: 16),
            AiCard(
              title: '亚丝娜的生活小结',
              actionLabel: '查看今日日程',
              onAction: () => context.push<bool>('/schedule'),
              secondaryActionLabel: '去相册看看',
              onSecondaryAction: () => context.push<bool>('/album'),
              child: Text(
                _lifeSummary(albumSummary),
                style:
                    type.body.copyWith(color: colors.bodyOnCard, height: 1.75),
              ),
            ),
            const SizedBox(height: 14),
            AnimatedSwitcher(
              duration: const Duration(milliseconds: 160),
              child: Text(
                _dragging ? _draggingHint : _idleHint,
                key: ValueKey(_dragging),
                style: type.caption.copyWith(
                  color: _dragging ? colors.aiPrimary : colors.ink3,
                ),
              ),
            ),
            const SizedBox(height: 2),
            Row(
              children: [
                Text('生活模块', style: type.sectionTitle),
                const Spacer(),
                Text(
                  '${order.length} 个 · 都在帮你跑',
                  style: type.caption.copyWith(color: colors.ink3),
                ),
              ],
            ),
            const SizedBox(height: 10),
            _ReorderableModuleGrid(
              order: order,
              tileOf: (module) => tiles[module]!,
              onReorder: _reorder,
              onDragStateChanged: (dragging) {
                if (_dragging == dragging) return;
                setState(() => _dragging = dragging);
              },
              onTapModule: (module) => context.push<bool>(module.routePath),
            ),
            if (_anyFailed) ...[
              const SizedBox(height: 10),
              Align(
                alignment: Alignment.centerRight,
                child: ChipButton(label: '重试', ghost: true, onTap: _load),
              ),
            ],
            const SizedBox(height: 40),
          ],
        ),
      ),
    );
  }
}

class _ModuleTile {
  const _ModuleTile({
    required this.module,
    required this.summary,
    required this.tileBg,
    required this.tileFg,
    this.trend,
    this.trendColor,
  });

  final LifeModule module;
  final String summary;
  final Color tileBg;
  final Color tileFg;
  final String? trend;
  final Color? trendColor;
}

/// Hero：本地日期 + 时段问候（有称呼才带名字）+ 副标题，右侧 Orb 是 AI 存在标记。
class _LifeHero extends StatelessWidget {
  const _LifeHero({
    required this.dateLabel,
    required this.greeting,
    required this.sub,
  });

  final String dateLabel;
  final String greeting;
  final String sub;

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
              Text(
                dateLabel,
                style: type.caption.copyWith(
                  fontSize: 12.5,
                  fontWeight: FontWeight.w600,
                  letterSpacing: 0.25,
                  color: colors.ink3,
                ),
              ),
              const SizedBox(height: 3),
              Text(greeting, style: type.heroTitle.copyWith(fontSize: 23)),
              const SizedBox(height: 3),
              Text(sub, style: type.sub.copyWith(color: colors.ink2)),
            ],
          ),
        ),
        const Orb(size: OrbSize.md),
      ],
    );
  }
}

/// 可拖动重排宫格：拖动中其余卡片实时让位，落位带回弹（对齐 react-beautiful-dnd 的观感）。
class _ReorderableModuleGrid extends StatefulWidget {
  const _ReorderableModuleGrid({
    required this.order,
    required this.tileOf,
    required this.onReorder,
    required this.onDragStateChanged,
    required this.onTapModule,
  });

  final List<LifeModule> order;
  final _ModuleTile Function(LifeModule module) tileOf;
  final Future<void> Function(int from, int to) onReorder;
  final ValueChanged<bool> onDragStateChanged;
  final ValueChanged<LifeModule> onTapModule;

  @override
  State<_ReorderableModuleGrid> createState() => _ReorderableModuleGridState();
}

class _ReorderableModuleGridState extends State<_ReorderableModuleGrid> {
  static const _columns = 3;
  static const _gap = 11.0;

  /// 容纳「图标 + 名称 + 两行摘要 + 一行 trend」，真机与环境字体下都不溢出。
  static const _tileHeight = 156.0;
  static const _moveDuration = Duration(milliseconds: 240);
  static const _liftDuration = Duration(milliseconds: 180);
  static const _liftScale = 1.05;

  final _gridKey = GlobalKey();
  LifeModule? _lifted;
  Offset? _point;
  Offset _grabOffset = Offset.zero;
  int? _target;

  bool get _dragging => _lifted != null;

  List<LifeModule> get _previewOrder {
    final lifted = _lifted;
    if (lifted == null) return widget.order;
    final rest = widget.order.where((item) => item != lifted).toList();
    rest.insert((_target ?? 0).clamp(0, rest.length), lifted);
    return rest;
  }

  double _tileWidth(double maxWidth) =>
      (maxWidth - _gap * (_columns - 1)) / _columns;

  Offset _slotOf(double maxWidth, int index) => Offset(
        (index % _columns) * (_tileWidth(maxWidth) + _gap),
        (index ~/ _columns) * (_tileHeight + _gap),
      );

  int _nearestIndex(Offset local, double maxWidth) {
    final tileWidth = _tileWidth(maxWidth);
    var best = 0;
    var bestDistance = double.infinity;
    for (var index = 0; index < widget.order.length; index++) {
      final center = _slotOf(maxWidth, index) +
          Offset(tileWidth / 2, _tileHeight / 2);
      final distance = (local - center).distanceSquared;
      if (distance < bestDistance) {
        bestDistance = distance;
        best = index;
      }
    }
    return best;
  }

  void _startDrag(LifeModule module, LongPressStartDetails details) {
    final local = _localPoint(details.globalPosition);
    setState(() {
      _lifted = module;
      _point = local;
      _grabOffset = details.localPosition;
      _target = widget.order.indexOf(module);
    });
    widget.onDragStateChanged(true);
    HapticFeedback.selectionClick();
  }

  void _updateDrag(LongPressMoveUpdateDetails details) {
    final local = _localPoint(details.globalPosition);
    final box = _box;
    if (box == null) return;
    setState(() {
      _point = local;
      _target = _nearestIndex(local, box.size.width);
    });
  }

  void _drop() {
    final lifted = _lifted;
    if (lifted == null) return;
    final from = widget.order.indexOf(lifted);
    final to = _previewOrder.indexOf(lifted);
    setState(() {
      _lifted = null;
      _point = null;
      _target = null;
    });
    widget.onDragStateChanged(false);
    if (from == to) return;
    HapticFeedback.mediumImpact();
    widget.onReorder(from, to);
  }

  RenderBox? get _box =>
      _gridKey.currentContext?.findRenderObject() as RenderBox?;

  Offset _localPoint(Offset global) {
    final box = _box;
    if (box == null) return global;
    return box.globalToLocal(global);
  }

  @override
  Widget build(BuildContext context) {
    final preview = _previewOrder;
    final lifted = _lifted;
    final activeModule = preview.first;
    return LayoutBuilder(
      builder: (context, constraints) {
        final maxWidth = constraints.maxWidth;
        final tileWidth = _tileWidth(maxWidth);
        final rows = (widget.order.length / _columns).ceil();
        final height = rows * _tileHeight + (rows - 1) * _gap;
        final point = _point;

        final children = <Widget>[
          for (var index = 0; index < preview.length; index++)
            if (preview[index] != lifted)
              _positioned(
                module: preview[index],
                left: _slotOf(maxWidth, index).dx,
                top: _slotOf(maxWidth, index).dy,
                width: tileWidth,
                duration: _moveDuration,
                lifted: false,
                active: preview[index] == activeModule,
                liftedScale: false,
              ),
          if (lifted != null)
            _positioned(
              module: lifted,
              left: (point?.dx ?? 0) - _grabOffset.dx,
              top: (point?.dy ?? 0) - _grabOffset.dy,
              width: tileWidth,
              duration: point == null ? _moveDuration : Duration.zero,
              lifted: true,
              active: lifted == activeModule,
              liftedScale: true,
            ),
        ];

        return SizedBox(
          key: _gridKey,
          height: height,
          child: Stack(
            clipBehavior: Clip.none,
            children: children,
          ),
        );
      },
    );
  }

  Widget _positioned({
    required LifeModule module,
    required double left,
    required double top,
    required double width,
    required Duration duration,
    required bool lifted,
    required bool active,
    required bool liftedScale,
  }) {
    final tile = widget.tileOf(module);
    return AnimatedPositioned(
      key: ValueKey(module),
      duration: duration,
      curve: Curves.easeOutCubic,
      left: left,
      top: top,
      width: width,
      height: _tileHeight,
      child: GestureDetector(
        onLongPressStart: (details) => _startDrag(module, details),
        onLongPressMoveUpdate: _updateDrag,
        onLongPressEnd: (_) => _drop(),
        onLongPressCancel: _drop,
        behavior: HitTestBehavior.opaque,
        child: AnimatedScale(
          scale: liftedScale ? _liftScale : 1,
          duration: _liftDuration,
          curve: Curves.easeOutCubic,
          child: AnimatedOpacity(
            opacity: _dragging && !lifted ? 0.72 : 1,
            duration: _liftDuration,
            child: _LiftWrap(
              lifted: lifted,
              child: ModuleCard(
                title: tile.module.label,
                summary: tile.summary,
                trend: tile.trend,
                trendColor: tile.trendColor,
                icon: tile.module.icon,
                tileBg: tile.tileBg,
                tileFg: tile.tileFg,
                active: active,
                onTap: _dragging ? null : () => widget.onTapModule(module),
              ),
            ),
          ),
        ),
      ),
    );
  }
}

/// 拖起的卡片加一层深阴影（普通态不加阴影，阴影来自卡片自身）。
class _LiftWrap extends StatelessWidget {
  const _LiftWrap({required this.lifted, required this.child});

  final bool lifted;
  final Widget child;

  @override
  Widget build(BuildContext context) {
    return AnimatedContainer(
      duration: const Duration(milliseconds: 180),
      curve: Curves.easeOutCubic,
      decoration: BoxDecoration(
        borderRadius: context.radii.rMd,
        boxShadow: lifted ? context.elevation.deep : const <BoxShadow>[],
      ),
      child: child,
    );
  }
}
