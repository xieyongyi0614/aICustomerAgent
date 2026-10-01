import 'dart:typed_data';

import 'package:flutter/painting.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:mobile/features/album/data/album_local_store.dart';
import 'package:mobile/features/album/data/album_repository.dart';
import 'package:mobile/features/album/domain/album_models.dart';
import 'package:shared_preferences/shared_preferences.dart';

class _FakeSource implements AlbumAssetSource {
  _FakeSource({
    this.permission = AlbumPermissionStatus.granted,
    this.count = 0,
  });

  final AlbumPermissionStatus permission;
  final int count;
  final List<String> trashedIds = [];
  int pathLookups = 0;

  @override
  Future<AlbumPermissionStatus> requestAccess() async => permission;

  @override
  Future<List<AlbumBucket>> loadBuckets() async => [
        AlbumBucket(id: 'all', name: '最近添加', assetCount: count, isAll: true),
      ];

  @override
  Future<AlbumAssetPage> loadAssets({
    String? bucketId,
    required int start,
    required int limit,
  }) async {
    final end = (start + limit).clamp(0, count);
    final items = <PhotoAsset>[
      for (var i = start; i < end; i++)
        PhotoAsset(
          id: 'asset-$i',
          title: 'IMG_$i.jpg',
          bucketId: 'all',
          takenAt: DateTime(2026, 1, 1),
          sizeBytes: 0,
          isVideo: false,
          duration: null,
          isScreenshot: false,
        ),
    ];
    return AlbumAssetPage(
      items: items,
      total: count,
      hasMore: end < count,
    );
  }

  @override
  Future<String?> resolvePath(PhotoAsset asset) async {
    pathLookups++;
    return null;
  }

  @override
  Future<ImageProvider> thumbnailProvider(PhotoAsset asset, {int size = 256}) async =>
      MemoryImage(Uint8List.fromList(asset.id.codeUnits));

  @override
  Future<ImageProvider?> coverProvider(AlbumBucket bucket, {int size = 256}) async =>
      MemoryImage(Uint8List(4));

  @override
  Future<bool> trashAsset(PhotoAsset asset) async {
    trashedIds.add(asset.id);
    return true;
  }
}

class _RecordingStore implements AlbumLocalStore {
  int savedScans = 0;
  final Map<String, bool> overrides = {};

  @override
  Future<Map<String, bool>> loadOverrides() async => Map.of(overrides);

  @override
  Future<void> saveOverride(String assetId, bool keep) async {
    overrides[assetId] = keep;
  }

  @override
  Future<DateTime?> loadLastScanAt() async => null;

  @override
  Future<void> saveLastScanAt(DateTime at) async {
    savedScans++;
  }
}

void main() {
  test('test_album_repository_permission_maps_denied_status', () async {
    final repository = AlbumRepository(
      source: _FakeSource(permission: AlbumPermissionStatus.denied),
    );
    expect(await repository.requestAccess(), AlbumPermissionStatus.denied);
  });

  test('test_album_repository_paginates_large_collections', () async {
    final repository = AlbumRepository(source: _FakeSource(count: 250));
    final first = await repository.assets(limit: 60);
    expect(first.total, 250);
    expect(first.items.length, 60);
    expect(first.hasMore, isTrue);

    var fetched = first.items.length;
    var hasMore = first.hasMore;
    var pages = 1;
    var start = 60;
    while (hasMore) {
      final page = await repository.assets(start: start, limit: 60);
      fetched += page.items.length;
      hasMore = page.hasMore;
      start += page.items.length;
      pages++;
    }
    expect(fetched, 250);
    expect(pages, 5);
  });

  test('test_album_delete_uses_system_recycle_bin', () async {
    final source = _FakeSource(count: 1);
    final repository = AlbumRepository(source: source);
    final asset = (await repository.assets()).items.single;
    final moved = await repository.moveToTrash(asset);
    expect(moved, isTrue);
    expect(source.trashedIds, ['asset-0']);
  });

  test('test_album_scan_cancel_has_no_side_effects', () async {
    final source = _FakeSource(count: 120);
    final store = _RecordingStore();
    final repository = AlbumRepository(source: source, store: store);
    var batches = 0;
    final result = await repository.scanSnapshots(
      isCancelled: () {
        batches++;
        return batches > 1;
      },
    );
    expect(result, isNull, reason: '中断时不得产出部分结果');
    expect(store.savedScans, 0, reason: '中断不得写入扫描时间');
    expect(source.trashedIds, isEmpty, reason: '扫描永远不删除');
  });

  test('test_album_scan_completes_and_records_scan_time', () async {
    final source = _FakeSource(count: 40);
    final store = _RecordingStore();
    final repository = AlbumRepository(source: source, store: store);
    final snapshots = await repository.scanSnapshots();
    expect(snapshots, isNotNull);
    expect(snapshots!.length, 40);
    expect(store.savedScans, 1);
  });

  test('test_album_local_store_survives_restart', () async {
    SharedPreferences.setMockInitialValues({});
    final store = SharedPreferencesAlbumLocalStore();
    await store.saveOverride('asset-7', false);
    await store.saveLastScanAt(DateTime(2026, 10, 1, 9, 30));

    final restarted = SharedPreferencesAlbumLocalStore();
    expect(await restarted.loadOverrides(), {'asset-7': false});
    expect(await restarted.loadLastScanAt(), DateTime(2026, 10, 1, 9, 30));
  });
}
