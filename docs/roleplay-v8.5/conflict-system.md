# V8.5 M5：Conflict System（冲突系统）

> tension 是标量，冲突是过程。本文给冲突一个显式状态机（紧张→冲突→冷战→修复→和解），补上疏远检测与张力自然消退，让"长期忽略"和"吵一架"有各自可审计的生命周期。

## 1. 冲突状态机

状态存 `relationship_conflicts`（历史表，单用户单活跃）+ `relationship_state.conflict_status`（当前态冗余，policy/prompt 单行读取）：

```text
none → strain → conflict → cold → recovery → resolved
```

迁移表（全部纯函数，输入 = Outcome + 状态 + 时间；非法迁移被拒并触发评估 conflict_state_invalid）：

| 当前 | 触发 | 目标 | 效果 |
|---|---|---|---|
| none | tension > 0.5（复用冻结阈值）或当日账本负向事件 ≥ 2 | strain | prompt 距离 note（M7） |
| strain | conflict / boundary_violation 事件升格 | conflict | tension 冻结（V5 既有）+ M8 R1 生效 |
| strain | tension ≤ 0.3 且 48h 无新负向 | none | 静默解除（记一行 system 账本） |
| conflict | rel_conflict_cold_hours=12h 内无修复信号 | cold | comfort 基线 −0.10（M1 §4） |
| conflict / cold | recovery 词表命中（§3） | recovery | 修复通道开启 |
| recovery | 累计 rel_conflict_recover_positive=2 个正向事件 | resolved | tension 折半、comfort +0.05、resolution=reconciled |
| recovery | 7 天无正向也无负向 | cold | 修复失败回落 |
| cold | tension 日衰减至 ≤ 0.3 且连续 3 天无负向 | resolved | resolution=time_heals |

- 冲突期内新负向事件刷新 last_negative_at（cold 计时归零）。
- resolved 后同轮再遇 conflict 事件 → 旧行闭合、新行开启（历史保留）。
- tension 折半 / comfort 恢复等结算 delta 走账本 source=system（无信号变化的显式"因"，评估对账白名单成员）。

## 2. 设计要点

- **strain 进入复用 tension>0.5**：不发明第二套阈值——V5 的"冻结升级"语义就是 strain 的既有效果，状态机只是给它命名并扩展后续阶段。
- **道歉本身不加分**：recovery 词表命中只开通道；关系修复靠修复期内的正向互动（recovery 需 2 个正向事件）——修复是行为不是一句话（原则 2 的冲突版）。
- **cold 期治疗**：comfort 基线下调 + 主动行为强抑制（M8 R1）+ 距离化语气（M7），但**不锁死**——用户主动示好随时可进 recovery。

## 3. 修复信号词表（recovery 通道）

`relationship_lexicon.py` 独立词表（与 M2 演化信号分属两流，不产 InteractionSignal）：

```text
对不起 / 抱歉 / 我错了 / 是我不好 / 别生气了 / 原谅我 / 我不是故意的
```

- 命中即 recovery 候选（conflict/cold 态下生效；none/strain 态命中只做温和去 tense：tension −0.02）。
- 词表只认"用户→角色"方向道歉；角色道歉属行为层，不在此列。

## 4. 疏远检测（neglect，非冲突通道的慢性伤害）

```text
读时检查（state_update 步骤内）：
  gap = now − last_interaction_at
  阈值 rel_neglect_days_json = {stranger:7, friend:5, close_friend:3, partner:2}
  （期待越高，越快感到被忽略）
gap > 阈值 且 neglect_active=False：
  → neglect_active=True
  → 账本落一行 source=system 的 neglect 事件（cause="久未联系"）
  → 效果：comfort −0.05；trust −0.01（仅 close_friend/partner——浅关系无资格失望）
下次互动（任何用户消息）：neglect_active=False（重逢即修复，不设额外惩罚）
```

- 期待梯度体现关系深度：partner 两天不说话就算疏远，stranger 一周不说话很正常。
- neglect 事件**可触发主动行为**（M8 R5：stage ≥ friend 时允许一次轻量召回问候）——疏远检测同时是修复入口。

## 5. 张力自然消退（时间演化）

```text
每日（state_update 内按 last_interaction_at 跨天结算，幂等）：
  tension − rel_tension_daily_decay(0.02)，下限 0
  active conflict（conflict/cold 态）期间暂停（冷战不会自己好，见 resolved=time_heals 的条件）
```

- 消退是显式"因"（source=system 账本行 + 评估白名单），不是隐藏衰减——无因不变量不破。
- 与 V5"正向互动消耗 tension"（−0.02/次）并行不悖：一个按天、一个按次。

## 6. 与其他模块的交接

| 消费方 | 消费内容 |
|---|---|
| M7 行为 | conflict_status 各态的固定指令句（资产常量）；cold 期距离化档 |
| M8 自主 | conflict_status → R1 强抑制 / R5 neglect 召回；comfort 修正基线进 R2 |
| M4 里程碑 | first_apology / first_forgiveness 谓词输入；conflict_recovery_available 解锁 |
| M6 记忆 | conflict 爆发 / 和解投递记忆候选（importance 0.75 / 0.85） |
| 评估 | ConflictRule：迁移表合法性 + 状态行与冗余列一致性 |

## 7. 验收标准

- 迁移矩阵逐格正反例；非法迁移拒绝并出 issue。
- cold 12h 计时、recovery 2 正向结算、time_heals 三日条件、修复回落——四条时序用注入时钟测试。
- neglect：阈值表按 stage 分档、一次性落账、重逢复位、trust 扣仅高级阶段。
- tension 日消退幂等（跨天一次）、冲突期暂停、账本可对账。
- 结算 delta 走 source=system 且对账白名单生效。
- 全流程异常注入不阻塞回合。
