import 'dart:ui';

import 'package:flutter/material.dart';

import '../tokens/tokens.dart';

/// A36 storage（本地存储卡）。
///
/// 「仅本机存储 · 未开启任何云同步」为红线 9 口径，**内置在组件内**不可被
/// 调用方替换——做成参数会被漏传，做成内置则漏不掉（skill `components.md:358`）。
/// `usageRatio` / `leftoverText` 无真实数据源时传 null：占用条与剩余行**不渲染**
/// （零假数据红线），不得传 0 或占位文案。
class StorageCard extends StatelessWidget {
  const StorageCard({
    super.key,
    required this.assetCount,
    this.leftoverText,
    this.usageRatio,
    this.unitText = '张',
  });

  static const usageFillKey = ValueKey('storage-card-usage-fill');
  static const localOnlyNotice = '仅本机存储 · 未开启任何云同步';

  final int assetCount;
  final String? leftoverText;
  final double? usageRatio;
  final String unitText;

  @override
  Widget build(BuildContext context) {
    final colors = Theme.of(context).extension<AppColors>()!;
    final type = Theme.of(context).extension<AppTypography>()!;
    final radii = Theme.of(context).extension<AppRadii>()!;
    final gradients = Theme.of(context).extension<AppGradients>()!;
    final ratio = (usageRatio ?? 0).isNaN ? 0.0 : (usageRatio ?? 0).clamp(0.0, 1.0);
    return Container(
      padding: const EdgeInsets.all(18),
      decoration: BoxDecoration(
        color: colors.surface,
        borderRadius: radii.rLg,
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            crossAxisAlignment: CrossAxisAlignment.end,
            children: [
              Text(
                assetCount.toString(),
                style: type.amountHero.copyWith(
                  fontSize: 22,
                  color: colors.ink,
                  fontFeatures: AppTypography.tabular,
                ),
              ),
              const SizedBox(width: 4),
              Padding(
                padding: const EdgeInsets.only(bottom: 2),
                child: Text(
                  unitText,
                  style: type.caption.copyWith(
                    fontSize: 12,
                    color: colors.ink3,
                  ),
                ),
              ),
              if (leftoverText != null) ...[
                const Spacer(),
                Padding(
                  padding: const EdgeInsets.only(bottom: 2),
                  child: Text(
                    leftoverText!,
                    style: type.caption.copyWith(
                      fontSize: 12,
                      color: colors.ink3,
                    ),
                  ),
                ),
              ],
            ],
          ),
          if (usageRatio != null) ...[
            const SizedBox(height: 12),
            Container(
              height: 7,
              decoration: BoxDecoration(
                color: colors.trackBar,
                borderRadius: radii.rFull,
              ),
              child: Align(
                alignment: Alignment.centerLeft,
                child: FractionallySizedBox(
                  widthFactor: ratio,
                  child: Container(
                    key: usageFillKey,
                    decoration: BoxDecoration(
                      gradient: gradients.barPurple,
                      borderRadius: radii.rFull,
                    ),
                  ),
                ),
              ),
            ),
          ],
          const SizedBox(height: 11),
          Row(
            children: [
              Icon(AppIcons.shield, size: 12, color: colors.health),
              const SizedBox(width: 6),
              Text(
                localOnlyNotice,
                style: type.caption.copyWith(
                  fontSize: 11.5,
                  color: colors.ink3,
                ),
              ),
            ],
          ),
        ],
      ),
    );
  }
}

/// A36 album（相簿卡）封面图源；封面高 86、圆角 12（rSm）。
///
/// `thumbnail` 为 null 时渲染中性空态（fillMuted + image 字形）：
/// 占位**禁止使用原型的渐变色**（skill `components.md:371`）。
class AlbumTile extends StatelessWidget {
  const AlbumTile({
    super.key,
    required this.thumbnail,
    required this.name,
    required this.countText,
    this.onTap,
  });

  static const gridCrossAxisCount = 2;
  static const gridSpacing = 11.0;

  final ImageProvider? thumbnail;
  final String name;
  final String countText;
  final VoidCallback? onTap;

