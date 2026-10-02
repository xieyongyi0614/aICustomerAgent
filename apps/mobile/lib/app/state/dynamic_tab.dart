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

  static LifeModule? tryFromId(String? id) {
    for (final module in values) {
      if (module.id == id) return module;
    }
    return null;
  }
}

const defaultLifeModule = LifeModule.ledger;

const defaultLifeModuleOrder = LifeModule.values;

final lifeModuleOrderProvider =
    NotifierProvider<LifeModuleOrderNotifier, List<LifeModule>>(
  LifeModuleOrderNotifier.new,
);

class LifeModuleOrderNotifier extends Notifier<List<LifeModule>> {
  @override
  List<LifeModule> build() => defaultLifeModuleOrder;

  Future<void> restore() async {
    final prefs = await PrefsStore.load();
    state = decodeLifeModuleOrder(prefs.moduleOrder());
  }

  Future<void> moveTo(int from, int to) async {
    if (from == to || from < 0 || from >= state.length) return;
    final next = [...state];
    next.insert(to.clamp(0, next.length), next.removeAt(from));
    await _commit(next);
  }

  Future<void> _commit(List<LifeModule> order) async {
    state = order;
    final prefs = await PrefsStore.load();
    await prefs.setModuleOrder(encodeLifeModuleOrder(order));
  }
}

final dynamicModuleProvider = Provider<LifeModule>(
  (ref) => ref.watch(lifeModuleOrderProvider).first,
);

String encodeLifeModuleOrder(List<LifeModule> order) =>
    order.map((module) => module.id).join(',');

List<LifeModule> decodeLifeModuleOrder(String? raw) {
  final ordered = <LifeModule>[];
  for (final id in (raw ?? '').split(',')) {
    final module = LifeModule.tryFromId(id);
    if (module != null && !ordered.contains(module)) ordered.add(module);
  }
  for (final module in LifeModule.values) {
    if (!ordered.contains(module)) ordered.add(module);
  }
  return ordered;
}
