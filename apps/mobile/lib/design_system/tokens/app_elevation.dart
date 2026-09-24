import 'package:flutter/material.dart';

class AppElevation extends ThemeExtension<AppElevation> {
  const AppElevation({
    required this.card,
    required this.deep,
    required this.orbGlow,
  });

  final List<BoxShadow> card;
  final List<BoxShadow> deep;
  final List<BoxShadow> orbGlow;

  static const light = AppElevation(
    card: [
      BoxShadow(
        color: Color(0x0F1B1C23),
        offset: Offset(0, 10),
        blurRadius: 30,
      ),
    ],
    deep: [
      BoxShadow(
        color: Color(0x591E1C37),
        offset: Offset(0, 16),
        blurRadius: 36,
      ),
    ],
    orbGlow: [
      BoxShadow(
        color: Color(0x73665AFF),
        offset: Offset(0, 10),
        blurRadius: 30,
      ),
      BoxShadow(
        color: Color(0x593F96FF),
        blurRadius: 60,
      ),
    ],
  );

  static const dark = AppElevation(
    card: [
      BoxShadow(
        color: Color(0x59000000),
        offset: Offset(0, 10),
        blurRadius: 30,
      ),
    ],
    deep: [
      BoxShadow(
        color: Color(0x591E1C37),
        offset: Offset(0, 16),
        blurRadius: 36,
      ),
    ],
    orbGlow: [
      BoxShadow(
        color: Color(0x73665AFF),
        offset: Offset(0, 10),
        blurRadius: 30,
      ),
      BoxShadow(
        color: Color(0x593F96FF),
        blurRadius: 60,
      ),
    ],
  );

  /// 悬浮对话球：外圈 6px 与页面底色同色，形成挖空感
  List<BoxShadow> orbButton(Color canvas) => [
        const BoxShadow(
          color: Color(0x73665AFF),
          offset: Offset(0, 10),
          blurRadius: 24,
        ),
        BoxShadow(color: canvas, spreadRadius: 6),
      ];

  @override
  AppElevation copyWith({
    List<BoxShadow>? card,
    List<BoxShadow>? deep,
    List<BoxShadow>? orbGlow,
  }) {
    return AppElevation(
      card: card ?? this.card,
      deep: deep ?? this.deep,
      orbGlow: orbGlow ?? this.orbGlow,
    );
  }

  @override
  AppElevation lerp(covariant AppElevation? other, double t) {
    if (other == null) return this;
    return this;
  }
}
