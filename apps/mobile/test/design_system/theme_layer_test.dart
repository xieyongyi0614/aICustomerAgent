import 'dart:io';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:mobile/app/theme/app_theme.dart';

void main() {
  test('test_color_scheme_not_from_seed', () {
    final files = Directory('lib')
        .listSync(recursive: true)
        .whereType<File>()
        .where((f) => f.path.endsWith('.dart'));
    for (final f in files) {
      expect(f.readAsStringSync().contains('ColorScheme.fromSeed'), isFalse,
          reason: f.path);
    }
  });

  test('test_surface_tint_disabled', () {
    final theme = buildAppTheme();
    expect(theme.cardTheme.surfaceTintColor, const Color(0x00000000));
    expect(theme.appBarTheme.surfaceTintColor, const Color(0x00000000));
  });

  test('test_default_elevation_zeroed', () {
    final theme = buildAppTheme();
    expect(theme.cardTheme.elevation, 0);
  });

  test('test_text_theme_overridden_by_design_scale', () {
    final theme = buildAppTheme();
    expect(theme.textTheme.bodyLarge?.fontSize, 14.5);
    expect(theme.textTheme.headlineLarge?.fontSize, 24);
  });

  test('test_navigation_bar_not_used', () {
    final files = Directory('lib')
        .listSync(recursive: true)
        .whereType<File>()
        .where((f) => f.path.endsWith('.dart'));
    for (final f in files) {
      expect(f.readAsStringSync().contains('NavigationBar'), isFalse,
          reason: f.path);
    }
  });

  test('test_dark_theme_swaps_canvas_surface_ink', () {
    final light = buildAppTheme();
    final dark = buildAppDarkTheme();
    expect(light.scaffoldBackgroundColor, const Color(0xFFF5F4F0));
    expect(dark.scaffoldBackgroundColor, const Color(0xFF191826));
  });
}
