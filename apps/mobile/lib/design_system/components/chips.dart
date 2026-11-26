import 'package:flutter/material.dart';

import '../tokens/tokens.dart';
import 'sparkle.dart';

AppColors _c(BuildContext context) => Theme.of(context).extension<AppColors>()!;
AppTypography _t(BuildContext context) =>
    Theme.of(context).extension<AppTypography>()!;
AppRadii _r(BuildContext context) => Theme.of(context).extension<AppRadii>()!;
AppElevation _e(BuildContext context) =>
    Theme.of(context).extension<AppElevation>()!;
AppGradients _g(BuildContext context) =>
    Theme.of(context).extension<AppGradients>()!;

/// A10 模式 chip
class ModeChip extends StatelessWidget {
  const ModeChip({super.key, required this.label});

  final String label;

  @override
  Widget build(BuildContext context) {
    final colors = _c(context);
    final type = _t(context);
    final radii = _r(context);
    return Container(
      padding: const EdgeInsets.symmetric(vertical: 4, horizontal: 11),
      decoration: BoxDecoration(
        color: colors.tagPreferenceBg,
        borderRadius: radii.rFull,
        border: Border.all(color: colors.aiPrimary.withValues(alpha: 0.22)),
      ),
      child: Row(
        mainAxisSize: MainAxisSize.min,
        children: [
          SparkleIcon(size: 11, color: colors.aiPrimary),
          const SizedBox(width: 5),
          Text(
            label,
            style: type.label.copyWith(color: colors.aiPrimary, fontSize: 11.5),
          ),
        ],
      ),
    );
  }
}

/// A11 记忆提示条
class MemHint extends StatelessWidget {
  const MemHint({super.key, required this.text});

  final String text;

  @override
  Widget build(BuildContext context) {
    final colors = _c(context);
    final type = _t(context);
    return Container(
      padding: const EdgeInsets.symmetric(vertical: 9, horizontal: 13),
      decoration: BoxDecoration(
        color: colors.tagPreferenceBg,
        borderRadius: BorderRadius.circular(12),
        border: Border.all(color: colors.aiPrimary.withValues(alpha: 0.16)),
      ),
      child: Row(
        children: [
          SparkleIcon(size: 14, color: colors.aiPrimary),
          const SizedBox(width: 8),
          Expanded(
            child: Text(
              text,
              style: type.caption.copyWith(
                color: colors.aiPrimary,
                fontSize: 12,
              ),
            ),
          ),
        ],
      ),
    );
  }
}

/// A12 建议操作 chip
class ChipButton extends StatelessWidget {
  const ChipButton({
    super.key,
    required this.label,
    this.onTap,
    this.ghost = false,
  });

  final String label;
  final VoidCallback? onTap;
  final bool ghost;

  @override
  Widget build(BuildContext context) {
    final colors = _c(context);
    final type = _t(context);
    final radii = _r(context);
    return GestureDetector(
      onTap: onTap,
      child: Container(
        padding: const EdgeInsets.symmetric(vertical: 7, horizontal: 14),
        decoration: BoxDecoration(
          color: ghost ? colors.surface : colors.tagPreferenceBg,
          borderRadius: radii.rFull,
          border: Border.all(
            color: ghost
                ? colors.line
                : colors.aiPrimary.withValues(alpha: 0.20),
          ),
        ),
        child: Text(
          label,
          style: type.label.copyWith(
            color: ghost ? colors.ink2 : colors.aiPrimary,
            fontSize: 12.5,
          ),
        ),
      ),
    );
  }
}

/// A8 输入丸
class AskPill extends StatelessWidget {
  const AskPill({super.key, this.hint = '问问亚丝娜，或直接说「午饭 35 元」…', this.onSend});

  final String hint;
  final VoidCallback? onSend;

  @override
  Widget build(BuildContext context) {
    final colors = _c(context);
    final type = _t(context);
    final radii = _r(context);
    final elevation = _e(context);
    return Container(
      padding: const EdgeInsets.fromLTRB(14, 8, 8, 8),
      decoration: BoxDecoration(
        color: colors.surface,
        borderRadius: radii.rFull,
        boxShadow: elevation.card,
      ),
      child: Row(
        children: [
          SparkleIcon(size: 16, color: colors.aiPrimary),
          const SizedBox(width: 8),
          Expanded(
            child: Text(hint, style: type.body.copyWith(color: colors.ink3)),
          ),
          GestureDetector(
            onTap: onSend,
            child: Container(
              width: 38,
              height: 38,
              decoration: BoxDecoration(
                shape: BoxShape.circle,
                gradient: _g(context).ai,
              ),
              child: Icon(
                AppIcons.arrowUp,
                size: 17,
                color: colors.onDeepPrimary,
              ),
            ),
          ),
        ],
      ),
    );
  }
}

