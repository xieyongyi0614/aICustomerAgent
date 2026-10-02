import 'package:flutter/material.dart';
import 'package:go_router/go_router.dart';

import '../../../app/theme/theme_context.dart';
import '../../../design_system/components/components.dart';
import '../data/album_analysis.dart';
import '../data/album_repository.dart';
import '../domain/album_models.dart';

/// B17 #albumAI AI 整理建议详情：先体量、再理由、最后原则。
///
/// 相似连拍独立呈未支持态（D16），不计入任何合计；四条整理原则第 4 条
/// 「你的推翻我会记住」由 album 域本地存储真实支撑。
class AlbumAiPage extends StatefulWidget {
  const AlbumAiPage({super.key, this.repository, this.analyzer, this.result});

  final AlbumRepository? repository;
  final AlbumAnalyzer? analyzer;

  /// 测试注入：跳过扫描直接呈现该结果。
  final AlbumAnalysisResult? result;

  @override
  State<AlbumAiPage> createState() => _AlbumAiPageState();
}

class _AlbumAiPageState extends State<AlbumAiPage> {
  late final AlbumRepository _repo = widget.repository ?? AlbumRepository();
  late final AlbumAnalyzer _analyzer =
      widget.analyzer ?? const AlbumAnalyzer();
  AlbumAnalysisResult? _result;
  bool _loading = true;
  bool _cancelled = false;
  int _rememberedOverrides = 0;

  @override
  void initState() {
    super.initState();
    _begin();
  }

  Future<void> _begin() async {
    setState(() => _loading = true);
    final injected = widget.result;
    if (injected != null) {
      setState(() {
        _result = injected;
        _loading = false;
      });
      return;
    }
    final snapshots = await _repo.scanSnapshots(isCancelled: () => _cancelled);
    if (!mounted) return;
    if (snapshots == null) {
      setState(() {
        _loading = false;
        _cancelled = false;
      });
      return;
    }
    final result = await _analyzer.analyze(
      snapshots,
      isCancelled: () => _cancelled,
    );
    final overrides = await _repo.store.loadOverrides();
    if (!mounted) return;
    setState(() {
      _result = result;
      _rememberedOverrides = overrides.length;
      _loading = false;
    });
  }

  int get _totalCleanable {
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

  int get _totalBytes {
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

  @override
  Widget build(BuildContext context) {
    final colors = context.colors;
    final type = context.typography;
    final result = _result;
    if (_loading) {
      return Scaffold(
        backgroundColor: colors.canvas,
        body: SafeArea(
          child: ListView(
            padding: const EdgeInsets.all(18),
            children: const [SkeletonCard(), SkeletonCard()],
          ),
        ),
      );
    }
    final sizeText = _totalBytes >= 1024 * 1024
        ? '${(_totalBytes / (1024 * 1024)).toStringAsFixed(1)} GB'
        : '${(_totalBytes / 1024).round()} MB';
    return Scaffold(
      backgroundColor: colors.canvas,
      body: SafeArea(
        child: ListView(
          padding: context.spacing.screenPadding.copyWith(bottom: 40),
          children: [
            BackLink(label: '相册'),
            const SizedBox(height: 10),
            Text('整理建议', style: type.pageTitle),
            Text(
              '在你这台手机上扫完 · 本机分析',
              style: type.caption.copyWith(fontSize: 13, color: colors.ink2),
            ),
            const SizedBox(height: 14),
            AiCard(
              title: '亚丝娜的整理建议',
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(
                    '$_totalCleanable 张可清理（截图与重复），腾出 $sizeText',
                    style: type.body.copyWith(fontWeight: FontWeight.w600),
                  ),
                  const SizedBox(height: 4),
                  Text(
                    '我先替你预选好，删之前由你确认——我不会自己动手',
                    style: type.caption.copyWith(fontSize: 11.5, color: colors.ink3),
                  ),
                ],
              ),
            ),
            const SizedBox(height: 18),
            _SectionHead(title: '可清理的 $_totalCleanable 张', hint: '合计 $sizeText'),
            const SizedBox(height: 10),
            if (result != null) _supportedRows(context, result),
            const SizedBox(height: 18),
            if (result != null) _unsupportedRows(context, result),
            const SizedBox(height: 18),
            _SectionHead(title: '我的整理原则', hint: '一直这样'),
            const SizedBox(height: 10),
            _principles(context),
            const SizedBox(height: 16),
            _primaryButton(
              context,
              label: '看看这 $_totalCleanable 张，已帮你预选',
              onTap: () => context.push('/album/manage'),
            ),
            PrivacyNote(
              child: Text(
                '全部来自本机分析 · 相册功能无需联网即可使用 · 无云同步 · 随时可以停下',
              ),
            ),
          ],
        ),
      ),
    );
  }

