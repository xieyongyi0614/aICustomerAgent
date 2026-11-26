import 'package:flutter/foundation.dart';
import 'package:flutter/material.dart';

import '../tokens/tokens.dart';
import 'chips.dart';
import 'gradient_border_card.dart';
import 'sparkle.dart';

export 'gradient_border_card.dart';

T _ext<T extends ThemeExtension<T>>(BuildContext context) =>
    Theme.of(context).extension<T>()!;

/// A1 通用卡片
class AppCard extends StatelessWidget {
  const AppCard({
    super.key,
    required this.child,
    this.padding = const EdgeInsets.all(18),
    this.listPadding = false,
  });

  final Widget child;
  final EdgeInsets padding;
  final bool listPadding;

  @override
  Widget build(BuildContext context) {
    final colors = _ext<AppColors>(context);
    final radii = _ext<AppRadii>(context);
    final elevation = _ext<AppElevation>(context);
    return Container(
      padding: listPadding
          ? const EdgeInsets.symmetric(vertical: 6, horizontal: 18)
          : padding,
      decoration: BoxDecoration(
        color: colors.surface,
        borderRadius: radii.rLg,
        boxShadow: elevation.card,
      ),
      child: child,
    );
  }
}

/// A2 AI 结论卡
///
/// 标签行（✦ + 12px/700 aiPrimary）是 AI 的身份标识 —— 红线 1：
/// 用户必须一眼分辨「哪部分是 AI」。渐变描边只属于本卡，不得下放到普通卡片。
class AiCard extends StatelessWidget {
  const AiCard({
    super.key,
    required this.title,
    required this.child,
    this.actionLabel,
    this.onAction,
    this.secondaryActionLabel,
    this.onSecondaryAction,
  });

  final String title;
  final Widget child;
  final String? actionLabel;
  final VoidCallback? onAction;

  /// 第二枚动作（chip 行的 ghost 位）。有它时两个动作都渲染成 chip（A2 动作行）。
  final String? secondaryActionLabel;
  final VoidCallback? onSecondaryAction;

  @override
  Widget build(BuildContext context) {
    final colors = _ext<AppColors>(context);
    final type = _ext<AppTypography>(context);
    return GradientBorderCard(
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              SparkleIcon(size: 13, color: colors.aiPrimary),
              const SizedBox(width: 7),
              Flexible(
                child: Text(
                  title,
                  style: type.caption.copyWith(
                    fontSize: 12,
                    fontWeight: FontWeight.w700,
                    letterSpacing: 0.72,
                    color: colors.aiPrimary,
                  ),
                ),
              ),
            ],
          ),
          const SizedBox(height: 9),
          child,
          if (secondaryActionLabel != null) ...[
            const SizedBox(height: 13),
            Row(
              children: [
                if (actionLabel != null) ...[
                  ChipButton(label: actionLabel!, onTap: onAction),
                  const SizedBox(width: 9),
                ],
                ChipButton(
                  label: secondaryActionLabel!,
                  onTap: onSecondaryAction,
                  ghost: true,
                ),
              ],
            ),
          ] else if (actionLabel != null) ...[
            const SizedBox(height: 12),
            GestureDetector(
              onTap: onAction,
              child: Text(
                actionLabel!,
                style: type.label.copyWith(color: colors.aiPrimary),
              ),
            ),
          ],
        ],
      ),
    );
  }
}

/// A5 指标迷你卡
class MetricCard extends StatelessWidget {
  const MetricCard({
    super.key,
    required this.label,
    required this.value,
    this.unit,
    this.note,
    this.sparkValues = const [],
  });

  final String label;
  final String value;
  final String? unit;
  final String? note;
  final List<double> sparkValues;

  @override
  Widget build(BuildContext context) {
    final colors = _ext<AppColors>(context);
    final type = _ext<AppTypography>(context);
    final radii = _ext<AppRadii>(context);
    final gradients = _ext<AppGradients>(context);
    final elevation = _ext<AppElevation>(context);
    return Container(
      padding: const EdgeInsets.symmetric(vertical: 13, horizontal: 12),
      decoration: BoxDecoration(
        color: colors.surface,
        borderRadius: radii.rMd,
        boxShadow: elevation.card,
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          // 标签与脚注都钉单行：同一行的多张指标卡不会因文案换行而高低不齐。
          Text(
            label,
            maxLines: 1,
            overflow: TextOverflow.ellipsis,
            style: type.caption.copyWith(color: colors.ink3),
          ),
          const SizedBox(height: 6),
          Row(
            crossAxisAlignment: CrossAxisAlignment.end,
            children: [
              Flexible(
                child: Text(
                  value,
                  maxLines: 1,
                  overflow: TextOverflow.ellipsis,
                  style: type.numeric(type.rowTitle),
                ),
              ),
              if (unit != null)
                Padding(
                  padding: const EdgeInsets.only(left: 2, bottom: 2),
                  child: Text(
                    unit!,
                    style: type.caption.copyWith(color: colors.ink3),
                  ),
                ),
            ],
          ),
          if (note != null) ...[
            const SizedBox(height: 4),
            Text(
              note!,
              maxLines: 1,
              overflow: TextOverflow.ellipsis,
              style: type.caption.copyWith(color: colors.ink3),
            ),
          ],
          if (sparkValues.isNotEmpty) ...[
            const SizedBox(height: 8),
            SizedBox(
              height: 22,
              child: CustomPaint(
                size: const Size(double.infinity, 22),
                painter: _SparkPainter(sparkValues, gradients.spark),
              ),
            ),
          ],
        ],
      ),
    );
  }
}

