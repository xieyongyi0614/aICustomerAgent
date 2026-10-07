import 'dart:io';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:mobile/app/theme/app_theme.dart';
import 'package:mobile/design_system/components/components.dart';
import 'package:mobile/design_system/tokens/tokens.dart';

final _colors = AppColors.light;

Widget _wrap(Widget child) => MaterialApp(
      theme: buildAppTheme(),
      home: Scaffold(
        backgroundColor: AppColors.light.canvas,
        body: Center(
          child: SingleChildScrollView(
            padding: const EdgeInsets.all(16),
            child: SizedBox(width: 320, child: child),
          ),
        ),
      ),
    );

Future<void> _pump(WidgetTester tester, Widget child) async {
  await tester.pumpWidget(_wrap(child));
  await tester.pump(const Duration(milliseconds: 16));
}

Future<void> _golden(WidgetTester tester, String name, Widget child) async {
  await _pump(tester, child);
  await expectLater(
    find.byType(Scaffold),
    matchesGoldenFile('goldens/$name.png'),
  );
}

BoxDecoration _decorationOf(Container container) =>
    container.decoration! as BoxDecoration;

Iterable<Container> _containers(WidgetTester tester) =>
    tester.widgetList<Container>(find.byType(Container));

bool _hasBackground(WidgetTester tester, Color color) => _containers(tester).any(
      (container) => _decorationOf(container).color == color,
    );

