import 'package:shared_preferences/shared_preferences.dart';

import '../domain/album_models.dart';

/// album 域自有端侧元数据存储（SharedPreferences 键空间 `album.*`）。
///
/// 不复用 `LocalStores` / drift 表——那些是服务端 DTO 投影且运行时零接线
/// （`APP-034` §4.2 裁决 3）；相册域的「仅本机」语义下也只需轻量偏好。
class SharedPreferencesAlbumLocalStore implements AlbumLocalStore {
  static const _overridePrefix = 'album.override.';
  static const _lastScanKey = 'album.last_scan_at';

  const SharedPreferencesAlbumLocalStore();

  @override
  Future<Map<String, bool>> loadOverrides() async {
    final prefs = await SharedPreferences.getInstance();
    final overrides = <String, bool>{};
    for (final key in prefs.getKeys()) {
      if (!key.startsWith(_overridePrefix)) continue;
      overrides[key.substring(_overridePrefix.length)] =
          prefs.getBool(key) ?? true;
    }
    return overrides;
  }

  @override
  Future<void> saveOverride(String assetId, bool keep) async {
    final prefs = await SharedPreferences.getInstance();
    await prefs.setBool('$_overridePrefix$assetId', keep);
  }

  @override
  Future<DateTime?> loadLastScanAt() async {
    final prefs = await SharedPreferences.getInstance();
    final millis = prefs.getInt(_lastScanKey);
    return millis == null ? null : DateTime.fromMillisecondsSinceEpoch(millis);
  }

  @override
  Future<void> saveLastScanAt(DateTime at) async {
    final prefs = await SharedPreferences.getInstance();
    await prefs.setInt(_lastScanKey, at.millisecondsSinceEpoch);
  }
}
