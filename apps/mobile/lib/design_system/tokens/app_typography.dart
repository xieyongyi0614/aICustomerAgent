import 'package:flutter/material.dart';

/// 字重降级映射（方案 B）：550→w500 / 650→w600 / 750→w700
class AppTypography extends ThemeExtension<AppTypography> {
  const AppTypography({
    required this.display,
    required this.title,
    required this.body,
    required this.caption,
    required this.label,
    required this.amountHero,
    required this.briefTitle,
    required this.heroTitle,
    required this.pageTitle,
    required this.sectionTitle,
    required this.rowTitle,
    required this.sub,
    required this.tabLabel,
  });

  final TextStyle display;
  final TextStyle title;
  final TextStyle body;
  final TextStyle caption;
  final TextStyle label;
  final TextStyle amountHero;
  final TextStyle briefTitle;
  final TextStyle heroTitle;
  final TextStyle pageTitle;
  final TextStyle sectionTitle;
  final TextStyle rowTitle;
  final TextStyle sub;
  final TextStyle tabLabel;

  static const List<FontFeature> tabular = [FontFeature.tabularFigures()];

  static const values = AppTypography(
    display: TextStyle(fontSize: 32, fontWeight: FontWeight.w700, letterSpacing: -0.64),
    title: TextStyle(fontSize: 16.5, fontWeight: FontWeight.w700),
    body: TextStyle(fontSize: 14.5, fontWeight: FontWeight.w500, height: 1.65),
    caption: TextStyle(fontSize: 11, fontWeight: FontWeight.w600),
    label: TextStyle(fontSize: 11.5, fontWeight: FontWeight.w600, letterSpacing: 0.6),
    amountHero: TextStyle(
      fontSize: 32,
      fontWeight: FontWeight.w700,
      letterSpacing: -0.64,
      fontFeatures: tabular,
    ),
    briefTitle: TextStyle(
      fontSize: 26,
      fontWeight: FontWeight.w700,
      height: 1.35,
      fontFeatures: tabular,
    ),
    heroTitle: TextStyle(
      fontSize: 25,
      fontWeight: FontWeight.w700,
      letterSpacing: -0.25,
    ),
    pageTitle: TextStyle(
      fontSize: 24,
      fontWeight: FontWeight.w700,
      letterSpacing: -0.24,
    ),
    sectionTitle: TextStyle(fontSize: 16.5, fontWeight: FontWeight.w700),
    rowTitle: TextStyle(fontSize: 14, fontWeight: FontWeight.w600),
    sub: TextStyle(fontSize: 13, fontWeight: FontWeight.w400),
    tabLabel: TextStyle(fontSize: 10.5, fontWeight: FontWeight.w600),
  );

  /// 数值型样式统一带等宽特性
  TextStyle numeric(TextStyle base) => base.copyWith(fontFeatures: tabular);

  @override
  AppTypography copyWith({
    TextStyle? display,
    TextStyle? title,
    TextStyle? body,
    TextStyle? caption,
    TextStyle? label,
    TextStyle? amountHero,
    TextStyle? briefTitle,
    TextStyle? heroTitle,
    TextStyle? pageTitle,
    TextStyle? sectionTitle,
    TextStyle? rowTitle,
    TextStyle? sub,
    TextStyle? tabLabel,
  }) {
    return AppTypography(
      display: display ?? this.display,
      title: title ?? this.title,
      body: body ?? this.body,
      caption: caption ?? this.caption,
      label: label ?? this.label,
      amountHero: amountHero ?? this.amountHero,
      briefTitle: briefTitle ?? this.briefTitle,
      heroTitle: heroTitle ?? this.heroTitle,
      pageTitle: pageTitle ?? this.pageTitle,
      sectionTitle: sectionTitle ?? this.sectionTitle,
      rowTitle: rowTitle ?? this.rowTitle,
      sub: sub ?? this.sub,
      tabLabel: tabLabel ?? this.tabLabel,
    );
  }

  @override
  AppTypography lerp(covariant AppTypography? other, double t) {
    if (other == null) return this;
    return this;
  }
}