void main() {
  testWidgets('test_entry_card_renders_title_and_dynamic_subtitle',
      (tester) async {
    await _pump(
      tester,
      EntryCard(
        title: '记一笔',
        subtitle: '本月已自动记 42 笔',
        icon: AppIcons.wallet,
        accent: EntryAccent.money,
        onTap: () {},
      ),
    );
    expect(find.text('记一笔'), findsOneWidget);
    expect(find.text('本月已自动记 42 笔'), findsOneWidget);
    expect(
      find.byIcon(AppIcons.chevronRight),
      findsOneWidget,
      reason: 'A31：entry 是横向行卡，右侧带 chevron',
    );
  });

  testWidgets('test_sync_link_renders_sparkle_label_and_chevron',
      (tester) async {
    await _pump(
      tester,
      SyncLink(label: '本月已自动记 42 笔 · 同步与 AI 规则', onTap: () {}),
    );
    expect(find.text('本月已自动记 42 笔 · 同步与 AI 规则'), findsOneWidget);
    expect(find.byType(SparkleIcon), findsOneWidget);
    expect(find.byIcon(AppIcons.chevronRight), findsOneWidget);
  });

  testWidgets('test_ledger_amount_uses_tabular_figures', (tester) async {
    await _pump(
      tester,
      const LedgerAmount(label: '金额', amountText: '128.00', focused: false),
    );
    final amount = tester.widget<Text>(find.text('128.00'));
    expect(amount.style!.fontSize, 38);
    expect(amount.style!.fontWeight, FontWeight.w700);
    expect(amount.style!.fontFeatures, contains(const FontFeature.tabularFigures()));
  });

  testWidgets('test_ledger_seg_selected_has_white_fill_and_shadow',
      (tester) async {
    await _pump(
      tester,
      LedgerSeg(
        value: 'expense',
        onChanged: (_) {},
        options: const [
          LedgerSegOption(value: 'expense', label: '支出'),
          LedgerSegOption(value: 'income', label: '收入'),
        ],
      ),
    );
    final selected = _containers(tester).firstWhere(
      (container) => _decorationOf(container).color == _colors.surface,
    );
    expect(_decorationOf(selected).boxShadow, isNotEmpty);
  });

  testWidgets('test_ledger_kind_grid_selected_border_is_money_accent',
      (tester) async {
    await _pump(
      tester,
      LedgerKindGrid(
        selectedKey: 'food',
        onSelected: (_) {},
        items: const [
          LedgerKindItem(key: 'food', label: '餐饮', icon: AppIcons.coffee),
          LedgerKindItem(key: 'traffic', label: '交通', icon: AppIcons.train),
          LedgerKindItem(key: 'shop', label: '购物', icon: AppIcons.wallet),
          LedgerKindItem(key: 'fun', label: '娱乐', icon: AppIcons.sparkles),
        ],
      ),
    );
    final accent = _colors.money.withValues(alpha: 0.55);
    final bordered = _containers(tester).where((container) {
      final decoration = _decorationOf(container);
      final border = decoration.border;
      return border is Border && border.top.color == accent;
    });
    expect(bordered, hasLength(1));
    expect(accent, isNot(_colors.aiPrimary));
  });

  testWidgets('test_ledger_save_button_uses_ink_not_ai_gradient',
      (tester) async {
    await _pump(tester, LedgerSaveButton(label: '保存', onPressed: () {}));
    expect(_hasBackground(tester, _colors.ink), isTrue);
    for (final container in _containers(tester)) {
      final decoration = _decorationOf(container);
      expect(decoration.gradient, isNull);
    }
    expect(find.byType(ShaderMask), findsNothing);
  });

  testWidgets('test_ledger_save_button_ghost_is_outlined_without_shadow',
      (tester) async {
    await _pump(
      tester,
      LedgerSaveButton(label: '取消', ghost: true, onPressed: () {}),
    );
    final ghost = _containers(tester).firstWhere(
      (container) => _decorationOf(container).color == _colors.surface,
    );
    final decoration = _decorationOf(ghost);
    expect(decoration.boxShadow, isNull);
    expect((decoration.border! as Border).top.color, _colors.line);
    final label = tester.widget<Text>(find.text('取消'));
    expect(label.style!.color, _colors.ink2);
  });

  testWidgets('test_ledger_save_button_inline_variant_drops_shadow',
      (tester) async {
    await _pump(
      tester,
      LedgerSaveButton(label: '保存档案', elevated: false, onPressed: () {}),
    );
    final primary = _containers(tester).firstWhere(
      (container) => _decorationOf(container).color == _colors.ink,
    );
    expect(_decorationOf(primary).boxShadow, isNull);
  });

  testWidgets('test_ledger_save_button_ghost_matches_primary_size',
      (tester) async {
    await _pump(
      tester,
      Row(
        children: [
          Expanded(
            child: LedgerSaveButton(label: '取消', ghost: true, onPressed: () {}),
          ),
          const SizedBox(width: 10),
          Expanded(
            child: LedgerSaveButton(label: '保存档案', onPressed: () {}),
          ),
        ],
      ),
    );
    final ghostSize =
        tester.getSize(find.widgetWithText(LedgerSaveButton, '取消'));
    final primarySize =
        tester.getSize(find.widgetWithText(LedgerSaveButton, '保存档案'));
    expect(ghostSize.height, closeTo(primarySize.height, 0.5));
    expect(ghostSize.width, primarySize.width);
  });

  testWidgets('test_ledger_stat_card_value_and_unit_typography', (tester) async {
    await _pump(
      tester,
      const LedgerStatCard(value: '42', unit: '笔', label: '本月自动记账'),
    );
    final value = tester.widget<Text>(find.text('42'));
    expect(value.style!.fontSize, 19);
    expect(value.style!.fontWeight, FontWeight.w700);
    final unit = tester.widget<Text>(find.text('笔'));
    expect(unit.style!.fontSize, 11);
    expect(unit.style!.color, _colors.ink3);
  });

  testWidgets('test_ledger_confirm_row_primary_is_health_and_ghost_is_surface',
      (tester) async {
    await _pump(
      tester,
      LedgerConfirmRow(
        title: '苹果店 · 3200',
        judgment: '我的判断：数码',
        actions: [
          LedgerConfirmAction(label: '修改', onTap: () {}),
          LedgerConfirmAction(
            label: '确认',
            onTap: () {},
            kind: LedgerActionKind.primary,
          ),
          LedgerConfirmAction(label: '忽略', onTap: () {}),
        ],
      ),
    );
    expect(_hasBackground(tester, _colors.health), isTrue);
    final ghost = _containers(tester).firstWhere((container) {
      final decoration = _decorationOf(container);
      final border = decoration.border;
      return decoration.color == _colors.surface &&
          border is Border &&
          border.top.color == _colors.line;
    });
    expect(_decorationOf(ghost).color, _colors.surface);
  });

  testWidgets('test_ledger_rule_row_renders_keyword_target_source',
      (tester) async {
    await _pump(
      tester,
      const LedgerRuleRow(keyword: '奶茶', target: '饮品', sourceNote: '来自你的分类修正'),
    );
    expect(find.text('奶茶'), findsOneWidget);
    expect(find.text('饮品'), findsOneWidget);
    expect(find.text('来自你的分类修正'), findsOneWidget);

    await _pump(tester, const LedgerRuleRow(keyword: '奶茶', target: '饮品'));
    expect(find.text('奶茶'), findsOneWidget);
    expect(find.text('饮品'), findsOneWidget);
    expect(find.byType(Text), findsNWidgets(2));
  });

  testWidgets('test_ledger_form_rows_placeholder_and_helper', (tester) async {
    await _pump(
      tester,
      const LedgerFormRows(
        rows: [
          LedgerFormRow(label: '账户', value: '微信零钱'),
          LedgerFormRow(label: '备注', placeholder: '写下备注，自动匹配分类'),
          LedgerFormRow(label: '时间', value: '今天 12:32', helper: '按记账时刻'),
        ],
      ),
    );
    expect(find.text('微信零钱'), findsOneWidget);
    final placeholder = tester.widget<Text>(find.text('写下备注，自动匹配分类'));
    expect(placeholder.style!.color, _colors.ink3);
    expect(placeholder.style!.fontWeight, FontWeight.w400);
    expect(find.text('按记账时刻'), findsOneWidget);
  });

  test('test_no_hardcoded_color_in_new_components', () {
    const files = [
      'lib/design_system/components/entry_card.dart',
      'lib/design_system/components/ledger_input.dart',
      'lib/design_system/components/ledger_auto.dart',
      'lib/design_system/components/press_scale.dart',
    ];
    for (final path in files) {
      final content = File(path).readAsStringSync();
      expect(RegExp(r'Color\(0x').hasMatch(content), isFalse, reason: path);
      expect(RegExp(r'\bColors\.').hasMatch(content), isFalse, reason: path);
      for (final bad in ['FontWeight.w550', 'FontWeight.w650', 'FontWeight.w750']) {
        expect(content.contains(bad), isFalse, reason: '$path has $bad');
      }
    }
  });

  testWidgets('golden_ledger_components', (tester) async {
    await _golden(
      tester,
      'ledger_entry',
      EntryCard(
        title: '记一笔',
        subtitle: '键盘输入，或直接说给亚丝娜',
        icon: AppIcons.wallet,
        onTap: () {},
      ),
    );
    await _golden(
      tester,
      'ledger_sync_link',
      SyncLink(label: '本月已自动记 42 笔 · 同步与 AI 规则', onTap: () {}),
    );
    await _golden(
      tester,
      'ledger_seg',
      LedgerSeg(
        value: 'expense',
        onChanged: (_) {},
        options: const [
          LedgerSegOption(value: 'expense', label: '支出'),
          LedgerSegOption(value: 'income', label: '收入'),
        ],
      ),
    );
    await _golden(
      tester,
      'ledger_amount',
      const LedgerAmount(label: '金额', amountText: '128.00'),
    );
    await _golden(
      tester,
      'ledger_kind',
      LedgerKindGrid(
        selectedKey: 'food',
        items: const [
          LedgerKindItem(key: 'food', label: '餐饮', icon: AppIcons.coffee),
          LedgerKindItem(key: 'traffic', label: '交通', icon: AppIcons.train),
          LedgerKindItem(key: 'shop', label: '购物', icon: AppIcons.wallet),
          LedgerKindItem(key: 'fun', label: '娱乐', icon: AppIcons.sparkles),
          LedgerKindItem(key: 'home', label: '居住', icon: AppIcons.layoutGrid),
          LedgerKindItem(key: 'care', label: '医疗', icon: AppIcons.activity),
          LedgerKindItem(key: 'trip', label: '旅行', icon: AppIcons.plane),
          LedgerKindItem(key: 'more', label: '其他', icon: AppIcons.repeat),
        ],
      ),
    );
    await _golden(
      tester,
      'ledger_form',
      const LedgerFormRows(
        rows: [
          LedgerFormRow(label: '账户', value: '微信零钱'),
          LedgerFormRow(label: '备注', placeholder: '写下备注，自动匹配分类'),
          LedgerFormRow(label: '时间', value: '今天 12:32', helper: '按记账时刻'),
        ],
      ),
    );
    await _golden(tester, 'ledger_pad', const LedgerPad());
    await _golden(
      tester,
      'ledger_save',
      LedgerSaveButton(label: '保存', onPressed: () {}),
    );
    await _golden(
      tester,
      'ledger_stat',
      const Row(
        children: [
          Expanded(child: LedgerStatCard(value: '42', unit: '笔', label: '本月自动记账')),
          SizedBox(width: 9),
          Expanded(child: LedgerStatCard(value: '3', unit: '笔', label: '待你确认')),
        ],
      ),
    );
    await _golden(
      tester,
      'ledger_confirm',
      LedgerConfirmRow(
        title: '苹果店 · ¥3,200',
        judgment: '我的判断：数码',
        showDivider: false,
        actions: [
          LedgerConfirmAction(label: '修改', onTap: () {}),
          LedgerConfirmAction(
            label: '确认',
            onTap: () {},
            kind: LedgerActionKind.primary,
          ),
        ],
      ),
    );
    await _golden(
      tester,
      'ledger_rule',
      const Column(
        children: [
          LedgerRuleRow(keyword: '奶茶', target: '饮品', sourceNote: '来自你的分类修正'),
          LedgerRuleRow(keyword: '充电桩', target: '交通 / 加油'),
        ],
      ),
    );
  });
}
