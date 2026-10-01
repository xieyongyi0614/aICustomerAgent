import 'dart:convert';
import 'dart:io';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:mobile/app/theme/app_theme.dart';
import 'package:mobile/design_system/components/components.dart';
import 'package:mobile/design_system/tokens/tokens.dart';

final _colors = AppColors.light;

const _tinyPng = '''
iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==
''';

final _thumb = MemoryImage(base64Decode(_tinyPng.trim()));

Widget _wrap(Widget child, {double width = 320}) => MaterialApp(
      theme: buildAppTheme(),
      home: Scaffold(
        backgroundColor: AppColors.light.canvas,
        body: Center(
          child: SingleChildScrollView(
            padding: const EdgeInsets.all(16),
            child: SizedBox(width: width, child: child),
          ),
        ),
      ),
    );

Future<void> _pump(
  WidgetTester tester,
  Widget child, {
  double width = 320,
}) async {
  await tester.pumpWidget(_wrap(child, width: width));
  await tester.pump(const Duration(milliseconds: 16));
  await tester.pump(const Duration(milliseconds: 100));
}

Future<void> _golden(
  WidgetTester tester,
  String name,
  Widget child, {
  double width = 320,
}) async {
  await _pump(tester, child, width: width);
  await expectLater(
    find.byType(Scaffold),
    matchesGoldenFile('goldens/$name.png'),
  );
}

Container _byKey(WidgetTester tester, Key key) =>
    tester.widget<Container>(find.byKey(key));

Widget _storageCard() => StorageCard(
      assetCount: 2847,
      leftoverText: '本机剩余 96 GB',
      usageRatio: 0.34,
    );

Widget _actionBar() => AlbumActionBar(
      actions: [
        AlbumAction(label: '移动到相簿', icon: AppIcons.move, onTap: () {}),
        AlbumAction(label: '批量加标签', icon: AppIcons.tag, onTap: () {}),
        AlbumAction(label: '删除 12 张', icon: AppIcons.trash, danger: true),
      ],
    );

Widget _suggestions() => SuggestionCard(
      rows: [
        SuggestionRow(
          icon: AppIcons.smartphone,
          accent: _colors.aiPrimary,
          title: '过期截图',
          reason: '超过 90 天未再打开的屏幕截图',
          countText: '38 张',
          sizeText: '620 MB',
          onTap: () {},
        ),
        SuggestionRow(
          icon: AppIcons.copy,
          accent: _colors.aiBlue,
          title: '重复保存',
          reason: '同一张照片在多个目录各存了一份',
          countText: '12 张',
          sizeText: '300 MB',
          onTap: () {},
        ),
      ],
    );