/// A17 快速捕获条
class CaptureBar extends StatelessWidget {
  const CaptureBar({super.key, this.hint = '「记一下，下个月准备去旅行」…', this.onTap});

  final String hint;
  final VoidCallback? onTap;

  @override
  Widget build(BuildContext context) {
    final colors = _c(context);
    final type = _t(context);
    final radii = _r(context);
    final elevation = _e(context);
    return GestureDetector(
      onTap: onTap,
      child: Container(
        margin: const EdgeInsets.only(bottom: 22),
        padding: const EdgeInsets.symmetric(vertical: 13, horizontal: 15),
        decoration: BoxDecoration(
          color: colors.surface,
          borderRadius: radii.rMd,
          boxShadow: elevation.card,
        ),
        child: Row(
          children: [
            SparkleIcon(size: 17, color: colors.aiPrimary),
            const SizedBox(width: 10),
            Expanded(
              child: Text(hint, style: type.body.copyWith(color: colors.ink3)),
            ),
          ],
        ),
      ),
    );
  }
}

/// A18 生活模块卡（含 soon 虚线变体）
class ModuleCard extends StatelessWidget {
  const ModuleCard({
    super.key,
    required this.title,
    required this.summary,
    this.icon,
    this.tileBg,
    this.tileFg,
    this.soon = false,
    this.active = false,
    this.trend,
    this.trendColor,
    this.onTap,
    this.onLongPress,
  });

  final String title;
  final String summary;
  final IconData? icon;
  final Color? tileBg;
  final Color? tileFg;
  final bool soon;
  final bool active;

  /// 卡片第三行：结论 / 趋势（A18）。摘要只放事实，结论走这一行。
  final String? trend;
  final Color? trendColor;
  final VoidCallback? onTap;
  final VoidCallback? onLongPress;

  @override
  Widget build(BuildContext context) {
    final colors = _c(context);
    final type = _t(context);
    final radii = _r(context);
    final elevation = _e(context);
    return GestureDetector(
      onTap: onTap,
      onLongPress: onLongPress,
      child: Stack(
        fit: StackFit.passthrough,
        clipBehavior: Clip.none,
        children: [
          Container(
            padding: const EdgeInsets.fromLTRB(10, 15, 10, 13),
            decoration: soon
                ? BoxDecoration(
                    borderRadius: radii.rMd,
                    border: Border.all(color: colors.borderDashed, width: 1.5),
                  )
                : BoxDecoration(
                    color: colors.surface,
                    borderRadius: radii.rMd,
                    boxShadow: elevation.card,
                  ),
            // 顶部起排、间距固定：图标 / 标题 / 摘要在 6 张卡里位置一致，
            // 不随 trend 行有无而漂移（spaceEvenly 会按内容行数重分配空隙）。
            child: Column(
              children: [
                Container(
                  width: 42,
                  height: 42,
                  decoration: BoxDecoration(
                    color: soon ? colors.fillMuted : (tileBg ?? colors.tileAi),
                    borderRadius: BorderRadius.circular(radii.iconTile(42)),
                  ),
                  child: icon == null
                      ? null
                      : Icon(
                          icon,
                          size: 20,
                          color: soon
                              ? colors.inkOnSoon
                              : (tileFg ?? colors.aiPrimary),
                        ),
                ),
                const SizedBox(height: 9),
                Text(
                  title,
                  style: type.body.copyWith(
                    fontWeight: FontWeight.w600,
                    color: soon ? colors.ink3 : colors.ink,
                  ),
                ),
                const SizedBox(height: 3),
                // 行高钉 1.4 + 摘要单行省略：卡内内容高度确定，卡高才能压实到贴合内容，
                // 不随设备字体度量漂移（摘要文案必须 ≤ 单行，长文案会在 390 宽下省略）。
                Text(
                  summary,
                  maxLines: 1,
                  overflow: TextOverflow.ellipsis,
                  style:
                      type.tabLabel.copyWith(color: colors.ink3, height: 1.4),
                  textAlign: TextAlign.center,
                ),
                if (trend != null) ...[
                  const SizedBox(height: 4),
                  Text(
                    trend!,
                    maxLines: 1,
                    overflow: TextOverflow.ellipsis,
                    style: type.tabLabel.copyWith(
                      fontSize: 10,
                      fontWeight: FontWeight.w600,
                      color: trendColor ?? colors.ink3,
                      height: 1.4,
                    ),
                    textAlign: TextAlign.center,
                  ),
                ],
              ],
            ),
          ),
          if (active)
            Positioned(
              top: 8,
              right: 8,
              child: Container(
                padding: const EdgeInsets.symmetric(vertical: 1, horizontal: 6),
                decoration: BoxDecoration(
                  color: colors.tileAi,
                  borderRadius: radii.rFull,
                ),
                child: Row(
                  mainAxisSize: MainAxisSize.min,
                  children: [
                    SparkleIcon(size: 9, color: colors.aiPrimary),
                    const SizedBox(width: 3),
                    Text(
                      '动态',
                      style: type.tabLabel.copyWith(color: colors.aiPrimary),
                    ),
                  ],
                ),
              ),
            ),
        ],
      ),
    );
  }
}

