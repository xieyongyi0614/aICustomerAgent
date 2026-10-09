/// 免商店自动更新的 DTO 与失败分类（手写 final class：本域无 union 需求，不引 Freezed）。
library;

/// 全量制品类型。未知类型（含未来 `patch`）一律 fail-closed 忽略，不猜测、不降级。
const String fullArtifactType = 'full';

/// 指纹归一化为「大写、冒号分隔」：与 `scripts/publish_release.py` 同口径，
/// 服务端 manifest、制品 APK、运行中 App 自身签名三方必须同形才能比对。
String normalizeFingerprint(String raw) {
  final hex = raw.replaceAll(RegExp('[^0-9a-fA-F]'), '').toUpperCase();
  if (hex.isEmpty) {
    return '';
  }
  final buffer = StringBuffer();
  for (var index = 0; index < hex.length; index += 2) {
    if (index > 0) {
      buffer.write(':');
    }
    buffer.write(hex.substring(index, index + 2));
  }
  return buffer.toString();
}

class ReleaseArtifact {
  const ReleaseArtifact({
    required this.id,
    required this.type,
    required this.url,
    required this.sizeBytes,
    required this.sha256,
    this.signatureFingerprint,
    this.fromVersionCode,
  });

  final String id;
  final String type;
  final String url;
  final int sizeBytes;
  final String sha256;
  final String? signatureFingerprint;
  final int? fromVersionCode;

  /// 解析单条制品；任一必需字段缺失或非法 → 返回 null（该条**不可用**）。
  static ReleaseArtifact? tryParse(Object? raw) {
    if (raw is! Map) {
      return null;
    }
    final id = raw['id'];
    final type = raw['type'];
    final url = raw['url'];
    final sizeBytes = raw['size_bytes'];
    final sha256 = raw['sha256'];
    if (id is! String || id.isEmpty) {
      return null;
    }
    if (type is! String || type.isEmpty) {
      return null;
    }
    if (url is! String || url.isEmpty) {
      return null;
    }
    if (sizeBytes is! int || sizeBytes <= 0) {
      return null;
    }
    if (sha256 is! String || sha256.length != 64) {
      return null;
    }
    final fingerprint = raw['signature_fingerprint'];
    final fromVersionCode = raw['from_version_code'];
    return ReleaseArtifact(
      id: id,
      type: type,
      url: url,
      sizeBytes: sizeBytes,
      sha256: sha256.toLowerCase(),
      signatureFingerprint:
          fingerprint is String && fingerprint.isNotEmpty ? fingerprint : null,
      fromVersionCode: fromVersionCode is int ? fromVersionCode : null,
    );
  }
}

class ReleaseInfo {
  const ReleaseInfo({
    required this.versionName,
    required this.versionCode,
    required this.minSupportedVersionCode,
    required this.forceUpdate,
    this.releaseNotes,
    this.publishedAt,
  });

  final String versionName;
  final int versionCode;
  final int minSupportedVersionCode;
  final bool forceUpdate;
  final String? releaseNotes;
  final String? publishedAt;

  static ReleaseInfo? tryParse(Object? raw) {
    if (raw is! Map) {
      return null;
    }
    final versionName = raw['version_name'];
    final versionCode = raw['version_code'];
    final minSupported = raw['min_supported_version_code'];
    if (versionName is! String || versionName.isEmpty) {
      return null;
    }
    if (versionCode is! int || versionCode <= 0) {
      return null;
    }
    if (minSupported is! int || minSupported < 0) {
      return null;
    }
    final notes = raw['release_notes'];
    final publishedAt = raw['published_at'];
    return ReleaseInfo(
      versionName: versionName,
      versionCode: versionCode,
      minSupportedVersionCode: minSupported,
      forceUpdate: raw['force_update'] == true,
      releaseNotes: notes is String && notes.isNotEmpty ? notes : null,
      publishedAt: publishedAt is String && publishedAt.isNotEmpty
          ? publishedAt
          : null,
    );
  }
}

class UpdateCheckResult {
  const UpdateCheckResult({
    required this.hasUpdate,
    this.latest,
    this.artifacts = const [],
  });

  final bool hasUpdate;
  final ReleaseInfo? latest;
  final List<ReleaseArtifact> artifacts;

  static UpdateCheckResult parse(Map<String, dynamic> json) {
    final rawArtifacts = json['artifacts'];
    final artifacts = <ReleaseArtifact>[];
    if (rawArtifacts is List) {
      for (final item in rawArtifacts) {
        final artifact = ReleaseArtifact.tryParse(item);
        if (artifact != null) {
          artifacts.add(artifact);
        }
      }
    }
    return UpdateCheckResult(
      hasUpdate: json['has_update'] == true,
      latest: ReleaseInfo.tryParse(json['latest']),
      artifacts: artifacts,
    );
  }
}

/// 失败分类：状态机与文案都按它分支，不解析自由文本。
enum UpdateFailureKind {
  none,
  network,
  invalidResponse,
  incomplete,
  hashMismatch,
  signatureMismatch,
  permissionRequired,
  platformError,
  noApplicableArtifact,
  cancelled,
}

String updateFailureText(UpdateFailureKind kind) {
  switch (kind) {
    case UpdateFailureKind.none:
      return '';
    case UpdateFailureKind.network:
      return '网络不太稳，等下再试一次';
    case UpdateFailureKind.invalidResponse:
      return '暂时拿不到新版本信息';
    case UpdateFailureKind.incomplete:
      return '安装包没有下载完整，可以接着下';
    case UpdateFailureKind.hashMismatch:
      return '安装包校验没通过，我重新下载一次';
    case UpdateFailureKind.signatureMismatch:
      return '这个安装包不是同一个签名，需要先卸载旧版本';
    case UpdateFailureKind.permissionRequired:
      return '还需要允许安装应用：设置 → 应用 → 允许安装未知应用';
    case UpdateFailureKind.platformError:
      return '安装没能启动，请保持应用在前台再试一次';
    case UpdateFailureKind.noApplicableArtifact:
      return '暂无可用的安装包，可以稍后再试';
    case UpdateFailureKind.cancelled:
      return '已取消';
  }
}