  @override
  Widget build(BuildContext context) {
    final colors = Theme.of(context).extension<AppColors>()!;
    final type = Theme.of(context).extension<AppTypography>()!;
    final radii = Theme.of(context).extension<AppRadii>()!;
    return GestureDetector(
      onTap: onTap,
      child: Container(
        padding: const EdgeInsets.all(9),
        decoration: BoxDecoration(
          color: colors.surface,
          borderRadius: radii.rMd,
        ),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            ClipRRect(
              borderRadius: radii.rSm,
              child: SizedBox(
                height: 86,
                width: double.infinity,
                child: thumbnail == null
                    ? _neutralThumb(colors, type)
                    : Image(image: thumbnail!, fit: BoxFit.cover),
              ),
            ),
            const SizedBox(height: 8),
            Text(
              name,
              maxLines: 1,
              overflow: TextOverflow.ellipsis,
              style: type.rowTitle.copyWith(
                fontSize: 13.5,
                fontWeight: FontWeight.w600,
              ),
            ),
            const SizedBox(height: 2),
            Text(
              countText,
              maxLines: 1,
              overflow: TextOverflow.ellipsis,
              style: type.caption.copyWith(
                fontSize: 11,
                color: colors.ink3,
                fontFeatures: AppTypography.tabular,
              ),
            ),
          ],
        ),
      ),
    );
  }
}

/// A36 photo（照片格）。
///
/// 选中态复选框是全站唯一允许 ai 渐变的例外（skill `components.md:364`
/// 明文授权）；`aiKept` 与 `selected` 互斥语义由调用方保证。
/// 缩略图按需解码（`cacheWidth`），组件不预载全量原图。
class PhotoTile extends StatelessWidget {
  const PhotoTile({
    super.key,
    this.thumbnail,
    this.selectionMode = false,
    this.selected = false,
    this.aiKept = false,
    this.durationText,
    this.cacheWidth,
    this.onTap,
    this.onToggle,
  });

  static const gridCrossAxisCount = 3;
  static const gridSpacing = 6.0;
  static const selectionCheckKey = ValueKey('photo-tile-chk');

  final ImageProvider? thumbnail;
  final bool selectionMode;
  final bool selected;
  final bool aiKept;
  final String? durationText;
  final int? cacheWidth;
  final VoidCallback? onTap;
  final VoidCallback? onToggle;

  @override
  Widget build(BuildContext context) {
    final colors = Theme.of(context).extension<AppColors>()!;
    final type = Theme.of(context).extension<AppTypography>()!;
    final radii = Theme.of(context).extension<AppRadii>()!;
    Widget tile = AspectRatio(
      aspectRatio: 1,
      child: GestureDetector(
        onTap: selectionMode ? onToggle : onTap,
        child: Stack(
          fit: StackFit.expand,
          children: [
            ClipRRect(
              borderRadius: radii.rSm,
              child: thumbnail == null
                  ? _neutralThumb(colors, type)
                  : Image(
                      image: cacheWidth == null
                          ? thumbnail!
                          : ResizeImage(thumbnail!, width: cacheWidth),
                      fit: BoxFit.cover,
                      gaplessPlayback: true,
                    ),
            ),
            if (durationText != null)
              Positioned(
                left: 6,
                bottom: 6,
                child: Container(
                  padding: const EdgeInsets.symmetric(
                    horizontal: 6,
                    vertical: 2,
                  ),
                  decoration: BoxDecoration(
                    color: colors.ink.withValues(alpha: 0.55),
                    borderRadius: radii.rSm,
                  ),
                  child: Text(
                    durationText!,
                    style: type.caption.copyWith(
                      fontSize: 10.5,
                      fontWeight: FontWeight.w600,
                      color: colors.onDeepPrimary,
                      fontFeatures: AppTypography.tabular,
                    ),
                  ),
                ),
              ),
            if (selectionMode)
              Positioned(
                top: 6,
                right: 6,
                child: _check(context),
              ),
            if (selected)
              Positioned.fill(
                child: IgnorePointer(
                  child: Container(
                    decoration: BoxDecoration(
                      border: Border.all(
                        color: colors.aiPrimary,
                        width: 2.5,
                      ),
                      borderRadius: radii.rSm,
                    ),
                  ),
                ),
              ),
          ],
        ),
      ),
    );
    if (aiKept) {
      tile = Opacity(opacity: 0.55, child: tile);
    }
    return tile;
  }

