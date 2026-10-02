import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:mobile/app/theme/app_theme.dart';
import 'package:mobile/design_system/components/components.dart';
import 'package:mobile/design_system/tokens/tokens.dart';

Widget _wrap(Widget child) => MaterialApp(
      theme: buildAppTheme(),
      home: Scaffold(
        backgroundColor: Colors.transparent,
        body: Center(
          child: SingleChildScrollView(padding: const EdgeInsets.all(16), child: child),
        ),
      ),
    );

Future<void> _golden(WidgetTester tester, String name, Widget child) async {
  await tester.pumpWidget(_wrap(child));
  await tester.pump(const Duration(milliseconds: 16));
  await expectLater(find.byType(Scaffold), matchesGoldenFile('goldens/$name.png'));
}

void main() {
  testWidgets('golden_tab_bar', (t) async {
    // 悬浮球的「挖空外圈 + 辉光」是 A9 的观感重点，测试默认会把影子画成硬边；
    // 这里单独打开真实影子，让 golden 能守住球陷进栏里的样子（测试结束前必须还原）。
    debugDisableShadows = false;
    try {
      // 栏高 88，上方再留 32：悬浮球顶在栏顶上方 12、外圈 6，必须完整落在画布里
      t.view.physicalSize = const Size(390, AppTabBar.barHeight + 32);
      t.view.devicePixelRatio = 1;
      addTearDown(t.view.reset);
      await t.pumpWidget(
        MaterialApp(
          theme: buildAppTheme(),
          home: Scaffold(
            backgroundColor: AppColors.light.canvas,
            bottomNavigationBar: AppTabBar(currentIndex: 1, onTap: (_) {}),
          ),
        ),
      );
      await t.pump(const Duration(milliseconds: 16));
      await expectLater(
        find.byType(Scaffold),
        matchesGoldenFile('goldens/a9_tabbar.png'),
      );
    } finally {
      debugDisableShadows = true;
    }
  });

  testWidgets('golden_app_card', (t) async {
    await _golden(t, 'a1_app_card', const AppCard(child: Text('卡内容')));
  });

  testWidgets('golden_ai_card', (t) async {
    await _golden(
      t,
      'a2_ai_card',
      const AiCard(title: '今日 AI 总结', child: Text('结论正文')),
    );
  });

  testWidgets('golden_metric_card', (t) async {
    await _golden(
      t,
      'a5_metric',
      const MetricCard(label: '睡眠', value: '7h12m', note: '优于上周', sparkValues: [1, 2, 3]),
    );
  });

  testWidgets('golden_task_row', (t) async {
    await _golden(
      t,
      'a6_task',
      const AppCard(
        listPadding: true,
        child: Column(
          children: [
            TaskRow(title: '回复导师邮件', tag: '工作', done: true, showDivider: true),
            TaskRow(title: '给妈妈回电话', tag: '晚间', showDivider: false),
          ],
        ),
      ),
    );
  });

  testWidgets('golden_spend_summary', (t) async {
    await _golden(
      t,
      'a7_spend',
      SpendSummary(
        amountLabel: '¥128',
        budgetLabel: '/ 今日预算 ¥200',
        progress: 0.64,
        weekBars: [1, 2, 3, 2, 4, 3, 5],
        conclusion: '本周日均 ¥96，节奏健康 —— 亚丝娜',
      ),
    );
  });

  testWidgets('golden_ask_pill', (t) async {
    await _golden(t, 'a8_ask_pill', const AskPill());
  });

  testWidgets('golden_mode_chip', (t) async {
    await _golden(t, 'a10_mode_chip', const ModeChip(label: 'Default 模式'));
  });

  testWidgets('golden_mem_hint', (t) async {
    await _golden(t, 'a11_mem_hint', const MemHint(text: '本轮已调用 3 条长期记忆'));
  });

  testWidgets('golden_chip_button', (t) async {
    await _golden(
      t,
      'a12_chip',
      const Wrap(children: [ChipButton(label: '查看行程'), ChipButton(label: '调整', ghost: true)]),
    );
  });

  testWidgets('golden_capture', (t) async {
    await _golden(t, 'a17_capture', const CaptureBar());
  });

  testWidgets('golden_module_soon', (t) async {
    await _golden(
      t,
      'a18_soon',
      const Row(
        children: [
          Expanded(child: ModuleCard(title: '记账', summary: '本月稳', icon: Icons.wallet)),
          SizedBox(width: 11),
          Expanded(child: ModuleCard(title: '阅读', summary: 'V2 见', icon: Icons.book, soon: true)),
        ],
      ),
    );
  });

  testWidgets('golden_category_bar', (t) async {
    await _golden(
      t,
      'a19_cat',
      CategoryBar(
        label: '餐饮',
        amountLabel: '¥1,240',
        ratio: 0.78,
        gradient: const LinearGradient(colors: [Color(0xFFEFA63C), Color(0xFFFFD08A)]),
      ),
    );
  });

  testWidgets('golden_tx_row', (t) async {
    await _golden(
      t,
      'a20_tx',
      const AppCard(
        listPadding: true,
        child: TxRow(
          title: '午餐 · 一碗拉面',
          amountLabel: '-35',
          tileColor: Color(0x24EFA63C),
          iconColor: Color(0xFFEFA63C),
          icon: Icons.restaurant,
          subtitle: '今天 12:32 · 语音记账',
          showDivider: false,
        ),
      ),
    );
  });

  testWidgets('golden_source_note', (t) async {
    await _golden(t, 'a23_src', const SourceNote(text: '● 数据来自 小米手环 9 Pro'));
  });

  testWidgets('golden_memory_card', (t) async {
    await _golden(
      t,
      'a24_mem',
      const MemoryCard(
        tagLabel: '偏好',
        tagBg: Color(0x1A7A5CFF),
        tagFg: Color(0xFF7A5CFF),
        content: '喜欢海边旅行',
        sourceNote: '来源：6 次对话提及',
        usageNote: '已用于任务排序',
      ),
    );
  });

  testWidgets('golden_privacy_note', (t) async {
    await _golden(t, 'a25_privacy', const PrivacyNote(child: Text('数据由你控制')));
  });

  testWidgets('golden_setting_group', (t) async {
    await _golden(
      t,
      'a26_set',
      SettingGroup(
        children: const [
          SettingRow(title: '设备连接', icon: Icons.watch, showDivider: false),
        ],
      ),
    );
  });

  testWidgets('golden_toggle', (t) async {
    await _golden(
      t,
      'a27_tgl',
      Row(
        mainAxisAlignment: MainAxisAlignment.center,
        children: [
          AppToggle(value: true, onChanged: (_) {}),
          const SizedBox(width: 12),
          AppToggle(value: false, onChanged: (_) {}),
        ],
      ),
    );
  });

  testWidgets('golden_back_link', (t) async {
    await _golden(t, 'a30_back', const BackLink(label: '返回首页'));
  });

  testWidgets('golden_confirm_dialog', (t) async {
    await _golden(
      t,
      'confirm_dialog',
      const ConfirmDialog(
        title: '退出登录',
        message: '退出后需要重新登录才能继续同步，本机数据不会丢失。',
        confirmLabel: '退出登录',
        icon: AppIcons.logOut,
        danger: true,
      ),
    );
  });

  testWidgets('golden_proc_card', (t) async {
    await _golden(
      t,
      'a14_proc',
      ProcCard(
        title: '正在为你记账',
        steps: const [
          ProcStep(label: '提取金额', status: 'done', detail: '¥35.00'),
          ProcStep(label: '识别分类', status: 'running'),
          ProcStep(label: '确认时间', status: 'todo'),
          ProcStep(label: '保存账单', status: 'failed', detail: '稍后再试'),
        ],
      ),
    );
  });

  testWidgets('golden_message_bubble', (t) async {
    await _golden(
      t,
      'a13_msg',
      Column(
        children: const [
          MessageBubble(text: '午饭 35 元', isUser: true),
          MessageBubble(text: '已记下。', isUser: false),
        ],
      ),
    );
  });

  testWidgets('golden_chat_input', (t) async {
    await _golden(t, 'a16_input', const ChatInputBar());
  });
}
