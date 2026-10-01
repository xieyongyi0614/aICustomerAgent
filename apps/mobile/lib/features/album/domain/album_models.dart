/// 相册域模型：全程本机、零网络（D18）。
///
/// 所有类型都是纯数据——`photo_manager` 的 `AssetEntity` 等 SDK 类型
/// 只存在于 data 层，不向页面泄漏。
library;

enum AlbumPermissionStatus { granted, limited, denied }

/// 相簿（37 页宫格 / 60 页入口）。
class AlbumBucket {
  const AlbumBucket({
    required this.id,
    required this.name,
    required this.assetCount,
    required this.isAll,
  });

  final String id;
  final String name;
  final int assetCount;

  /// 「最近添加」虚拟相簿（全部照片流）。
  final bool isAll;
}

/// 一张照片 / 一段视频（元数据，不含位图）。
class PhotoAsset {
  const PhotoAsset({
    required this.id,
    required this.title,
    required this.bucketId,
    required this.takenAt,
    required this.sizeBytes,
    required this.isVideo,
    required this.duration,
    required this.isScreenshot,
  });

  final String id;
  final String title;
  final String bucketId;
  final DateTime takenAt;
  final int sizeBytes;
  final bool isVideo;
  final Duration? duration;
  final bool isScreenshot;

  /// 元数据快照（供 isolate 分析使用；`sizeBytes` 可用文件 stat 结果覆盖，
  /// 读取期只补元数据，不读内容）。
  AlbumAssetSnapshot toSnapshot({String? path, int? sizeBytes}) =>
      AlbumAssetSnapshot(
        id: id,
        title: title,
        sizeBytes: sizeBytes ?? this.sizeBytes,
        takenAt: takenAt,
        isScreenshot: isScreenshot,
        path: path,
      );
}

/// 相册读取分页结果。
class AlbumAssetPage {
  const AlbumAssetPage({
    required this.items,
    required this.total,
    required this.hasMore,
  });

  final List<PhotoAsset> items;
  final int total;
  final bool hasMore;
}

/// 分析维度。`similarBursts` 本期不做（D16），数据面返回「未支持」信号。
enum AlbumSuggestionKind { expiredScreenshots, duplicateSaves, similarBursts }

/// 单个维度的分析结果。
///
/// `supported == false` 表示该维度本期明确不支持（D16），调用方必须以
/// 「未支持」外观呈现——它与 `supported == true` 且 `suggestion == null`
/// （扫过、没有可清理项）是**两种语义**，不得混淆。
class AlbumAnalysisSection {
  const AlbumAnalysisSection({
    required this.kind,
    required this.supported,
    this.suggestion,
    this.unsupportedReason,
  });

  factory AlbumAnalysisSection.done(AlbumSuggestion suggestion) =>
      AlbumAnalysisSection(
        kind: suggestion.kind,
        supported: true,
        suggestion: suggestion,
      );

  factory AlbumAnalysisSection.unsupported(
    AlbumSuggestionKind kind,
    String unsupportedReason,
  ) =>
      AlbumAnalysisSection(
        kind: kind,
        supported: false,
        unsupportedReason: unsupportedReason,
      );

  final AlbumSuggestionKind kind;
  final bool supported;
  final AlbumSuggestion? suggestion;
  final String? unsupportedReason;
}

/// 一条「可清理」建议（A38 建议行的数据）。
class AlbumSuggestion {
  const AlbumSuggestion({
    required this.kind,
    required this.count,
    required this.totalBytes,
    required this.reason,
    required this.assetIds,
  });

  final AlbumSuggestionKind kind;
  final int count;
  final int totalBytes;

  /// 判定理由（`components.md:396`：不能只给类型名与数量）。
  final String reason;

  /// 预选集合（删除永远由用户确认，AI 只预选）。
  final List<String> assetIds;
}

/// 一次分析的完整产物。
class AlbumAnalysisResult {
  const AlbumAnalysisResult({
    required this.sections,
    required this.completed,
    required this.scannedCount,
  });

  /// 各维度结果；相似连拍固定为「未支持」信号（D16）。
  final List<AlbumAnalysisSection> sections;

  /// false = 被用户中断（「停下的部分不会有任何改变」）。
  final bool completed;
  final int scannedCount;

  AlbumAnalysisSection? section(AlbumSuggestionKind kind) {
    for (final s in sections) {
      if (s.kind == kind) return s;
    }
    return null;
  }
}

/// 进入 isolate 的纯元数据（可跨 isolate 传递）。
class AlbumAssetSnapshot {
  const AlbumAssetSnapshot({
    required this.id,
    required this.title,
    required this.sizeBytes,
    required this.takenAt,
    required this.isScreenshot,
    this.path,
  });

  final String id;
  final String title;
  final int sizeBytes;
  final DateTime takenAt;
  final bool isScreenshot;
  final String? path;
}

/// 相册域端侧元数据（预选推翻记录等），album 域自有存储的读写契约。
abstract class AlbumLocalStore {
  /// 用户推翻 AI 预选的记录：assetId → 用户是否保留（true = 留）。
  Future<Map<String, bool>> loadOverrides();

  Future<void> saveOverride(String assetId, bool keep);

  Future<DateTime?> loadLastScanAt();

  Future<void> saveLastScanAt(DateTime at);
}
