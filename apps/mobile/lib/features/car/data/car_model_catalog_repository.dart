import 'package:flutter/services.dart';

import '../domain/car_model_catalog.dart';

/// 车型目录数据源：`assets/car/car_models.json`（JSON 维护，改数据不用改代码）。
///
/// 目录只服务「选车型」这一个辅助输入，读取或解析失败都不上抛：
/// 返回空目录，页面仍允许用户直接手写车型。
class CarModelCatalogRepository {
  CarModelCatalogRepository({AssetBundle? bundle})
      : _bundle = bundle ?? rootBundle;

  static const assetPath = 'assets/car/car_models.json';

  final AssetBundle _bundle;

  Future<CarModelCatalog> load() async {
    try {
      return parseCarModelCatalog(await _bundle.loadString(assetPath));
    } catch (_) {
      return CarModelCatalog.empty;
    }
  }
}
