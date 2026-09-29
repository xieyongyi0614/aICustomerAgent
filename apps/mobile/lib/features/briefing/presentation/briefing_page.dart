import 'package:flutter/material.dart';
import 'package:intl/intl.dart';

import '../../../app/theme/theme_context.dart';
import '../../../design_system/components/components.dart';
import '../../../design_system/orb/orb.dart';
import '../data/briefing_repository.dart';
import '../data/location_service.dart';

/// B9 #briefing：深色全屏，早间/晚间共用布局，按 type 切换文案与卡片。
///
/// 文案与卡片全部渲染自服务端（API-008 契约字段），端上不拼装结论文案；
/// 天气定位链：请求坐标（端侧实时定位）> 偏好城市 > 服务端兜底——
/// 已设偏好城市时不再带定位坐标（显式选择压过环境感知）。
class BriefingPage extends StatefulWidget {
  const BriefingPage({
    super.key,
    this.type = 'morning',
    this.repository,
    this.location,
    this.debugContent,
  });

  final String type; // morning | evening（深链 query，端上不按时刻推断）

  final BriefingRepository? repository;
  final LocationService? location;
  final BriefContentData? debugContent;

  @override
  State<BriefingPage> createState() => _BriefingPageState();
}

class _BriefingPageState extends State<BriefingPage> {
  static const _setCityHint = '按实时定位';
  static const _citySourceHint = '按城市';

  late final BriefingRepository _repo;
  late final LocationService _location;
  BriefContentData? _content;
  BriefPrefsData? _prefs;
  bool _fromCache = false;
  bool _loading = true;
  Object? _error;

  @override
  void initState() {
    super.initState();
    _repo = widget.repository ?? BriefingRepository();
    _location = widget.location ?? const LocationService();
    _initialLoad();
  }

  Future<void> _initialLoad() async {
    final debug = widget.debugContent;
    if (debug != null) {
      setState(() {
        _content = debug;
        _loading = false;
      });
      return;
    }
    final cached = await _repo.cachedBrief(widget.type);
    if (!mounted) return;
    if (cached != null) {
      setState(() {
        _content = cached;
        _fromCache = true;
        _loading = false;
      });
    }
    await _refresh();
  }

  Future<void> _refresh() async {
    try {
      final prefs = await _repo.fetchPrefs();
      final city = prefs.city?.trim() ?? '';
      final coords =
          city.isEmpty ? await _location.getCurrentCoords() : null;
      final content = await _repo.fetchBrief(
        widget.type,
        lat: coords?.lat,
        lon: coords?.lon,
      );
      if (!mounted) return;
      setState(() {
        _prefs = prefs;
        _content = content;
        _fromCache = false;
        _loading = false;
        _error = null;
      });
    } catch (e) {
      if (!mounted) return;
      setState(() {
        _error = e;
        _loading = false;
      });
    }
  }

