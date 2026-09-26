import 'package:flutter/material.dart';

class AppElevation extends ThemeExtension<AppElevation> {
  const AppElevation({
    required this.card,
    required this.deep,
    required this.orbGlow,
    required this.btnWechat,
    required this.btnPrimary,
    required this.pill,
  });

  final List<BoxShadow> card;
  final List<BoxShadow> deep;
  final List<BoxShadow> orbGlow;
  final List<BoxShadow> btnWechat;
  final List<BoxShadow> btnPrimary;

  /// 矮宽元素（输入栏 pill / 输入卡）的阴影：
  /// blur 过大（如 card 的 30）在这类几何上会被 Skia 九宫格路径渲染成实色带，
  /// 必须保持小模糊（模拟器 Skia 实测；真机 Impeller 不受影响）。
  final List<BoxShadow> pill;

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
    pill: [
      BoxShadow(
        color: Color(0x141B1C23),
        offset: Offset(0, 3),
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
    pill: [
      BoxShadow(
        color: Color(0x33000000),
        offset: Offset(0, 3),
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
    List<BoxShadow>? pill,
  }) {
    return AppElevation(
      card: card ?? this.card,
      deep: deep ?? this.deep,
      orbGlow: orbGlow ?? this.orbGlow,
      btnWechat: btnWechat ?? this.btnWechat,
      btnPrimary: btnPrimary ?? this.btnPrimary,
      pill: pill ?? this.pill,
    );
  }

  @override
  AppElevation lerp(covariant AppElevation? other, double t) {
    if (other == null) return this;
    return this;
  }
}