class _SparkPainter extends CustomPainter {
  _SparkPainter(this.values, this.gradient);
  final List<double> values;
  final Gradient gradient;

  @override
  void paint(Canvas canvas, Size size) {
    if (values.isEmpty) return;
    final maxV = values.reduce((a, b) => a > b ? a : b);
    final barW = 7.0;
    final gap = 3.0;
    final paint = Paint()..shader = gradient.createShader(Offset.zero & size);
    for (var i = 0; i < values.length && i < 7; i++) {
      final h = (values[i] / maxV) * size.height;
      final x = i * (barW + gap);
      canvas.drawRRect(
        RRect.fromRectAndRadius(
          Rect.fromLTWH(x, size.height - h, barW, h),
          const Radius.circular(3),
        ),
        paint,
      );
    }
  }

  @override
  bool shouldRepaint(covariant _SparkPainter old) => old.values != values;
}

/// A7 消费速览块
class SpendSummary extends StatelessWidget {
  const SpendSummary({
    super.key,
    required this.amountLabel,
    required this.noteLabel,
    this.progress,
    required this.weekBars,
    this.weekLabels = const <String>[],
    required this.conclusion,
  });

  final String amountLabel;

  /// 说明行（如「近 7 天 · 6 笔」）。
  final String noteLabel;

  /// 无真实预算时为 null —— 不渲染进度条（不再用编造的额度撑进度）。
  final double? progress;

  /// 近 7 天每日消费（元，旧→新）。**空列表或全 0 都是合法输入**：会画 7 根空桩，
  /// 不是什么都不画——否则「近 7 天没记账」看起来就像图表坏了。
  final List<double> weekBars;

  /// 与 [weekBars] 逐位对齐的横轴标签（周几，末位「今天」）；长度不足 7 则不画轴。
  final List<String> weekLabels;
  final String conclusion;

  @override
  Widget build(BuildContext context) {
    final colors = _ext<AppColors>(context);
    final type = _ext<AppTypography>(context);
    final gradients = _ext<AppGradients>(context);
    return AppCard(
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(amountLabel, style: type.numeric(type.briefTitle)),
          Text(noteLabel, style: type.caption.copyWith(color: colors.ink3)),
          if (progress != null) ...[
            const SizedBox(height: 12),
            ProgressBar(value: progress!, gradient: gradients.barMoney),
          ],
          const SizedBox(height: 12),
          _DayBarsChart(
            values: weekBars,
            labels: weekLabels,
            gradient: gradients.dayBars,
            trackColor: colors.trackBar,
          ),
          const SizedBox(height: 12),
          Text(conclusion, style: type.sub.copyWith(color: colors.ink2)),
        ],
      ),
    );
  }
}

/// A7 周柱状图：柱顶金额（只标非零，峰值加深，**贴着各自柱顶**）+ 7 根柱 + 横轴日期。
///
/// 金额与日期都按「7 等分 + 间隙 6」排槽位，与 [_DayBarsPainter] 的柱位逐根对齐。
/// 金额不是一条固定横带：每根标签从图底抬起 `柱高 + 4`，柱矮就跟着低（2026-10-07 实机反馈）。
class _DayBarsChart extends StatelessWidget {
  const _DayBarsChart({
    required this.values,
    required this.labels,
    required this.gradient,
    required this.trackColor,
  });

  final List<double> values;
  final List<String> labels;
  final Gradient gradient;
  final Color trackColor;

