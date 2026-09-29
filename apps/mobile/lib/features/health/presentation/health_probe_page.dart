import 'package:flutter/material.dart';
import 'package:flutter/services.dart';

import '../../../app/theme/theme_context.dart';
import '../../../design_system/components/cards.dart';
import '../data/health_connect_probe.dart';

/// PLT-001 手环实机验证探针页：采集 P1/P2/P3 证据并生成报告草稿（验证工具，非产品链路）。
class HealthProbePage extends StatefulWidget {
  const HealthProbePage({super.key});

  @override
  State<HealthProbePage> createState() => _HealthProbePageState();
}

class _HealthProbePageState extends State<HealthProbePage> {
  final _probe = HealthConnectProbe();
  final _latencySamples = <LatencySample>[];

  bool _busy = false;
  bool? _healthConnectAvailable;
  ProbeSnapshot? _snapshot;
  ProbeTypeSpec _latencySpec = probeTypeSpecs.first;

  @override
  void initState() {
    super.initState();
    _checkAvailability();
  }

  Future<void> _checkAvailability() async {
    try {
      final available = await _probe.healthConnectAvailable();
      if (!mounted) return;
      setState(() => _healthConnectAvailable = available);
    } catch (_) {
      if (!mounted) return;
      setState(() => _healthConnectAvailable = false);
    }
  }

  Future<void> _requestAndRead() async {
    setState(() => _busy = true);
    try {
      final granted = await _probe.requestAuthorization();
      if (!granted) {
        _toast('授权未完成：请在 Health Connect 中允许后重试');
        return;
      }
      final snapshot = await _probe.readSnapshot();
      if (!mounted) return;
      setState(() => _snapshot = snapshot);
    } catch (error) {
      _toast('读取失败：$error');
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  Future<void> _sampleLatency() async {
    setState(() => _busy = true);
    try {
      final sample = await _probe.sampleLatest(_latencySpec);
      if (!mounted) return;
      if (sample == null) {
        _toast('近 24h 内没有「${_latencySpec.label}」数据，先在手环产生一条再采样');
        return;
      }
      setState(() => _latencySamples.add(sample));
    } catch (error) {
      _toast('采样失败：$error');
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  Future<void> _copyReport() async {
    final snapshot = _snapshot;
    if (snapshot == null) {
      _toast('先「申请权限并读取」再复制报告');
      return;
    }
    await Clipboard.setData(
      ClipboardData(text: probeReportText(snapshot, _latencySamples)),
    );
    _toast('报告草稿已复制，可粘贴到 phase0-miband-validation.md');
  }

  void _toast(String message) {
    if (!mounted) return;
    ScaffoldMessenger.of(context)
      ..hideCurrentSnackBar()
      ..showSnackBar(SnackBar(content: Text(message)));
  }

  @override
  Widget build(BuildContext context) {
    final colors = context.colors;
    final type = context.typography;
    return Scaffold(
      backgroundColor: colors.canvas,
      appBar: AppBar(title: const Text('手环数据探针（PLT-001）')),
      body: _busy
          ? const Center(child: CircularProgressIndicator())
          : ListView(
              padding: const EdgeInsets.fromLTRB(18, 8, 18, 40),
              children: [
                _availabilityCard(),
                const SizedBox(height: 12),
                Wrap(
                  spacing: 10,
                  runSpacing: 8,
                  children: [
                    FilledButton(
                      onPressed: _healthConnectAvailable == true
                          ? _requestAndRead
                          : null,
                      child: const Text('申请权限并读取近 7 天'),
                    ),
                    OutlinedButton(
                      onPressed: _snapshot == null ? null : _copyReport,
                      child: const Text('复制报告草稿'),
                    ),
                  ],
                ),
                const SizedBox(height: 16),
                if (_snapshot != null) ...[
                  _p1Card(),
                  const SizedBox(height: 12),
                  _fieldsCard(),
                  const SizedBox(height: 12),
                ],
                _latencyCard(),
                const SizedBox(height: 18),
                Text(
                  '非医疗建议，请咨询医生',
                  textAlign: TextAlign.center,
                  style: type.caption.copyWith(color: colors.ink3),
                ),
              ],
            ),
    );
  }

  Widget _availabilityCard() {
    final colors = context.colors;
    final type = context.typography;
    final available = _healthConnectAvailable;
    return AppCard(
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text('Health Connect 状态', style: type.sectionTitle),
          const SizedBox(height: 8),
          Text(
            switch (available) {
              null => '检查中…',
              true => '可用。继续「申请权限并读取近 7 天」。',
              false => '不可用。需在应用商店安装 / 更新 Health Connect（健康互联）。',
            },
            style: type.body.copyWith(color: colors.ink2),
          ),
          if (available == false)
            Padding(
              padding: const EdgeInsets.only(top: 10),
              child: OutlinedButton(
                onPressed: () => _probe.installHealthConnect(),
                child: const Text('前往安装 Health Connect'),
              ),
            ),
        ],
      ),
    );
  }

  Widget _p1Card() {
    final colors = context.colors;
    final type = context.typography;
    final snapshot = _snapshot!;
    return AppCard(
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text('P1 · 原生写入（探针证据）', style: type.sectionTitle),
          const SizedBox(height: 8),
          Text(
            snapshot.p1Evidence,
            style: type.body.copyWith(
              color: snapshot.miFitnessWritten ? colors.health : colors.ink2,
            ),
          ),
          if (snapshot.sourceIds.isNotEmpty)
            Padding(
              padding: const EdgeInsets.only(top: 10),
              child: Wrap(
                spacing: 8,
                runSpacing: 6,
                children: [
                  for (final source in snapshot.sourceIds)
                    Chip(
                      label: Text(
                        sourceDisplayName(source),
                        style: type.caption,
                      ),
                      visualDensity: VisualDensity.compact,
                    ),
                ],
              ),
            ),
        ],
      ),
    );
  }

