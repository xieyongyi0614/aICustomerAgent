import 'dart:convert';
import 'dart:io';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:mobile/app/router/app_router.dart';
import 'package:mobile/app/theme/app_theme.dart';
import 'package:mobile/design_system/tokens/tokens.dart';
import 'package:mobile/features/album/data/album_analysis.dart';
import 'package:mobile/features/album/data/album_repository.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'package:mobile/features/album/domain/album_models.dart';
import 'package:mobile/features/album/presentation/album_ai_page.dart';
import 'package:mobile/features/album/presentation/album_detail_page.dart';
import 'package:mobile/features/album/presentation/album_manage_page.dart';
import 'package:mobile/design_system/components/components.dart';
import 'package:mobile/features/album/presentation/album_page.dart';

final _thumbBytes = base64Decode(
  'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==',
);

PhotoAsset _asset(
  String id, {
  bool video = false,
  DateTime? takenAt,
}) =>
    PhotoAsset(
      id: id,
      title: '$id.jpg',
      bucketId: 'all',
      takenAt: takenAt ?? DateTime(2026, 9, 20, 10, 0),
      sizeBytes: 1024,
      isVideo: video,
      duration: video ? const Duration(seconds: 24) : null,
      isScreenshot: false,
    );

class _FakeSource implements AlbumAssetSource {
  _FakeSource({
    this.permission = AlbumPermissionStatus.granted,
    this.count = 6,
    Set<String>? videoIds,
  }) : _videoIds = videoIds ?? <String>{};

  final AlbumPermissionStatus permission;
  final int count;
  final Set<String> _videoIds;

  final List<String> trashedIds = [];
  final List<String> movedIds = [];

  @override
  Future<AlbumPermissionStatus> requestAccess() async => permission;

  @override
  Future<List<AlbumBucket>> loadBuckets() async => [
        AlbumBucket(id: 'all', name: '最近添加', assetCount: count, isAll: true),
        AlbumBucket(id: 'shots', name: 'Screenshots', assetCount: 40, isAll: false),
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
        _asset('asset-$i', video: _videoIds.contains('asset-$i')),
    ];
    return AlbumAssetPage(items: items, total: count, hasMore: end < count);
  }

  @override
  Future<String?> resolvePath(PhotoAsset asset) async => null;

  @override
  Future<ImageProvider?> coverProvider(AlbumBucket bucket, {int size = 256}) async =>
      MemoryImage(_thumbBytes);

  @override
  Future<ImageProvider> thumbnailProvider(PhotoAsset asset, {int size = 256}) async =>
      MemoryImage(_thumbBytes);

  @override
  Future<bool> trashAsset(PhotoAsset asset) async {
    trashedIds.add(asset.id);
    return true;
  }

  @override
  Future<bool> setFavorite(PhotoAsset asset, {required bool favorite}) async =>
      true;

  @override
  Future<bool> moveAsset(PhotoAsset asset, AlbumBucket target) async {
    movedIds.add(asset.id);
    return true;
  }

  @override
  Future<void> openSettings() async {}
}

class _FakeAnalyzer extends AlbumAnalyzer {
  const _FakeAnalyzer(this.result);

  final AlbumAnalysisResult result;

  @override
  Future<AlbumAnalysisResult> analyze(
    List<AlbumAssetSnapshot> snapshots, {
    AlbumAnalysisConfig? config,
    bool Function()? isCancelled,
    void Function(double progress)? onProgress,
  }) async =>
      result;
}

AlbumAnalysisResult _resultWith({int expired = 38, int duplicates = 12}) {
  const expiredBytes = 620 * 1024;
  const duplicateBytes = 300 * 1024;
  return AlbumAnalysisResult(
    completed: true,
    scannedCount: 100,
    sections: [
      AlbumAnalysisSection.done(
        AlbumSuggestion(
          kind: AlbumSuggestionKind.expiredScreenshots,
          count: expired,
          totalBytes: expiredBytes,
          reason: '保存超过 90 天、早就不再看内容的屏幕截图',
          assetIds: const ['old-1', 'old-2'],
        ),
      ),
      AlbumAnalysisSection.done(
        AlbumSuggestion(
          kind: AlbumSuggestionKind.duplicateSaves,
          count: duplicates,
          totalBytes: duplicateBytes,
          reason: '同一内容保存了多份：文件大小一致、首尾内容相同',
          assetIds: const ['dup-1'],
        ),
      ),
      AlbumAnalysisSection.unsupported(
        AlbumSuggestionKind.similarBursts,
        AlbumAnalyzer.similarBurstUnsupportedReason,
      ),
    ],
  );
}

