import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:go_router/go_router.dart';

import '../../design_system/components/app_tab_bar.dart';
import '../../features/briefing/presentation/briefing_page.dart';
import '../../features/chat/presentation/chat_ledger_page.dart';
import '../../features/chat/presentation/chat_page.dart';
import '../../features/health/presentation/health_consent_page.dart';
import '../../features/health/presentation/health_page.dart';
import '../../features/home/presentation/home_page.dart';
import '../../features/ledger/presentation/ledger_page.dart';
import '../../features/life/presentation/life_page.dart';
import '../../features/memory/presentation/memory_page.dart';
import '../../features/profile/presentation/pairing_page.dart';
import '../../features/profile/presentation/privacy_page.dart';
import '../../features/profile/presentation/profile_page.dart';

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
const chromeLedger = RouteChrome(hideTabBar: true);
const chromeBriefing = RouteChrome(hideTabBar: true, lightStatusBar: true);

const chromeByPath = <String, RouteChrome>{
  '/home': chromeHome,
  '/life': chromeHome,
  '/chat': chromeHome,
  '/memory': chromeHome,
  '/profile': chromeHome,
  '/health': chromeHome,
  '/ledger': chromeLedger,
  '/chat/ledger': chromeLedger,
  '/briefing': chromeBriefing,
  '/profile/privacy': chromeLedger,
  '/health/consent': chromeLedger,
  '/profile/pairing': chromeLedger,
};

RouteChrome chromeForLocation(String location) {
  final path = Uri.tryParse(location)?.path ?? location;
  return chromeByPath[path] ?? chromeHome;
}

final appRouter = GoRouter(
  initialLocation: '/home',
  errorBuilder: (context, state) => const HomePage(),
  routes: [
    ShellRoute(
      builder: (context, state, child) => _AppShell(
        location: state.uri.path,
        child: child,
      ),
      routes: [
        GoRoute(path: '/home', builder: (_, _) => const HomePage()),
        GoRoute(path: '/life', builder: (_, _) => const LifePage()),
        GoRoute(path: '/chat', builder: (_, _) => const ChatPage()),
        GoRoute(
          path: '/chat/ledger',
          builder: (_, state) => ChatLedgerPage(
            conversationId: state.uri.queryParameters['conversationId'],
          ),
        ),
        GoRoute(path: '/memory', builder: (_, _) => const MemoryPage()),
        GoRoute(path: '/profile', builder: (_, _) => const ProfilePage()),
        GoRoute(
          path: '/profile/privacy',
          builder: (_, _) => const ProfilePrivacyPage(),
        ),
        GoRoute(
          path: '/profile/pairing',
          builder: (_, _) => const PairingPage(),
        ),
        GoRoute(path: '/health', builder: (_, _) => const HealthPage()),
        GoRoute(
          path: '/health/consent',
          builder: (_, _) => const HealthConsentPage(),
        ),
        GoRoute(path: '/ledger', builder: (_, _) => const LedgerPage()),
        GoRoute(
          path: '/briefing',
          builder: (_, state) => BriefingPage(
            form: state.uri.queryParameters['form'] ?? 'morning',
          ),
        ),
      ],
    ),
  ],
);

class _AppShell extends StatelessWidget {
  const _AppShell({required this.location, required this.child});

  final String location;
  final Widget child;

  int _tabIndex(String path) {
    if (path.startsWith('/home') || path.startsWith('/health')) return 0;
    if (path.startsWith('/life') || path.startsWith('/ledger')) return 1;
    if (path.startsWith('/chat')) return 2;
    if (path.startsWith('/memory')) return 3;
    return 4;
  }

  void _onTap(BuildContext context, int index) {
    const paths = ['/home', '/life', '/chat', '/memory', '/profile'];
    context.go(paths[index]);
  }

  @override
  Widget build(BuildContext context) {
    final chrome = chromeForLocation(location);
    final index = _tabIndex(location);
    return AnnotatedRegion<SystemUiOverlayStyle>(
      value: chrome.lightStatusBar
          ? SystemUiOverlayStyle.light
          : SystemUiOverlayStyle.dark,
      child: Scaffold(
        body: child,
        bottomNavigationBar: chrome.hideTabBar
            ? null
            : AppTabBar(
                currentIndex: index,
                onTap: (i) => _onTap(context, i),
              ),
      ),
    );
  }
}
