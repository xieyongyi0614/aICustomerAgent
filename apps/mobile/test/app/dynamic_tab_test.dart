import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:mobile/app/state/dynamic_tab.dart';
import 'package:mobile/core/storage/prefs_store.dart';
import 'package:shared_preferences/shared_preferences.dart';

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();

  setUp(() => SharedPreferences.setMockInitialValues({}));

  test('test_life_module_registry_lists_six_modules', () {
    expect(LifeModule.values.length, 6);
    expect(defaultLifeModule, LifeModule.ledger);
    for (final module in LifeModule.values) {
      expect(module.label, isNotEmpty);
      expect(module.routePath.startsWith('/'), isTrue);
    }
  });

  test('test_life_module_from_id_falls_back_to_default', () {
    expect(LifeModule.fromId('car'), LifeModule.car);
    expect(LifeModule.fromId('album'), LifeModule.album);
    expect(LifeModule.fromId(null), defaultLifeModule);
    expect(LifeModule.fromId('ghost'), defaultLifeModule);
  });

  test('test_dynamic_module_defaults_to_ledger', () {
    final container = ProviderContainer();
    addTearDown(container.dispose);

    expect(container.read(dynamicModuleProvider), LifeModule.ledger);
  });

  test('test_dynamic_module_select_persists_and_restores', () async {
    final container = ProviderContainer();
    addTearDown(container.dispose);
    await container.read(dynamicModuleProvider.notifier).select(LifeModule.car);
    expect(container.read(dynamicModuleProvider), LifeModule.car);

    final restored = ProviderContainer();
    addTearDown(restored.dispose);
    await restored.read(dynamicModuleProvider.notifier).restore();
    expect(restored.read(dynamicModuleProvider), LifeModule.car);
  });

  test('test_dynamic_module_restore_falls_back_on_unknown_id', () async {
    SharedPreferences.setMockInitialValues({
      PrefsStore.keyDynamicModule: 'ghost',
    });
    final container = ProviderContainer();
    addTearDown(container.dispose);

    await container.read(dynamicModuleProvider.notifier).restore();
    expect(container.read(dynamicModuleProvider), LifeModule.ledger);
  });
}
