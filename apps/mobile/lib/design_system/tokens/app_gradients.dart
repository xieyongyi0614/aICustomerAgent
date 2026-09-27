import 'package:flutter/material.dart';

class AppGradients extends ThemeExtension<AppGradients> {
  const AppGradients({
    required this.ai,
    required this.deepSummary,
    required this.deepPersona,
    required this.deepBrief,
    required this.barMoney,
    required this.barBlue,
    required this.barPurple,
    required this.barGreen,
    required this.spark,
    required this.dayBars,
    required this.hbar,
    required this.avatar,
    required this.insightHero,
    required this.orbHalo,
  });

  final LinearGradient ai;
  final LinearGradient deepSummary;
  final LinearGradient deepPersona;
  final LinearGradient deepBrief;
  final LinearGradient barMoney;
  final LinearGradient barBlue;
  final LinearGradient barPurple;
  final LinearGradient barGreen;
  final LinearGradient spark;
  final LinearGradient dayBars;
  final LinearGradient hbar;
  final LinearGradient avatar;
  final LinearGradient insightHero;

  /// 登录页 Orb 背后 160px 静态辉光
  final RadialGradient orbHalo;

  static const values = AppGradients(
    ai: LinearGradient(
      begin: Alignment.topLeft,
      end: Alignment.bottomRight,
      colors: [Color(0xFF8B6DFF), Color(0xFF4D8DFF), Color(0xFF2BD2E8)],
      stops: [0.0, 0.55, 1.0],
    ),
    deepSummary: LinearGradient(
      begin: Alignment.topLeft,
      end: Alignment.bottomRight,
      colors: [Color(0xFF23232E), Color(0xFF33304A), Color(0xFF3E3A63)],
      stops: [0.0, 0.6, 1.0],
    ),
    deepPersona: LinearGradient(
      begin: Alignment.topLeft,
      end: Alignment.bottomRight,
      colors: [Color(0xFF23232E), Color(0xFF37335C), Color(0xFF4A4390)],
      stops: [0.0, 0.65, 1.0],
    ),
    deepBrief: LinearGradient(
      begin: Alignment.topCenter,
      end: Alignment.bottomCenter,
      colors: [
        Color(0xFF191826),
        Color(0xFF262445),
        Color(0xFF3B3672),
        Color(0xFF4A4390),
      ],
      stops: [0.0, 0.46, 0.78, 1.0],
    ),
    barMoney: LinearGradient(
      begin: Alignment.centerLeft,
      end: Alignment.centerRight,
      colors: [Color(0xFFEFA63C), Color(0xFFFFD08A)],
    ),
    barBlue: LinearGradient(
      begin: Alignment.centerLeft,
      end: Alignment.centerRight,
      colors: [Color(0xFF3E8BFF), Color(0xFF9CC2FF)],
    ),
    barPurple: LinearGradient(
      begin: Alignment.centerLeft,
      end: Alignment.centerRight,
      colors: [Color(0xFF7A5CFF), Color(0xFFC3B3FF)],
    ),
    barGreen: LinearGradient(
      begin: Alignment.centerLeft,
      end: Alignment.centerRight,
      colors: [Color(0xFF33BC8C), Color(0xFF9FE8CF)],
    ),
    spark: LinearGradient(
      begin: Alignment.topCenter,
      end: Alignment.bottomCenter,
      colors: [Color(0xFF33BC8C), Color(0xFF9FE8CF)],
    ),
    dayBars: LinearGradient(
      begin: Alignment.topCenter,
      end: Alignment.bottomCenter,
      colors: [Color(0xFFF4C066), Color(0xFFF8DCAB)],
    ),
    hbar: LinearGradient(
      begin: Alignment.topCenter,
      end: Alignment.bottomCenter,
      colors: [Color(0xFF6E93FF), Color(0xFFB9CCFF)],
    ),
    avatar: LinearGradient(
      begin: Alignment.topLeft,
      end: Alignment.bottomRight,
      colors: [Color(0xFFFFD9C2), Color(0xFFFF9D76)],
    ),
    insightHero: LinearGradient(
      begin: Alignment.topLeft,
      end: Alignment.bottomRight,
      colors: [Color(0xFFFFFFFF), Color(0xFFF4F1FF)],
    ),
    orbHalo: RadialGradient(
      colors: [Color(0x337A5CFF), Color(0x007A5CFF)],
      stops: [0.0, 0.95],
    ),
  );

  @override
  AppGradients copyWith({
    LinearGradient? ai,
    LinearGradient? deepSummary,
    LinearGradient? deepPersona,
    LinearGradient? deepBrief,
    LinearGradient? barMoney,
    LinearGradient? barBlue,
    LinearGradient? barPurple,
    LinearGradient? barGreen,
    LinearGradient? spark,
    LinearGradient? dayBars,
    LinearGradient? hbar,
    LinearGradient? avatar,
    LinearGradient? insightHero,
    RadialGradient? orbHalo,
  }) {
    return AppGradients(
      ai: ai ?? this.ai,
      deepSummary: deepSummary ?? this.deepSummary,
      deepPersona: deepPersona ?? this.deepPersona,
      deepBrief: deepBrief ?? this.deepBrief,
      barMoney: barMoney ?? this.barMoney,
      barBlue: barBlue ?? this.barBlue,
      barPurple: barPurple ?? this.barPurple,
      barGreen: barGreen ?? this.barGreen,
      spark: spark ?? this.spark,
      dayBars: dayBars ?? this.dayBars,
      hbar: hbar ?? this.hbar,
      avatar: avatar ?? this.avatar,
      insightHero: insightHero ?? this.insightHero,
      orbHalo: orbHalo ?? this.orbHalo,
    );
  }

  @override
  AppGradients lerp(covariant AppGradients? other, double t) {
    if (other == null) return this;
    LinearGradient g(LinearGradient a, LinearGradient b) =>
        LinearGradient.lerp(a, b, t)!;
    return AppGradients(
      ai: g(ai, other.ai),
      deepSummary: g(deepSummary, other.deepSummary),
      deepPersona: g(deepPersona, other.deepPersona),
      deepBrief: g(deepBrief, other.deepBrief),
      barMoney: g(barMoney, other.barMoney),
      barBlue: g(barBlue, other.barBlue),
      barPurple: g(barPurple, other.barPurple),
      barGreen: g(barGreen, other.barGreen),
      spark: g(spark, other.spark),
      dayBars: g(dayBars, other.dayBars),
      hbar: g(hbar, other.hbar),
      avatar: g(avatar, other.avatar),
      insightHero: g(insightHero, other.insightHero),
      orbHalo: RadialGradient.lerp(orbHalo, other.orbHalo, t)!,
    );
  }
}
