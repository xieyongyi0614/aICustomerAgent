import 'package:flutter/material.dart';

/// Orb 四态径向渐变色板（值来自 zhaoxi orb.md §2 / §4，禁止自创）。
class AppOrbPalette extends ThemeExtension<AppOrbPalette> {
  const AppOrbPalette({
    required this.idle,
    required this.caring,
    required this.done,
    required this.innerCyan,
    required this.innerWhite,
  });

  /// 待机/思考：#D9CCFF → #8B6DFF → #4D6BFF → #1FB9D8
  final List<Color> idle;

  /// 主动关怀：#FFE6D2 → #FFB48F → #FF9D76 → #FF7A4D
  final List<Color> caring;

  /// 完成：#C8F7E4 → #6FD9B4 → #33BC8C → #1F9A70
  final List<Color> done;

  final Color innerCyan;
  final Color innerWhite;

  static const values = AppOrbPalette(
    idle: [
      Color(0xFFD9CCFF),
      Color(0xFF8B6DFF),
      Color(0xFF4D6BFF),
      Color(0xFF1FB9D8),
    ],
    caring: [
      Color(0xFFFFE6D2),
      Color(0xFFFFB48F),
      Color(0xFFFF9D76),
      Color(0xFFFF7A4D),
    ],
    done: [
      Color(0xFFC8F7E4),
      Color(0xFF6FD9B4),
      Color(0xFF33BC8C),
      Color(0xFF1F9A70),
    ],
    innerCyan: Color(0xD92BD2E8),
    innerWhite: Color(0xE6FFFFFF),
  );

  List<Color> forState(OrbVisualState state) => switch (state) {
        OrbVisualState.caring => caring,
        OrbVisualState.done => done,
        OrbVisualState.idle || OrbVisualState.thinking => idle,
      };

  @override
  AppOrbPalette copyWith({
    List<Color>? idle,
    List<Color>? caring,
    List<Color>? done,
    Color? innerCyan,
    Color? innerWhite,
  }) {
    return AppOrbPalette(
      idle: idle ?? this.idle,
      caring: caring ?? this.caring,
      done: done ?? this.done,
      innerCyan: innerCyan ?? this.innerCyan,
      innerWhite: innerWhite ?? this.innerWhite,
    );
  }

  @override
  AppOrbPalette lerp(covariant AppOrbPalette? other, double t) {
    if (other == null) return this;
    return this;
  }
}

enum OrbVisualState { idle, thinking, caring, done }

enum OrbSize { lg, md, sm }

extension OrbSizePx on OrbSize {
  double get px => switch (this) {
        OrbSize.lg => 76,
        OrbSize.md => 34,
        OrbSize.sm => 22,
      };
}
