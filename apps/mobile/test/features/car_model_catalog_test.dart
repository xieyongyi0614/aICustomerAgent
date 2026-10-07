import 'package:flutter/foundation.dart';
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:mobile/features/car/data/car_model_catalog_repository.dart';
import 'package:mobile/features/car/domain/car_model_catalog.dart';

class _MissingAssetBundle extends CachingAssetBundle {
  @override
  Future<ByteData> load(String key) async =>
      throw FlutterError('asset not found: $key');
}

void main() {
  test('test_parse_catalog_reads_variants_and_battery', () {
    final catalog = parseCarModelCatalog('''
    {
      "updated_at": "2026-10-07",
      "source": "厂商公开参数",
      "disclaimer": "仅预填参考",
      "models": [
        {
          "brand": "比亚迪",
          "series": "汉 EV",
          "powertrain": "ev",
          "variants": [
            { "name": "715km 尊贵型", "battery_kwh": 85.4 },
            { "name": "610km 尊享型", "battery_kwh": 72.0 }
          ]
        },
        { "brand": "丰田", "series": "凯美瑞", "powertrain": "fuel" }
      ]
    }
    ''');

    expect(catalog.updatedAt, '2026-10-07');
    expect(catalog.disclaimer, isNotEmpty);
    expect(catalog.models, hasLength(2));

    final han = catalog.models.first;
    expect(han.name, '比亚迪 汉 EV');
    expect(han.powertrain, CarPowertrain.ev);
    expect(han.hasBatteryData, isTrue);
    expect(
      han.variants.map((variant) => variant.name),
      ['715km 尊贵型', '610km 尊享型'],
    );
    expect(han.variants.first.batteryKwh, 85.4);

    final camry = catalog.models.last;
    expect(camry.powertrain, CarPowertrain.fuel);
    expect(camry.variants, isEmpty);
    expect(camry.hasBatteryData, isFalse);
  });

  test('test_parse_catalog_skips_incomplete_entries', () {
    final catalog = parseCarModelCatalog('''
    {
      "models": [
        { "brand": "比亚迪" },
        { "series": "没品牌" },
        { "brand": "小鹏", "series": "G6", "variants": [ { "name": "" } ] }
      ]
    }
    ''');

    expect(catalog.models, hasLength(1));
    expect(catalog.models.single.variants, isEmpty);
  });

  test('test_parse_catalog_rejects_non_object_root', () {
    expect(() => parseCarModelCatalog('[]'), throwsFormatException);
  });

  testWidgets('test_catalog_asset_is_loadable_and_mainstream', (tester) async {
    final catalog = await CarModelCatalogRepository().load();

    expect(catalog.isEmpty, isFalse, reason: 'assets/car/car_models.json 必须可加载');
    expect(catalog.updatedAt, isNotEmpty);
    expect(catalog.disclaimer, isNotEmpty);
    expect(catalog.models.length, greaterThan(100));

    final han = catalog.models.firstWhere((model) => model.series == '汉 EV');
    expect(han.brand, '比亚迪');
    expect(han.powertrain, CarPowertrain.ev);
    expect(
      han.variants.map((variant) => variant.batteryKwh),
      contains(85.4),
    );

    final camry = catalog.models.firstWhere((model) => model.series == '凯美瑞');
    expect(camry.powertrain, CarPowertrain.fuel);
    expect(camry.hasBatteryData, isFalse);
  });

  testWidgets('test_catalog_missing_asset_degrades_to_empty', (tester) async {
    final catalog =
        await CarModelCatalogRepository(bundle: _MissingAssetBundle()).load();
    expect(catalog.isEmpty, isTrue);
  });
}
