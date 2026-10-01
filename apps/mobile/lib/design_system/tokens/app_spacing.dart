import 'package:flutter/material.dart';

class AppSpacing extends ThemeExtension<AppSpacing> {
  const AppSpacing({
    required this.pageH,
    required this.cardPadding,
    required this.cardPaddingSm,
    required this.listCardPadding,
    required this.gapCard,
    required this.gapGrid,
    required this.gapSection,
    required this.statusBarHeight,
    required this.tabBarHeight,
    required this.screenPadding,
  });

  final double pageH;
  final double cardPadding;
  final double cardPaddingSm;
  final EdgeInsets listCardPadding;
  final double gapCard;
  final double gapGrid;
  final double gapSection;
  final double statusBarHeight;
  final double tabBarHeight;
  final EdgeInsets screenPadding;

  static const values = AppSpacing(
    pageH: 18,
    cardPadding: 18,
    cardPaddingSm: 15,
    listCardPadding: EdgeInsets.symmetric(vertical: 6, horizontal: 18),
    gapCard: 12,
    gapGrid: 11,
    gapSection: 24,
    statusBarHeight: 48,
    tabBarHeight: 88,
    // 设计稿屏幕内边距为 top 60 / bottom 118，其中 48 让开状态栏、88 让开 Tab 栏；
    // Flutter 侧状态栏已由 SafeArea 让开、Tab 栏已由 Scaffold 让开，此处只取余量。
    screenPadding: EdgeInsets.only(top: 12, left: 18, right: 18, bottom: 30),
  );

  @override
  AppSpacing copyWith({
    double? pageH,
    double? cardPadding,
    double? cardPaddingSm,
    EdgeInsets? listCardPadding,
    double? gapCard,
    double? gapGrid,
    double? gapSection,
    double? statusBarHeight,
    double? tabBarHeight,
    EdgeInsets? screenPadding,
  }) {
    return AppSpacing(
      pageH: pageH ?? this.pageH,
      cardPadding: cardPadding ?? this.cardPadding,
      cardPaddingSm: cardPaddingSm ?? this.cardPaddingSm,
      listCardPadding: listCardPadding ?? this.listCardPadding,
      gapCard: gapCard ?? this.gapCard,
      gapGrid: gapGrid ?? this.gapGrid,
      gapSection: gapSection ?? this.gapSection,
      statusBarHeight: statusBarHeight ?? this.statusBarHeight,
      tabBarHeight: tabBarHeight ?? this.tabBarHeight,
      screenPadding: screenPadding ?? this.screenPadding,
    );
  }

  @override
  AppSpacing lerp(covariant AppSpacing? other, double t) {
    if (other == null) return this;
    double m(double a, double b) => a + (b - a) * t;
    return AppSpacing(
      pageH: m(pageH, other.pageH),
      cardPadding: m(cardPadding, other.cardPadding),
      cardPaddingSm: m(cardPaddingSm, other.cardPaddingSm),
      listCardPadding: EdgeInsets.lerp(listCardPadding, other.listCardPadding, t)!,
      gapCard: m(gapCard, other.gapCard),
      gapGrid: m(gapGrid, other.gapGrid),
      gapSection: m(gapSection, other.gapSection),
      statusBarHeight: m(statusBarHeight, other.statusBarHeight),
      tabBarHeight: m(tabBarHeight, other.tabBarHeight),
      screenPadding: EdgeInsets.lerp(screenPadding, other.screenPadding, t)!,
    );
  }
}
