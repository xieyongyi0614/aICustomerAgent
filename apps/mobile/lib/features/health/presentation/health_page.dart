import 'package:flutter/material.dart';
import 'package:go_router/go_router.dart';

import '../../../app/theme/theme_context.dart';
import '../../../design_system/components/components.dart';
import '../data/health_repository.dart';

/// APP-024 / B6 健康页：AI 状态解读优先 → 睡眠趋势 → 今日指标 → 来源声明，
/// 并在任意滚动位置常驻「非医疗建议」免责（红线 8）。
///
/// 健康域当前是 **M4 门控空读面**（`/health/score` 的 `authorized` 恒为 false）：
/// 没有真实数据时只出诚实空态，**不编造**评分、睡眠时长或步数。
class HealthPage extends StatefulWidget {
  const HealthPage({super.key, this.repository});

  final HealthRepository? repository;

  static const disclaimer = '非医疗建议，请咨询医生';

  @override
  State<HealthPage> createState() => _HealthPageState();
}

class _HealthPageState extends State<HealthPage> {
  late final HealthRepository _repo = widget.repository ?? HealthRepository();
  HealthScoreData? _score;
  bool _loading = true;

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    try {
      final score = await _repo.fetchScore();
      if (!mounted) return;
      setState(() {
        _score = score;
        _loading = false;
      });
    } catch (_) {
      if (!mounted) return;
      setState(() {
        _score = null;
        _loading = false;
      });
    }
  }

  String get _heroTitle {
    if (_loading) return '正在读取';
    return _score?.hasInsight == true ? '亚丝娜的解读' : '还没有可解读的数据';
  }

  String get _heroBody {
    if (_loading) return '正在读取你授权的健康数据…';
    final narrative = _score?.narrative;
    if (_score?.hasInsight == true && narrative != null) return narrative;
    return '连接手环并授权后，我会在这里给出状态解读——只讲趋势，不做诊断。';
  }

  String? get _heroTag {
    final score = _score;
    if (score == null || !score.hasInsight) return null;
    return '综合 ${score.score} 分';
  }

  @override
  Widget build(BuildContext context) {
    final colors = context.colors;
    final type = context.typography;
    return Scaffold(
      backgroundColor: colors.canvas,
      body: SafeArea(
        child: Column(
          children: [
            Expanded(
              child: ListView(
                padding: const EdgeInsets.fromLTRB(18, 12, 18, 24),
                children: [
                  Text('健康', style: type.pageTitle),
                  const SizedBox(height: 4),
                  Text(
                    '不是数据，是亚丝娜对你的理解',
                    style: type.sub.copyWith(color: colors.ink2),
                  ),
                  const SizedBox(height: 16),
                  InsightHero(
                    title: _heroTitle,
                    body: _heroBody,
                    tag: _heroTag,
                  ),
                  const SizedBox(height: 24),
                  _SectionTitle(title: '睡眠趋势', hint: '近 7 天'),
                  const SizedBox(height: 10),
                  const _EmptySection(
                    hint: '连接手环后，这里会显示近 7 天的睡眠时长趋势',
                  ),
                  const SizedBox(height: 24),
                  const _SectionTitle(title: '今日指标'),
                  const SizedBox(height: 10),
                  const _EmptySection(
                    hint: '连接手环后，这里会显示静息心率、步数与今日运动',
                  ),
                  if (_score?.authorized == true) ...[
                    const SizedBox(height: 18),
                    SourceNote(text: '数据来自已授权的设备 · 已授权同步'),
                  ],
                  const SizedBox(height: 18),
                  FilledButton.tonal(
                    onPressed: () => context.go('/health/consent'),
                    child: const Text('健康数据授权'),
                  ),
                  const SizedBox(height: 8),
                  TextButton(
                    onPressed: () => context.go('/health/probe'),
                    child: const Text('PLT-001 手环数据探针（验证工具）'),
                  ),
                ],
              ),
            ),
            // 常驻免责：任意滚动位置均可见（红线 8 / APP-024 AC2）
            Container(
              width: double.infinity,
              padding: const EdgeInsets.fromLTRB(18, 10, 18, 12),
              decoration: BoxDecoration(
                color: colors.surface,
                border: Border(top: BorderSide(color: colors.line)),
              ),
              child: Text(
                _score?.disclaimer ?? HealthPage.disclaimer,
                textAlign: TextAlign.center,
                style: type.caption.copyWith(color: colors.ink3),
              ),
            ),
          ],
        ),
      ),
    );
  }
}

class _SectionTitle extends StatelessWidget {
  const _SectionTitle({required this.title, this.hint});

  final String title;
  final String? hint;

  @override
  Widget build(BuildContext context) {
    final colors = context.colors;
    final type = context.typography;
    return Row(
      children: [
        Text(title, style: type.sectionTitle),
        const Spacer(),
        if (hint != null)
          Text(hint!, style: type.caption.copyWith(color: colors.ink3)),
      ],
    );
  }
}

/// 无数据时的诚实空态：只说明「有数据后会显示什么」，不出任何数值。
class _EmptySection extends StatelessWidget {
  const _EmptySection({required this.hint});

  final String hint;

  @override
  Widget build(BuildContext context) {
    final colors = context.colors;
    final type = context.typography;
    return AppCard(
      child: Text(hint, style: type.body.copyWith(color: colors.ink2)),
    );
  }
}
