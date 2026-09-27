import 'package:flutter/material.dart';

class AppElevation extends ThemeExtension<AppElevation> {
  const AppElevation({
    required this.card,
    required this.deep,
    required this.orbGlow,
    required this.btnWechat,
    required this.btnPrimary,
  });

  final List<BoxShadow> card;
  final List<BoxShadow> deep;
  final List<BoxShadow> orbGlow;
  final List<BoxShadow> btnWechat;
  final List<BoxShadow> btnPrimary;

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
    btnWechat: [
      BoxShadow(
        color: Color(0x4707C160),
        offset: Offset(0, 4),
        blurRadius: 12,
      ),
    ],
    btnPrimary: [
      BoxShadow(
        color: Color(0x66665AFF),
        offset: Offset(0, 4),
        blurRadius: 12,
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
    btnWechat: [
      BoxShadow(
        color: Color(0x4707C160),
        offset: Offset(0, 4),
        blurRadius: 12,
      ),
    ],
    btnPrimary: [
      BoxShadow(
        color: Color(0x66665AFF),
        offset: Offset(0, 4),
        blurRadius: 12,
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
    List<BoxShadow>? btnWechat,
    List<BoxShadow>? btnPrimary,
  }) {
    return AppElevation(
      card: card ?? this.card,
      deep: deep ?? this.deep,
      orbGlow: orbGlow ?? this.orbGlow,
      btnWechat: btnWechat ?? this.btnWechat,
      btnPrimary: btnPrimary ?? this.btnPrimary,
    );
  }

  @override
  AppElevation lerp(covariant AppElevation? other, double t) {
    if (other == null) return this;
    return this;
  }
}
