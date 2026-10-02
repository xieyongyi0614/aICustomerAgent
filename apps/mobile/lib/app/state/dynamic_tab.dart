import 'package:flutter/widgets.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/storage/prefs_store.dart';
import '../../design_system/tokens/tokens.dart';

enum LifeModule {
  ledger('ledger', '记账', AppIcons.wallet, '/ledger'),
  memo('memo', '备忘录', AppIcons.fileText, '/memo'),
  schedule('schedule', '日程', AppIcons.calendar, '/schedule'),
  health('health', '健康', AppIcons.heart, '/health'),
  car('car', '车辆', AppIcons.car, '/car'),
  album('album', '相册', AppIcons.image, '/album');

  const LifeModule(this.id, this.label, this.icon, this.routePath);

  final String id;
  final String label;
  final IconData icon;
  final String routePath;

  static LifeModule fromId(String? id) {
    for (final module in values) {
      if (module.id == id) return module;
    }
    return defaultLifeModule;
  }
}

const defaultLifeModule = LifeModule.ledger;

final dynamicModuleProvider =
    NotifierProvider<DynamicModuleNotifier, LifeModule>(
  DynamicModuleNotifier.new,
);

class DynamicModuleNotifier extends Notifier<LifeModule> {
  @override
  LifeModule build() => defaultLifeModule;

  Future<void> restore() async {
    final prefs = await PrefsStore.load();
    state = LifeModule.fromId(prefs.dynamicModuleId());
  }

  Future<void> select(LifeModule module) async {
    if (state != module) {
      state = module;
    }
    final prefs = await PrefsStore.load();
    await prefs.setDynamicModuleId(module.id);
  }
}
