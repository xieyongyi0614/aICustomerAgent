import 'package:flutter/foundation.dart';
import 'package:geolocator/geolocator.dart';

/// 经纬度对（天气定位链的「请求坐标」载荷）。
class CoordPair {
  const CoordPair({required this.lat, required this.lon});

  final double lat;
  final double lon;
}

/// 端侧实时定位（APP-018 定位链的「请求坐标」来源）。
///
/// 任何失败路径（未授权 / 定位服务关闭 / 超时 / 异常）一律返回 `null`：
/// 客户端不弹阻断式错误，直接不带坐标请求，由后端「偏好城市 > 请求坐标 >
/// 默认北京」链接管——定位失败不得影响页面渲染。
///
/// [requestIfDenied] 决定未授权时是否拉起系统授权弹窗：简报页等用户显式
/// 进入的界面保持默认 true；首页等启动即载的界面传 false 静默降级，
/// 避免冷启动被权限弹窗卡住。
class LocationService {
  const LocationService();

  Future<CoordPair?> getCurrentCoords({
    Duration timeLimit = const Duration(seconds: 5),
    bool requestIfDenied = true,
  }) async {
    try {
      if (!await Geolocator.isLocationServiceEnabled()) {
        _log('定位服务未开启');
        return null;
      }
      var permission = await Geolocator.checkPermission();
      if (permission == LocationPermission.denied && requestIfDenied) {
        permission = await Geolocator.requestPermission();
      }
      if (permission == LocationPermission.denied ||
          permission == LocationPermission.deniedForever ||
          permission == LocationPermission.unableToDetermine) {
        _log('定位权限未授予: $permission');
        return null;
      }
      // 低精度走网络定位：真机快而省电；模拟器没有网络定位数据源，永远
      // 拿不到 fix——给它最多 2s，超时换高精度走 GPS（模拟器靠 geo fix 供位）。
      final lowBudget = timeLimit > _lowAttemptBudget
          ? _lowAttemptBudget
          : timeLimit;
      return await _locate(LocationAccuracy.low, lowBudget) ??
          await _locate(LocationAccuracy.high, timeLimit);
    } catch (error) {
      _log('定位失败: ${error.runtimeType}: $error');
      return null;
    }
  }

  static const _lowAttemptBudget = Duration(seconds: 2);

  Future<CoordPair?> _locate(LocationAccuracy accuracy, Duration timeLimit) async {
    try {
      final position = await Geolocator.getCurrentPosition(
        locationSettings: LocationSettings(
          accuracy: accuracy,
          timeLimit: timeLimit,
        ),
      );
      _log('$accuracy 定位成功: ${position.latitude},${position.longitude}');
      return CoordPair(lat: position.latitude, lon: position.longitude);
    } catch (error) {
      _log('$accuracy 定位失败: ${error.runtimeType}: $error');
      return null;
    }
  }

  /// 与 `[net]` 同惯例的 logcat 诊断日志：定位是静默降级链，
  /// 没有这行日志时「为什么走到默认北京」完全不可见。
  void _log(String message) {
    if (kDebugMode) debugPrint('[geo] $message');
  }
}
