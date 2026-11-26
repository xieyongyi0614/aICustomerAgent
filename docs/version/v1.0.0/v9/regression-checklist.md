# Roleplay V9 Action System Regression Checklist（真实模型人工回归）

> 前置：V9-001~010 已实现。真实模型下验证「行动是真执行、如实报告、可审计」，并完成三条主线演练。
> 执行前：`alembic upgrade head`（落至迁移 0021），`.env` 设置 `ACTION_ENABLED=true`（出厂默认 false，人工回归时才开启）。

## 1. 开关准备（开关矩阵）

| 环境变量 | 取值 | 目的 |
|---|---|---|
| `ACTION_ENABLED` | false→true | 总开关；每一步先以 false 对照（回到 V8.5），再切 true |
| `ACTION_DETECTOR_ENABLED` | true | 只观测检测（不改执行） |
| `ACTION_RELATIONSHIP_ENABLED` | false（默认） | 关系信号投递（保持默认关） |
| `AUTONOMY_ACTION_ENABLED` | false（默认） | 自治产行动分支（保持默认关） |
| `EVALUATION_ACTION_ENABLED` | true | 行动评估护栏 |
| `WORLD_ENABLED` | true | 世界宿主（Reminder=WorldEvent 必须有） |

对照纪律：切到 `ACTION_ENABLED=false` 后，用同一批消息跑一遍，非行动消息回复与开启时逐字节一致、无任何动作痕迹。

## 2. 三条主线演练

### 主线 A：委托提醒（Reminder 全链）

| # | 动作 | 核对点 | 结果 |
|---|---|---|---|
| A1 | 聊天「明天早上8点提醒我开会」 | 回复只能进行时承诺（"我去设个提醒"），**不得**宣称"已经设好" | ☐ |
| A2 | 后台完成动作 | `/debug/actions` 出现一条 create_reminder **succeeded** ActionRecord | ☐ |
| A3 | 下轮世界切片 | 【当前世界】含 reminder(scheduled, due=明天 8:00) | ☐ |
| A4 | 下轮行动段 | 【行动】显示"设提醒：开会"；此后可作完成宣称 | ☐ |
| A5 | 到期前取消「不用提醒了」 | 行动 cancel_reminder；事件 cancelled | ☐ |

### 主线 B：显式记忆（remember_fact）

| # | 动作 | 核对点 | 结果 |
|---|---|---|---|
| B1 | 聊天「记住我生日是7月30日」 | 回复进行时承诺；行动段可见「记住：…」 | ☐ |
| B2 | `/debug/actions` | remember_fact succeeded，effect[memory] 有 memory_id | ☐ |
| B3 | memories 库 | 沉淀 source=user_stated 的 user_fact，仅一条（防双写） | ☐ |
| B4 | 重复委托同事实 | 不重复沉淀（effects 幂等） | ☐ |

### 主线 C：失败补救（Failure → 澄清 → 成功）

| # | 动作 | 核对点 | 结果 |
|---|---|---|---|
| C1 | 聊天「提醒我睡觉」（无时间） | 回复进行时承诺；后台记录 cancelled(ambiguous_params) | ☐ |
| C2 | 下轮澄清「今晚10点提醒我睡觉」 | 行动段标注上次待补救；新行动 create_reminder succeeded | ☐ |
| C3 | 宣称一致性抽查 | 角色完成时宣称"已设好"必须能与 succeeded ActionRecord 对账；若有 failed 却宣称完成 → `/debug`+评估应能识别 | ☐ |

## 3. 错误/边界抽查

| # | 场景 | 核对点 | 结果 |
|---|---|---|---|
| E1 | `ACTION_ENABLED=false` 时发「明天提醒我开会」 | 无 ActionRecord、无 WorldEvent、回复与 V8.5 一致 | ☐ |
| E2 | 角色说"我做完了"但行动实际 failed | 评估出现 action_overclaim（warning） | ☐ |
| E3 | `/debug/actions` 详情 | 能看 status / result / error / gate_reason / steps / timestamps | ☐ |
| E4 | 手动重试/取消端点 | 仅对可重试/可取消状态生效，其余 409 | ☐ |

## 4. 审计演练（/debug/actions）

1. 列表按 user/status/action_type/时间窗过滤 → 应可用。
2. 任选一条 succeeded 记录 → 对账其 effect[world]/effect[memory] 宿主是否真实存在（防幻觉登记）。
3. 任选一条 failed 记录 → 看失败原因；用 retry 端点触发重试后观察 attempt 递增与退避。

> 基线：行动关闭时全量既有测试（1120+）零回归、golden 字节不变；行动开启时非行动消息逐字节不变。全部 `tests/v9/` 单命令可绿。
>
> 归档说明（2026-10-08）：`tests/v9/` 套件已删除，动作域覆盖由 `tests/v26/`（`--run-legacy` 启用）承接；本行仅存历史坐标。登记见 `docs/TESTING.md` §9。