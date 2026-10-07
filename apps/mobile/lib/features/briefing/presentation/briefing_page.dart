import 'dart:async';

import 'package:flutter/material.dart';
import 'package:go_router/go_router.dart';
import 'package:intl/intl.dart';

import '../../../app/theme/theme_context.dart';
import '../../../core/location/location_service.dart';
import '../../../design_system/components/components.dart';
import '../../../design_system/orb/orb.dart';
import '../data/briefing_repository.dart';
import '../data/cities.dart';

/// B9 #briefing：深色全屏，早间/晚间共用布局，按 type 切换文案与卡片。
///
/// 文案与卡片全部渲染自服务端（API-008 契约字段），端上不拼装结论文案；
/// 天气定位链（服务端）：偏好城市 > 请求坐标 > 默认北京——
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
  late final BriefingRepository _repo;
  late final LocationService _location;
  BriefContentData? _content;
  BriefPrefsData? _prefs;
  List<BriefingCity>? _cities;
  bool _fromCache = false;
  bool _usedCoords = false;
  bool _loading = true;
  Object? _error;

  @override
  void initState() {
    super.initState();
    _repo = widget.repository ?? BriefingRepository();
    _location = widget.location ?? const LocationService();
    _initialLoad();
    _loadCities();
  }

  /// 城市目录用于切城面板与已存名回显；资产读取失败不阻塞页面主体。
  Future<void> _loadCities() async {
    try {
      final cities = await loadBriefingCities();
      if (!mounted) return;
      setState(() => _cities = cities);
    } catch (_) {
      // 加载失败时切城面板回退自由输入
    }
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

  Future<void> _refresh({BriefPrefsData? prefs}) async {
    try {
      // 偏好与定位并行取（定位上限 3s），串行等待是进页慢的主因；
      // 设了城市就用不到坐标（显式选择压过环境感知）。
      final coordsFuture = _location.getCurrentCoords(
        timeLimit: const Duration(seconds: 3),
      );
      final effectivePrefs = prefs ?? await _repo.fetchPrefs();
      final city = effectivePrefs.city?.trim() ?? '';
      CoordPair? coords;
      if (city.isEmpty) {
        coords = await coordsFuture;
      } else {
        unawaited(coordsFuture);
      }
      final content = await _repo.fetchBrief(
        widget.type,
        lat: coords?.lat,
        lon: coords?.lon,
      );
      if (!mounted) return;
      setState(() {
        _prefs = effectivePrefs;
        _usedCoords = coords != null;
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
    final currentCity = _prefs?.city?.trim() ?? '';
    final cities = _cities ?? await loadBriefingCities();
    final picked = await showChoiceSheet<String>(
      context: context,
      title: '天气城市',
      items: [
        const ChoiceSheetItem(
          value: '',
          label: '使用实时定位',
          note: '清除已存城市，跟随当前位置',
        ),
        for (final city in cities)
          ChoiceSheetItem(
            value: city.saveAs ?? city.name,
            label: city.name,
            group: city.region,
          ),
      ],
      selected: currentCity.isEmpty ? '' : currentCity,
      searchable: true,
      searchHint: '搜索城市',
      freeTextBuilder: (query) => query,
    );
    if (!mounted || picked == null) return;
    try {
      final prefs = await _repo.savePrefs(
        morningAt: _prefs?.morningAt,
        eveningAt: _prefs?.eveningAt,
        city: picked.isEmpty ? null : picked,
      );
      if (!mounted) return;
      setState(() => _prefs = prefs);
      // PUT 响应即最新偏好，直接复用，不再 GET preferences。
      await _refresh(prefs: prefs);
    } catch (_) {
      if (!mounted) return;
      ScaffoldMessenger.of(context)
          .showSnackBar(const SnackBar(content: Text('城市无法识别，换个写法试试')));
    }
  }

  @override
  Widget build(BuildContext context) {
    final colors = context.colors;
    final type = context.typography;
    final content = _content;
    if (_loading && content == null) {
      return _BriefingScaffold(child: const Center(child: LoadingState()));
    }
    if (_error != null && content == null) {
      return _BriefingScaffold(
        child: ErrorState(message: StateCopy.serverError, onRetry: () => _refresh()),
      );
    }
    final cachedAtLabel = _fromCache ? _cachedAtLabel(content) : null;
    return _BriefingScaffold(
      child: ListView(
        padding: const EdgeInsets.fromLTRB(18, 8, 18, 32),
        children: [
          BackLink(
            label: '返回首页',
            onDark: true,
            onTap: () => context.go('/home'),
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
              trailingValue: c.title == '天气' ? _cityValueLabel : null,
              onTap: c.title == '天气' ? _editCity : null,
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
                onTap: () => context.go('/home'),
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
        ],
      ),
    );
  }

  String get _cityValueLabel {
    final city = _prefs?.city?.trim() ?? '';
    if (city.isEmpty) return _usedCoords ? '实时定位' : '默认北京';
    final cities = _cities;
    if (cities == null) return city;
    return briefingCityDisplayName(cities, city) ?? city;
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
///
/// [trailingValue] 给出时标题行尾展示该值（天气卡的当前城市来源），
/// [onTap] 让整卡可点（天气卡 = 天气城市切换入口）。
class _BriefCard extends StatelessWidget {
  const _BriefCard({
    required this.title,
    required this.body,
    required this.note,
    this.trailingValue,
    this.onTap,
  });

  final String title;
  final String body;
  final String note;
  final String? trailingValue;
  final VoidCallback? onTap;

  @override
  Widget build(BuildContext context) {
    final colors = context.colors;
    final type = context.typography;
    return Material(
      color: colors.surface.withValues(alpha: 0.08),
      borderRadius: context.radii.rMd,
      child: InkWell(
        borderRadius: context.radii.rMd,
        onTap: onTap,
        child: Container(
          padding: const EdgeInsets.symmetric(vertical: 15, horizontal: 16),
          decoration: BoxDecoration(
            borderRadius: context.radii.rMd,
            border: Border.all(
              color: colors.onDeepSecondary.withValues(alpha: 0.12),
            ),
          ),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Row(
                children: [
                  Text(
                    title,
                    style: type.label.copyWith(
                      color: colors.onDeepTertiary,
                      fontSize: 11.5,
                    ),
                  ),
                  if (trailingValue != null) ...[
                    const Spacer(),
                    Text(
                      trailingValue!,
                      style: type.caption.copyWith(
                        color: colors.onDeepTertiary,
                        fontSize: 11.5,
                      ),
                    ),
                    const SizedBox(width: 4),
                    Icon(
                      AppIcons.chevronRight,
                      size: 12,
                      color: colors.onDeepTertiary,
                    ),
                  ],
                ],
              ),
              const SizedBox(height: 6),
              Text(
                body,
                style: type.rowTitle.copyWith(
                  color: colors.onDeepPrimary,
                  height: 1.5,
                ),
              ),
              if (note.isNotEmpty) ...[
                const SizedBox(height: 4),
                Text(
                  note,
                  style: type.caption.copyWith(
                    color: colors.onDeepSecondary,
                    fontSize: 11,
                  ),
                ),
              ],
            ],
          ),
        ),
      ),
    );
  }
}