  Future<void> _editCity() async {
    final controller = TextEditingController(text: _prefs?.city ?? '');
    final action = await showDialog<_CityAction>(
      context: context,
      builder: (dialogContext) => AlertDialog(
        title: const Text('天气定位'),
        content: TextField(
          controller: controller,
          decoration: const InputDecoration(
            labelText: '城市',
            hintText: '如：上海',
            helperText: '保存为空 = 清除城市，恢复实时定位',
          ),
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.of(dialogContext).pop(_CityAction.clear),
            child: const Text('清除'),
          ),
          TextButton(
            onPressed: () => Navigator.of(dialogContext).pop(_CityAction.save),
            child: const Text('保存'),
          ),
        ],
      ),
    );
    if (!mounted || action == null) return;
    final city = action == _CityAction.save ? controller.text.trim() : '';
    try {
      final prefs = await _repo.savePrefs(
        morningAt: _prefs?.morningAt,
        eveningAt: _prefs?.eveningAt,
        city: city.isEmpty ? null : city,
      );
      if (!mounted) return;
      setState(() => _prefs = prefs);
      await _refresh();
    } catch (_) {
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(content: Text('城市无法识别，换个写法试试')),
      );
    }
  }

  @override
  Widget build(BuildContext context) {
    final colors = context.colors;
    final type = context.typography;
    final content = _content;
    if (_loading && content == null) {
      return _BriefingScaffold(
        child: const Center(child: LoadingState()),
      );
    }
    if (_error != null && content == null) {
      return _BriefingScaffold(
        child: ErrorState(
          message: StateCopy.serverError,
          onRetry: _refresh,
        ),
      );
    }
    final cachedAtLabel = _fromCache ? _cachedAtLabel(content) : null;
    return _BriefingScaffold(
      child: ListView(
        padding: const EdgeInsets.fromLTRB(18, 8, 18, 32),
        children: [
          BackLink(
            label: '‹ 返回首页',
            onDark: true,
            onTap: () => Navigator.of(context).maybePop(),
          ),
          Text(
            content!.greeting,
            style: type.caption.copyWith(color: colors.onDeepTertiary),
          ),
          const SizedBox(height: 8),
          Text(
            content.title,
            style: type.briefTitle.copyWith(color: colors.onDeepPrimary),
          ),
          if (cachedAtLabel != null) ...[
            const SizedBox(height: 6),
            Text(
              cachedAtLabel,
              style: type.caption.copyWith(color: colors.onDeepTertiary),
            ),
          ],
          const SizedBox(height: 18),
          const Center(child: Orb(size: OrbSize.md)),
          const SizedBox(height: 12),
          Text(
            content.orbNote,
            textAlign: TextAlign.center,
            style: type.body.copyWith(color: colors.onDeepSecondary),
          ),
          const SizedBox(height: 20),
          for (final c in content.cards) ...[
            _BriefCard(
              title: c.title,
              body: c.body,
              note: c.note ?? '',
            ),
            const SizedBox(height: 12),
          ],
          const SizedBox(height: 8),
          SizedBox(
            width: double.infinity,
            child: Material(
              color: colors.surface,
              borderRadius: context.radii.rFull,
              child: InkWell(
                borderRadius: context.radii.rFull,
                onTap: () => Navigator.of(context).maybePop(),
                child: Padding(
                  padding: const EdgeInsets.symmetric(vertical: 15),
                  child: Text(
                    content.cta,
                    textAlign: TextAlign.center,
                    style: type.rowTitle.copyWith(
                      color: colors.onWhitePill,
                      fontSize: 15,
                      fontWeight: FontWeight.w700,
                    ),
                  ),
                ),
              ),
            ),
          ),
          const SizedBox(height: 10),
          Center(
            child: GestureDetector(
              behavior: HitTestBehavior.opaque,
              onTap: _editCity,
              child: Padding(
                padding: const EdgeInsets.symmetric(
                  vertical: 6,
                  horizontal: 10,
                ),
                child: Row(
                  mainAxisSize: MainAxisSize.min,
                  children: [
                    Icon(
                      AppIcons.slidersHorizontal,
                      size: 13,
                      color: colors.onDeepTertiary,
                    ),
                    const SizedBox(width: 5),
                    Text(
                      _cityEntryLabel,
                      style: type.caption.copyWith(
                        color: colors.onDeepTertiary,
                      ),
                    ),
                  ],
                ),
              ),
            ),
          ),
        ],
      ),
    );
  }

  String get _cityEntryLabel {
    final city = _prefs?.city?.trim() ?? '';
    final source = city.isEmpty
        ? _setCityHint
        : '$_citySourceHint：$city';
    return '天气$source · 点按设置';
  }

  String? _cachedAtLabel(BriefContentData? content) {
    final generatedAt = content?.generatedAt;
    if (generatedAt == null) return null;
    final at = DateTime.tryParse(generatedAt);
    if (at == null) return null;
    final formatted = DateFormat('MM-dd HH:mm').format(at);
    return '离线内容 · 数据时间 $formatted';
  }
}

enum _CityAction { save, clear }

/// deepBrief 全屏容器：无 Tab 栏（壳层 chrome 控制），文字白。
class _BriefingScaffold extends StatelessWidget {
  const _BriefingScaffold({required this.child});

  final Widget child;

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      body: DecoratedBox(
        decoration: BoxDecoration(gradient: context.gradients.deepBrief),
        child: SafeArea(child: child),
      ),
    );
  }
}

/// A29 b-card：底白 .09 / 边白 .14 / rMd / 内边距 15/16。
class _BriefCard extends StatelessWidget {
  const _BriefCard({
    required this.title,
    required this.body,
    required this.note,
  });

  final String title;
  final String body;
  final String note;

  @override
  Widget build(BuildContext context) {
    final colors = context.colors;
    final type = context.typography;
    return Container(
      padding: const EdgeInsets.symmetric(vertical: 15, horizontal: 16),
      decoration: BoxDecoration(
        color: colors.surface.withValues(alpha: 0.08),
        borderRadius: context.radii.rMd,
        border:
            Border.all(color: colors.onDeepSecondary.withValues(alpha: 0.12)),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(title,
              style: type.label
                  .copyWith(color: colors.onDeepTertiary, fontSize: 11.5)),
          const SizedBox(height: 6),
          Text(body,
              style: type.rowTitle
                  .copyWith(color: colors.onDeepPrimary, height: 1.5)),
          if (note.isNotEmpty) ...[
            const SizedBox(height: 4),
            Text(note,
                style: type.caption
                    .copyWith(color: colors.onDeepSecondary, fontSize: 11)),
          ],
        ],
      ),
    );
  }
}
