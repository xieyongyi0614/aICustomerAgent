import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:mobile/app/state/dynamic_tab.dart';
import 'package:mobile/core/storage/prefs_store.dart';
import 'package:shared_preferences/shared_preferences.dart';

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();

  setUp(() => SharedPreferences.setMockInitialValues({}));

  test('test_life_module_registry_lists_five_modules', () {
    expect(LifeModule.values.length, 5);
    expect(defaultLifeModule, LifeModule.ledger);
    for (final module in LifeModule.values) {
      expect(module.label, isNotEmpty);
      expect(module.routePath.startsWith('/'), isTrue);
    }
  });

  test('test_life_module_order_defaults_to_registry_order', () {
    expect(defaultLifeModuleOrder, LifeModule.values);
    final container = ProviderContainer();
    addTearDown(container.dispose);

    expect(container.read(lifeModuleOrderProvider), LifeModule.values);
    expect(container.read(dynamicModuleProvider), LifeModule.ledger);
  });

  test('test_decode_life_module_order_drops_unknown_and_refills', () {
    expect(decodeLifeModuleOrder(null), LifeModule.values);
    expect(decodeLifeModuleOrder(''), LifeModule.values);
    expect(
      decodeLifeModuleOrder('car,ghost,car'),
      [LifeModule.car, ...LifeModule.values.where((m) => m != LifeModule.car)],
    );
  });

  test('test_encode_life_module_order_round_trips', () {
    const order = [
      LifeModule.car,
      LifeModule.ledger,
      LifeModule.memo,
      LifeModule.schedule,
      LifeModule.album,
    ];
    expect(decodeLifeModuleOrder(encodeLifeModuleOrder(order)), order);
  });

  test('test_move_to_reorders_and_persists', () async {
    final container = ProviderContainer();
    addTearDown(container.dispose);
    await container.read(lifeModuleOrderProvider.notifier).moveTo(3, 0);
    expect(container.read(lifeModuleOrderProvider).first, LifeModule.car);
    expect(container.read(dynamicModuleProvider), LifeModule.car);

    final restored = ProviderContainer();
    addTearDown(restored.dispose);
    await restored.read(lifeModuleOrderProvider.notifier).restore();
    expect(restored.read(dynamicModuleProvider), LifeModule.car);
  });

  test('test_move_to_keeps_relative_order', () async {
    final container = ProviderContainer();
    addTearDown(container.dispose);

    await container.read(lifeModuleOrderProvider.notifier).moveTo(0, 2);
    expect(container.read(lifeModuleOrderProvider), [
      LifeModule.memo,
      LifeModule.schedule,
      LifeModule.ledger,
      LifeModule.car,
      LifeModule.album,
    ]);
  });

  test('test_restore_falls_back_on_broken_order', () async {
    SharedPreferences.setMockInitialValues({
      PrefsStore.keyModuleOrder: 'ghost,ghost',
    });
    final container = ProviderContainer();
    addTearDown(container.dispose);

    await container.read(lifeModuleOrderProvider.notifier).restore();
    expect(container.read(lifeModuleOrderProvider), LifeModule.values);
  });
}
