import 'package:flutter/material.dart';

import '../tokens/tokens.dart';

AppColors _c(BuildContext context) =>
    Theme.of(context).extension<AppColors>()!;
AppTypography _t(BuildContext context) =>
    Theme.of(context).extension<AppTypography>()!;
AppRadii _r(BuildContext context) => Theme.of(context).extension<AppRadii>()!;
AppElevation _e(BuildContext context) =>
    Theme.of(context).extension<AppElevation>()!;
AppGradients _g(BuildContext context) =>
    Theme.of(context).extension<AppGradients>()!;

/// A6 任务行
class TaskRow extends StatelessWidget {
  const TaskRow({
    super.key,
    required this.title,
    this.subtitle,
    this.tag,
    this.done = false,
    this.onToggle,
    this.showDivider = true,
  });

  final String title;
  final String? subtitle;
  final String? tag;
  final bool done;
  final VoidCallback? onToggle;
  final bool showDivider;

  @override
  Widget build(BuildContext context) {
    final colors = _c(context);
    final type = _t(context);
    return Container(
      padding: const EdgeInsets.symmetric(vertical: 13, horizontal: 2),
      decoration: BoxDecoration(
        border: showDivider
            ? Border(bottom: BorderSide(color: colors.line))
            : null,
      ),
      child: Row(
        children: [
          GestureDetector(
            onTap: onToggle,
            child: Container(
              width: 21,
              height: 21,
              decoration: BoxDecoration(
                shape: BoxShape.circle,
                gradient: done ? _g(context).ai : null,
                border: done ? null : Border.all(color: colors.borderCheck),
              ),
              child: done
                  ? Icon(Icons.check, size: 14, color: colors.onDeepPrimary)
                  : null,
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
                    color: done ? colors.ink3 : colors.ink,
                    decoration: done ? TextDecoration.lineThrough : null,
                  ),
                ),
                if (subtitle != null)
                  Text(subtitle!,
                      style: type.caption.copyWith(color: colors.ink3)),
              ],
            ),
          ),
          if (tag != null)
            Container(
              padding: const EdgeInsets.symmetric(vertical: 4, horizontal: 9),
              decoration: BoxDecoration(
                color: colors.fillSubtle,
                borderRadius: BorderRadius.circular(8),
              ),
              child: Text(tag!,
                  style: type.caption.copyWith(color: colors.ink2)),
            ),
        ],
      ),
    );
  }
}

/// A20 账单行
class TxRow extends StatelessWidget {
  const TxRow({
    super.key,
    required this.title,
    required this.amountLabel,
    required this.tileColor,
    required this.iconColor,
    this.icon,
    this.subtitle,
    this.showDivider = true,
  });

  final String title;
  final String amountLabel;
  final Color tileColor;
  final Color iconColor;
  final IconData? icon;
  final String? subtitle;
  final bool showDivider;

  @override
  Widget build(BuildContext context) {
    final colors = _c(context);
    final type = _t(context);
    return Container(
      padding: const EdgeInsets.symmetric(vertical: 12),
      decoration: BoxDecoration(
        border: showDivider
            ? Border(bottom: BorderSide(color: colors.line))
            : null,
      ),
      child: Row(
        children: [
          Container(
            width: 36,
            height: 36,
            decoration: BoxDecoration(
              color: tileColor,
              borderRadius: BorderRadius.circular(12),
            ),
            child: icon == null
                ? null
                : Icon(icon, size: 18, color: iconColor),
          ),
          const SizedBox(width: 12),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(title, style: type.rowTitle),
                if (subtitle != null)
                  Text(subtitle!,
                      style: type.caption.copyWith(color: colors.ink3)),
              ],
            ),
          ),
          Text(amountLabel, style: type.numeric(type.body)),
        ],
      ),
    );
  }
}

/// A26 设置组 / 设置行
class SettingGroup extends StatelessWidget {
  const SettingGroup({super.key, required this.children});

  final List<Widget> children;

  @override
  Widget build(BuildContext context) {
    final colors = _c(context);
    final radii = _r(context);
    final elevation = _e(context);
    return Container(
      margin: const EdgeInsets.only(bottom: 18),
      clipBehavior: Clip.antiAlias,
      decoration: BoxDecoration(
        color: colors.surface,
        borderRadius: radii.rLg,
        boxShadow: elevation.card,
      ),
      child: Column(children: children),
    );
  }
}

