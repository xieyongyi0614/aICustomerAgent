import 'dart:convert';

/// 车型目录：数据源是 `assets/car/car_models.json`（JSON 可配置，改数据不用改代码）。
///
/// 只登记品牌 / 车系 / 动力类型，以及**版本级**的电池容量参考值：容量随年款与
/// 配置变化（同一车系常有 2~4 个版本），所以只用于表单预填、用户可改，
/// 口径与 JSON 里的 `disclaimer` 一致，不作为购车或理赔依据。
enum CarPowertrain {
  ev('纯电'),
  phev('插混 / 增程'),
  fuel('燃油');

  const CarPowertrain(this.label);

  final String label;

  static CarPowertrain parse(String? raw) => switch (raw) {
        'ev' => ev,
        'phev' => phev,
        _ => fuel,
      };
}

class CarModelVariant {
  const CarModelVariant({required this.name, this.batteryKwh});

  final String name;

  /// 该版本的电池容量（kWh，CLTC 口径的公开值）；无数据时为 null。
  final double? batteryKwh;
}

class CarModelOption {
  const CarModelOption({
    required this.brand,
    required this.series,
    required this.powertrain,
    this.variants = const [],
  });

  final String brand;
  final String series;
  final CarPowertrain powertrain;
  final List<CarModelVariant> variants;

  String get name => '$brand $series';

  bool get hasBatteryData =>
      variants.any((variant) => variant.batteryKwh != null);
}

class CarModelCatalog {
  const CarModelCatalog({
    required this.updatedAt,
    required this.source,
    required this.disclaimer,
    required this.models,
  });

  final String updatedAt;
  final String source;
  final String disclaimer;
  final List<CarModelOption> models;

  static const empty = CarModelCatalog(
    updatedAt: '',
    source: '',
    disclaimer: '',
    models: [],
  );

  bool get isEmpty => models.isEmpty;
}

/// 解析车型目录 JSON。结构不合法时抛 [FormatException]，字段缺失按缺失处理。
CarModelCatalog parseCarModelCatalog(String raw) {
  final root = jsonDecode(raw);
  if (root is! Map<String, dynamic>) {
    throw const FormatException('catalog root must be a JSON object');
  }
  final models = <CarModelOption>[];
  for (final item in (root['models'] as List?) ?? const []) {
    if (item is! Map) continue;
    final brand = '${item['brand'] ?? ''}'.trim();
    final series = '${item['series'] ?? ''}'.trim();
    if (brand.isEmpty || series.isEmpty) continue;
    models.add(
      CarModelOption(
        brand: brand,
        series: series,
        powertrain: CarPowertrain.parse(item['powertrain'] as String?),
        variants: [
          for (final variant in (item['variants'] as List?) ?? const [])
            if (variant is Map && '${variant['name'] ?? ''}'.trim().isNotEmpty)
              CarModelVariant(
                name: '${variant['name']}'.trim(),
                batteryKwh: (variant['battery_kwh'] as num?)?.toDouble(),
              ),
        ],
      ),
    );
  }
  return CarModelCatalog(
    updatedAt: '${root['updated_at'] ?? ''}',
    source: '${root['source'] ?? ''}',
    disclaimer: '${root['disclaimer'] ?? ''}',
    models: models,
  );
}
