import 'dart:io';
import 'dart:isolate';

import '../domain/album_models.dart';

/// 分析配置（可跨 isolate 传递）。
class AlbumAnalysisConfig {
  const AlbumAnalysisConfig({
    required this.now,
    this.screenshotMaxAge = const Duration(days: 90),
    this.sampleBytes = 256,
  });

  final DateTime now;
  final Duration screenshotMaxAge;
  final int sampleBytes;
}

/// isolate 内单块扫描的产出（全部可传递的纯数据）。
class AlbumChunkFindings {
  const AlbumChunkFindings({
    required this.expired,
    required this.duplicateClusters,
  });

  final List<AlbumAssetSnapshot> expired;
  final List<AlbumDuplicateCluster> duplicateClusters;
}

/// 重复保存聚类：`key` 是跨块合并依据（尺寸 + 采样内容指纹）。
class AlbumDuplicateCluster {
  const AlbumDuplicateCluster({
    required this.key,
    required this.ids,
    required this.bytesPerAsset,
  });

  final String key;
  final List<String> ids;
  final int bytesPerAsset;
}

/// 本机分析器：过期截图 + 重复保存（D16：相似连拍本期不做，返回未支持信号）。
///
/// - 分块在后台 isolate 执行，批间响应取消；
/// - 全程只读：中断或完成都不删除 / 移动 / 修改任何照片；
/// - 重复判定 = 相同文件尺寸 + 首尾采样内容一致（或文件名副本模式），
///   不载入原图。
class AlbumAnalyzer {
  const AlbumAnalyzer({this.chunkSize = 200});

  final int chunkSize;

  static const similarBurstUnsupportedReason =
      '相似连拍需要逐张画面比对，能耗与你的相册体量不匹配，本期未开启';

  Future<AlbumAnalysisResult> analyze(
    List<AlbumAssetSnapshot> snapshots, {
    AlbumAnalysisConfig? config,
    bool Function()? isCancelled,
    void Function(double progress)? onProgress,
  }) async {
    final effectiveConfig =
        config ?? AlbumAnalysisConfig(now: DateTime.now());
    final expired = <AlbumAssetSnapshot>[];
    final clusters = <String, AlbumDuplicateCluster>{};
    var processed = 0;
    var cancelled = false;
    for (var start = 0; start < snapshots.length; start += chunkSize) {
      if (isCancelled?.call() ?? false) {
        cancelled = true;
        break;
      }
      final end = (start + chunkSize).clamp(0, snapshots.length);
      final chunk = snapshots.sublist(start, end);
      final findings = await Isolate.run(
        () => analyzeChunk(chunk, effectiveConfig),
      );
      expired.addAll(findings.expired);
      for (final cluster in findings.duplicateClusters) {
        final existing = clusters[cluster.key];
        if (existing == null) {
          clusters[cluster.key] = cluster;
        } else {
          clusters[cluster.key] = AlbumDuplicateCluster(
            key: existing.key,
            ids: [...existing.ids, ...cluster.ids],
            bytesPerAsset: existing.bytesPerAsset,
          );
        }
      }
      processed = end;
      onProgress?.call(end / snapshots.length);
    }
    return AlbumAnalysisResult(
      sections: [
        AlbumAnalysisSection.done(_expiredSuggestion(expired)),
        AlbumAnalysisSection.done(_duplicateSuggestion(clusters.values)),
        AlbumAnalysisSection.unsupported(
          AlbumSuggestionKind.similarBursts,
          similarBurstUnsupportedReason,
        ),
      ],
      completed: !cancelled,
      scannedCount: processed,
    );
  }

  AlbumSuggestion _expiredSuggestion(List<AlbumAssetSnapshot> expired) {
    final bytes = expired.fold<int>(0, (sum, s) => sum + s.sizeBytes);
    return AlbumSuggestion(
      kind: AlbumSuggestionKind.expiredScreenshots,
      count: expired.length,
      totalBytes: bytes,
      reason: '保存超过 90 天、早就不再看内容的屏幕截图',
      assetIds: [for (final s in expired) s.id],
    );
  }