class SettingRow extends StatelessWidget {
  const SettingRow({
    super.key,
    required this.title,
    this.subtitle,
    this.trailing,
    this.icon,
    this.iconBg,
    this.iconColor,
    this.onTap,
    this.showDivider = true,
  });

  final String title;
  final String? subtitle;
  final Widget? trailing;
  final IconData? icon;
  final Color? iconBg;

  /// 设计稿 .s-ic 彩色图标（默认 ink2）
  final Color? iconColor;
  final VoidCallback? onTap;
  final bool showDivider;

  @override
  Widget build(BuildContext context) {
    final colors = _c(context);
    final type = _t(context);
    return InkWell(
      onTap: onTap,
      child: Container(
        padding: const EdgeInsets.symmetric(vertical: 15, horizontal: 17),
        decoration: BoxDecoration(
          border: showDivider
              ? Border(bottom: BorderSide(color: colors.line))
              : null,
        ),
        child: Row(
          children: [
            if (icon != null) ...[
              Container(
                width: 32,
                height: 32,
                decoration: BoxDecoration(
                  color: iconBg ?? colors.fillSubtle,
                  borderRadius: BorderRadius.circular(10),
                ),
                child: Icon(icon, size: 16, color: iconColor ?? colors.ink2),
              ),
              const SizedBox(width: 12),
            ],
            Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(title, style: type.body),
                  if (subtitle != null)
                    Text(subtitle!,
                        style: type.caption.copyWith(color: colors.ink3)),
                ],
              ),
            ),
            ?trailing,
          ],
        ),
      ),
    );
  }
}

/// A27 开关（44×26）
class AppToggle extends StatelessWidget {
  const AppToggle({super.key, required this.value, required this.onChanged});

  final bool value;
  final ValueChanged<bool> onChanged;

  @override
  Widget build(BuildContext context) {
    final colors = _c(context);
    final radii = _r(context);
    return GestureDetector(
      onTap: () => onChanged(!value),
      child: Container(
        width: 44,
        height: 26,
        padding: const EdgeInsets.all(3),
        decoration: BoxDecoration(
          gradient: value ? _g(context).ai : null,
          color: value ? null : colors.toggleOff,
          borderRadius: radii.rFull,
        ),
        child: Align(
          alignment: value ? Alignment.centerRight : Alignment.centerLeft,
          child: Container(
            width: 20,
            height: 20,
            decoration: BoxDecoration(
              shape: BoxShape.circle,
              color: colors.onDeepPrimary,
            ),
          ),
        ),
      ),
    );
  }
}

/// A23 数据来源声明
class SourceNote extends StatelessWidget {
  const SourceNote({super.key, required this.text});

  final String text;

  @override
  Widget build(BuildContext context) {
    final colors = _c(context);
    final type = _t(context);
    return Padding(
      padding: const EdgeInsets.only(top: 18),
      child: Center(
        child: Row(
          mainAxisSize: MainAxisSize.min,
          children: [
            Container(
              width: 7,
              height: 7,
              decoration: BoxDecoration(
                shape: BoxShape.circle,
                color: colors.health,
              ),
            ),
            const SizedBox(width: 6),
            Text(text, style: type.caption.copyWith(color: colors.ink3)),
          ],
        ),
      ),
    );
  }
}

/// A30 返回
class BackLink extends StatelessWidget {
  const BackLink({
    super.key,
    this.label = '‹ 返回首页',
    this.onTap,
    this.onDark = false,
  });

  final String label;
  final VoidCallback? onTap;
  final bool onDark;

  @override
  Widget build(BuildContext context) {
    final colors = _c(context);
    final type = _t(context);
    final color = onDark ? colors.onDeepSecondary : colors.ink2;
    return Padding(
      padding: const EdgeInsets.only(bottom: 14),
      child: GestureDetector(
        onTap: onTap ?? () => Navigator.of(context).maybePop(),
        child: Text(label, style: type.rowTitle.copyWith(color: color)),
      ),
    );
  }
}