  Widget _check(BuildContext context) {
    final colors = Theme.of(context).extension<AppColors>()!;
    final gradients = Theme.of(context).extension<AppGradients>()!;
    if (selected) {
      return Container(
        key: selectionCheckKey,
        width: 22,
        height: 22,
        decoration: BoxDecoration(
          gradient: gradients.ai,
          shape: BoxShape.circle,
        ),
        child: Icon(AppIcons.check, size: 13, color: colors.onDeepPrimary),
      );
    }
    return Container(
      key: selectionCheckKey,
      width: 22,
      height: 22,
      decoration: BoxDecoration(
        color: colors.surface.withValues(alpha: 0.85),
        shape: BoxShape.circle,
        border: Border.all(color: colors.borderCheck, width: 1.5),
      ),
    );
  }
}

/// A36 actionbar 单个动作。
class AlbumAction {
  const AlbumAction({
    required this.label,
    required this.icon,
    this.danger = false,
    this.onTap,
  });

  final String label;
  final IconData icon;
  final bool danger;
  final VoidCallback? onTap;
}

/// A36 actionbar（批量操作条）。
///
/// 底部「删除只在本机生效 · 最近删除 30 天可恢复」口径行为红线 9 强制项，
/// **内置在组件内**不可被调用方替换（skill `components.md:370`）。
class AlbumActionBar extends StatelessWidget {
  const AlbumActionBar({super.key, required this.actions});

  static const recoveryNotice = '删除只在本机生效 · 最近删除 30 天可恢复';
  static const privacyNoticeKey = ValueKey('album-action-bar-notice');

  final List<AlbumAction> actions;

  @override
  Widget build(BuildContext context) {
    final colors = Theme.of(context).extension<AppColors>()!;
    final type = Theme.of(context).extension<AppTypography>()!;
    return ClipRect(
      child: BackdropFilter(
        filter: ImageFilter.blur(sigmaX: 18, sigmaY: 18),
        child: Container(
          decoration: BoxDecoration(
            color: colors.surface.withValues(alpha: 0.94),
            border: Border(top: BorderSide(color: colors.line)),
          ),
          padding: const EdgeInsets.fromLTRB(16, 14, 16, 26),
          child: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              Row(
                children: [
                  for (var i = 0; i < actions.length; i++) ...[
                    if (i > 0) const SizedBox(width: 10),
                    Expanded(child: _button(context, actions[i])),
                  ],
                ],
              ),
              const SizedBox(height: 10),
              Row(
                key: privacyNoticeKey,
                mainAxisAlignment: MainAxisAlignment.center,
                children: [
                  Icon(AppIcons.shield, size: 12, color: colors.health),
                  const SizedBox(width: 5),
                  Text(
                    recoveryNotice,
                    style: type.caption.copyWith(
                      fontSize: 11,
                      color: colors.ink3,
                    ),
                  ),
                ],
              ),
            ],
          ),
        ),
      ),
    );
  }

  Widget _button(BuildContext context, AlbumAction action) {
    final colors = Theme.of(context).extension<AppColors>()!;
    final type = Theme.of(context).extension<AppTypography>()!;
    final radii = Theme.of(context).extension<AppRadii>()!;
    final foreground = action.danger ? colors.dangerText : colors.ink;
    return Material(
      color: action.danger ? colors.dangerBg : colors.fillSubtle,
      borderRadius: radii.rFull,
      child: InkWell(
        onTap: action.onTap,
        borderRadius: radii.rFull,
        child: Padding(
          padding: const EdgeInsets.symmetric(vertical: 12),
          child: Row(
            mainAxisAlignment: MainAxisAlignment.center,
            children: [
              Icon(action.icon, size: 15, color: foreground),
              const SizedBox(width: 6),
              Flexible(
                child: Text(
                  action.label,
                  maxLines: 1,
                  overflow: TextOverflow.ellipsis,
                  style: type.caption.copyWith(
                    fontSize: 13.5,
                    fontWeight: FontWeight.w600,
                    color: foreground,
                  ),
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }
}


Widget _neutralThumb(AppColors colors, AppTypography type) {
  return Container(
    color: colors.fillMuted,
    alignment: Alignment.center,
    child: Icon(AppIcons.image, size: 20, color: colors.ink3),
  );
}
