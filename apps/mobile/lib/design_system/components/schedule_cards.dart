import 'package:flutter/material.dart';

import '../tokens/tokens.dart';

AppColors _c(BuildContext context) =>
    Theme.of(context).extension<AppColors>()!;
AppTypography _t(BuildContext context) =>
    Theme.of(context).extension<AppTypography>()!;
AppRadii _r(BuildContext context) => Theme.of(context).extension<AppRadii>()!;
AppElevation _e(BuildContext context) =>
    Theme.of(context).extension<AppElevation>()!;

/// A40 week 迷你周日历的单日数据。
class WeekDay {
  const WeekDay({
    required this.weekdayLabel,
    required this.dayNumber,
    this.isToday = false,
    this.eventCount = 0,
  });

  final String weekdayLabel;
  final int dayNumber;
  final bool isToday;

  /// 当日事件数：仅用于画事件点（最多 3 个）。
  final int eventCount;
}

/// A40 week（迷你周日历）：7 列等宽 · 间隙 7 · 白卡圆角 14 · 内边距 9/0/8。
///
/// 今日态：底 ink + 文字白，事件点用 ai 三色；其余日事件点用 borderCheck。
class WeekStrip extends StatelessWidget {
  const WeekStrip({super.key, required this.days});

  static const dotSize = 5.0;
  static const maxDots = 3;

  final List<WeekDay> days;

  @override
  Widget build(BuildContext context) {
    return Row(
      children: [
        for (var i = 0; i < days.length; i++) ...[
          if (i > 0) const SizedBox(width: 7),
          Expanded(child: _day(context, days[i])),
        ],
      ],
    );
  }

  Widget _day(BuildContext context, WeekDay day) {
    final colors = _c(context);
    final type = _t(context);
    final elevation = _e(context);
    final onDark = day.isToday;
    return Container(
      padding: const EdgeInsets.fromLTRB(0, 9, 0, 8),
      decoration: BoxDecoration(
        color: onDark ? colors.ink : colors.surface,
        borderRadius: BorderRadius.circular(14),
        boxShadow: onDark ? null : elevation.card,
      ),
      child: Column(
        children: [
          Text(
            day.weekdayLabel,
            style: type.tabLabel.copyWith(
              fontSize: 10.5,
              color: onDark
                  ? colors.onDeepPrimary.withValues(alpha: 0.6)
                  : colors.ink3,
            ),
          ),
          const SizedBox(height: 3),
          Text(
            '${day.dayNumber}',
            style: type.numeric(type.rowTitle).copyWith(
              fontSize: 15,
              fontWeight: FontWeight.w700,
              color: onDark ? colors.onDeepPrimary : colors.ink,
            ),
          ),
          SizedBox(
            height: dotSize + 2,
            child: Padding(
              padding: const EdgeInsets.only(top: 5),
              child: Row(
                mainAxisAlignment: MainAxisAlignment.center,
                children: [
                  for (var i = 0;
                      i < day.eventCount && i < maxDots;
                      i++) ...[
                    if (i > 0) const SizedBox(width: 3),
                    Container(
                      width: dotSize,
                      height: dotSize,
                      decoration: BoxDecoration(
                        shape: BoxShape.circle,
                        color: onDark ? _aiDot(colors, i) : colors.borderCheck,
                      ),
                    ),
                  ],
                ],
              ),
            ),
          ),
        ],
      ),
    );
  }

  Color _aiDot(AppColors colors, int index) => switch (index) {
    0 => colors.aiPrimary,
    1 => colors.aiBlue,
    _ => colors.aiCyan,
  };
}

/// A40 tl 今日时间线单项。
class ScheduleTimelineItem {
  const ScheduleTimelineItem({
    required this.timeLabel,
    required this.title,
    this.subtitle,
    this.aiNote,
    this.badge,
    this.done = false,
  });

  final String timeLabel;
  final String title;
  final String? subtitle;

  /// 副文案里以 aiPrimary 高亮的 AI 回执。
  final String? aiNote;

  /// 标题右侧徽章（如任务标签），底色 rgba(122,92,255,.1)。
  final String? badge;
  final bool done;
}

/// A40 tl（今日时间线）：时间戳左置 + 白卡 + 卡片间垂直连线（末项无）。
class ScheduleTimeline extends StatelessWidget {
  const ScheduleTimeline({super.key, required this.items});

  final List<ScheduleTimelineItem> items;

  @override
  Widget build(BuildContext context) {
    return Column(
      children: [
        for (var i = 0; i < items.length; i++)
          _item(context, items[i], i == items.length - 1),
      ],
    );
  }

