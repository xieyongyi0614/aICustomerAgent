# Privacy Tiers & Memory Governance（V4-012 结论文档）

> 本 Task 为 P2 仅文档，产出结论供后续版本实现。现状以 privacy.md 为准：V4 第一版记忆只存本地 PostgreSQL，分级与总量治理未实施。

## 1. 敏感信息分级保存策略（结论）

### 1.1 分级定义

| 级别 | 内容示例 | V4 现状 | 目标策略 |
|---|---|---|---|
| L0 公开/普通 | 喜欢的食物、所在城市、兴趣爱好 | 照常保存 | 不变 |
| L1 一般隐私 | 工作单位、职位、健康习惯 | 照常保存（本地库） | 照常保存，可被 `expires_at` 回收 |
| L2 敏感 | 身份证号、详细住址门牌、财务数据 | 照常保存（有风险） | **不保存**：Extractor 输出后 Policy 新增 R9 直接丢弃并 trace 记 `privacy_drop` |
| L3 医疗/心理 | 病历、心理状态推断 | 照常保存（有风险） | 仅在用户明确要求记住时保存（source 必须为 user_stated 且带显式指令） |

### 1.2 实施要点（当启用 L2/L3 时）

- 识别方式：Extractor prompt 增加分级说明输出 `sensitivity` 字段 + Policy 端正则兜底（身份证/银行卡号模式），双保险。
- L2 丢弃是硬规则（沿用 R1 优先级思路），不提供豁免；trace 记录丢弃原因但不记录原文。
- Prompt 注入面控制不变：注入只含 content + type 标签。

## 2. 单用户 active 记忆总量治理（结论）

### 2.1 软上限：200 条（privacy.md 已定）

| 指标 | 值 | 依据 |
|---|---|---|
| 单轮候选上限 | 3 条（settings.memory_max_candidates） | 已实现，防刷库硬上界 |
| 单条 content | ≤ 50 字 | extractor prompt 约束 + Policy R8 兜底 |
| active 软上限 | 200 条 / 用户 | 达到后保存策略见 2.2 |
| 回收 | expires_at 定期批量 invalidated | V4-011 已实现 |

### 2.2 达到 200 条后的写入策略（未实现，按此执行）

1. **不自动删除用户记忆**（privacy.md 原则）。
2. 新候选照常走 Policy；Conflict Resolver 若产生 update/supersede 则正常执行（替换不算增长）。
3. 仅当确要新增 active 行且 active 数已达 200：
   - 候选 importance ≥ 当前 active 中最低 importance → 新行照常保存，并将最低 importance 的最旧一行置 `superseded`（软失效，保留审计链）；
   - 候选 importance < 最低值 → 丢弃候选，trace 记 `capacity_drop`。
4. superseded/invalidated 行不占 200 名额；长期可归档到冷表（本版不做）。

### 2.3 监控建议

- 记录每用户 active 计数（Debug API 已可查全量）；
- `capacity_drop` / `privacy_drop` 出现频率进入日志监控。

## 3. 实施边界

- 本文档仅为结论记录；分级（R9）与 200 条写入策略均未实现，实现时需新增 Task（涉及 extractor prompt、memory_policy、memory_service）。
- 当前规模下（单用户候选上限 3 条/轮 + expires_at 回收）库膨胀风险可控，不构成 V4 验收阻塞项。
