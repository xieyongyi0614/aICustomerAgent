import 'package:flutter/material.dart';
import 'package:flutter_local_notifications/flutter_local_notifications.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:timezone/data/latest.dart' as tzdata;
import 'package:timezone/timezone.dart' as tz;

import '../core/env/app_env.dart';
import '../core/network/session_expiry.dart';
import '../core/notify/local_brief_notifier.dart';
import '../core/storage/secure_token_store.dart';
import 'router/app_router.dart';
import 'state/auth_epoch.dart';
import 'state/dynamic_tab.dart';
import 'theme/app_theme.dart';
import 'update/update_gate.dart';

late final SecureTokenStore appTokenStore;
late final LocalBriefNotifier appBriefNotifier;

Future<void> bootstrap() async {
  WidgetsFlutterBinding.ensureInitialized();
  AppEnv.ensureInitialized();
  tzdata.initializeTimeZones();
  try {
    tz.setLocalLocation(tz.getLocation(DateTime.now().timeZoneName));
  } catch (_) {
    // 时区名不可用时回退 UTC，通知仍可调度
  }
  appTokenStore = SecureTokenStore();
  await appTokenStore.readAccessToken();
  appBriefNotifier = LocalBriefNotifier(FlutterLocalNotificationsPlugin());
  await appBriefNotifier.init();
  LocalBriefNotifier.attach(appBriefNotifier);
  LocalBriefNotifier.onOpenBriefing = (payload) {
    final type = payload.contains('evening') ? 'evening' : 'morning';
    appRouter.go('/briefing?type=$type');
  };
  final container = ProviderContainer();
  await container.read(lifeModuleOrderProvider.notifier).restore();
  onUnauthorized = () async {
    await appTokenStore.clearCredentials();
    container.read(authEpochProvider.notifier).bump();
    appRouter.go('/login');
  };
  runApp(
    UncontrolledProviderScope(
      container: container,
      child: const MobileApp(),
    ),
  );
}

class MobileApp extends StatelessWidget {
  const MobileApp({super.key});

  @override
  Widget build(BuildContext context) {
    return MaterialApp.router(
      title: '朝夕',
      theme: buildAppTheme(),
      darkTheme: buildAppDarkTheme(),
      routerConfig: appRouter,
      builder: (context, child) =>
          UpdateGate(child: child ?? const SizedBox.shrink()),
    );
  }
}