/// A19 分类支出条
class CategoryBar extends StatelessWidget {
  const CategoryBar({
    super.key,
    required this.label,
    required this.amountLabel,
    required this.ratio,
    required this.gradient,
  });

  final String label;
  final String amountLabel;
  final double ratio;
  final Gradient gradient;

  @override
  Widget build(BuildContext context) {
    final type = _t(context);
    return Padding(
      padding: const EdgeInsets.only(bottom: 13),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              Text(
                label,
                style: type.body.copyWith(
                  fontWeight: FontWeight.w600,
                  fontSize: 13,
                ),
              ),
              const Spacer(),
              Text(amountLabel, style: type.numeric(type.sub)),
            ],
          ),
          const SizedBox(height: 6),
          _BarTrack(ratio: ratio, gradient: gradient),
        ],
      ),
    );
  }
}

/// A39 计数胶囊：标题右侧「12 条 · 3 个主题」。
class CountPill extends StatelessWidget {
  const CountPill({super.key, required this.text});

  final String text;

  @override
  Widget build(BuildContext context) {
    final colors = _c(context);
    final type = _t(context);
    final radii = _r(context);
    return Container(
      padding: const EdgeInsets.symmetric(vertical: 6, horizontal: 12),
      decoration: BoxDecoration(
        color: colors.surface,
        borderRadius: radii.rFull,
        border: Border.all(color: colors.line),
      ),
      child: Text(
        text,
        style: type.caption.copyWith(fontSize: 12.5, color: colors.ink2),
      ),
    );
  }
}

/// A39 备忘行：主题色点 + 内容 + 来源行（来源可带 AI 关联回执）。
///
/// 长按触发删除（设计稿 41 只承诺「长按删除」；修改未落地）。
class MemoRow extends StatelessWidget {
  const MemoRow({
    super.key,
    required this.title,
    required this.dotColor,
    this.sourceNote,
    this.aiNote,
    this.showDivider = true,
    this.onLongPress,
  });

  final String title;
  final Color dotColor;
  final String? sourceNote;

  /// AI 关联回执（如「已排进今日任务」），以 aiPrimary 高亮。
  final String? aiNote;
  final bool showDivider;
  final VoidCallback? onLongPress;

  @override
  Widget build(BuildContext context) {
    final colors = _c(context);
    final type = _t(context);
    final hasNote = sourceNote != null || aiNote != null;
    return GestureDetector(
      onLongPress: onLongPress,
      behavior: HitTestBehavior.opaque,
      child: Container(
        padding: const EdgeInsets.symmetric(vertical: 13),
        decoration: showDivider
            ? BoxDecoration(
                border: Border(bottom: BorderSide(color: colors.line)),
              )
            : null,
        child: Row(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Container(
              width: 8,
              height: 8,
              margin: const EdgeInsets.only(top: 7),
              decoration: BoxDecoration(
                shape: BoxShape.circle,
                color: dotColor,
              ),
            ),
            const SizedBox(width: 12),
            Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(
                    title,
                    style: type.body.copyWith(
                      height: 1.55,
                      color: colors.ink,
                    ),
                  ),
                  if (hasNote) ...[
                    const SizedBox(height: 4),
                    Text.rich(
                      TextSpan(
                        children: [
                          if (sourceNote != null) TextSpan(text: sourceNote),
                          if (sourceNote != null && aiNote != null)
                            const TextSpan(text: ' · '),
                          if (aiNote != null)
                            TextSpan(
                              text: aiNote,
                              style: TextStyle(
                                color: colors.aiPrimary,
                                fontWeight: FontWeight.w600,
                              ),
                            ),
                        ],
                      ),
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
          ],
        ),
      ),
    );
  }
}

class _BarTrack extends StatelessWidget {
  const _BarTrack({required this.ratio, required this.gradient});
  final double ratio;
  final Gradient gradient;

  @override
  Widget build(BuildContext context) {
    final colors = _c(context);
    final radii = _r(context);
    return LayoutBuilder(
      builder: (context, constraints) {
        final w = constraints.maxWidth * ratio.clamp(0, 1);
        return Container(
          height: 8,
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
