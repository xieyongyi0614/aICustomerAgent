import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/updater/release_models.dart';
import '../../core/updater/update_checker.dart';
import '../../core/updater/update_providers.dart';
import '../theme/theme_context.dart';

/// 更新面板（A41 底部面板规格 + A32 主次按钮规格）。
///
/// 纪律：面板是用户动作的容器——确认键取 `ink` 深色，**禁止 AI 渐变**；
/// 数字（版本号 / 百分比 / 体积）一律走 `AppTypography.numeric`。
class UpdateSheet extends ConsumerWidget {
  const UpdateSheet({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final state = ref.watch(updateControllerProvider);
    final controller = ref.read(updateControllerProvider.notifier);
    final colors = context.colors;
    final type = context.typography;
    final radii = context.radii;
    final spacing = context.spacing;
    final decision = state.decision;
    final latest = decision?.latest;
    final local = state.localVersion;
    final bottomInset = MediaQuery.of(context).viewInsets.bottom;

    return PopScope(
      canPop: state.stage != UpdateStage.available ||
          (decision?.dismissible ?? true),
      child: Container(
        decoration: BoxDecoration(
          color: colors.surface,
          borderRadius: BorderRadius.vertical(
            top: Radius.circular(radii.lg),
          ),
          boxShadow: context.elevation.deep,
        ),
        padding: EdgeInsets.fromLTRB(
          spacing.cardPadding,
          12,
          spacing.cardPadding,
          bottomInset + 22,
        ),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            Center(
              child: Container(
                width: 38,
                height: 4,
                decoration: BoxDecoration(
                  color: colors.line,
                  borderRadius: radii.rFull,
                ),
              ),
            ),
            const SizedBox(height: 16),
            Text(
              _titleFor(state),
              textAlign: TextAlign.center,
              style: type.title,
            ),
            const SizedBox(height: 6),
            Text(
              '${local == null ? '' : 'v${local.versionName}'}'
              '${latest == null ? '' : ' → v${latest.versionName}'}',
              textAlign: TextAlign.center,
              style: type.numeric(type.sub).copyWith(color: colors.ink2),
            ),
            if (latest?.releaseNotes != null) ...[
              const SizedBox(height: 14),
              ConstrainedBox(
                constraints: const BoxConstraints(maxHeight: 168),
                child: SingleChildScrollView(
                  child: Text(
                    latest!.releaseNotes!,
                    style: type.sub.copyWith(color: colors.ink2),
                  ),
                ),
              ),
            ],
            if (state.stage == UpdateStage.downloading ||
                state.stage == UpdateStage.verifying) ...[
              const SizedBox(height: 18),
              _DownloadProgress(state: state),
            ],
            if (state.failure != null &&
                state.failure != UpdateFailureKind.noApplicableArtifact) ...[
              const SizedBox(height: 14),
              Text(
                updateFailureText(state.failure!),
                textAlign: TextAlign.center,
                style: type.sub.copyWith(color: colors.dangerText),
              ),
            ],
            if (state.failure == UpdateFailureKind.noApplicableArtifact) ...[
              const SizedBox(height: 14),
              Text(
                updateFailureText(UpdateFailureKind.noApplicableArtifact),
                textAlign: TextAlign.center,
                style: type.sub.copyWith(color: colors.ink2),
              ),
            ],
            if (!state.installSupported) ...[
              const SizedBox(height: 14),
              Text(
                '开发版本只做检测，安装包请到发布页下载',
                textAlign: TextAlign.center,
                style: type.sub.copyWith(color: colors.ink2),
              ),
            ],
            const SizedBox(height: 20),
            _primaryButton(context, state, controller),
            if (state.stage == UpdateStage.confirmWifi) ...[
              const SizedBox(height: 10),
              _secondaryButton(
                context,
                label: '等 Wi-Fi 再更新',
                onTap: controller.dismiss,
              ),
            ] else if (state.stage == UpdateStage.available &&
                (decision?.dismissible ?? true)) ...[
              const SizedBox(height: 10),
              _secondaryButton(
                context,
                label: '稍后再说',
                onTap: controller.dismiss,
              ),
              const SizedBox(height: 6),
              Center(
                child: GestureDetector(
                  behavior: HitTestBehavior.opaque,
                  onTap: controller.ignoreCurrentVersion,
                  child: Padding(
                    padding: const EdgeInsets.symmetric(
                      vertical: 8,
                      horizontal: 5,
                    ),
                    child: Row(
                      mainAxisSize: MainAxisSize.min,
                      children: [
                        Text(
                          '忽略这个版本',
                          style: type.caption.copyWith(color: colors.ink2),
                        ),
                        const SizedBox(width: 4),
                        // M3 禁令 4：图标一律 Lucide（AppIcons），不用 Material Icons
                        Icon(AppIcons.chevronRight, size: 14, color: colors.ink3),
                      ],
                    ),
                  ),
                ),
              ),
            ],
          ],
        ),
      ),
    );
  }

  Widget _primaryButton(
    BuildContext context,
    UpdateState state,
    UpdateController controller,
  ) {
    final colors = context.colors;
    final type = context.typography;
    final radii = context.radii;

    if (!state.installSupported) {
      return _SecondaryChip(
        label: '前往发布页下载',
        onTap: controller.dismiss,
      );
    }
    late final String label;
    late final VoidCallback onTap;
    switch (state.stage) {
      case UpdateStage.downloading:
        label = '取消下载';
        onTap = controller.cancelDownload;
      case UpdateStage.verifying:
        label = '正在校验…';
        onTap = () {};
      case UpdateStage.readyToInstall:
        label = '去安装';
        onTap = controller.install;
      case UpdateStage.permissionRequired:
        label = '去开启安装权限';
        onTap = controller.openInstallPermissionSettings;
      case UpdateStage.failed:
        label = '重试';
        onTap = controller.retry;
      case UpdateStage.confirmWifi:
        label = '继续下载';
        onTap = controller.confirmWifiAndDownload;
      case UpdateStage.available:
      case UpdateStage.idle:
      case UpdateStage.checking:
      case UpdateStage.upToDate:
        label = '立即更新';
        onTap = controller.startDownload;
    }
    return Container(
      decoration: BoxDecoration(
        color: colors.ink,
        borderRadius: radii.rFull,
        boxShadow: [
          BoxShadow(
            color: colors.ink.withValues(alpha: 0.22),
            offset: const Offset(0, 12),
            blurRadius: 26,
          ),
        ],
      ),
      child: GestureDetector(
        behavior: HitTestBehavior.opaque,
        onTap: onTap,
        child: Padding(
          padding: const EdgeInsets.symmetric(vertical: 15),
          child: Text(
            label,
            textAlign: TextAlign.center,
            style: type.rowTitle.copyWith(
              fontSize: 15,
              fontWeight: FontWeight.w700,
              color: colors.onDeepPrimary,
            ),
          ),
        ),
      ),
    );
  }

  Widget _secondaryButton(
    BuildContext context, {
    required String label,
    required VoidCallback onTap,
  }) {
    final colors = context.colors;
    final type = context.typography;
    final radii = context.radii;
    return GestureDetector(
      behavior: HitTestBehavior.opaque,
      onTap: onTap,
      child: Container(
        decoration: BoxDecoration(
          color: colors.surface,
          borderRadius: radii.rFull,
          border: Border.all(color: colors.line),
        ),
        padding: const EdgeInsets.symmetric(vertical: 15),
        child: Text(
          label,
          textAlign: TextAlign.center,
          style: type.rowTitle.copyWith(
            fontSize: 15,
            fontWeight: FontWeight.w700,
            color: colors.ink2,
          ),
        ),
      ),
    );
  }

  String _titleFor(UpdateState state) {
    switch (state.stage) {
      case UpdateStage.permissionRequired:
        return '还差一步就能装好';
      case UpdateStage.readyToInstall:
        return '安装包准备好了';
      case UpdateStage.failed:
        return '更新没有完成';
      case UpdateStage.confirmWifi:
        return '要用移动网络下载吗';
      default:
        final force = state.decision?.strategy == UpdateStrategy.force;
        return force ? '这个版本需要更新' : '新版本准备好了';
    }
  }
}

