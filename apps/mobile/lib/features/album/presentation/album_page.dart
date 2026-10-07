import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../../app/theme/theme_context.dart';
import '../../../app/state/album_summary_provider.dart';
import '../../../design_system/components/components.dart';
import '../data/album_analysis.dart';
import '../data/album_repository.dart';
import '../domain/album_models.dart';

/// B14 #album 相册：整理建议 → 占用 → 分类相簿 → 最近添加 → 批量管理。
///
/// 全程本机、零网络（D18）；每处 AI 能力都带「本机分析」定语（红线 9）。
class AlbumPage extends ConsumerStatefulWidget {
  const AlbumPage({
    super.key,
    this.repository,
    this.analyzer,
    this.showBackLink = true,
  });

  final AlbumRepository? repository;
  final AlbumAnalyzer? analyzer;

  /// false = 作为「动态」Tab 根页渲染：不出现「‹ 生活」返回链接。
  final bool showBackLink;

  @override
  ConsumerState<AlbumPage> createState() => _AlbumPageState();
}

enum _Phase { permissionPending, denied, loading, ready, loadFailed }

class _AlbumPageState extends ConsumerState<AlbumPage> {
  late final AlbumRepository _repo = widget.repository ?? AlbumRepository();
  late final AlbumAnalyzer _analyzer =
      widget.analyzer ?? const AlbumAnalyzer();
  _Phase _phase = _Phase.permissionPending;
  bool _cancelled = false;
  bool _analyzing = false;
  bool _analysisSkipped = false;
  double _progress = 0;
  int _totalCount = 0;
  List<AlbumBucket> _buckets = [];
  List<PhotoAsset> _recent = [];
  Map<String, ImageProvider?> _covers = {};
  List<ImageProvider?> _recentThumbs = [];
  AlbumAnalysisResult? _result;

  @override
  void initState() {
    super.initState();
    _begin();
  }

  Future<void> _begin() async {
    setState(() => _phase = _Phase.loading);
    final permission = await _repo.requestAccess();
    if (!mounted) return;
    if (permission == AlbumPermissionStatus.denied) {
      ref.read(albumSummaryProvider.notifier).update(
            const AlbumSummary(authorized: false, totalCount: null),
          );
      setState(() {
        _phase = _Phase.denied;
        _analyzing = false;
      });
      return;
    }
    await _load();
  }

  Future<void> _load() async {
    setState(() => _phase = _Phase.loading);
    try {
      await _loadGallery();
      if (!mounted) return;
      setState(() => _phase = _Phase.ready);
      unawaited(_runAnalysis());
    } catch (_) {
      if (!mounted) return;
      setState(() => _phase = _Phase.loadFailed);
    }
  }

  /// 相簿 / 最近添加 / 计数的轻量重载：子页（管理、删除）返回后调用，
  /// 不重跑整理分析（分析是否重扫由 TTL 决定）。
  Future<void> _loadGallery() async {
    final buckets = await _repo.buckets();
    final recent = await _repo.assets(start: 0, limit: 6);
    final covers = <String, ImageProvider?>{};
    final thumbs = <ImageProvider?>[];
    for (final bucket in buckets) {
      try {
        covers[bucket.id] = await _repo.source.coverProvider(bucket);
      } catch (_) {
        covers[bucket.id] = null;
      }
    }
    for (final asset in recent.items) {
      try {
        thumbs.add(await _repo.source.thumbnailProvider(asset));
      } catch (_) {
        thumbs.add(null);
      }
    }
    if (!mounted) return;
    setState(() {
      _buckets = buckets;
      _recent = recent.items;
      _covers = covers;
      _recentThumbs = thumbs;
      _totalCount = recent.total;
    });
    ref.read(albumSummaryProvider.notifier).update(
          AlbumSummary(authorized: true, totalCount: recent.total),
        );
  }