  AlbumSuggestion _duplicateSuggestion(
    Iterable<AlbumDuplicateCluster> clusters,
  ) {
    final ids = <String>[];
    var bytes = 0;
    for (final cluster in clusters) {
      if (cluster.ids.length < 2) continue;
      ids.addAll(cluster.ids);
      bytes += cluster.bytesPerAsset * (cluster.ids.length - 1);
    }
    return AlbumSuggestion(
      kind: AlbumSuggestionKind.duplicateSaves,
      count: ids.length,
      totalBytes: bytes,
      reason: '同一内容保存了多份：文件大小一致、首尾内容相同',
      assetIds: ids,
    );
  }
}

/// 单块分析：在 isolate 内执行（纯函数，只读快照与文件采样）。
AlbumChunkFindings analyzeChunk(
  List<AlbumAssetSnapshot> chunk,
  AlbumAnalysisConfig config,
) {
  final expired = <AlbumAssetSnapshot>[];
  final clusters = <String, List<AlbumAssetSnapshot>>{};
  for (final snapshot in chunk) {
    if (snapshot.isScreenshot &&
        config.now.difference(snapshot.takenAt) > config.screenshotMaxAge) {
      expired.add(snapshot);
    }
    if (snapshot.sizeBytes <= 0) continue;
    clusters
        .putIfAbsent('${snapshot.sizeBytes}', () => [])
        .add(snapshot);
  }
  final duplicateClusters = <AlbumDuplicateCluster>[];
  for (final entry in clusters.entries) {
    if (entry.value.length < 2) continue;
    final merged = _mergeSameContent(entry.value, config);
    if (merged != null) duplicateClusters.add(merged);
  }
  return AlbumChunkFindings(
    expired: expired,
    duplicateClusters: duplicateClusters,
  );
}

/// 同尺寸组内再按采样内容指纹合并，避免「恰好同尺寸」误判。
AlbumDuplicateCluster? _mergeSameContent(
  List<AlbumAssetSnapshot> group,
  AlbumAnalysisConfig config,
) {
  final byFingerprint = <String, List<AlbumAssetSnapshot>>{};
  for (final snapshot in group) {
    byFingerprint.putIfAbsent(
      contentKey(snapshot, config),
      () => [],
    ).add(snapshot);
  }
  for (final entry in byFingerprint.entries) {
    if (entry.value.length < 2) continue;
    final ids = [for (final s in entry.value) s.id];
    return AlbumDuplicateCluster(
      key: entry.key,
      ids: ids,
      bytesPerAsset: entry.value.first.sizeBytes,
    );
  }
  return null;
}

/// 内容指纹：尺寸 + 首尾采样字节（无路径时退化为尺寸 + 时间）。
String contentKey(AlbumAssetSnapshot s, AlbumAnalysisConfig config) {
  if (s.path == null) {
    return '${s.sizeBytes}:${s.takenAt.millisecondsSinceEpoch}';
  }
  final file = File(s.path!);
  final head = _sample(file, 0, config.sampleBytes);
  final tailStart = (s.sizeBytes - config.sampleBytes).clamp(0, s.sizeBytes);
  final tail = _sample(file, tailStart, config.sampleBytes);
  return '${s.sizeBytes}:${head.fold<int>(0x811c9dc5, fnv1a)}:'
      '${tail.fold<int>(0x811c9dc5, fnv1a)}';
}

int fnv1a(int hash, int byte) => (hash ^ byte) * 0x01000193 & 0xFFFFFFFF;

List<int> _sample(File file, int start, int length) {
  try {
    final handle = file.openSync();
    try {
      handle.setPositionSync(start);
      return handle.readSync(length);
    } finally {
      handle.closeSync();
    }
  } on FileSystemException {
    return const [];
  }
}
