import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../app/theme/theme_context.dart';
import '../../../core/updater/release_models.dart';
import '../../../core/updater/update_providers.dart';
import '../../../design_system/components/components.dart';

/// 关于页（skill 登记 B20 #about）：真实版本号 + 更新入口 + 更新说明。
///
/// 承接 `self-distribution-guide.md:139` 登记的缺口。备案号 / 软著名公示位
/// **只留位不填值**——内容归 `PLT-002`，本页不自行编写合规话术。
class AboutPage extends ConsumerWidget {
  const AboutPage({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final colors = context.colors;
    final type = context.typography;
    final state = ref.watch(updateControllerProvider);
    final controller = ref.read(updateControllerProvider.notifier);
    final version = state.localVersion;
    final latest = state.decision?.latest;

    return Scaffold(
      backgroundColor: colors.canvas,
      appBar: AppBar(title: const Text('关于')),
      body: ListView(
        padding: const EdgeInsets.fromLTRB(18, 8, 18, 40),
        children: [
          Padding(
            padding: const EdgeInsets.only(top: 6, bottom: 18),
            child: Text(
              '朝夕 ${version == null ? '—' : 'v${version.versionName}'} (MVP) · '
              'Personal AI OS 的第一步',
              textAlign: TextAlign.center,
              style: type.numeric(type.sub).copyWith(color: colors.ink2),
            ),
          ),
          SettingGroup(
            children: [
              SettingRow(
                title: '当前版本',
                subtitle: version == null
                    ? '读取中…'
                    : '${version.versionName}（${version.versionCode}）',
                trailing: version == null
                    ? const SizedBox(
                        width: 20,
                        height: 20,
                        child: CircularProgressIndicator(strokeWidth: 2),
                      )
                    : null,
              ),
              SettingRow(
                title: '上次检查',
                subtitle: _lastCheckText(state.checkedAt),
              ),
              SettingRow(
                title: '检查更新',
                subtitle: _checkSubtitle(state, latest),
                icon: AppIcons.download,
                iconBg: colors.tileInfo,
                iconColor: colors.tagPreferenceFg,
                trailing: state.stage == UpdateStage.checking
                    ? const SizedBox(
                        width: 20,
                        height: 20,
                        child: CircularProgressIndicator(strokeWidth: 2),
                      )
                    : Icon(
                        AppIcons.chevronRight,
                        size: 16,
                        color: colors.ink3,
                      ),
                onTap: () => controller.check(manual: true),
              ),
              SettingRow(
                title: '仅 Wi-Fi 下载',
                subtitle: '默认开启，避免用掉手机流量',
                trailing: AppToggle(
                  value: state.wifiOnly,
                  onChanged: controller.setWifiOnly,
                ),
                showDivider: false,
              ),
            ],
          ),
          if (latest?.releaseNotes != null) ...[
            Padding(
              padding: const EdgeInsets.fromLTRB(2, 6, 2, 11),
              child: Text('这个版本更新了什么', style: type.sectionTitle),
            ),
            SettingGroup(
              children: [
                Padding(
                  padding: const EdgeInsets.all(17),
                  child: Text(
                    latest!.releaseNotes!,
                    style: type.sub.copyWith(color: colors.ink2),
                  ),
                ),
              ],
            ),
          ],
          Padding(
            padding: const EdgeInsets.only(top: 10),
            child: Text(
              '备案号 / 软件著作权公示位（待 PLT-002 填写）',
              textAlign: TextAlign.center,
              style: type.caption.copyWith(color: colors.ink3),
            ),
          ),
        ],
      ),
    );
  }

  String _checkSubtitle(UpdateState state, ReleaseInfo? latest) {
    switch (state.stage) {
      case UpdateStage.checking:
        return '正在检查…';
      case UpdateStage.failed:
        return state.failure == null
            ? '检查没成功，可以再试一次'
            : updateFailureText(state.failure!);
      case UpdateStage.available:
      case UpdateStage.confirmWifi:
      case UpdateStage.downloading:
      case UpdateStage.verifying:
      case UpdateStage.readyToInstall:
      case UpdateStage.permissionRequired:
        return latest == null ? '有新版本可用' : 'v${latest.versionName} 可用';
      case UpdateStage.upToDate:
        return '已是最新';
      case UpdateStage.idle:
        return '看看有没有新版本';
    }
  }

  String _lastCheckText(DateTime? checkedAt) {
    if (checkedAt == null) {
      return '还没有检查过';
    }
    String two(int value) => value.toString().padLeft(2, '0');
    return '${checkedAt.year}-${two(checkedAt.month)}-${two(checkedAt.day)} '
        '${two(checkedAt.hour)}:${two(checkedAt.minute)}';
  }
}