void main() {
  testWidgets('test_storage_card_always_shows_local_only_notice',
      (tester) async {
    await _pump(tester, _storageCard());
    expect(find.text(StorageCard.localOnlyNotice), findsOneWidget);
  });

  testWidgets('test_storage_card_usage_bar_uses_track_and_purple_tokens',
      (tester) async {
    await _pump(tester, _storageCard());
    final track = tester.widget<Container>(
      find.byWidgetPredicate(
        (w) =>
            w is Container &&
            w.decoration is BoxDecoration &&
            (w.decoration! as BoxDecoration).color == _colors.trackBar,
      ),
    );
    expect(track, isNotNull);
    final fill = _byKey(tester, StorageCard.usageFillKey);
    expect(
      (fill.decoration! as BoxDecoration).gradient,
      AppGradients.values.barPurple,
    );
  });

  testWidgets('test_album_tile_requires_real_thumbnail', (tester) async {
    await _pump(
      tester,
      AlbumTile(
        thumbnail: _thumb,
        name: '旅行',
        countText: '342 张 · 26 张可清理',
      ),
    );
    final image = tester.widget<Image>(find.byType(Image));
    expect(image.image, same(_thumb));
    expect(find.text('旅行'), findsOneWidget);
    expect(find.text('342 张 · 26 张可清理'), findsOneWidget);
  });

  testWidgets('test_photo_tile_selection_checkbox_may_use_ai_gradient',
      (tester) async {
    await _pump(
      tester,
      PhotoTile(
        thumbnail: _thumb,
        selectionMode: true,
        selected: true,
      ),
    );
    final chk = _byKey(tester, PhotoTile.selectionCheckKey);
    expect(
      (chk.decoration! as BoxDecoration).gradient,
      AppGradients.values.ai,
    );
    final border = tester.widget<Container>(
      find.byWidgetPredicate(
        (w) =>
            w is Container &&
            w.decoration is BoxDecoration &&
            (w.decoration! as BoxDecoration).border != null,
      ),
    );
    expect(
      (border.decoration! as BoxDecoration).gradient,
      isNull,
      reason: '渐变只允许出现在选中态 chk，其余部分一律中性色',
    );
  });

  testWidgets('test_photo_tile_ai_kept_uses_opacity_055', (tester) async {
    await _pump(tester, PhotoTile(thumbnail: _thumb, aiKept: true));
    final opacity = tester.widget<Opacity>(find.byType(Opacity));
    expect(opacity.opacity, 0.55);
  });

  testWidgets('test_photo_tile_grid_is_three_columns_with_six_gap',
      (tester) async {
    await _pump(tester, PhotoTile(thumbnail: _thumb));
    expect(PhotoTile.gridCrossAxisCount, 3);
    expect(PhotoTile.gridSpacing, 6.0);
    expect(tester.widget<AspectRatio>(find.byType(AspectRatio)).aspectRatio, 1);
  });

  testWidgets('test_album_action_bar_always_shows_recovery_notice',
      (tester) async {
    await _pump(tester, _actionBar(), width: 390);
    expect(find.byKey(AlbumActionBar.privacyNoticeKey), findsOneWidget);
    expect(find.text(AlbumActionBar.recoveryNotice), findsOneWidget);
  });

  testWidgets('test_album_action_bar_danger_uses_danger_token_colors',
      (tester) async {
    await _pump(tester, _actionBar(), width: 390);
    final material = tester.widget<Material>(
      find.byWidgetPredicate(
        (w) => w is Material && w.color == _colors.dangerBg,
      ),
    );
    expect(material, isNotNull);
    final label = tester.widget<Text>(find.text('删除 12 张'));
    expect(label.style!.color, _colors.dangerText);
  });

  testWidgets('test_suggestion_row_requires_reason_and_paired_numbers',
      (tester) async {
    await _pump(tester, _suggestions());
    expect(find.text('超过 90 天未再打开的屏幕截图'), findsOneWidget);
    expect(find.text('38 张'), findsOneWidget);
    expect(find.text('620 MB'), findsOneWidget);
  });

  testWidgets('test_suggestion_row_last_row_has_no_divider', (tester) async {
    await _pump(tester, _suggestions());
    expect(
      _byKey(tester, SuggestionCard.rowKey(0)).decoration,
      isNotNull,
    );
    expect(
      _byKey(tester, SuggestionCard.rowKey(1)).decoration,
      isNull,
    );
  });

  testWidgets('test_suggestion_row_numbers_use_tabular_figures',
      (tester) async {
    await _pump(tester, _suggestions());
    final count = tester.widget<Text>(find.text('38 张'));
    final size = tester.widget<Text>(find.text('620 MB'));
    expect(
      count.style!.fontFeatures,
      contains(const FontFeature.tabularFigures()),
    );
    expect(
      size.style!.fontFeatures,
      contains(const FontFeature.tabularFigures()),
    );
  });

  test('test_album_icons_are_registered_and_in_cmap', () {
    final source = File(
      'lib/design_system/tokens/app_icons.dart',
    ).readAsStringSync();
    for (final name in const [
      'image',
      'images',
      'album',
      'camera',
      'play',
      'copy',
      'trash',
      'tag',
      'move',
    ]) {
      expect(
        source.contains('static const $name = IconData('),
        isTrue,
        reason: name,
      );
    }
  });

  test('test_no_hardcoded_color_in_album_components', () {
    const files = [
      'lib/design_system/components/album_cards.dart',
      'lib/design_system/components/album_report.dart',
    ];
    for (final path in files) {
      final content = File(path).readAsStringSync();
      expect(RegExp(r'Color\(0x').hasMatch(content), isFalse, reason: path);
      expect(RegExp(r'\bColors\.').hasMatch(content), isFalse, reason: path);
      for (final bad in [
        'FontWeight.w550',
        'FontWeight.w650',
        'FontWeight.w750',
      ]) {
        expect(content.contains(bad), isFalse, reason: '$path has $bad');
      }
    }
  });

  testWidgets('test_album_components_golden', (tester) async {
    await _golden(tester, 'album_storage', _storageCard());
    await _golden(
      tester,
      'album_tiles',
      Row(
        children: [
          Expanded(
            child: AlbumTile(
              thumbnail: _thumb,
              name: '旅行',
              countText: '342 张',
            ),
          ),
          const SizedBox(width: 11),
          Expanded(
            child: AlbumTile(
              thumbnail: _thumb,
              name: '截图',
              countText: '402 张 · 38 张可清理',
            ),
          ),
        ],
      ),
    );
    await _golden(
      tester,
      'album_photo_tiles',
      Row(
        children: [
          Expanded(
            child: PhotoTile(
              thumbnail: _thumb,
              durationText: '00:12',
            ),
          ),
          const SizedBox(width: 6),
          Expanded(
            child: PhotoTile(
              thumbnail: _thumb,
              selectionMode: true,
              selected: true,
            ),
          ),
          const SizedBox(width: 6),
          Expanded(
            child: PhotoTile(
              thumbnail: _thumb,
              selectionMode: true,
            ),
          ),
          const SizedBox(width: 6),
          Expanded(
            child: PhotoTile(
              thumbnail: _thumb,
              selectionMode: true,
              aiKept: true,
            ),
          ),
        ],
      ),
    );
    await _golden(
      tester,
      'album_action_bar',
      _actionBar(),
      width: 390,
    );
    await _golden(tester, 'album_suggestions', _suggestions());
  });
}
