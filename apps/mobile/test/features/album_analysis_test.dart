import 'dart:io';
import 'dart:typed_data';

import 'package:flutter_test/flutter_test.dart';
import 'package:mobile/features/album/data/album_analysis.dart';
import 'package:mobile/features/album/domain/album_models.dart';

AlbumAssetSnapshot _snapshot({
  required String id,
  String title = 'IMG_0001.jpg',
  int sizeBytes = 1024,
  DateTime? takenAt,
  bool isScreenshot = false,
  String? path,
}) =>
    AlbumAssetSnapshot(
      id: id,
      title: title,
      sizeBytes: sizeBytes,
      takenAt: takenAt ?? DateTime(2026, 1, 1),
      isScreenshot: isScreenshot,
      path: path,
    );

Future<List<File>> _writeFiles(
  Directory dir,
  Map<String, List<int>> contents,
) async {
  final files = <File>[];
  var index = 0;
  for (final entry in contents.entries) {
    final file = File('${dir.path}/$index-${entry.key}');
    await file.writeAsBytes(entry.value, flush: true);
    files.add(file);
    index++;
  }
  return files;
}

void main() {
  test('test_album_analysis_expired_screenshot_has_reason', () async {
    final analyzer = const AlbumAnalyzer(chunkSize: 2);
    final now = DateTime(2026, 10, 1);
    final result = await analyzer.analyze([
      _snapshot(
        id: 'old-1',
        isScreenshot: true,
        takenAt: DateTime(2026, 1, 1),
      ),
      _snapshot(
        id: 'old-2',
        isScreenshot: true,
        takenAt: DateTime(2026, 2, 1),
      ),
      _snapshot(
        id: 'fresh',
        isScreenshot: true,
        takenAt: DateTime(2026, 9, 20),
      ),
      _snapshot(id: 'photo', takenAt: DateTime(2025, 1, 1)),
    ], config: AlbumAnalysisConfig(now: now));

    final section = result.section(AlbumSuggestionKind.expiredScreenshots)!;
    expect(section.supported, isTrue);
    expect(section.suggestion!.count, 2, reason: '90 天内的截图与普通照片不算');
    expect(section.suggestion!.reason, isNotEmpty);
    expect(section.suggestion!.assetIds, ['old-1', 'old-2']);
  });

  test('test_album_analysis_similar_burst_returns_unsupported_signal',
      () async {
    final analyzer = const AlbumAnalyzer();
    final result = await analyzer.analyze(const []);
    final section = result.section(AlbumSuggestionKind.similarBursts)!;
    expect(section.supported, isFalse, reason: 'D16：未支持 ≠ 空结果');
    expect(section.suggestion, isNull);
    expect(section.unsupportedReason, isNotEmpty);
  });

  test('test_album_analysis_duplicate_groups_identical_files', () async {
    final dir = await Directory.systemTemp.createTemp('album-analysis');
    addTearDown(() => dir.deleteSync(recursive: true));
    final payload = Uint8List.fromList(List.filled(4096, 7));
    final files = await _writeFiles(dir, {
      'a.jpg': payload,
      'b.jpg': payload,
      'c.jpg': List.filled(4096, 9),
    });
    final analyzer = const AlbumAnalyzer(chunkSize: 10);
    final result = await analyzer.analyze([
      _snapshot(
        id: 'dup-1',
        sizeBytes: 4096,
        path: files[0].path,
      ),
      _snapshot(
        id: 'dup-2',
        sizeBytes: 4096,
        path: files[1].path,
      ),
      _snapshot(
        id: 'distinct',
        sizeBytes: 4096,
        path: files[2].path,
      ),
    ], config: AlbumAnalysisConfig(now: DateTime(2026, 10, 1)));

    final section = result.section(AlbumSuggestionKind.duplicateSaves)!;
    expect(section.supported, isTrue);
    expect(section.suggestion!.assetIds, ['dup-1', 'dup-2'],
        reason: '同尺寸但首尾内容不同的文件不得入组');
    expect(section.suggestion!.count, 1,
        reason: 'count 是可删副本数（每组保留一份），与 totalBytes 同口径');
  });

  test('test_album_analysis_reports_all_duplicate_groups_in_size_group',
      () async {
    final dir = await Directory.systemTemp.createTemp('album-analysis');
    addTearDown(() => dir.deleteSync(recursive: true));
    final payloadA = Uint8List.fromList(List.filled(4096, 7));
    final payloadB = Uint8List.fromList(List.filled(4096, 11));
    final files = await _writeFiles(dir, {
      'a1.jpg': payloadA,
      'a2.jpg': payloadA,
      'b1.jpg': payloadB,
      'b2.jpg': payloadB,
      'b3.jpg': payloadB,
    });
    final analyzer = const AlbumAnalyzer(chunkSize: 10);
    final result = await analyzer.analyze([
      _snapshot(id: 'a1', sizeBytes: 4096, path: files[0].path),
      _snapshot(id: 'a2', sizeBytes: 4096, path: files[1].path),
      _snapshot(id: 'b1', sizeBytes: 4096, path: files[2].path),
      _snapshot(id: 'b2', sizeBytes: 4096, path: files[3].path),
      _snapshot(id: 'b3', sizeBytes: 4096, path: files[4].path),
    ], config: AlbumAnalysisConfig(now: DateTime(2026, 10, 1)));

    final section = result.section(AlbumSuggestionKind.duplicateSaves)!;
    expect(section.suggestion!.count, 3,
        reason: '同尺寸组内两组不同内容都要上报，提前 return 只报第一组');
    expect(
      section.suggestion!.assetIds.toSet(),
      {'a1', 'a2', 'b1', 'b2', 'b3'},
    );
  });

  test('test_album_analysis_runs_off_main_isolate', () async {
    final analyzer = const AlbumAnalyzer(chunkSize: 500);
    final snapshots = <AlbumAssetSnapshot>[
      for (var i = 0; i < 4000; i++)
        _snapshot(id: 's-$i', sizeBytes: 100 + i % 7),
    ];
    final watch = Stopwatch()..start();
    final result = await analyzer.analyze(
      snapshots,
      config: AlbumAnalysisConfig(now: DateTime(2026, 10, 1)),
    );
    watch.stop();
    expect(result.completed, isTrue);
    expect(result.scannedCount, 4000);
    expect(watch.elapsed, lessThan(const Duration(seconds: 20)),
        reason: '4000 张元数据分析不得长时间阻塞');
  });

  test('test_album_analysis_cancel_stops_between_chunks_without_changes',
      () async {
    final analyzer = const AlbumAnalyzer(chunkSize: 3);
    final snapshots = <AlbumAssetSnapshot>[
      for (var i = 0; i < 30; i++)
        _snapshot(id: 's-$i', isScreenshot: true, takenAt: DateTime(2020)),
    ];
    var checked = 0;
    final before = List.of(snapshots);
    final result = await analyzer.analyze(
      snapshots,
      config: AlbumAnalysisConfig(now: DateTime(2026, 10, 1)),
      isCancelled: () {
        checked++;
        return checked > 1;
      },
    );
    expect(result.completed, isFalse);
    expect(result.scannedCount, lessThan(30));
    expect(snapshots, before, reason: '中断不改变任何输入，更不改变任何照片');
    final section = result.section(AlbumSuggestionKind.expiredScreenshots)!;
    expect(section.suggestion!.assetIds.length, lessThan(30));
  });

  test('test_album_analysis_progress_reports_full_range', () async {
    final analyzer = const AlbumAnalyzer(chunkSize: 4);
    final progress = <double>[];
    await analyzer.analyze(
      <AlbumAssetSnapshot>[
        for (var i = 0; i < 8; i++) _snapshot(id: 'p-$i'),
      ],
      config: AlbumAnalysisConfig(now: DateTime(2026, 10, 1)),
      onProgress: progress.add,
    );
    expect(progress.last, 1.0);
  });
}