  @override
  Widget build(BuildContext context) {
    final colors = _ext<AppColors>(context);
    final type = _ext<AppTypography>(context);
    final maxValue =
        values.isEmpty ? 0.0 : values.reduce((a, b) => a > b ? a : b);
    final hasSpend = maxValue > 0;
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        SizedBox(
          // 有金额时图高多让出一条金额带，柱区仍然只占底部 44，保证最高的柱也放得下标签。
          height: hasSpend ? _chartHeight : _barAreaHeight,
          child: Stack(
            children: [
              Positioned(
                left: 0,
                right: 0,
                bottom: 0,
                height: _barAreaHeight,
                child: CustomPaint(
                  size: const Size(double.infinity, _barAreaHeight),
                  painter: _DayBarsPainter(values, gradient, trackColor),
                ),
              ),
              if (hasSpend)
                Positioned.fill(
                  child: _slots(
                    (index) => _amount(type, colors, index, maxValue),
                  ),
                ),
            ],
          ),
        ),
        if (labels.length == dayBarCount) ...[
          const SizedBox(height: 6),
          _slots((index) => _day(type, colors, index)),
        ],
      ],
    );
  }

  Widget _slots(Widget Function(int index) build) => Row(
        children: [
          for (var index = 0; index < dayBarCount; index++) ...[
            if (index > 0) const SizedBox(width: _barGap),
            Expanded(child: build(index)),
          ],
        ],
      );

  Widget _amount(
    AppTypography type,
    AppColors colors,
    int index,
    double maxValue,
  ) {
    final value = index < values.length ? values[index] : 0.0;
    if (value <= 0) return const SizedBox.shrink();
    final isPeak = value >= maxValue;
    final lift =
        dayBarGeometry(value, maxValue, _barAreaHeight).height + _amountGap;
    return Align(
      alignment: Alignment.bottomCenter,
      child: Padding(
        padding: EdgeInsets.only(bottom: lift),
        child: FittedBox(
          fit: BoxFit.scaleDown,
          child: Text(
            dayBarAmountLabel(value),
            maxLines: 1,
            style: type.caption.copyWith(
              fontSize: 10,
              fontWeight: isPeak ? FontWeight.w700 : FontWeight.w400,
              color: isPeak ? colors.ink : colors.ink3,
            ),
          ),
        ),
      ),
    );
  }

  Widget _day(AppTypography type, AppColors colors, int index) {
    final isToday = index == dayBarCount - 1;
    return Text(
      labels[index],
      textAlign: TextAlign.center,
      maxLines: 1,
      style: type.caption.copyWith(
        fontSize: 10,
        fontWeight: isToday ? FontWeight.w600 : FontWeight.w400,
        color: isToday ? colors.ink2 : colors.ink3,
      ),
    );
  }
}

/// A7 周柱状的根数与间隙（设计稿：7 根等宽铺满，间隙 6）。
const dayBarCount = 7;
const _barGap = 6.0;

/// 柱子的最小可见高：0.5 元的柱不该消失；同时用作「空桩」的高度。
const _barMinHeight = 4.0;

/// 柱区高度（设计稿：周柱状高 44）。
const _barAreaHeight = 44.0;

/// 金额标签与柱顶的间隙。
const _amountGap = 4.0;

/// 柱顶金额带的高度：间隙 4 + 文本余量 16。
/// 图高 = 柱区 44 + 金额带 20 —— 最高的柱（44）抬起 48 后仍有 16 放得下标签，不会溢出。
const _amountBandHeight = 20.0;
const _chartHeight = _barAreaHeight + _amountBandHeight;

/// A7 柱顶金额文案：整数元、不带千分位——每根柱只有 ~40px，5 字符内放得下，
/// 再长由 `FittedBox` 缩放兜底。
@visibleForTesting
String dayBarAmountLabel(double yuan) => '¥${yuan.round()}';

/// A7 单根柱的几何：`(height, empty)`。
///
/// - 该天为 0（或整周全 0）→ `empty = true`，画一根 `trackBar` 色的**空桩**。
///   数据源真实返回了 0，画空桩表达的是「这天没账」；什么都不画才会让人以为图表坏了。
/// - 非 0 → 按周内最大值归一，并给 [_barMinHeight] 的可见下限。
@visibleForTesting
({double height, bool empty}) dayBarGeometry(
  double value,
  double maxValue,
  double maxHeight,
) {
  if (maxValue <= 0 || value <= 0) {
    return (height: _barMinHeight, empty: true);
  }
  return (
    height: (value / maxValue * maxHeight).clamp(_barMinHeight, maxHeight),
    empty: false,
  );
}

class _DayBarsPainter extends CustomPainter {
  _DayBarsPainter(this.values, this.gradient, this.trackColor);

  final List<double> values;
  final Gradient gradient;
  final Color trackColor;

