# Quiet Hours（静音时段）

## 1. 规则

```text
默认静音：23:00 ~ 08:00（本地时区，settings.autonomy_quiet_hours_start/end）
静音期间：AutonomyPolicy 直接 IGNORE（"静音时段"）——不评估、不生成、不入队
跨午夜区间：start > end 时按 [start, 24h) ∪ [00:00, end) 处理
```

## 2. 为什么静音优先于一切动机

深夜主动消息的产品代价（打扰、观感）远大于收益；V6 的 user_care 目标（"守护用户身心"）在深夜的正确表达恰恰是**不打扰**。这条规则与人格自洽，不是外部限制。

## 3. 时区

- 服务器本地时区（`datetime.now()` 既有约定）；单用户部署下与用户时区一致。
- 多时区用户属 V8+（需 user 偏好字段），V7 不引入。

## 4. 高优先事件豁免（留接口不实现）

`autonomy-model.md` 的五条件门中，scheduled_followup 类 Trigger 将来可携带 priority，静音豁免条件为 `priority ≥ HIGH 且 trigger.type == scheduled_followup`。MVP 的 follow-up（面试询问类）一律不豁免——面试结果晚问 8 小时无伤大雅，深夜推送伤害关系。豁免代码路径以常量开关 `QUIET_HOURS_EXEMPT_TYPES: frozenset = frozenset()` 实现（空集 = 全部不豁免）。

## 5. 边界值

- `start == end` → 视为无静音时段；
- 配置非法（非 HH:MM）→ settings 校验报错（对齐 LLM_PROFILES_JSON 校验模式）；
- 静音期内到达的 Trigger：IGNORE 且**不留候选**（不需要"早上 8 点补发"——错过的关心由下一轮闲置触发自然补上）。

## 6. 测试锚点

- Case 2（Scenario 2）：23:30 用户说"我去睡觉了"→ 闲置阈值后 Worker 评估 → IGNORE("静音时段")，零 action 行；
- 边界：07:59 IGNORE、08:00 放行（mock now 注入）；
- 跨午夜：01:00 属静音、22:59 不属。
