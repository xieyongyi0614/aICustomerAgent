import 'dart:io';

import 'package:flutter/painting.dart';
import 'package:photo_manager/photo_manager.dart';
import 'package:photo_manager_image_provider/photo_manager_image_provider.dart';

import '../domain/album_models.dart';
import 'album_local_store.dart';

/// 相册域资产源抽象：`photo_manager` 的真实实现 + 测试替身。
///
/// 相册域全程零网络（D18）：本接口的任何实现只允许触达本机媒体库。
abstract class AlbumAssetSource {
  Future<AlbumPermissionStatus> requestAccess();

  Future<List<AlbumBucket>> loadBuckets();

  Future<AlbumAssetPage> loadAssets({
    String? bucketId,
    required int start,
    required int limit,
  });

  /// 元数据快照的路径补充（文件 stat，供重复保存分析）。
  Future<String?> resolvePath(PhotoAsset asset);

  /// 缩略图按需解码的 ImageProvider（尺寸由调用方给定，不载原图）。
  Future<ImageProvider> thumbnailProvider(PhotoAsset asset, {int size = 256});

  /// 相簿封面（该相簿第一张的缩略图；空相簿返回 null，调用方呈中性占位）。
  Future<ImageProvider?> coverProvider(AlbumBucket bucket, {int size = 256});

  /// 删除 = 系统回收站（D17）：不自建回收站、不复制原图。
  Future<bool> trashAsset(PhotoAsset asset);
}

/// `photo_manager` 实现的资产源。
class PhotoManagerAssetSource implements AlbumAssetSource {
  const PhotoManagerAssetSource();

  @override
  Future<AlbumPermissionStatus> requestAccess() async {
    final state = await PhotoManager.requestPermissionExtend();
    if (state.hasAccess) {
      return state == PermissionState.authorized
          ? AlbumPermissionStatus.granted
          : AlbumPermissionStatus.limited;
    }
    return AlbumPermissionStatus.denied;
  }

  @override
  Future<List<AlbumBucket>> loadBuckets() async {
    final paths = await PhotoManager.getAssetPathList(
      type: RequestType.common,
      hasAll: true,
    );
    return [
      for (final path in paths)
        AlbumBucket(
          id: path.id,
          name: path.name,
          assetCount: await path.assetCountAsync,
          isAll: path.isAll,
        ),
    ];
  }

  @override
  Future<AlbumAssetPage> loadAssets({
    String? bucketId,
    required int start,
    required int limit,
  }) async {
    final path = await _pathOf(bucketId);
    if (path == null) {
      return const AlbumAssetPage(items: [], total: 0, hasMore: false);
    }
    final total = await path.assetCountAsync;
    final end = (start + limit).clamp(start, total);
    final entities = end > start
        ? await path.getAssetListRange(start: start, end: end)
        : const <AssetEntity>[];
    return AlbumAssetPage(
      items: [for (final e in entities) _toAsset(e)],
      total: total,
      hasMore: end < total,
    );
  }

  @override
  Future<String?> resolvePath(PhotoAsset asset) async {
    final entity = await AssetEntity.fromId(asset.id);
    return (await entity?.originFile)?.path;
  }

  @override
  Future<ImageProvider> thumbnailProvider(PhotoAsset asset, {int size = 256}) async {
    final entity = await AssetEntity.fromId(asset.id);
    if (entity == null) {
      throw StateError('asset 不存在: ${asset.id}');
    }
    return AssetEntityImageProvider(
      entity,
      isOriginal: false,
      thumbnailSize: ThumbnailSize(size, size),
    );
  }

  @override
  Future<ImageProvider?> coverProvider(AlbumBucket bucket, {int size = 256}) async {
    final path = await _pathOf(bucket.id);
    if (path == null) return null;
    final entities = await path.getAssetListRange(start: 0, end: 1);
    if (entities.isEmpty) return null;
    return AssetEntityImageProvider(
      entities.first,
      isOriginal: false,
      thumbnailSize: ThumbnailSize(size, size),
    );
  }

