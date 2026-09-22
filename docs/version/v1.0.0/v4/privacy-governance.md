# Privacy Tiers & Memory Governance（V4-012 结论文档）

> **改写性质登记（V4.0 PLA-003，2026-09-22）**：本文档属**策略结论更新**，非史实改写。V4.0 将「财务数据」由 L2「不保存」重裁为 **L1 受控保存**（见 §1.1 与 §1.3）。这是 V4.0 **唯一允许修改的历史文档**（架构 §4.7）；`privacy.md` 原始策略文件不动。
> 本 Task 为 P2 仅文档，产出结论供后续版本实现。现状以 privacy.md 为准：V4 第一版记忆只存本地 PostgreSQL，分级与总量治理未实施。

## 1. 敏感信息分级保存策略（结论）

### 1.1 分级定义

| 级别 | 内容示例 | V4 现状 | 目标策略 |
|---|---|---|---|
| L0 公开/普通 | 喜欢的食物、所在城市、兴趣爱好 | 照常保存 | 不变 |
| L1 一般隐私 | 工作单位、职位、健康习惯、**财务数据（账目）** | 照常保存（本地库） | 照常保存，可被 `expires_at` 回收；**财务账目另见 §1.3** |
| L2 敏感 | 身份证号、详细住址门牌 | 照常保存（有风险） | **不保存**：Extractor 输出后 Policy 新增 R9 直接丢弃并 trace 记 `privacy_drop` |
| L3 医疗/心理 | 病历、心理状态推断 | 照常保存（有风险） | 仅在用户明确要求记住时保存（source 必须为 user_stated 且带显式指令） |

### 1.2 实施要点（当启用 L2/L3 时）

- 识别方式：Extractor prompt 增加分级说明输出 `sensitivity` 字段 + Policy 端正则兜底（身份证/银行卡号模式），双保险。
- L2 丢弃是硬规则（沿用 R1 优先级思路），不提供豁免；trace 记录丢弃原因但不记录原文。
- Prompt 注入面控制不变：注入只含 content + type 标签。

### 1.3 账本类数据重裁（V4.0 PLA-003）

**财务数据由 L2「不保存」降为 L1「受控保存」**，条件如下（缺一不可）：

| 条件 | 说明 |
|---|---|
| 本地存储 | 账目落本地 PostgreSQL 账本域，不外传 |
| 用户可控 | 提供导出（JSON/CSV）与删除（级联零残留） |
| 明细永不进 Prompt | 见 §1.4 |
| 记录级溯源 | 每条账目带 `source` + `source_ref` |

**记忆域的 R1~R8 与敏感分级 R9 不动**；本重裁只作用于**账本域**与治理服务。账目金额明细**永不进 `memories` / `memory_candidates`**。

### 1.4 账本类数据的 Prompt 边界

- **禁止**：账目明细（单笔金额、商户、时间组合）进入任何 Prompt 上下文 / prompt 快照 / trace 明文。
- **允许**：聚合结果（合计、分布、计数）进入 Prompt；推荐显式使用「合计 / 总计 / 分布 / 共 N 笔」等聚合语境表述。
- 护栏：`services/governance/prompt_guard.py::assert_no_financial_detail`，账本相关链路写 prompt 前调用。

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
- **V4.0 例外**：财务数据 L1 受控保存与导出/删除权利面随 PLA-003 落地；账本域登记归 PLA-005。
- 当前规模下（单用户候选上限 3 条/轮 + expires_at 回收）库膨胀风险可控，不构成 V4 验收阻塞项。