class _DownloadProgress extends StatelessWidget {
  const _DownloadProgress({required this.state});

  final UpdateState state;

  @override
  Widget build(BuildContext context) {
    final colors = context.colors;
    final type = context.typography;
    final radii = context.radii;
    final progress = state.progress ?? 0;
    final percent = (progress * 100).round();
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        Stack(
          children: [
            Container(
              height: 7,
              decoration: BoxDecoration(
                color: colors.trackBar,
                borderRadius: radii.rFull,
              ),
            ),
            FractionallySizedBox(
              widthFactor: progress.clamp(0, 1).toDouble(),
              child: Container(
                height: 7,
                decoration: BoxDecoration(
                  gradient: context.gradients.barBlue,
                  borderRadius: radii.rFull,
                ),
              ),
            ),
          ],
        ),
        const SizedBox(height: 8),
        Text(
          state.stage == UpdateStage.verifying
              ? '正在校验 · $percent%'
              : '正在下载 · $percent%',
          textAlign: TextAlign.center,
          style: type.numeric(type.caption).copyWith(color: colors.ink2),
        ),
        const SizedBox(height: 2),
        Text(
          '${_mb(state.receivedBytes)} / ${_mb(state.totalBytes)}',
          textAlign: TextAlign.center,
          style: type.numeric(type.caption).copyWith(color: colors.ink3),
        ),
      ],
    );
  }

  String _mb(int bytes) {
    if (bytes <= 0) {
      return '—';
    }
    return '${(bytes / 1024 / 1024).toStringAsFixed(1)} MB';
  }
}

class _SecondaryChip extends StatelessWidget {
  const _SecondaryChip({required this.label, required this.onTap});

  final String label;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    final colors = context.colors;
    final type = context.typography;
    final radii = context.radii;
    return GestureDetector(
      behavior: HitTestBehavior.opaque,
      onTap: onTap,
      child: Container(
        decoration: BoxDecoration(
          color: colors.surface,
          borderRadius: radii.rFull,
          border: Border.all(color: colors.line),
        ),
        padding: const EdgeInsets.symmetric(vertical: 15),
        child: Text(
          label,
          textAlign: TextAlign.center,
          style: type.rowTitle.copyWith(
            fontSize: 15,
            fontWeight: FontWeight.w700,
            color: colors.ink2,
          ),
        ),
      ),
    );
  }
}
