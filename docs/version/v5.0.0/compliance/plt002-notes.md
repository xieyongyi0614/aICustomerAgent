# PLT-002 合规与上架（4 项未闭合调研结论）

| # | 事项 | 结论 |
|---|---|---|
| 1 | 中国 App 备案 | 个人主体需 ICP 备案 + 应用备案；上架国内商店前完成 |
| 2 | NMPA SaMD 分类 | 本产品仅「趋势参考 / 非医疗建议」，不宣称诊断 → 不按 SaMD 管理；文案已常驻免责 |
| 3 | Google Play 健康政策 | Health Connect 权限需单独声明用途；隐私政策写明健康数据用途 |
| 4 | 国内安卓商店健康资质 | 读健康传感器可能需「健康」类目资质；未接实机前保持空态引导，不展示医疗结论 |

健康文案纪律（红线 8）：所有健康界面常驻「非医疗建议，请咨询医生」。

## 落地文档（2026-10-08）

- `compliance/android-store-release-guide.md` — 个人主体国内安卓商店上架指南（硬门槛 / 素材规格 / 待补清单 / 权限用途表）
- `apps/mobile/docs/launcher-icon.md` — 启动图标与商店素材的手工迁入清单（路径 / 尺寸 / 裁剪参数）
- 签名：`apps/mobile/android/zhaoxi-release.jks` + `key.properties`（已被 `android/.gitignore` 排除，丢失无法覆盖升级，必须双备份）
