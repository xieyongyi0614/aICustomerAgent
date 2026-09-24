import 'package:flutter/material.dart';

import '../../design_system/tokens/tokens.dart';
import 'theme_context.dart';

/// M3 显式覆盖层：保留交互与无障碍底座，剥掉视觉主张。
/// 禁令：fromSeed / 默认 TextTheme / surfaceTint / 默认 elevation / Material Icons / 系统 Tab 栏
ThemeData buildAppTheme() => _build(brightness: Brightness.light);

ThemeData buildAppDarkTheme() => _build(brightness: Brightness.dark);

ThemeData _build({required Brightness brightness}) {
  final dark = brightness == Brightness.dark;
  final colors = dark ? AppColors.dark : AppColors.light;
  final elevation = dark ? AppElevation.dark : AppElevation.light;

  final scheme = ColorScheme(
    brightness: brightness,
    primary: colors.aiPrimary,
    onPrimary: colors.onDeepPrimary,
    secondary: colors.aiBlue,
    onSecondary: colors.onDeepPrimary,
    surface: colors.surface,
    onSurface: colors.ink,
    error: colors.warm,
    onError: colors.onDeepPrimary,
  );

  final base = ThemeData(
    useMaterial3: true,
    colorScheme: scheme,
    scaffoldBackgroundColor: colors.canvas,
    splashFactory: InkRipple.splashFactory,
    fontFamily: 'PingFang SC',
  );

  return base.copyWith(
    cardTheme: CardThemeData(
      color: colors.surface,
      elevation: 0,
      surfaceTintColor: colors.transparent,
      shape: RoundedRectangleBorder(borderRadius: AppRadii.values.rLg),
    ),
    elevatedButtonTheme: ElevatedButtonThemeData(
      style: ElevatedButton.styleFrom(
        elevation: 0,
        backgroundColor: colors.aiPrimary,
        foregroundColor: colors.onDeepPrimary,
        surfaceTintColor: colors.transparent,
      ),
    ),
    appBarTheme: AppBarTheme(
      backgroundColor: colors.canvas,
      foregroundColor: colors.ink,
      surfaceTintColor: colors.transparent,
      elevation: 0,
      centerTitle: false,
      titleTextStyle: AppTypography.values.pageTitle.copyWith(color: colors.ink),
    ),
    dividerTheme: DividerThemeData(color: colors.line, space: 1, thickness: 1),
    textTheme: _textTheme(colors),
    iconTheme: IconThemeData(color: colors.ink, size: 18),
    extensions: <ThemeExtension<dynamic>>[
      colors,
      AppGradients.values,
      AppRadii.values,
      AppTypography.values,
      AppSpacing.values,
      AppMotion.values,
      AppOrbPalette.values,
      elevation,
    ],
  );
}

TextTheme _textTheme(AppColors colors) {
  final t = AppTypography.values;
  return TextTheme(
    displayLarge: t.display.copyWith(color: colors.ink),
    displayMedium: t.briefTitle.copyWith(color: colors.ink),
    displaySmall: t.heroTitle.copyWith(color: colors.ink),
    headlineLarge: t.pageTitle.copyWith(color: colors.ink),
    headlineMedium: t.sectionTitle.copyWith(color: colors.ink),
    headlineSmall: t.rowTitle.copyWith(color: colors.ink),
    titleLarge: t.sectionTitle.copyWith(color: colors.ink),
    titleMedium: t.rowTitle.copyWith(color: colors.ink),
    titleSmall: t.label.copyWith(color: colors.ink2),
    bodyLarge: t.body.copyWith(color: colors.ink),
    bodyMedium: t.sub.copyWith(color: colors.ink2),
    bodySmall: t.caption.copyWith(color: colors.ink3),
    labelLarge: t.label.copyWith(color: colors.ink),
    labelMedium: t.caption.copyWith(color: colors.ink2),
    labelSmall: t.tabLabel.copyWith(color: colors.ink3),
  );
}
