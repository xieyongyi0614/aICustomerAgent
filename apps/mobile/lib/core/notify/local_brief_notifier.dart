import 'package:flutter_local_notifications/flutter_local_notifications.dart';
import 'package:timezone/timezone.dart' as tz;

/// APP-019 本地通知：按设定时刻触发，点击落简报页。
/// 关闭 = 未设定时刻（参数类，非 *_enabled）。
class LocalBriefNotifier {
  LocalBriefNotifier(this._plugin);

  final FlutterLocalNotificationsPlugin _plugin;

  static const channelId = 'zhaoxi_brief';
  static const channelName = '朝夕简报';

  Future<void> init() async {
    const android = AndroidInitializationSettings('@mipmap/ic_launcher');
    const ios = DarwinInitializationSettings();
    await _plugin.initialize(
      const InitializationSettings(android: android, iOS: ios),
      onDidReceiveNotificationResponse: _onTap,
    );
  }

  static void _onTap(NotificationResponse response) {
    // 落地简报页由路由层处理（payload: briefing:morning|evening）
  }

  Future<void> scheduleDaily({
    required int hour,
    required int minute,
    required bool evening,
  }) async {
    final tzNow = tz.TZDateTime.now(tz.local);
    var when = tz.TZDateTime(tz.local, tzNow.year, tzNow.month, tzNow.day, hour, minute);
    if (when.isBefore(tzNow)) {
      when = when.add(const Duration(days: 1));
    }
    await _plugin.zonedSchedule(
      evening ? 2 : 1,
      evening ? '晚间总结' : '早间简报',
      evening ? '今天辛苦了，看看明天怎么排' : '早上好，今天交给我吧',
      when,
      const NotificationDetails(
        android: AndroidNotificationDetails(
          channelId,
          channelName,
          importance: Importance.defaultImportance,
        ),
        iOS: DarwinNotificationDetails(),
      ),
      androidScheduleMode: AndroidScheduleMode.inexactAllowWhileIdle,
      uiLocalNotificationDateInterpretation:
          UILocalNotificationDateInterpretation.absoluteTime,
      matchDateTimeComponents: DateTimeComponents.time,
      payload: evening ? 'briefing:evening' : 'briefing:morning',
    );
  }

  Future<void> cancelAll() => _plugin.cancelAll();
}

/// 由「设定时刻」参数驱动；null = 关闭。
class CareSchedulePrefs {
  CareSchedulePrefs({this.morningHHmm, this.eveningHHmm});

  String? morningHHmm;
  String? eveningHHmm;

  bool get morningOn => morningHHmm != null && morningHHmm!.isNotEmpty;
  bool get eveningOn => eveningHHmm != null && eveningHHmm!.isNotEmpty;

  (int, int)? parse(String? hhmm) {
    if (hhmm == null || !hhmm.contains(':')) return null;
    final p = hhmm.split(':');
    final h = int.tryParse(p[0]);
    final m = int.tryParse(p[1]);
    if (h == null || m == null) return null;
    return (h, m);
  }
}

/// 权限被拒时的引导文案。
const notificationDeniedGuide = '需要打开通知权限，才能在设定时刻收到简报';
