# V6 实现期备注（implementation-notes）

> 记录 V6-001~009 编码期间对设计的实现解释、偏差与遗留问题。设计文档未推翻，仅补实现细节。

## 1. 实现解释（设计留白处的确定性落法）

### 1.1 suggest_rest 创建信号（goal-policy.md §1 第 2 行）
设计原文："V5 suggest_rest 类 Intention 被执行且用户显式接受"。实现：当轮 validated intention == suggest_rest 即创建"劝用户早点休息"目标（把进行中的劝休升级为显式目标，保证后续轮次持续推进）；"用户显式接受"的完成语义由 §2 已有的简化（持续 ≥ goal_rest_complete_turns=5 轮自动完成）覆盖，不额外做接受判定。

### 1.2 修复目标的 cancel 区间（goal-policy.md §3）
"关系冲突目标在 tension 回落时若未完成 → cancelled"：实现为 tension 落入 (0.3, 0.5) 开区间时 cancelled——低于等于 0.3 走完成（§2），回落到创建阈值以下但未达完成阈值（理由已消失、又不满足完成）→ 取消防悬挂。

### 1.3 IntentionPolicy.enforce 签名扩展（intention-selection.md §4）
设计签名 `enforce(decision, selected_goal, state, now)` 无法承载 §4 有效性表所需的"本轮 user_emotion / emotion_event"与"scene pending"信号。实现为：

```python
enforce(decision, selected_goal, state, analysis, now, scene_pending=False)
```

- `analysis`：本轮 TurnAnalysis（gather 后可得），供 celebrate/comfort/suggest_rest 有效性判定；
- `scene_pending`：显式布尔（pipeline 由 resolve 后的 scene_state 计算），ConversationState 不携带 scene，保持模型边界。

### 1.4 选择器的 user_emotion 信号来源（goal-selection.md §1 第二步）
"深夜 且 user_emotion ∈ {tired}"的修正需要用户侧情绪，而当前轮 turn_analysis 尚未跑完（选择先于 gather）。实现：`state_service.load_last_user_emotion(user_id)` 读取 emotion_history 最近 1 条（+1 次索引查询，读取失败按 neutral 降级）。前台的动机修正因此滞后一轮，属可接受的确定性近似。

### 1.5 上下文修正的数值表（goal-selection.md effective tier）
tier 排序基线 scene=0 / user_care=1 / relationship=2 / conversation=3，修正值（都是纯代码常量，goal_service.py）：

- relationship 修复目标在 tension > rel_tension_freeze(0.5) 时 → 0.9（提升到 user_care 之前）
- user_care 在角色强负面情绪（intensity ≥ emotion_strong_threshold(0.6) 且 mood 负面）时 → 0.8
- user_care-劝休在深夜+用户疲惫时 → 0.85
- conversation 在强负面情绪时压制 → 3.5

强负面（0.8）> 深夜劝休（0.85）> 修复（0.9）> 常规 user_care（1.0），对应冲突原则"福祉 > 关系"。同分内平局：priority 高者 → created_at 最新者 → 固定描述序（劝休 > 陪伴 > 修复）→ id，保证永远有确定性输出。

### 1.6 同轮创建的目标不参与当轮完成判定
review 流程按设计顺序"先创建后完成扫描"；若新建目标立即进入完成判定（如 tension=0 满足修复完成条件）会被瞬间扫掉。实现：完成/过期/取消扫描排除本轮 `changes.created` 的行。

### 1.7 scene 目标描述与替换
scene 目标 description = "完成" + action（action 截断至 40-2 字）。V3 pending action 被新动作替换时，旧 scene 目标 cancelled、新动作可再次触发创建；pending 标记 completed/cancelled 或消失时 scene 目标 completed。

## 2. 与 tasks.md 的映射偏差

- **测试目录**：tasks.md 写 `tests/v6/`，实际沿用 REF-013 确立的 `tests/unit` / `tests/integration` 分层（testing.md 同样按此分层），未新建平行目录。
- **V6-010（P1）/ V6-011（P2）未实现**：V6-010 需改前端与 /state API（本次约束禁止修改前端/API Contract，turn_meta 已携带 intention/current_goal，面板展示留待 V6-010）；V6-011 的 LLM 辅助评审与记忆联动按注册表为 P2 延期。
- **goal-policy §5 的 conversation 类"陪聊"创建信号**：需要语义判定（"陪我聊聊天"），超出 §1 表驱动信号范围，归入 V6-011 的 LLM 评估一并考虑；§5 的护栏（用户语言不产生 persistent goal）已在结构上成立——review 只创建 source ∈ {policy, scene}、horizon=current 的行。

## 3. 顺带修复的既有问题（非 V6 引入）

- `tests/integration/test_db_migration.py::test_http_lifecycle_on_postgres` 的 FakeLLM 结构化响应仍是 V3 时代的 `MemoryDecision`，V4 换 `MemoryExtraction` 后该用例在无 PG 环境被跳过、无人察觉失效；已按现行 schema 修复。
- `tests/unit/test_prompt_v5.py` 两个预算用例直接改写 settings 单例（`get_settings().context_total_char_budget = 700/800`）且不恢复，属跨文件测试污染地雷；改为 monkeypatch 自动恢复。
- 观察到（未动）：`state_service.apply_and_save` 尾部二次记忆回放把 tuple 传给 `upsert_relationship`，抛 AttributeError 被吞掉、仅日志噪音（`_replay_relationship_memories` 返回 (state, events) 二元组）。属 V5 遗留，不影响功能，建议后续清理。

## 4. 环境备忘（本机）

- **PG 测试默认 URL 已从 `localhost` 改为 `127.0.0.1`（test_db_migration.py）**：Windows 下 `localhost` 先解析为 IPv6 `::1`，而 docker 端口只绑定 127.0.0.1，每次新建连接都要在 `::1` 上耗尽超时后才回退——SQLAlchemy URL 默认无 connect_timeout 时表现为长时间挂起。这就是此前 PG 用例动辄 8~15 分钟、`test_http_lifecycle_on_postgres` 的 3 秒 wait_until 必败的根因（本地 docker postgres）。改为 127.0.0.1 后全量套件 938s → 27s。
- migration 一致性测试（alembic vs ORM）已验证 0008 与 GoalRow 一致；本地 PG 跑在 docker（asuna-postgres，127.0.0.1:5432）。
