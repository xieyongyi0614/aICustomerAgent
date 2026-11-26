import 'dart:convert';

import 'package:flutter/services.dart' show rootBundle;

/// 天气城市选择目录：JSON 资产（`assets/data/briefing_cities.json`）运行时加载。
///
/// [name] 是展示名；[saveAs] 是保存/地理编码值，缺省等于 [name]——少数城市在
/// GeoNames 里只有全名或罗马化名可搜（如廊坊市 / Lianyungang），保存时发
/// saveAs，展示仍用中文短名；坐标一律由后端地理编码解析。
class BriefingCity {
  const BriefingCity({required this.name, required this.region, this.saveAs});

  factory BriefingCity.fromJson(Map<String, dynamic> json) => BriefingCity(
        name: json['name'] as String,
        region: json['region'] as String,
        saveAs: json['saveAs'] as String?,
      );

  final String name;
  final String region;
  final String? saveAs;
}

const _assetPath = 'assets/data/briefing_cities.json';

List<BriefingCity>? _cache;

/// 首次读取资产并解析，之后返回内存缓存。
Future<List<BriefingCity>> loadBriefingCities() async {
  final cached = _cache;
  if (cached != null) return cached;
  final raw = await rootBundle.loadString(_assetPath);
  final cities = [
    for (final entry in jsonDecode(raw) as List<dynamic>)
      BriefingCity.fromJson(entry as Map<String, dynamic>),
  ];
  _cache = cities;
  return cities;
}

/// 已存城市值回中文显示名（saveAs 存的城市如 Lianyungang -> 连云港）；
/// 目录外自由输入的城市原样返回。
String? briefingCityDisplayName(List<BriefingCity> cities, String saved) {
  for (final city in cities) {
    if (city.name == saved || city.saveAs == saved) return city.name;
  }
  return null;
}
