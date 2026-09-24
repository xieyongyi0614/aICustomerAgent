import 'package:flutter/material.dart';

class AppRadii extends ThemeExtension<AppRadii> {
  const AppRadii({
    required this.lg,
    required this.md,
    required this.sm,
    required this.full,
    required this.bubbleTail,
  });

  final double lg;
  final double md;
  final double sm;
  final double full;
  final double bubbleTail;

  static const values = AppRadii(
    lg: 24,
    md: 18,
    sm: 12,
    full: 999,
    bubbleTail: 6,
  );

  BorderRadius get rLg => BorderRadius.all(Radius.circular(lg));
  BorderRadius get rMd => BorderRadius.all(Radius.circular(md));
  BorderRadius get rSm => BorderRadius.all(Radius.circular(sm));
  BorderRadius get rFull => BorderRadius.all(Radius.circular(full));

  /// 图标底色方块圆角 = 边长 ÷ 3（取整）
  /// 对照表：26→8 / 32→10 / 36→12 / 38→13 / 42→14
  double iconTile(double size) {
    switch (size) {
      case 26:
        return 8;
      case 32:
        return 10;
      case 36:
        return 12;
      case 38:
        return 13;
      case 42:
        return 14;
      default:
        return (size / 3).floorToDouble();
    }
  }

  @override
  AppRadii copyWith({
    double? lg,
    double? md,
    double? sm,
    double? full,
    double? bubbleTail,
  }) {
    return AppRadii(
      lg: lg ?? this.lg,
      md: md ?? this.md,
      sm: sm ?? this.sm,
      full: full ?? this.full,
      bubbleTail: bubbleTail ?? this.bubbleTail,
    );
  }

  @override
  AppRadii lerp(covariant AppRadii? other, double t) {
    if (other == null) return this;
    double m(double a, double b) => a + (b - a) * t;
    return AppRadii(
      lg: m(lg, other.lg),
      md: m(md, other.md),
      sm: m(sm, other.sm),
      full: m(full, other.full),
      bubbleTail: m(bubbleTail, other.bubbleTail),
    );
  }
}
