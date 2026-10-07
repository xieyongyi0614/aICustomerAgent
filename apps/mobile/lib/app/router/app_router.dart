import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';
import 'package:shared_preferences/shared_preferences.dart';

import '../../core/storage/prefs_store.dart';
import '../../core/storage/secure_token_store.dart';
import '../../design_system/components/app_tab_bar.dart';
import '../../features/briefing/presentation/briefing_page.dart';
import '../../features/album/presentation/album_ai_page.dart';
import '../../features/album/presentation/album_detail_page.dart';
import '../../features/album/presentation/album_manage_page.dart';
import '../../features/album/presentation/album_page.dart';
import '../../features/album/presentation/photo_view_page.dart';
import '../../features/car/presentation/car_add_page.dart';
import '../../features/car/presentation/car_page.dart';
import '../../features/car/presentation/car_profile_page.dart';
import '../../features/chat/presentation/chat_ledger_page.dart';
import '../../features/chat/presentation/chat_page.dart';
import '../../features/home/presentation/home_page.dart';
import '../../features/ledger/presentation/ledger_add_page.dart';
import '../../features/ledger/presentation/ledger_auto_page.dart';
import '../../features/ledger/presentation/ledger_page.dart';
import '../../features/life/presentation/life_page.dart';
import '../../features/life/presentation/memo_page.dart';
import '../../features/life/presentation/schedule_page.dart';
import '../../features/memory/presentation/memory_page.dart';
import '../../features/profile/presentation/login_page.dart';
import '../../features/profile/presentation/privacy_page.dart';
import '../../features/profile/presentation/profile_page.dart';
import '../../features/profile/presentation/verify_code_page.dart';
import '../state/dynamic_tab.dart';
import 'dynamic_tab_page.dart';

/// 路由元数据：Tab 隐藏与状态栏样式由壳层统一消费，禁止页面内局部 if。
class RouteChrome {
  const RouteChrome({
    this.hideTabBar = false,
    this.lightStatusBar = false,
  });

  final bool hideTabBar;
  final bool lightStatusBar;
}

const chromeHome = RouteChrome();
const chromeImmersive = RouteChrome(hideTabBar: true);
const chromeBriefing = RouteChrome(hideTabBar: true, lightStatusBar: true);

const chromeByPath = <String, RouteChrome>{
  '/home': chromeHome,
  '/dynamic': chromeHome,
  '/life': chromeHome,
  '/chat': chromeImmersive,
  // 记忆是「我的 · 记忆管理」子页（B7：此页无 Tab 栏）
  '/memory': chromeImmersive,
  '/profile': chromeHome,
  '/login': chromeImmersive,
  '/verify': chromeImmersive,
  '/ledger': chromeImmersive,
  '/ledger/add': chromeImmersive,
  '/ledger/auto': chromeImmersive,
  // 备忘录（41）/ 日程（42）是「生活」子页（2026-09-30 IA 裁决：宫格 6 格无悬空入口）
  '/memo': chromeImmersive,
  '/schedule': chromeImmersive,
  '/car': chromeImmersive,
  '/car/add': chromeImmersive,
  '/car/profile': chromeImmersive,
  '/album': chromeImmersive,
  '/album/manage': chromeImmersive,
  '/album/detail': chromeImmersive,
  '/album/photo': chromeImmersive,
  '/album/ai': chromeImmersive,
  '/chat/ledger': chromeImmersive,
  '/briefing': chromeBriefing,
  '/profile/privacy': chromeImmersive,
};

RouteChrome chromeForLocation(String location) {
  final path = Uri.tryParse(location)?.path ?? location;
  return chromeByPath[path] ?? chromeHome;
}

/// 主 Tab 的语义标识。Tab 归属与切换都以此为唯一真源：
/// 声明顺序即 TabBar 从左到右的顺序，禁止再用裸下标表达归属。
enum ShellTab {
  home(path: '/home'),
  dynamic(path: '/dynamic'),
  chat(path: '/chat'),
  life(
    path: '/life',
    owns: ['/ledger', '/memo', '/schedule', '/car', '/album'],
  ),
  profile(path: '/profile', owns: ['/memory']);

  const ShellTab({required this.path, this.owns = const []});

  final String path;
  final List<String> owns;

  /// 顶级路径段 → Tab 的查表，把原先的 startsWith 链收敛成一次 O(1) 命中。
  static final Map<String, ShellTab> _bySegment = {
    for (final tab in values) _segmentOf(tab.path): tab,
    for (final tab in values)
      for (final owned in tab.owns) _segmentOf(owned): tab,
  };

  static String _segmentOf(String path) =>
      path.split('/').firstWhere((s) => s.isNotEmpty, orElse: () => '');

  /// 按顶级路径段归属 Tab；`/life/detail` 与 `/life` 同为 life，
  /// 且 `/lifestyle` 不会误命中 `/life`（段级匹配，非前缀匹配）。
  static ShellTab forLocation(String location) {
    final path = Uri.tryParse(location)?.path ?? location;
    return _bySegment[_segmentOf(path)] ?? home;
  }
}