  Widget _fieldsCard() {
    final colors = context.colors;
    final type = context.typography;
    final rows = _snapshot!.rows;
    return AppCard(
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text('P2 · 可读字段（近 ${_snapshot!.windowDays} 天）', style: type.sectionTitle),
          const SizedBox(height: 8),
          for (var i = 0; i < rows.length; i++) ...[
            if (i > 0) Divider(height: 1, color: colors.line),
            Padding(
              padding: const EdgeInsets.symmetric(vertical: 10),
              child: Row(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Icon(
                    rows[i].granted ? Icons.check_circle : Icons.cancel,
                    size: 16,
                    color: rows[i].granted ? colors.health : colors.ink3,
                  ),
                  const SizedBox(width: 8),
                  Expanded(
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Text(
                          '${rows[i].spec.label}（${rows[i].spec.unitHint}）',
                          style: type.body,
                        ),
                        const SizedBox(height: 2),
                        Text(
                          _rowDetail(rows[i]),
                          style: type.caption.copyWith(color: colors.ink3),
                        ),
                      ],
                    ),
                  ),
                ],
              ),
            ),
          ],
        ],
      ),
    );
  }

  String _rowDetail(ProbeRow row) {
    if (row.error != null) return '读取异常：${row.error}';
    if (!row.granted) return '未授权';
    if (!row.hasData) return '已授权，窗口内 0 条';
    return '${row.count} 条 · 最新 ${row.latestValueText} ${row.spec.unitHint} · '
        '${_formatTime(row.latest!.dateTo)} · 来源 ${row.sourceIds.map(sourceDisplayName).join('、')}';
  }

  Widget _latencyCard() {
    final colors = context.colors;
    final type = context.typography;
    return AppCard(
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text('P3 · 延迟采样', style: type.sectionTitle),
          const SizedBox(height: 4),
          Text(
            '在手环产生一条数据（如走 30 步）→ 到 Mi Fitness 确认可见 → 回这里采样，'
            '记录数据龄；数据产生时刻按 PLT-001 §4.1.4 人工补记。',
            style: type.caption.copyWith(color: colors.ink2, height: 1.5),
          ),
          const SizedBox(height: 10),
          Row(
            children: [
              Expanded(
                child: DropdownButtonFormField<ProbeTypeSpec>(
                  initialValue: _latencySpec,
                  isDense: true,
                  items: [
                    for (final spec in probeTypeSpecs)
                      DropdownMenuItem(
                        value: spec,
                        child: Text(spec.label, style: type.body),
                      ),
                  ],
                  onChanged: (spec) =>
                      setState(() => _latencySpec = spec ?? _latencySpec),
                ),
              ),
              const SizedBox(width: 10),
              OutlinedButton(
                onPressed: _healthConnectAvailable == true ? _sampleLatency : null,
                child: const Text('延迟采样'),
              ),
            ],
          ),
          if (_latencySamples.isNotEmpty)
            Padding(
              padding: const EdgeInsets.only(top: 10),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  for (final sample in _latencySamples.reversed)
                    Padding(
                      padding: const EdgeInsets.symmetric(vertical: 3),
                      child: Text(
                        '${_formatTime(sample.takenAt)} · ${sample.spec.label} · '
                        '记录结束 ${_formatTime(sample.recordEnd)} · '
                        '数据龄 ${sample.age.inMinutes}min · ${sample.bucket}',
                        style: type.caption.copyWith(color: colors.ink3),
                      ),
                    ),
                ],
              ),
            ),
        ],
      ),
    );
  }
}

String _formatTime(DateTime time) {
  String two(int v) => v.toString().padLeft(2, '0');
  return '${two(time.month)}-${two(time.day)} ${two(time.hour)}:${two(time.minute)}';
}
