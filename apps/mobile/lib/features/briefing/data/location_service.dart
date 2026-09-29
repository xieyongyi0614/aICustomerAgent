import 'package:geolocator/geolocator.dart';

/// 经纬度对（简报天气卡的「请求坐标」载荷）。
class CoordPair {
  const CoordPair({required this.lat, required this.lon});

  final double lat;
  final double lon;
}

/// 端侧实时定位（APP-018 定位链的「请求坐标」来源）。
///
/// 任何失败路径（未授权 / 定位服务关闭 / 超时 / 异常）一律返回 `null`：
/// 客户端不弹阻断式错误，直接不带坐标请求，由后端「偏好城市 > env 兜底」
/// 链接管——定位失败不得影响简报渲染。
class LocationService {
  const LocationService();

  Future<CoordPair?> getCurrentCoords({
    Duration timeLimit = const Duration(seconds: 5),
  }) async {
    try {
      if (!await Geolocator.isLocationServiceEnabled()) return null;
      var permission = await Geolocator.checkPermission();
      if (permission == LocationPermission.denied) {
        permission = await Geolocator.requestPermission();
      }
      if (permission == LocationPermission.denied ||
          permission == LocationPermission.deniedForever ||
          permission == LocationPermission.unableToDetermine) {
        return null;
      }
      final position = await Geolocator.getCurrentPosition(
        locationSettings: LocationSettings(
          accuracy: LocationAccuracy.low,
          timeLimit: timeLimit,
        ),
      );
      return CoordPair(lat: position.latitude, lon: position.longitude);
    } catch (_) {
      return null;
    }
  }
}