bool _entryGateChecked = false;

/// 设计稿 ⓪：无令牌且未看过登录页 → 首启落「初见登录页」；先逛逛 / 已配对直进。
Future<String?> _entryGateRedirect() async {
  try {
    final token = await SecureTokenStore().readAccessToken();
    if (token != null && token.isNotEmpty) return null;
  } catch (_) {
    return null;
  }
  try {
    final prefs = await SharedPreferences.getInstance();
    if (prefs.getBool(PrefsStore.keyLoginSeen) ?? false) return null;
  } catch (_) {}
  return '/login';
}

final appRouter = GoRouter(
  initialLocation: '/home',
  errorBuilder: (context, state) => const HomePage(),
  redirect: (context, state) async {
    if (_entryGateChecked) return null;
    _entryGateChecked = true;
    return _entryGateRedirect();
  },
  routes: [
    ShellRoute(
      builder: (context, state, child) => _AppShell(
        location: state.uri.path,
        child: child,
      ),
      routes: [
        GoRoute(path: '/home', builder: (_, _) => const HomePage()),
        GoRoute(path: '/dynamic', builder: (_, _) => const DynamicTabPage()),
        GoRoute(path: '/life', builder: (_, _) => const LifePage()),
        GoRoute(
          path: '/chat',
          builder: (_, state) => ChatPage(initialText: state.extra as String?),
        ),
        GoRoute(
          path: '/chat/ledger',
          builder: (_, state) => ChatLedgerPage(
            conversationId: state.uri.queryParameters['conversationId'],
          ),
        ),
        GoRoute(path: '/memory', builder: (_, _) => const MemoryPage()),
        GoRoute(path: '/login', builder: (_, _) => const LoginPage()),
        GoRoute(
          path: '/verify',
          builder: (_, state) =>
              VerifyCodePage(email: state.extra as String?),
        ),
        GoRoute(path: '/profile', builder: (_, _) => const ProfilePage()),
        GoRoute(
          path: '/profile/privacy',
          builder: (_, _) => const ProfilePrivacyPage(),
        ),
        GoRoute(
          path: '/ledger',
          builder: (_, state) => LedgerPage(
            backLabel: state.extra as String? ?? '生活',
          ),
        ),
        GoRoute(path: '/ledger/add', builder: (_, _) => const LedgerAddPage()),
        GoRoute(path: '/ledger/auto', builder: (_, _) => const LedgerAutoPage()),
        GoRoute(path: '/memo', builder: (_, _) => const MemoPage()),
        GoRoute(
          path: '/schedule',
          builder: (_, state) =>
              SchedulePage(backLabel: state.extra as String? ?? '生活'),
        ),
        GoRoute(path: '/car', builder: (_, _) => const CarPage()),
        GoRoute(
          path: '/car/add',
          builder: (_, state) => CarAddPage(
            initialKind: state.uri.queryParameters['kind'] ?? 'charge',
          ),
        ),
        GoRoute(
          path: '/car/profile',
          builder: (_, _) => const CarProfilePage(),
        ),
        GoRoute(path: '/album', builder: (_, _) => const AlbumPage()),
        GoRoute(
          path: '/album/manage',
          builder: (_, state) => AlbumManagePage(
            bucketId: state.uri.queryParameters['album'],
            bucketName: state.uri.queryParameters['name'],
          ),
        ),
        GoRoute(
          path: '/album/detail',
          builder: (_, state) => AlbumDetailPage(
            albumId: state.uri.queryParameters['album'],
            albumName: state.uri.queryParameters['name'],
          ),
        ),
        GoRoute(
          path: '/album/photo',
          builder: (_, state) =>
              PhotoViewPage(assetId: state.uri.queryParameters['id']),
        ),
        GoRoute(path: '/album/ai', builder: (_, _) => const AlbumAiPage()),
        GoRoute(
          path: '/briefing',
          builder: (_, state) => BriefingPage(
            type: state.uri.queryParameters['type'] ?? 'morning',
          ),
        ),
      ],
    ),
  ],
);

class _AppShell extends ConsumerWidget {
  const _AppShell({required this.location, required this.child});

  final String location;
  final Widget child;

  void _onTap(BuildContext context, int index) {
    context.go(ShellTab.values[index].path);
  }

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final dynamicModule = ref.watch(dynamicModuleProvider);
    final chrome = chromeForLocation(location);
    final tab = ShellTab.forLocation(location);
    return AnnotatedRegion<SystemUiOverlayStyle>(
      value: chrome.lightStatusBar
          ? SystemUiOverlayStyle.light
          : SystemUiOverlayStyle.dark,
      child: Scaffold(
        body: child,
        bottomNavigationBar: chrome.hideTabBar
            ? null
            : AppTabBar(
                currentIndex: tab.index,
                onTap: (i) => _onTap(context, i),
                dynamicLabel: dynamicModule.label,
                dynamicIcon: dynamicModule.icon,
              ),
      ),
    );
  }
}
