import 'dart:developer' as dev;

import 'release_models.dart';

/// 更新策略：服务端只下发事实（`force_update` / `min_supported_version_code`），
/// 由这里统一裁决，UI 不参与判断。
enum UpdateStrategy { force, recommend, none }

class UpdateDecision {
  const UpdateDecision({
    required this.strategy,
    this.latest,
    this.artifact,
    this.failure,
  });

  const UpdateDecision.none({this.latest, this.failure})
      : strategy = UpdateStrategy.none,
        artifact = null;

  final UpdateStrategy strategy;
  final ReleaseInfo? latest;
  final ReleaseArtifact? artifact;
  final UpdateFailureKind? failure;

  bool get installable => artifact != null;
  bool get dismissible => strategy != UpdateStrategy.force;

  String get latestVersionLabel => latest == null ? '' : 'v${latest!.versionName}';
}

/// 纯函数策略裁决：无 IO、无副作用，便于全分支单测。
///
/// ① 未知 `type`（含未来 `patch`）**忽略并记 WARN**，不猜测、不降级；
/// ② 用户忽略过的版本号不再提示，但**更高版本会重新提示**；
/// ③ 无可用制品时给出 `noApplicableArtifact`，由 UI 降级为手动下载指引。
UpdateDecision decideUpdate({
  required UpdateCheckResult result,
  required int localVersionCode,
  int? ignoredVersionCode,
}) {
  final latest = result.latest;
  if (!result.hasUpdate || latest == null) {
    return const UpdateDecision.none();
  }
  if (latest.versionCode <= localVersionCode) {
    return UpdateDecision.none(latest: latest);
  }
  if (ignoredVersionCode != null && ignoredVersionCode == latest.versionCode) {
    return UpdateDecision.none(latest: latest);
  }
  final artifact = pickArtifact(result.artifacts);
  if (artifact == null) {
    return UpdateDecision.none(
      latest: latest,
      failure: UpdateFailureKind.noApplicableArtifact,
    );
  }
  final force =
      latest.forceUpdate || localVersionCode < latest.minSupportedVersionCode;
  return UpdateDecision(
    strategy: force ? UpdateStrategy.force : UpdateStrategy.recommend,
    latest: latest,
    artifact: artifact,
  );
}

/// 只认 `full`：多条时取第一条并记 WARN，未知 `type` 一律忽略。
ReleaseArtifact? pickArtifact(List<ReleaseArtifact> artifacts) {
  ReleaseArtifact? picked;
  for (final artifact in artifacts) {
    if (artifact.type != fullArtifactType) {
      dev.log(
        '忽略未知制品类型 type=${artifact.type} id=${artifact.id}',
        name: 'updater',
      );
      continue;
    }
    if (picked != null) {
      dev.log('存在多条全量制品，取第一条 id=${picked.id}', name: 'updater');
      continue;
    }
    picked = artifact;
  }
  return picked;
}
