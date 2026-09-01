# V9 Memory Integration（Action Memory Policy）

> 行动不是都值得记住。本篇定义哪些行动沉淀为记忆的边界表、候选构造与投递路径。**不改 memory_service / extractor / 既有 policy 规则**——V9 是记忆的又一个供给方（V4 extractor、V8 world_bridge、V8.5 relationship_memory 之后的第四个），走同一投递纪律。

## 1. 为什么需要行动记忆政策

用户创建生日提醒，一个月后角色应该记得"曾为用户设过生日提醒"（关系资产）；角色查询天气，不该在记忆里堆满"查过 100 次天气"（记忆污染）。需要一张**边界表**回答：什么行动 → 什么记忆 → 多重要。

## 2. Action Memory Policy 边界表

落点：`settings action_memory_policy_json`（默认内置表）+ 纯函数 `to_memory_candidates(record: ActionRecord) -> list[dict]`（`app/services/action/memory_bridge.py`，V8 world_bridge 同构）。

| ActionType | 沉淀？ | memory_type | importance | source | 理由 |
|---|---|---|---|---|---|
| create_reminder | ✅（succeeded 时） | important_event | 0.7 | user_derived | 用户委托的承诺是关系资产（"我曾为 TA 设过生日提醒"） |
| create_reminder（birthday 关键词命中） | ✅ | user_fact | 0.8 | user_derived | 生日是用户事实，重要度上调 |
| cancel_reminder | ✅（用户主动取消时） | important_event | 0.5 | user_derived | 偏好信号（"TA 不想被提醒这个"），低重要度 |
| remember_fact | ✅ | user_fact | 0.8 | **user_stated** | 用户显式委托"记住"——这是行动，记忆本体由能力写入（§3 特例） |
| create_object | ✅（succeeded 且重要物品） | user_preference | 0.5 | user_derived | 采购偏好弱事实；普通物品不沉淀（参数 importance 门槛） |
| move_object / use_object | ❌ | — | — | — | 世界状态已记录（WorldObject），记忆重复 |
| query_environment | ❌ | — | — | — | 高频查询，沉淀即污染 |
| query_search / send_notification | ❌ | — | — | — | 无闭环价值 |
| 任意行动 **failed**（用户重要委托） | ✅ | important_event | 0.6 | user_derived | 失败留痕供角色后续补救/致歉（"上次没帮你设成"） |
| 任意行动 **cancelled by gate** | ❌ | — | — | — | 内部闸门，对记忆不可见 |

边界表纪律：

1. **查询不沉淀、叙事不重复**：query_* 全部不沉淀（世界状态与世界 notes 已覆盖）；use/move 与 WorldObject 状态重复，不沉淀。
2. **承诺与委托是记忆主粮**：reminder 系（创建/取消）与显式记忆委托是 V9 记忆核心产出——它们是跨会话关系资产。
3. **失败的重要委托沉淀**：不是为了记仇，是为了闭环（补救/致歉需要事实依据）。
4. importance/confidence 全部 ≥ 0.6（R5/R6 阈值）才可能通过既有 policy——表内取值已对齐（0.5 项依赖阈值下调时才生效，属有意预留）。

## 3. 投递路径

```text
integrate_result（第 9 步收尾）
    └─ memory_bridge.deliver_action_memory(record, user_id, character_id="asuna")
          ├─ 门控 action_memory_policy_enabled + 边界表查行 → 无行即返回
          ├─ to_memory_candidates(record) → 0..1 条候选（单行动单记忆，V8 同款）
          ├─ 既有 memory_policy._evaluate 校验（R1~R8 全量适用，零豁免）
          └─ memory_repository.create_memory(...)   # source 透传
```

- **特例：remember_fact 双写合一**。显式记忆委托的记忆本体由 memory 能力在**执行时**写入（capability-system.md §4，source=user_stated）；整合层查重后跳过（dedupe_key 含 fact 摘要），避免边界表再投一条重复记忆。
- **source 映射纪律**：行动派生记忆只用 `user_stated`（显式委托）与 `user_derived`（从用户请求推导），**不用 `ai_inferred`**——既有 policy R1 丢弃 ai_inferred（V4 隐私纪律），world_bridge 的 user_derived 映射经验直接复用。
- **幂等**：`record.result.effects` 中登记 effect[memory]（memory_id 回填），重复投递以 effects 存在性判断跳过（V8 payload["memory_materialized"] 同款思路，宿主从 event payload 换成 record effects）。
- **失败语义**：投递失败只 log 不回滚行动（记忆是增益不是契约）；边界表行缺失零候选（宁缺毋滥）。

## 4. 与既有记忆供给方的边界

| 供给方 | 输入 | 触发 | 典型产出 |
|---|---|---|---|
| V4 extractor（第 5 步） | 对话文本 | 每轮 LLM 抽取 | 用户偏好/事实 |
| V8 world_bridge（第 8 步收尾） | WorldEvent 完结 | completed + importance 达标 | "用户在 X 日完成了面试" |
| V8.5 relationship_memory | 关系事件/里程碑 | 演化产出 | 关系编年史 |
| **V9 action bridge（第 9 步收尾）** | **ActionRecord 终态** | **succeeded/failed + 边界表** | **"已设生日提醒 / 上次委托失败"** |

- 防重复三角：同一事实可能被 V4（对话里"我生日是 7 月 30 日"）与 V9（remember_fact 行动）先后捕获——既有 `resolve_batch` 冲突消解（V4）+ V9 侧 dedupe_key（fact 摘要）双保险；残余重复由既有 memory_conflict 语义承接，V9 不新增消解逻辑。
- 隐私纪律继承：行动记忆进 prompt 与否由既有 memory 检索预算决定，V9 不新增 prompt 通道（行动上下文段是另一条**行动事实**通道，不含记忆内容）。

## 5. 记忆模板（角色资产）

`app/character/asuna/action.py::ACTION_MEMORY_TEMPLATES`：各 ActionType 的人读模板（"用户请我{verb}：{content}"），保证记忆文本风格与 V8 world_bridge 模板（"用户在 MM 月 DD 日完成了{title}"）一致——记忆是角色视角的叙事，不是日志。