Widget _wrap(Widget child, {double height = 1400}) => ProviderScope(
      child: MaterialApp(
        theme: buildAppTheme(),
        home: Scaffold(
          backgroundColor: AppColors.light.canvas,
          body: SizedBox(width: 390, height: height, child: child),
        ),
      ),
    );

void _tallViewport(WidgetTester tester) {
  tester.view.physicalSize = const Size(390, 2600);
  tester.view.devicePixelRatio = 1.0;
  addTearDown(tester.view.reset);
}

Future<void> _pumpAlbumPage(
  WidgetTester tester,
  AlbumRepository repo, {
  AlbumAnalysisResult? result,
}) async {
  _tallViewport(tester);
  await tester.pumpWidget(
    _wrap(
      AlbumPage(
        repository: repo,
        analyzer: _FakeAnalyzer(result ?? _resultWith()),
      ),
    ),
  );
  await tester.pumpAndSettle(const Duration(milliseconds: 50));
}

void main() {
  setUp(() {
    SharedPreferences.setMockInitialValues({});
  });

  test('test_album_page_has_no_network_access', () {
    final content =
        File('lib/features/album/presentation/album_page.dart')
            .readAsStringSync();
    expect(content.contains('package:dio'), isFalse);
    expect(content.contains('core/network'), isFalse);
    expect(content.contains('http://'), isFalse);
    expect(content.contains('https://'), isFalse);
  });

  testWidgets('test_album_page_renders_ready_sections', (tester) async {
    final repo = AlbumRepository(source: _FakeSource(count: 6));
    await _pumpAlbumPage(tester, repo);
    expect(find.text('相册'), findsOneWidget);
    expect(find.text('只存在这台手机上，不会上传服务器'), findsOneWidget);
    expect(find.text('亚丝娜的整理建议'), findsOneWidget);
    expect(find.text('分类相簿'), findsOneWidget);
    expect(find.text('最近添加'), findsWidgets);
    expect(find.text('批量管理照片'), findsOneWidget);
    expect(find.textContaining('仅本机存储 · 未开启任何云同步'), findsOneWidget);
  });

  testWidgets('test_album_page_never_claims_no_network_permission',
      (tester) async {
    final repo = AlbumRepository(source: _FakeSource(count: 6));
    await _pumpAlbumPage(tester, repo);
    expect(find.textContaining('不需要联网权限'), findsNothing);
    expect(find.textContaining('不会上传服务器'), findsWidgets);
    expect(find.textContaining('系统「最近删除」'), findsOneWidget);
    expect(find.textContaining('30 天'), findsOneWidget);
  });

  testWidgets('test_album_page_suggestion_card_counts_only_supported_kinds',
      (tester) async {
    final repo = AlbumRepository(source: _FakeSource(count: 6));
    await _pumpAlbumPage(tester, repo);
    expect(find.text('50 张可清理，腾出 920 MB'), findsOneWidget);
  });

  testWidgets('test_album_page_permission_denied_shows_guidance',
      (tester) async {
    final repo = AlbumRepository(
      source: _FakeSource(count: 6, permission: AlbumPermissionStatus.denied),
    );
    await _pumpAlbumPage(tester, repo);
    expect(find.text('去开启权限'), findsOneWidget);
    expect(find.textContaining('照片不会上传服务器'), findsOneWidget);
  });

  testWidgets('test_album_page_empty_state_when_no_photos', (tester) async {
    final repo = AlbumRepository(source: _FakeSource(count: 0));
    await _pumpAlbumPage(tester, repo);
    expect(find.text('最近添加'), findsWidgets);
  });

  testWidgets('test_album_page_video_tile_shows_duration_badge',
      (tester) async {
    final repo = AlbumRepository(
      source: _FakeSource(count: 6, videoIds: {'asset-0'}),
    );
    await _pumpAlbumPage(tester, repo);
    expect(find.text('00:24'), findsOneWidget);
  });

  testWidgets('test_album_page_analysis_progress_is_interruptible',
      (tester) async {
    final repo = AlbumRepository(source: _FakeSource(count: 6));
    final interrupted = AlbumAnalysisResult(
      completed: false,
      scannedCount: 10,
      sections: [
        AlbumAnalysisSection.done(
          AlbumSuggestion(
            kind: AlbumSuggestionKind.expiredScreenshots,
            count: 3,
            totalBytes: 2048,
            reason: '保存超过 90 天的屏幕截图',
            assetIds: ['a'],
          ),
        ),
        AlbumAnalysisSection.unsupported(
          AlbumSuggestionKind.similarBursts,
          '本期未开启',
        ),
      ],
    );
    await tester.pumpWidget(
      _wrap(AlbumPage(
        repository: repo,
        analyzer: _FakeAnalyzer(interrupted),
      )),
    );
    await tester.pumpAndSettle(const Duration(milliseconds: 50));
    expect(find.byType(LinearProgressIndicator), findsNothing,
        reason: '中断后进度条不残留，卡片保持中断前的数值');
  });

  testWidgets('test_album_manage_page_preselect_can_be_overridden',
      (tester) async {
    final data = AlbumManageData(
      assets: [_asset('dup-1'), _asset('old-1'), _asset('keep-1')],
      thumbnails: const {},
      preselectedIds: const {'dup-1', 'old-1'},
      totalCount: 3,
    );
    await tester.pumpWidget(_wrap(AlbumManagePage(preloaded: data)));
    await tester.pumpAndSettle();
    expect(find.text('已选 2 张'), findsOneWidget);
    expect(tester.widgetList<PhotoTile>(find.byType(PhotoTile)).length, 3);
  });

  testWidgets('test_album_manage_page_groups_preselected_and_manual',
      (tester) async {
    final data = AlbumManageData(
      assets: [_asset('old-1'), _asset('dup-1'), _asset('keep-1')],
      thumbnails: const {},
      preselectedIds: const {'old-1', 'dup-1'},
      totalCount: 3,
      sections: _resultWith().sections,
    );
    _tallViewport(tester);
    await tester.pumpWidget(_wrap(AlbumManagePage(preloaded: data), height: 2600));
    await tester.pumpAndSettle();
    expect(find.textContaining('过期截图 · 共 1 张（AI 预选）'), findsOneWidget);
    expect(find.textContaining('重复保存 · 共 1 张（AI 预选）'), findsOneWidget);
    expect(find.text('手动挑选'), findsOneWidget);
    expect(find.textContaining('相似连拍 · 本期未开启'), findsOneWidget);
    expect(find.textContaining('逐张画面比对'), findsOneWidget);
    expect(find.textContaining('已帮你预选 2 张'), findsOneWidget);
    expect(find.textContaining('1 张过期截图 + 1 张重复保存'), findsOneWidget);
    expect(find.text('这些预选是怎么算出来的 →'), findsOneWidget);
  });

  testWidgets('test_album_manage_page_select_all_toggles', (tester) async {
    final data = AlbumManageData(
      assets: [_asset('old-1'), _asset('dup-1'), _asset('keep-1')],
      thumbnails: const {},
      preselectedIds: const {'old-1'},
      totalCount: 3,
    );
    await tester.pumpWidget(_wrap(AlbumManagePage(preloaded: data)));
    await tester.pumpAndSettle();
    expect(find.text('已选 1 张'), findsOneWidget);
    await tester.tap(find.text('全选'));
    await tester.pumpAndSettle();
    expect(find.text('已选 3 张'), findsOneWidget);
    await tester.tap(find.text('全不选'));
    await tester.pumpAndSettle();
    expect(find.text('已选 0 张'), findsOneWidget);
  });

  testWidgets('test_album_manage_page_move_uses_system_albums',
      (tester) async {
    final data = AlbumManageData(
      assets: [_asset('keep-1')],
      thumbnails: const {},
      preselectedIds: const {},
      totalCount: 1,
    );
    final repo = AlbumRepository(source: _FakeSource());
    _tallViewport(tester);
    await tester.pumpWidget(_wrap(AlbumManagePage(preloaded: data, repository: repo)));
    await tester.pumpAndSettle();
    await tester.tap(find.text('全选'));
    await tester.pumpAndSettle();
    await tester.tap(find.text('移动'));
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 400));
    expect(find.text('移动到相簿'), findsOneWidget);
    await tester.tap(find.text('Screenshots'));
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 400));
    expect(find.textContaining('已移动 1 张到「Screenshots」'), findsOneWidget);
  });

  testWidgets('test_album_detail_shows_video_count_and_manage_entry',
      (tester) async {
    final data = AlbumManageData(
      assets: [
        _asset('a-1', takenAt: DateTime(2026, 9, 12)),
        _asset('a-4', video: true, takenAt: DateTime(2026, 9, 12)),
      ],
      thumbnails: const {},
      preselectedIds: const {},
      totalCount: 2,
    );
    await tester.pumpWidget(_wrap(AlbumDetailPage(
      preloaded: data,
      albumName: '旅行',
    )));
    await tester.pumpAndSettle();
    expect(find.textContaining('2 张 · 1 段视频'), findsOneWidget);
    expect(find.text('批量管理这个相簿'), findsOneWidget);
    expect(find.textContaining('无云同步'), findsNothing, reason: '相册域禁止云表述');
    expect(find.textContaining('不上传服务器'), findsOneWidget);
  });

  testWidgets('test_album_detail_groups_by_day_without_ai_badges',
      (tester) async {
    final data = AlbumManageData(
      assets: [
        _asset('a-1', takenAt: DateTime(2026, 9, 12)),
        _asset('a-2', takenAt: DateTime(2026, 9, 12)),
        _asset('a-3', takenAt: DateTime(2026, 9, 20)),
        _asset('a-4', video: true, takenAt: DateTime(2026, 9, 20)),
      ],
      thumbnails: const {},
      preselectedIds: const {},
      totalCount: 4,
    );
    await tester.pumpWidget(_wrap(AlbumDetailPage(preloaded: data)));
    await tester.pumpAndSettle();
    expect(find.text('2026 年 9 月 12 日'), findsOneWidget);
    expect(find.text('2026 年 9 月 20 日'), findsOneWidget);
    expect(find.text('00:24'), findsOneWidget, reason: '视频时长徽章');
    expect(find.textContaining('最清楚'), findsNothing, reason: '无 AI 假结论（D16）');
  });

  testWidgets('test_album_ai_page_shows_unsupported_row_and_principles',
      (tester) async {
    _tallViewport(tester);
    await tester.pumpWidget(_wrap(AlbumAiPage(result: _resultWith())));
    await tester.pumpAndSettle();
    expect(find.text('50 张可清理（截图与重复），腾出 920 MB'), findsOneWidget);
    expect(find.text('相似连拍 · 本期未开启'), findsOneWidget);
    expect(find.textContaining('逐张画面比对'), findsOneWidget);
    expect(find.text('只在本机算——分析全部在你手机上完成'), findsOneWidget);
    expect(find.text('只预选不自动删——删之前由你确认'), findsOneWidget);
    expect(find.textContaining('最近删除」保留 30 天'), findsOneWidget);
    expect(find.text('你的推翻我会记住'), findsOneWidget);
  });

  test('test_album_routes_registered_immersive_and_life_tab', () {
    for (final path in const [
      '/album',
      '/album/manage',
      '/album/detail',
      '/album/photo',
      '/album/ai',
    ]) {
      expect(chromeByPath.containsKey(path), isTrue, reason: path);
    }
  });
}
