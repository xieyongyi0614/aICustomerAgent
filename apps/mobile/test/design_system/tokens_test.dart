import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:mobile/design_system/tokens/tokens.dart';

void main() {
  test('test_app_colors_matches_tokens_contract', () {
    const c = AppColors.light;
    expect(c.canvas, const Color(0xFFF5F4F0));
    expect(c.surface, const Color(0xFFFFFFFF));
    expect(c.ink, const Color(0xFF1B1C23));
    expect(c.ink2, const Color(0xFF6E7079));
    expect(c.ink3, const Color(0xFFA7A8B1));
    expect(c.line, const Color(0xFFECEAE3));
    expect(c.aiPrimary, const Color(0xFF7A5CFF));
    expect(c.aiBlue, const Color(0xFF3E8BFF));
    expect(c.aiCyan, const Color(0xFF2BD2E8));
    expect(c.warm, const Color(0xFFFF9D76));
    expect(c.health, const Color(0xFF33BC8C));
    expect(c.money, const Color(0xFFEFA63C));
    const banned = [
      Color(0xFFFAF9F6),
      Color(0xFF62646E),
      Color(0xFF9C9DA7),
      Color(0xFFEAE8E1),
    ];
    for (final bad in banned) {
      expect(c.canvas, isNot(bad));
      expect(c.ink2, isNot(bad));
      expect(c.ink3, isNot(bad));
      expect(c.line, isNot(bad));
    }
  });

  test('test_dark_theme_swaps_colors', () {
    const d = AppColors.dark;
    expect(d.canvas, const Color(0xFF191826));
    expect(d.surface, const Color(0xFF262445));
    expect(d.ink, const Color(0xFFF4F4F7));
  });

  test('test_app_gradients_three_deep_variants_are_distinct', () {
    const g = AppGradients.values;
    expect(g.deepSummary, isNot(g.deepPersona));
    expect(g.deepPersona, isNot(g.deepBrief));
    expect(g.deepSummary, isNot(g.deepBrief));
    expect(g.deepSummary.stops, isNot(g.deepPersona.stops));
  });

  test('test_icon_tile_rounds_to_one_third', () {
    const r = AppRadii.values;
    expect(r.iconTile(26), 8);
    expect(r.iconTile(32), 10);
    expect(r.iconTile(36), 12);
    expect(r.iconTile(38), 13);
    expect(r.iconTile(42), 14);
  });

  test('test_typography_numeric_uses_tabular_figures', () {
    const t = AppTypography.values;
    final n = t.numeric(t.body);
    expect(n.fontFeatures, contains(FontFeature.tabularFigures()));
    expect(t.amountHero.fontFeatures, contains(FontFeature.tabularFigures()));
  });

  test('test_orb_breathe_is_4200ms', () {
    expect(AppMotion.values.orbBreathe, const Duration(milliseconds: 4200));
  });

  test('test_motion_except_orb_within_400ms', () {
    const m = AppMotion.values;
    expect(m.pageTransition.inMilliseconds, lessThanOrEqualTo(400));
    expect(m.pressScale.inMilliseconds, lessThanOrEqualTo(400));
  });

  test('test_elevation_has_single_regular_shadow', () {
    expect(AppElevation.light.card.length, 1);
  });
}