  Widget _supportedRows(BuildContext context, AlbumAnalysisResult result) {
    final rows = <SuggestionRow>[];
    for (final section in result.sections) {
      final suggestion = section.suggestion;
      if (!section.supported || suggestion == null || suggestion.count == 0) {
        continue;
      }
      rows.add(
        SuggestionRow(
          icon: suggestion.kind == AlbumSuggestionKind.expiredScreenshots
              ? AppIcons.smartphone
              : AppIcons.copy,
          accent: suggestion.kind == AlbumSuggestionKind.expiredScreenshots
              ? context.colors.aiPrimary
              : context.colors.aiBlue,
          title: suggestion.kind == AlbumSuggestionKind.expiredScreenshots
              ? '过期截图'
              : '重复保存',
          reason: suggestion.reason,
          countText: '${suggestion.count} 张',
          sizeText: _sizeText(suggestion.totalBytes),
          onTap: () => context.push('/album/manage'),
        ),
      );
    }
    if (rows.isEmpty) {
      return Text(
        '目前没有可以清理的内容',
        style: context.typography.body.copyWith(color: context.colors.ink2),
      );
    }
    return SuggestionCard(rows: rows);
  }

  Widget _unsupportedRows(BuildContext context, AlbumAnalysisResult result) {
    final colors = context.colors;
    final type = context.typography;
    final unsupported = result.sections
        .where((s) => !s.supported)
        .map((s) => s.unsupportedReason ?? '')
        .where((reason) => reason.isNotEmpty)
        .toList();
    if (unsupported.isEmpty) return const SizedBox.shrink();
    return Container(
      padding: const EdgeInsets.all(16),
      decoration: BoxDecoration(
        color: colors.surface,
        borderRadius: context.radii.rMd,
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text('相似连拍 · 本期未开启', style: type.caption.copyWith(
            fontSize: 13.5,
            fontWeight: FontWeight.w600,
          )),
          const SizedBox(height: 4),
          for (final reason in unsupported)
            Text(
              reason,
              style: type.caption.copyWith(fontSize: 11.5, color: colors.ink3),
            ),
        ],
      ),
    );
  }

  Widget _principles(BuildContext context) {
    final colors = context.colors;
    final type = context.typography;
    String remembered = '你的推翻我会记住';
    if (_rememberedOverrides > 0) {
      remembered = '你的推翻我会记住（已记住 $_rememberedOverrides 条）';
    }
    final principles = [
      '只在本机算——分析全部在你手机上完成',
      '只预选不自动删——删之前由你确认',
      '删错了也能回来——系统「最近删除」保留 30 天',
      remembered,
    ];
    return Column(
      children: [
        for (var i = 0; i < principles.length; i++)
          Container(
            margin: const EdgeInsets.only(bottom: 8),
            padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 12),
            decoration: BoxDecoration(
              color: colors.surface,
              borderRadius: context.radii.rMd,
            ),
            child: Row(
              children: [
                Icon(AppIcons.shield, size: 14, color: colors.health),
                const SizedBox(width: 8),
                Expanded(
                  child: Text(
                    principles[i],
                    style: type.caption.copyWith(
                      fontSize: 12.5,
                      fontWeight: FontWeight.w600,
                    ),
                  ),
                ),
              ],
            ),
          ),
      ],
    );
  }

  String _sizeText(int bytes) {
    if (bytes >= 1024 * 1024) {
      return '${(bytes / (1024 * 1024)).toStringAsFixed(1)} GB';
    }
    return '${(bytes / 1024).round()} MB';
  }

  Widget _primaryButton(
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
        padding: const EdgeInsets.symmetric(vertical: 14),
        decoration: BoxDecoration(
          color: colors.ink,
          borderRadius: BorderRadius.circular(999),
        ),
        child: Text(
          label,
          textAlign: TextAlign.center,
          style: type.caption.copyWith(
            fontSize: 13.5,
            fontWeight: FontWeight.w700,
            color: colors.canvas,
          ),
        ),
      ),
    );
  }
}

class _SectionHead extends StatelessWidget {
  const _SectionHead({required this.title, required this.hint});

  final String title;
  final String hint;

  @override
  Widget build(BuildContext context) {
    final colors = context.colors;
    final type = context.typography;
    return Row(
      crossAxisAlignment: CrossAxisAlignment.end,
      children: [
        Text(title, style: type.sectionTitle.copyWith(fontSize: 15)),
        const Spacer(),
        Text(hint, style: type.caption.copyWith(fontSize: 11.5, color: colors.ink3)),
      ],
    );
  }
}
