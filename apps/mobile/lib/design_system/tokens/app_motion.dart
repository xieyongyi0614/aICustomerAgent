import 'package:flutter/material.dart';

class AppMotion extends ThemeExtension<AppMotion> {
  const AppMotion({
    required this.pageTransition,
    required this.orbBreathe,
    required this.orbSwirl,
    required this.spin,
    required this.typing,
    required this.pressScale,
    required this.pageCurve,
  });

  final Duration pageTransition;
  final Duration orbBreathe;
  final Duration orbSwirl;
  final Duration spin;
  final Duration typing;
  final Duration pressScale;
  final Curve pageCurve;

  static const values = AppMotion(
    pageTransition: Duration(milliseconds: 380),
    orbBreathe: Duration(milliseconds: 4200),
    orbSwirl: Duration(milliseconds: 7000),
    spin: Duration(milliseconds: 900),
    typing: Duration(milliseconds: 1100),
    pressScale: Duration(milliseconds: 150),
    pageCurve: Cubic(0.22, 0.9, 0.3, 1),
  );

  @override
  AppMotion copyWith({
    Duration? pageTransition,
    Duration? orbBreathe,
    Duration? orbSwirl,
    Duration? spin,
    Duration? typing,
    Duration? pressScale,
    Curve? pageCurve,
  }) {
    return AppMotion(
      pageTransition: pageTransition ?? this.pageTransition,
      orbBreathe: orbBreathe ?? this.orbBreathe,
      orbSwirl: orbSwirl ?? this.orbSwirl,
      spin: spin ?? this.spin,
      typing: typing ?? this.typing,
      pressScale: pressScale ?? this.pressScale,
      pageCurve: pageCurve ?? this.pageCurve,
    );
  }

  @override
  AppMotion lerp(covariant AppMotion? other, double t) {
    if (other == null) return this;
    return this;
  }
}
