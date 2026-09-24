import 'package:go_router/go_router.dart';

import '../../features/briefing/presentation/briefing_page.dart';
import '../../features/chat/presentation/chat_page.dart';
import '../../features/health/presentation/health_page.dart';
import '../../features/home/presentation/home_page.dart';
import '../../features/ledger/presentation/ledger_page.dart';
import '../../features/life/presentation/life_page.dart';
import '../../features/memory/presentation/memory_page.dart';
import '../../features/profile/presentation/profile_page.dart';

final appRouter = GoRouter(
  initialLocation: '/home',
  routes: [
    GoRoute(path: '/home', builder: (_, _) => const HomePage()),
    GoRoute(path: '/life', builder: (_, _) => const LifePage()),
    GoRoute(path: '/chat', builder: (_, _) => const ChatPage()),
    GoRoute(path: '/ledger', builder: (_, _) => const LedgerPage()),
    GoRoute(path: '/memory', builder: (_, _) => const MemoryPage()),
    GoRoute(path: '/health', builder: (_, _) => const HealthPage()),
    GoRoute(path: '/profile', builder: (_, _) => const ProfilePage()),
    GoRoute(path: '/briefing', builder: (_, _) => const BriefingPage()),
  ],
);