  Widget _item(BuildContext context, ScheduleTimelineItem item, bool isLast) {
    final colors = _c(context);
    final type = _t(context);
    return IntrinsicHeight(
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          SizedBox(
            width: 44,
            child: Padding(
              padding: const EdgeInsets.only(top: 2),
              child: Text(
                item.timeLabel,
                textAlign: TextAlign.right,
                style: type.numeric(type.caption).copyWith(
                  fontSize: 12,
                  color: colors.ink2,
                ),
              ),
            ),
          ),
          const SizedBox(width: 10),
          SizedBox(
            width: 1.5,
            child: isLast
                ? null
                : Padding(
                    padding: const EdgeInsets.only(top: 20),
                    child: ColoredBox(color: colors.line),
                  ),
          ),
          const SizedBox(width: 0.5),
          Expanded(
            child: Padding(
              padding: const EdgeInsets.only(bottom: 18),
              child: _card(context, item),
            ),
          ),
        ],
      ),
    );
  }

  Widget _card(BuildContext context, ScheduleTimelineItem item) {
    final colors = _c(context);
    final type = _t(context);
    final radii = _r(context);
    final elevation = _e(context);
    final titleColor = item.done ? colors.ink3 : colors.ink;
    final hasSub = item.subtitle != null || item.aiNote != null;
    return Container(
      padding: const EdgeInsets.symmetric(vertical: 13, horizontal: 15),
      decoration: BoxDecoration(
        color: colors.surface,
        borderRadius: radii.rMd,
        boxShadow: elevation.card,
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Wrap(
            crossAxisAlignment: WrapCrossAlignment.center,
            spacing: 7,
            runSpacing: 4,
            children: [
              Text(
                item.title,
                style: type.body.copyWith(
                  fontWeight: FontWeight.w600,
                  color: titleColor,
                  decoration: item.done ? TextDecoration.lineThrough : null,
                ),
              ),
              if (item.badge != null)
                Container(
                  padding: const EdgeInsets.symmetric(
                    vertical: 2,
                    horizontal: 8,
                  ),
                  decoration: BoxDecoration(
                    color: colors.tagPreferenceBg,
                    borderRadius: radii.rFull,
                  ),
                  child: Text(
                    item.badge!,
                    style: type.tabLabel.copyWith(
                      fontSize: 10.5,
                      fontWeight: FontWeight.w700,
                      color: colors.aiPrimary,
                    ),
                  ),
                ),
            ],
          ),
          if (hasSub) ...[
            const SizedBox(height: 3),
            Text.rich(
              TextSpan(
                children: [
                  if (item.subtitle != null) TextSpan(text: item.subtitle),
                  if (item.subtitle != null && item.aiNote != null)
                    const TextSpan(text: ' · '),
                  if (item.aiNote != null)
                    TextSpan(
                      text: item.aiNote,
                      style: TextStyle(
                        color: colors.aiPrimary,
                        fontWeight: FontWeight.w600,
                      ),
                    ),
                ],
              ),
              style: type.caption.copyWith(
                fontSize: 12,
                fontWeight: FontWeight.w400,
                height: 1.55,
                color: colors.ink3,
              ),
            ),
          ],
        ],
      ),
    );
  }
}

/// A40 next-card（即将到来卡）：日期方块 + 标题 / 副文案 + chevron，整行可点。
class NextCard extends StatelessWidget {
  const NextCard({
    super.key,
    required this.dateLabel,
    required this.dateNote,
    required this.title,
    this.subtitle,
    this.tint,
    this.tintFg,
    this.onTap,
  });

  final String dateLabel;
  final String dateNote;
  final String title;
  final String? subtitle;
  final Color? tint;
  final Color? tintFg;
  final VoidCallback? onTap;

  @override
  Widget build(BuildContext context) {
    final colors = _c(context);
    final type = _t(context);
    final radii = _r(context);
    final elevation = _e(context);
    final accent = tintFg ?? colors.ink2;
    return GestureDetector(
      onTap: onTap,
      behavior: HitTestBehavior.opaque,
      child: Container(
        margin: const EdgeInsets.only(bottom: 11),
        padding: const EdgeInsets.symmetric(vertical: 15, horizontal: 16),
        decoration: BoxDecoration(
          color: colors.surface,
          borderRadius: radii.rLg,
          boxShadow: elevation.card,
        ),
        child: Row(
          children: [
            Container(
              width: 46,
              height: 46,
              alignment: Alignment.center,
              decoration: BoxDecoration(
                color: tint ?? colors.fillSubtle,
                borderRadius: BorderRadius.circular(14),
              ),
              child: FittedBox(
                fit: BoxFit.scaleDown,
                child: Column(
                  mainAxisAlignment: MainAxisAlignment.center,
                  children: [
                    Text(
                      dateLabel,
                      style: type.numeric(type.rowTitle).copyWith(
                        fontSize: 16,
                        fontWeight: FontWeight.w700,
                        height: 1.1,
                        color: accent,
                      ),
                    ),
                    Text(
                      dateNote,
                      style: type.tabLabel.copyWith(
                        fontSize: 10,
                        color: accent.withValues(alpha: 0.75),
                      ),
                    ),
                  ],
                ),
              ),
            ),
            const SizedBox(width: 13),
            Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(
                    title,
                    style: type.body.copyWith(fontWeight: FontWeight.w600),
                  ),
                  if (subtitle != null) ...[
                    const SizedBox(height: 3),
                    Text(
                      subtitle!,
                      style: type.caption.copyWith(
                        fontSize: 11.5,
                        fontWeight: FontWeight.w400,
                        color: colors.ink3,
                      ),
                    ),
                  ],
                ],
              ),
            ),
            Icon(AppIcons.chevronRight, size: 16, color: colors.ink3),
          ],
        ),
      ),
    );
  }
}