  @override
  Future<bool> trashAsset(PhotoAsset asset) async {
    final entity = await AssetEntity.fromId(asset.id);
    if (entity == null) return false;
    final result = await PhotoManager.editor.deleteWithIds([asset.id]);
    return result.isNotEmpty;
  }

  Future<AssetPathEntity?> _pathOf(String? bucketId) async {
    final paths = await PhotoManager.getAssetPathList(
      type: RequestType.common,
      hasAll: true,
    );
    if (bucketId == null) {
      return paths.firstWhere((p) => p.isAll, orElse: () => paths.first);
    }
    return paths.firstWhere(
      (p) => p.id == bucketId,
      orElse: () => paths.firstWhere((p) => p.isAll, orElse: () => paths.first),
    );
  }

  PhotoAsset _toAsset(AssetEntity e) {
    final title = e.title ?? e.id;
    final relative = (e.relativePath ?? '').toLowerCase();
    return PhotoAsset(
      id: e.id,
      title: title,
      bucketId: '',
      takenAt: e.modifiedDateTime,
      sizeBytes: 0,
      isVideo: e.type == AssetType.video,
      duration: e.videoDuration == Duration.zero ? null : e.videoDuration,
      isScreenshot:
          relative.contains('screenshot') || relative.contains('screenshots'),
    );
  }
}

/// 相册域数据面：权限、分页读取、快照扫描、删除（全部本机）。
class AlbumRepository {
  AlbumRepository({AlbumAssetSource? source, AlbumLocalStore? store})
      : source = source ?? const PhotoManagerAssetSource(),
        store = store ?? SharedPreferencesAlbumLocalStore();

  final AlbumAssetSource source;
  final AlbumLocalStore store;

  static const defaultPageSize = 60;
  static const scanBatchSize = 50;

  Future<AlbumPermissionStatus> requestAccess() => source.requestAccess();

  Future<List<AlbumBucket>> buckets() => source.loadBuckets();

  /// 分页读取（缺口 28：数千张不一次性载入）。
  Future<AlbumAssetPage> assets({
    String? bucketId,
    int start = 0,
    int limit = defaultPageSize,
  }) =>
      source.loadAssets(bucketId: bucketId, start: start, limit: limit);

  /// 扫描元数据快照：分批进行、批间可中断、只读不写。
  ///
  /// 返回 null = 中断（已完成的部分不会有任何改变）。
  Future<List<AlbumAssetSnapshot>?> scanSnapshots({
    String? bucketId,
    void Function(int scanned, int total)? onProgress,
    bool Function()? isCancelled,
  }) async {
    final snapshots = <AlbumAssetSnapshot>[];
    var start = 0;
    var total = 0;
    while (true) {
      final page = await source.loadAssets(
        bucketId: bucketId,
        start: start,
        limit: scanBatchSize,
      );
      total = page.total;
      for (final asset in page.items) {
        final path = await source.resolvePath(asset);
        final size = path == null ? 0 : await File(path).length();
        snapshots.add(asset.toSnapshot(path: path, sizeBytes: size));
      }
      start += page.items.length;
      onProgress?.call(start, total);
      if (isCancelled?.call() ?? false) return null;
      if (!page.hasMore || page.items.isEmpty) break;
    }
    await store.saveLastScanAt(DateTime.now());
    return snapshots;
  }

  /// 删除 = 系统「最近删除」（D17）：交给系统能力，App 不自建回收站。
  Future<bool> moveToTrash(PhotoAsset asset) => source.trashAsset(asset);
}

/// 删除能力走 `PhotoManager.editor`（系统回收站语义）的静态说明常量，
/// 供守卫与页面文案引用，避免口径漂移。
const albumDeleteCapabilityNote = '删除后进系统「最近删除」，30 天内可恢复';
