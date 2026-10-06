import 'package:flutter/widgets.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../features/album/presentation/album_page.dart';
import '../../features/car/presentation/car_page.dart';
import '../../features/ledger/presentation/ledger_page.dart';
import '../../features/life/presentation/memo_page.dart';
import '../../features/life/presentation/schedule_page.dart';
import '../state/dynamic_tab.dart';

/// 「动态」Tab 根页：按用户设定渲染对应模块页。
/// 作为 Tab 根，模块页不显示「‹ 生活」返回链接（宫格进入时才显示）。
class DynamicTabPage extends ConsumerWidget {
  const DynamicTabPage({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final module = ref.watch(dynamicModuleProvider);
    return switch (module) {
      LifeModule.ledger => const LedgerPage(showBackLink: false),
      LifeModule.memo => const MemoPage(showBackLink: false),
      LifeModule.schedule => const SchedulePage(showBackLink: false),
      LifeModule.car => const CarPage(showBackLink: false),
      LifeModule.album => const AlbumPage(showBackLink: false),
    };
  }
}