  /// 分析只读本机元数据；任何失败都呈「无建议」诚实态，不伪装成权限问题。
  Future<void> _runAnalysis() async {
    try {
      if (await _repo.analysisScanFresh()) {
        if (!mounted) return;
        setState(() {
          _analyzing = false;
          _analysisSkipped = true;
        });
        return;
      }
      setState(() {
        _analyzing = true;
        _cancelled = false;
        _progress = 0;
        _analysisSkipped = false;
      });
      final snapshots = await _repo.scanSnapshots(
        onProgress: (scanned, total) {
          if (total > 0 && mounted) {
            setState(() => _progress = scanned / total);
          }
        },
        isCancelled: () => _cancelled,
      );
      if (snapshots == null) {
        if (!mounted) return;
        setState(() => _analyzing = false);
        return;
      }
      final result = await _analyzer.analyze(
        snapshots,
        isCancelled: () => _cancelled,
      );
      if (!mounted) return;
      setState(() {
        _result = result;
        _analyzing = false;
      });
    } catch (_) {
      if (!mounted) return;
      setState(() => _analyzing = false);
    }
  }

  void _stopAnalysis() {
    _cancelled = true;
  }

  /// 子页返回即刷新（对照 ledger_page 的 push+reload 口径）：
  /// 管理页删除/移动、详情页变动后，网格与计数不能再停在旧数据。
  Future<void> _pushThenRefresh(String location) async {
    await context.push(location);
    if (!mounted) return;
    try {
      await _loadGallery();
    } catch (_) {
      if (!mounted) return;
      setState(() => _phase = _Phase.loadFailed);
    }
  }

  int get _cleanableCount {
    final result = _result;
    if (result == null) return 0;
    return result.sections.fold<int>(
      0,
      (sum, section) =>
          section.supported && section.suggestion != null
              ? sum + section.suggestion!.count
              : sum,
    );
  }

  int get _cleanableBytes {
    final result = _result;
    if (result == null) return 0;
    return result.sections.fold<int>(
      0,
      (sum, section) =>
          section.supported && section.suggestion != null
              ? sum + section.suggestion!.totalBytes
              : sum,
    );
  }

  int get _screenshotCleanable {
    final result = _result;
    if (result == null) return 0;
    final section = result.section(AlbumSuggestionKind.expiredScreenshots);
    return section?.suggestion?.count ?? 0;
  }

  String get _recentMonth {
    if (_recent.isEmpty) return '';
    final taken = _recent.first.takenAt;
    return '${taken.month} 月';
  }

