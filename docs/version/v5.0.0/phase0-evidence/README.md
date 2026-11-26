# Phase 0 证据附件目录

> 归属任务：`PLT-001 Phase 0 Mi Band On-Device Validation`
> 主报告：`../phase0-miband-validation.md`
> 命名规则：`{命题}-{日期}-{说明}.{png|mp4}`

## 命名约定

| 前缀 | 含义 |
|---|---|
| `P1-` | 原生写入命题（数据来源列表、同步开关） |
| `P2-` | 可同步字段命题（逐字段截图） |
| `P3-` | 同步延迟命题（测量记录、录屏） |
| `R1-` | 降级路径验证（CSV 导出、Gadgetbridge 状态） |

## 期望文件

| 文件 | 对应命题 | 说明 |
|---|---|---|
| `P1-YYYY-MM-DD-datasource.png` | P1 | 系统健康应用「数据来源 / 已连接应用」列表截图 |
| `P1-YYYY-MM-DD-mifitness-sync-switch.png` | P1 | Mi Fitness 内「同步至健康平台」开关状态（如有） |
| `P2-YYYY-MM-DD-fields.png` | P2 | 逐字段核对截图 |
| `P3-YYYY-MM-DD-delay.png` | P3 | 延迟测量记录 / 录屏 |
| `R1-YYYY-MM-DD-csv-export.png` | 降级① | Mi Fitness / Huami GDPR 导出入口 |
| `R1-YYYY-MM-DD-gadgetbridge.png` | 降级② | Gadgetbridge 设备支持状态页 |

> ⚠️ 截图前请**遮蔽个人信息**（手机号、账号、头像）。健康数值本身是本任务的验证对象，需保留。