  @override
  void paint(Canvas canvas, Size size) {
    final maxV = values.isEmpty
        ? 0.0
        : values.reduce((a, b) => a > b ? a : b);
    final barW =
        ((size.width - _barGap * (dayBarCount - 1)) / dayBarCount)
            .clamp(1.0, size.width);
    final barPaint = Paint()..shader = gradient.createShader(Offset.zero & size);
    final stubPaint = Paint()..color = trackColor;
    for (var i = 0; i < dayBarCount; i++) {
      final value = i < values.length ? values[i] : 0.0;
      final bar = dayBarGeometry(value, maxV, size.height);
      canvas.drawRRect(
        RRect.fromRectAndRadius(
          Rect.fromLTWH(
            i * (barW + _barGap),
            size.height - bar.height,
            barW,
            bar.height,
          ),
          const Radius.circular(5),
        ),
        bar.empty ? stubPaint : barPaint,
      );
    }
  }

  @override
  bool shouldRepaint(covariant _DayBarsPainter old) =>
      !listEquals(old.values, values) ||
      old.gradient != gradient ||
      old.trackColor != trackColor;
}

/// 进度条（高 7 / rFull）
class ProgressBar extends StatelessWidget {
  const ProgressBar({
    super.key,
    required this.value,
    required this.gradient,
  });

  final double value;
  final Gradient gradient;

  @override
  Widget build(BuildContext context) {
    final colors = _ext<AppColors>(context);
    final radii = _ext<AppRadii>(context);
    return LayoutBuilder(
      builder: (context, constraints) {
        final w = constraints.maxWidth * value.clamp(0, 1);
        return Container(
          height: 7,
          decoration: BoxDecoration(
            color: colors.trackBar,
            borderRadius: radii.rFull,
          ),
          child: Align(
            alignment: Alignment.centerLeft,
            child: Container(
              width: w,
              decoration: BoxDecoration(
                gradient: gradient,
                borderRadius: radii.rFull,
              ),
            ),
          ),
        );
      },
    );
  }
}

/// A24 记忆卡
class MemoryCard extends StatelessWidget {
  const MemoryCard({
    super.key,
    required this.tagLabel,
    required this.tagBg,
    required this.tagFg,
    required this.content,
    required this.sourceNote,
    this.usageNote,
    this.onEdit,
    this.onForget,
  });

  final String tagLabel;
  final Color tagBg;
  final Color tagFg;
  final String content;
  final String sourceNote;
  final String? usageNote;
  final VoidCallback? onEdit;
  final VoidCallback? onForget;

  @override
  Widget build(BuildContext context) {
    final colors = _ext<AppColors>(context);
    final type = _ext<AppTypography>(context);
    final radii = _ext<AppRadii>(context);
    final elevation = _ext<AppElevation>(context);
    return Container(
      margin: const EdgeInsets.only(bottom: 11),
      padding: const EdgeInsets.symmetric(vertical: 15, horizontal: 16),
      decoration: BoxDecoration(
        color: colors.surface,
        borderRadius: radii.rMd,
        boxShadow: elevation.card,
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              Container(
                padding: const EdgeInsets.symmetric(vertical: 3, horizontal: 9),
                decoration: BoxDecoration(
                  color: tagBg,
                  borderRadius: radii.rFull,
                ),
                child: Text(
                  tagLabel,
                  style: type.tabLabel.copyWith(color: tagFg, letterSpacing: 0.5),
                ),
              ),
              const Spacer(),
              if (onEdit != null)
                GestureDetector(
                  onTap: onEdit,
                  child: Text('编辑',
                      style: type.caption.copyWith(color: colors.ink3)),
                ),
              if (onForget != null) ...[
                const SizedBox(width: 12),
                GestureDetector(
                  onTap: onForget,
                  child: Text('遗忘',
                      style: type.caption.copyWith(color: colors.ink3)),
                ),
              ],
            ],
          ),
          const SizedBox(height: 10),
          Text(content, style: type.rowTitle.copyWith(height: 1.55)),
          const SizedBox(height: 8),
          Text(sourceNote, style: type.caption.copyWith(color: colors.ink3)),
          if (usageNote != null)
            Text(usageNote!, style: type.caption.copyWith(color: colors.ink3)),
        ],
      ),
    );
  }
}

/// A25 隐私承诺卡
class PrivacyNote extends StatelessWidget {
  const PrivacyNote({super.key, required this.child});

  final Widget child;

  @override
  Widget build(BuildContext context) {
    final colors = _ext<AppColors>(context);
    final radii = _ext<AppRadii>(context);
    return Container(
      margin: const EdgeInsets.only(top: 20),
      padding: const EdgeInsets.symmetric(vertical: 15, horizontal: 16),
      decoration: BoxDecoration(
        color: colors.tileHealth,
        borderRadius: radii.rMd,
        border: Border.all(color: colors.health.withValues(alpha: 0.18)),
      ),
      child: DefaultTextStyle(
        style: TextStyle(
          fontSize: 12,
          height: 1.7,
          color: colors.privacyText,
        ),
        child: child,
      ),
    );
  }
}
