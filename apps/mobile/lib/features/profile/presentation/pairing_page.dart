import 'package:flutter/material.dart';
import 'package:go_router/go_router.dart';

import '../../../app/theme/theme_context.dart';
import '../../../design_system/components/components.dart';
import '../data/auth_repository.dart';

/// APP-004 设备配对：输入部署侧配对码，换取长期令牌。
class PairingPage extends StatefulWidget {
  const PairingPage({super.key});

  @override
  State<PairingPage> createState() => _PairingPageState();
}

class _PairingPageState extends State<PairingPage> {
  final _secret = TextEditingController();
  final _deviceName = TextEditingController(text: '我的设备');
  final _repo = AuthRepository();
  bool _busy = false;
  String? _error;

  @override
  void dispose() {
    _secret.dispose();
    _deviceName.dispose();
    super.dispose();
  }

  Future<void> _pair() async {
    final code = _secret.text.trim();
    if (code.isEmpty) {
      setState(() => _error = '请输入配对码');
      return;
    }
    setState(() {
      _busy = true;
      _error = null;
    });
    try {
      final deviceId = DateTime.now().millisecondsSinceEpoch.toRadixString(36);
      await _repo.pair(
        pairingSecret: code,
        deviceId: deviceId,
        platform: Theme.of(context).platform.name,
        deviceName: _deviceName.text.trim().isEmpty
            ? null
            : _deviceName.text.trim(),
      );
      if (!mounted) return;
      context.go('/profile');
    } catch (e) {
      if (!mounted) return;
      setState(() {
        _busy = false;
        _error = '配对失败，检查配对码后再试';
      });
    }
  }

  @override
  Widget build(BuildContext context) {
    final colors = context.colors;
    final type = context.typography;
    return Scaffold(
      backgroundColor: colors.canvas,
      appBar: AppBar(title: const Text('设备配对')),
      body: ListView(
        padding: const EdgeInsets.fromLTRB(18, 12, 18, 40),
        children: [
          Text(
            '输入部署侧提供的配对码，把这台设备绑定到你的朝夕账号。',
            style: type.body.copyWith(color: colors.ink2, height: 1.6),
          ),
          const SizedBox(height: 20),
          TextField(
            controller: _secret,
            decoration: const InputDecoration(
              labelText: '配对码',
              border: OutlineInputBorder(),
            ),
          ),
          const SizedBox(height: 12),
          TextField(
            controller: _deviceName,
            decoration: const InputDecoration(
              labelText: '设备名称（可选）',
              border: OutlineInputBorder(),
            ),
          ),
          if (_error != null) ...[
            const SizedBox(height: 12),
            Text(_error!, style: type.caption.copyWith(color: colors.warm)),
          ],
          const SizedBox(height: 20),
          FilledButton(
            onPressed: _busy ? null : _pair,
            child: Text(_busy ? '配对中…' : '开始配对'),
          ),
        ],
      ),
    );
  }
}
