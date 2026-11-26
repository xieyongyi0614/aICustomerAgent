import 'package:flutter/material.dart';

import '../../../app/theme/theme_context.dart';

/// 31 账单行「分类 → 语义色 / 图标」（设计稿 31：餐饮=money / 交通=aiBlue /
/// 购物=aiPrimary；娱乐沿用分类条的 green 语义）。
///
/// 未识别分类回落 money 基线，不编造新语义；分类 id → 名称由页面先经
/// `/ledger/categories` 解析后再进本映射。
({Color tile, Color fg, IconData icon}) ledgerCategoryVisuals(
  AppColors colors,
  String? categoryName,
) {
  final name = categoryName ?? '';
  if (name.contains('餐饮') || name.contains('咖啡')) {
    return (tile: colors.tileMoney, fg: colors.money, icon: AppIcons.coffee);
  }
  if (name.contains('交通')) {
    return (tile: colors.tileInfo, fg: colors.aiBlue, icon: AppIcons.train);
  }
  if (name.contains('购物')) {
    return (tile: colors.tileAi, fg: colors.aiPrimary, icon: AppIcons.wallet);
  }
  if (name.contains('娱乐')) {
    return (
      tile: colors.tileHealth,
      fg: colors.health,
      icon: AppIcons.sparkles,
    );
  }
  return (tile: colors.tileMoney, fg: colors.money, icon: AppIcons.fileText);
}