  @override
  Widget build(BuildContext context) {
    final colors = context.colors;
    final type = context.typography;
    switch (_phase) {
      case _Phase.permissionPending:
      case _Phase.loading:
        return Scaffold(
          backgroundColor: colors.canvas,
          body: const SafeArea(child: SkeletonCard()),
        );
      case _Phase.denied:
        return Scaffold(
          backgroundColor: colors.canvas,
          body: SafeArea(
            child: ListView(
              padding: const EdgeInsets.all(18),
              children: [
                if (widget.showBackLink) BackLink(label: '生活'),
                const SizedBox(height: 40),
                EmptyState(
                  message: '还没有相册访问权限。授权后，整理建议只在本机计算，照片不会上传服务器。',
                  actionLabel: '去开启权限',
                  onAction: _begin,
                ),
                TextButton(
                  onPressed: _repo.openSystemSettings,
                  child: Text(
                    '没弹窗？到系统设置手动开启',
                    style: type.caption.copyWith(color: colors.ink2),
                  ),
                ),
              ],
            ),
          ),
        );
      case _Phase.loadFailed:
        return Scaffold(
          backgroundColor: colors.canvas,
          body: SafeArea(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.stretch,
              children: [
                if (widget.showBackLink)
                  const Padding(
                    padding: EdgeInsets.fromLTRB(18, 12, 18, 0),
                    child: BackLink(label: '生活'),
                  ),
                Expanded(
                  child: ErrorState(
                    message: '相册加载失败，照片读取出了点问题',
                    onRetry: _load,
                  ),
                ),
              ],
            ),
          ),
        );
      case _Phase.ready:
        return _readyPage(context);
    }
  }

  Widget _readyPage(BuildContext context) {
    final colors = context.colors;
    final type = context.typography;
    final recentMonth = _recentMonth;
    return Scaffold(
      backgroundColor: colors.canvas,
      body: SafeArea(
        child: ListView(
          padding: context.spacing.screenPadding.copyWith(bottom: 40),
          children: [
            if (widget.showBackLink) BackLink(label: '生活'),
            const SizedBox(height: 10),
            Text('相册', style: type.pageTitle),
            Text(
              '只存在这台手机上，不会上传服务器',
              style: type.caption.copyWith(fontSize: 13, color: colors.ink2),
            ),
            const SizedBox(height: 14),
            AiCard(
              title: '亚丝娜的整理建议',
              actionLabel: '看看我发现了什么 →',
              onAction: () => context.push('/album/ai'),
              child: _analysisBody(context),
            ),
            const SizedBox(height: 14),
            StorageCard(assetCount: _totalCount),
            const SizedBox(height: 18),
            _SectionTitle(
              title: '分类相簿',
              hint: '${_buckets.length} 个 · 在本机自动归类',
            ),
            const SizedBox(height: 10),
            _bucketGrid(context),
            const SizedBox(height: 18),
            _SectionTitle(title: '最近添加', hint: recentMonth),
            const SizedBox(height: 10),
            _recentGrid(context),
            const SizedBox(height: 16),
            _secondaryButton(
              context,
              label: '批量管理照片',
              onTap: () => _pushThenRefresh('/album/manage'),
            ),
            const SizedBox(height: 14),
            PrivacyNote(
              child: Text(
                '相册功能无需联网即可使用，照片不会上传服务器；'
                '删除的照片进系统「最近删除」，30 天内可恢复。',
              ),
            ),
          ],
        ),
      ),
    );
  }

  Widget _analysisBody(BuildContext context) {
    final colors = context.colors;
    final type = context.typography;
    if (_analysisSkipped) {
      return Text(
        '最近已经分析过，先不重复扫描；想重新看建议去「整理建议」页。',
        style: type.body.copyWith(color: colors.ink2),
      );
    }
    if (_analyzing) {
      return Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(
            '正在本机扫描…${(_progress * 100).round()}%',
            style: type.body.copyWith(color: colors.ink2),
          ),
          const SizedBox(height: 8),
          Row(
            children: [
              Expanded(
                child: ClipRRect(
                  borderRadius: BorderRadius.circular(999),
                  child: LinearProgressIndicator(
                    value: _progress,
                    minHeight: 6,
                    backgroundColor: colors.trackBar,
                    valueColor: AlwaysStoppedAnimation(colors.aiPrimary),
                  ),
                ),
              ),
              TextButton(
                onPressed: _stopAnalysis,
                child: Text(
                  '停止',
                  style: type.caption.copyWith(
                    fontWeight: FontWeight.w600,
                    color: colors.ink2,
                  ),
                ),
              ),
            ],
          ),
        ],
      );
    }
    final cleanable = _cleanableCount;
    if (cleanable == 0 && _result != null) {
      return Text(
        '我还没发现可以清理的内容；分析全部在你手机上完成，照片不会离开设备。',
        style: type.body.copyWith(color: colors.ink2),
      );
    }
    final sizeText = _cleanableBytes >= 1024 * 1024
        ? '${(_cleanableBytes / (1024 * 1024)).toStringAsFixed(1)} GB'
        : '${(_cleanableBytes / 1024).round()} MB';
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text(
          '$cleanable 张可清理，腾出 $sizeText',
          style: type.body.copyWith(fontWeight: FontWeight.w600),
        ),
        const SizedBox(height: 4),
        Text(
          '分析全部在你手机上完成，照片不会离开设备',
          style: type.caption.copyWith(fontSize: 11.5, color: colors.ink3),
        ),
      ],
    );
  }

  Widget _bucketGrid(BuildContext context) {
    final colors = context.colors;
    if (_buckets.isEmpty) {
      return Text(
        '相簿内容会在这里出现',
        style: context.typography.caption.copyWith(color: colors.ink3),
      );
    }
    return GridView.builder(
      shrinkWrap: true,
      physics: const NeverScrollableScrollPhysics(),
      gridDelegate: const SliverGridDelegateWithFixedCrossAxisCount(
        crossAxisCount: AlbumTile.gridCrossAxisCount,
        crossAxisSpacing: AlbumTile.gridSpacing,
        mainAxisSpacing: AlbumTile.gridSpacing,
        childAspectRatio: 1.08,
      ),
      itemCount: _buckets.length,
      itemBuilder: (context, index) {
        final bucket = _buckets[index];
        final isScreenshotBucket =
            bucket.name.toLowerCase().contains('screenshot');
        final countText = isScreenshotBucket && _screenshotCleanable > 0
            ? '${bucket.assetCount} 张 · $_screenshotCleanable 张可清理'
            : '${bucket.assetCount} 张';
        return AlbumTile(
          thumbnail: _covers[bucket.id],
          name: bucket.name,
          countText: countText,
          onTap: () => _pushThenRefresh(
            '/album/detail?album=${Uri.encodeComponent(bucket.id)}'
            '&name=${Uri.encodeComponent(bucket.name)}',
          ),
        );
      },
    );
  }

  Widget _recentGrid(BuildContext context) {
    final colors = context.colors;
    if (_recent.isEmpty) {
      return Text(
        '还没有照片；拍下第一张后这里会出现最近添加',
        style: context.typography.caption.copyWith(color: colors.ink3),
      );
    }
    return GridView.builder(
      shrinkWrap: true,
      physics: const NeverScrollableScrollPhysics(),
      gridDelegate: const SliverGridDelegateWithFixedCrossAxisCount(
        crossAxisCount: PhotoTile.gridCrossAxisCount,
        crossAxisSpacing: PhotoTile.gridSpacing,
        mainAxisSpacing: PhotoTile.gridSpacing,
        childAspectRatio: 1,
      ),
      itemCount: _recent.length,
      itemBuilder: (context, index) {
        final asset = _recent[index];
        return PhotoTile(
          thumbnail:
              _recentThumbs.length > index ? _recentThumbs[index] : null,
          durationText: asset.duration == null
              ? null
              : _formatDuration(asset.duration!),
          onTap: () =>
              _pushThenRefresh('/album/photo?id=${Uri.encodeComponent(asset.id)}'),
        );
      },
    );
  }

  String _formatDuration(Duration d) {
    final minutes = d.inMinutes.remainder(60).toString().padLeft(2, '0');
    final seconds = d.inSeconds.remainder(60).toString().padLeft(2, '0');
    return '$minutes:$seconds';
  }

  Widget _secondaryButton(
    BuildContext context, {
    required String label,
    required VoidCallback onTap,
  }) {
    final colors = context.colors;
    final type = context.typography;
    return GestureDetector(
      onTap: onTap,
      child: Container(
        width: double.infinity,
        padding: const EdgeInsets.symmetric(vertical: 13),
        decoration: BoxDecoration(
          color: colors.surface,
          borderRadius: BorderRadius.circular(999),
          border: Border.all(color: colors.line),
        ),
        child: Text(
          label,
          textAlign: TextAlign.center,
          style: type.caption.copyWith(
            fontSize: 13.5,
            fontWeight: FontWeight.w600,
          ),
        ),
      ),
    );
  }
}

class _SectionTitle extends StatelessWidget {
  const _SectionTitle({required this.title, required this.hint});

  final String title;
  final String hint;

  @override
  Widget build(BuildContext context) {
    final colors = context.colors;
    final type = context.typography;
    return Row(
      crossAxisAlignment: CrossAxisAlignment.end,
      children: [
        Text(title, style: type.sectionTitle),
        const Spacer(),
        Text(hint, style: type.caption.copyWith(fontSize: 11.5, color: colors.ink3)),
      ],
    );
  }
}
