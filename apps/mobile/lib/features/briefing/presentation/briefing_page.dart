import 'package:flutter/material.dart';

import '../../../app/theme/theme_context.dart';
import '../../../design_system/components/components.dart';
import '../../../design_system/components/rows.dart';
import '../../../design_system/orb/orb.dart';
import '../data/brief_repository.dart';

/// B9 #briefing：深色全屏，早间/晚间共用布局，按 form 切换文案与卡片。
class BriefingPage extends StatefulWidget {
  const BriefingPage({super.key, this.form = 'morning'});

  final String form;

  @override
  State<BriefingPage> createState() => _BriefingPageState();
}

class _BriefingPageState extends State<BriefingPage> {
  final _repo = BriefRepository();
  BriefContentData? _data;
  bool _loading = true;
  Object? _error;

  bool get isEvening => widget.form == 'evening';

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    setState(() {
      _loading = true;
      _error = null;
    });
    try {
      final data = await _repo.fetchBrief(widget.form);
      if (!mounted) return;
      setState(() {
        _data = data;
        _loading = false;
      });
    } catch (e) {
      if (!mounted) return;
      setState(() {
        _error = e;
        _loading = false;
      });
    }
  }

  @override
  Widget build(BuildContext context) {
    final colors = context.colors;
    final type = context.typography;
    if (_loading && _data == null) {
      return Scaffold(
        body: DecoratedBox(
          decoration: BoxDecoration(gradient: context.gradients.deepBrief),
          child: const SafeArea(child: Center(child: LoadingState())),
        ),
      );
    }
    if (_error != null && _data == null) {
      return Scaffold(
        body: DecoratedBox(
          decoration: BoxDecoration(gradient: context.gradients.deepBrief),
          child: SafeArea(
            child: ErrorState(
              message: StateCopy.serverError,
              onRetry: _load,
            ),
          ),
        ),
      );
    }
    final d = _data!;
    return Scaffold(
      body: DecoratedBox(
        decoration: BoxDecoration(gradient: context.gradients.deepBrief),
        child: SafeArea(
          child: ListView(
            padding: const EdgeInsets.fromLTRB(18, 8, 18, 32),
            children: [
              BackLink(
                label: '‹ 返回首页',
                onDark: true,
                onTap: () => Navigator.of(context).maybePop(),
              ),
              Text(
                d.eyebrow,
                style: type.caption.copyWith(color: colors.onDeepTertiary),
              ),
              const SizedBox(height: 8),
              Text(
                d.headline,
                style: type.briefTitle.copyWith(color: colors.onDeepPrimary),
              ),
              const SizedBox(height: 18),
              const Center(child: Orb(size: OrbSize.md)),
              const SizedBox(height: 12),
              Text(
                d.orbLine,
                textAlign: TextAlign.center,
                style: type.body.copyWith(color: colors.onDeepSecondary),
              ),
              const SizedBox(height: 20),
              for (final c in d.cards) ...[
                _BriefCard(
                  title: c.title,
                  body: c.body,
                  note: c.note ?? '',
                ),
                const SizedBox(height: 12),
              ],
              const SizedBox(height: 8),
              Center(
                child: GestureDetector(
                  onTap: () => Navigator.of(context).maybePop(),
                  child: Container(
                    padding: const EdgeInsets.symmetric(
                        vertical: 12, horizontal: 28),
                    decoration: BoxDecoration(
                      color: colors.surface,
                      borderRadius: context.radii.rFull,
                    ),
                    child: Text(
                      d.footer,
                      style: type.rowTitle.copyWith(color: colors.onWhitePill),
                    ),
                  ),
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }
}

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
