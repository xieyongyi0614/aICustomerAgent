# Character Action Sync — 代码审查报告

> 审查对象：ACTION-001~005 实现提交 `2188f5c` / `acae567` / `00b6880` / `b3e03dc`
> 审查方法：逐文件阅读（models / extractor / validator / mutator / world_engine / context_selector / post_process / 迁移）+ 探针实测（提取器、校验器、渲染器）+ 测试运行
> 上游设计：[architecture.md](architecture.md) ｜ [tasks.md](tasks.md) ｜ [task-details/](task-details/)
> 审查日期：2026-09-10

---

## 1. 结论摘要

| 维度 | 结论 |
|---|---|
| 架构一致性 | ✅ 与设计骨架一致：三层分离、唯一写入出口、Flag 门控、第 9 步位次、事件历史复用 world_events |
| 测试自洽性 | ✅ 模块 125 用例全绿；golden 9 用例 + 既有 World 42 用例零回归 |
| **可用性** | ❌ **模块当前处于关闭状态**（`v2_character_action_sync_enabled` 未在 `.env` 登记，默认 False） |
| **逻辑缺陷** | ⚠️ 发现 **3 个 P1 逻辑缺陷 + 2 项 P0 级校验未实现 + 1 处语义错位（会误扣库存）** |
| 观测对话问题 | ⚠️ 该对话的"编造库存"**不是本模块的 bug**，而是设计明确划出去的 grounding 问题（见 §3） |

**一句话**：代码骨架是对的、能跑、测试自洽；但它**没被打开**，且即使打开也修不了你贴的那段对话——那段对话暴露的是另一个问题（叙事 grounding），需要单独补一个小模块。

---

## 2. 探针实测证据（可复现）

用仓库 venv 直接调用实现，输入与实测输出：

| 输入 | 期望（按设计） | **实测** | 判定 |
|---|---|---|---|
| `我做好了一碗面。` | CREATE 面 | CREATE name=`面` qty=1 | ✅ |
| `我用了两个鸡蛋。` | CONSUME 鸡蛋 ×2 | CONSUME name=`鸡蛋` qty=2 | ✅ |
| `我把牛奶拿到了厨房。` | MOVE 牛奶 → kitchen | MOVE name=`牛奶` loc=`home.kitchen` | ✅ |
| **`我把牛奶拿到桌上。`**（设计验收用例） | MOVE 牛奶 | **0 候选** | ❌ **P1-3** |
| **`我拿了两个鸡蛋。`** | MOVE/不识别 | **CONSUME 鸡蛋 ×2** | ❌ **P1-1 误扣库存** |
| **`我做了个梦。`** | 丢弃 | **CREATE name=`梦`** | ❌ **P2-5 造实体** |
| **同轮 CREATE 面 → CONSUME 面** | 第 2 条命中新实体 | `wv.find_object("面") is None` → 判 NOT_FOUND | ❌ **P1-2** |
| **CREATE 已存在的 `鸡蛋`** | DUPLICATE_ENTITY | `_check_create` 返回 `None`（放行） | ❌ **P1-5** |
| **角色在卧室、鸡蛋在冰箱（CONSUME）** | LOCATION_UNREACHABLE | 返回 `None`（放行） | ❌ **P1-4** |
| **两个同名活跃实体 + MOVE 该名** | AMBIGUOUS_TARGET | 静默选中最后一个（`food_8`） | ❌ **P2-1** |
| **别名匹配（aliases）** | 命中 | 只匹配 `obj.name` | ❌ **P2-2** |
| 观测对话 4 条回复（见 §3.2） | — | **全部 0 候选** | 说明见 §3 |

补充：渲染器实测【当前世界】段共 164 字符（预算 600），库存清单**确实在 prompt 里**：

```
【当前世界】
现在是周四下午 16:00。你在家·客厅。
家里的物品、数量、位置与可消耗状态以本清单为准，不得凭空捏造或增减。
冰箱：
  鸡蛋 × 6
  牛奶 × 1
  可乐 × 2
橱柜：
  面条 × 2
  大米 × 2kg
  面包 × 1
最近世界变化：
  - 消耗鸡蛋 ×2
  - 做出面
```

---

## 3. 「仍存在问题」的对话：三层根因

### 3.1 第一层（直接原因）：模块根本没开

- `app/core/settings/world.py:23` → `v2_character_action_sync_enabled: bool = False`
- `apps/backend/.env` **没有**该条目；`.env.example` **也没有**登记。
- `post_process.py:331` 第一步就是 `if not get_settings().v2_character_action_sync_enabled: return`。

**结论**：当前所有角色回复都不会进入同步链路，世界零变更——这与观测到的现象完全一致。

> 启用方式（env 无前缀、大小写不敏感）：在 `apps/backend/.env` 增加 `V2_CHARACTER_ACTION_SYNC_ENABLED=true`。

### 3.2 第二层：**即使打开，这段对话也提取不到任何动作**（实测 0 候选）

逐句对照：

| 角色回复（片段） | 实测 | 原因 |
|---|---|---|
| `*把切好的水果拼盘放在你手边，顺手把冰镇过的果汁推到你面前*` | 0 | 动词表只有 `放到/放进了/…`，**没有 `放在`**；`推` 不在表内 |
| `*指了指旁边刚拆封的快递箱*` / `就顺手买了一些。` | 0 | CREATE 表无 `买了`；`拆封` 不在表内 |
| `冰箱里还有之前买的面包、牛奶和一些简单的蔬菜。` | 0 | 无动作动词（"还有"是状态声称，非三动作） |
| `我可以给你煮碗面` / `或者烤片面包?` | 0 | 前者命中噪声 `我可以给你`（正确跳过）；后者无 `烤了` |
| `冰箱里还有两个鸡蛋、半根黄瓜、一盒牛奶和一些剩饭。` | 0 | 状态声称，非动作 |
| `要不要用这些给你简单炒个蛋，再煮碗泡面？` | 0 | 命中噪声 `要不` / `？`（正确跳过） |

**结论**：这段对话里角色**没有做**（CREATE/MOVE/CONSUME）任何事，只有"存在性声称"和"未来提议"。CAS 产出 0 候选是**符合设计**的行为——它本来就不该把"有番茄汤""我会给你煮面"变成世界事实（见 [architecture.md](architecture.md) §12.2、ACTION-002 §语义边界）。

### 3.3 第三层（真正失败点）：叙事 grounding

- 角色声称 `冰箱里还有两个鸡蛋、半根黄瓜、一盒牛奶和一些剩饭`；
- 真实库存是 `鸡蛋 6 / 牛奶 1 / 可乐 2 / 面条 2 / 大米 2 / 面包 1`（见 §2 渲染实测）；
- **`半根黄瓜`、`剩饭`、`水果拼盘`、`果汁`、`快递箱` 在世界中完全不存在**。

也就是说：prompt 里**给了正确清单 + 明确的"不得凭空捏造"引导语**，模型仍然编造。这正是 [`docs/household-inventory-review.md`](../../../../household-inventory-review.md) §3 的结论：「**仅靠 prompt 约束不足，需要系统侧强制**」，对应报告的**改进方向 1（库存数量强制校验 / grounding）**——而该方向在设计时被**明确排除在 CAS 范围之外**（architecture §12.2、§1.4）。

**所以**：CAS 能保证"世界账本是真的"，但保证不了"角色说的话是真的"。两者是**互补的两件事**，缺一不可。

### 3.4 建议动作（分三步）

1. **立即可做**：`.env` 打开 `V2_CHARACTER_ACTION_SYNC_ENABLED=true`，让真实消耗/创建/移动开始记账（缩小编造空间）。
2. **修复 §4 的 P1 缺陷**：否则打开后会出现"拿了两个鸡蛋 → 误扣库存""同轮 CREATE 后引用不到"等新问题。
3. **另立一个小任务（如 ACTION-006 或独立模块）做「回复-库存 grounding 守卫」**：对回复中涉及库存的陈述做数量/存在性校验，冲突时受约束重生成或标注。这是唯一能真正消除你贴的这段现象的手段。

---

## 4. Bug 清单（按严重度）

### P0

| ID | 位置 | 现象 | 影响 | 建议 |
|---|---|---|---|---|
| **P0-1** | `core/settings/world.py:23`；`.env`；`.env.example` | 总闸默认 False，且未在两处 env 文件登记 | **功能完全未生效**，用户以为已上线 | `.env` 置 true；`.env.example` 补登记（含 `V2_CHARACTER_ACTION_SYNC_CONTEXT_LINES`） |
| **P0-2** | `validator.py:93-100` `_check_create` | 未实现"同名活跃实体 → DUPLICATE_ENTITY" | 角色反复说"我做好了面"会不断新增同名实体，直至撞 `world_active_entities_limit=200` → 世界污染 | 查同名活跃实体，拒绝或按策略累加数量 |

### P1

| ID | 位置 | 现象 | 影响 | 建议 |
|---|---|---|---|---|
| **P1-1** | `character/asuna/narrative.py:18` | CONSUME 动词表**误含 `拿了`** | **`我拿了两个鸡蛋` → 真扣 2 个库存**（拿≠消耗）；这是"造事实"，比不记账更危险 | 从 CONSUME 移除 `拿了`；如需支持"取物"并入 MOVE 或直接不识别（宁缺毋滥） |
| **P1-2** | `validator.py:42-49` `register_created` | 新建实体未写入 `name_to_obj`，`find_object` 只查 `name_to_obj` | 同轮 `CREATE 面` 后的 `CONSUME/MOVE 面` 判 OBJECT_NOT_FOUND，**违反 tasks.md ACTION-003 验收第 3 条** | `register_created` 同步登记 `name_to_obj`（用合成对象/id），保持 `id_to_obj` 一致 |
| **P1-3** | `narrative.py:37-50` | MOVE 动词只有 `拿到了`，**缺 `拿到`** | 设计/任务书明确的验收用例 `我把牛奶拿到桌上` **实测 0 候选** | 补 `拿到`、`放进`、`放进`、`端到`、`摆到`、`搬进` 等无"了"形式；补齐后 **需同时决策** `HOME_LOCATIONS` 是否新增桌面节点（见 ACTION-003 §已知缺口），否则仍会判 LOCATION_UNRESOLVED |
| **P1-4** | `validator.py:71-123` | `LOCATION_UNREACHABLE` 声明但**从未返回**；无任何可达性判定 | 任务书四项校验之一"**location 是否合理**"**完全缺失**；角色可"在卧室消耗冰箱里的鸡蛋" | 补可达性判定（对象位置 ∈ 角色位置子树 / 同房间簇，默认宽松），role 位置取自 `world.current_location` |
| **P1-5** | 见 P0-2 | 同 | 同 | 同 |

### P2

| ID | 位置 | 现象 | 影响 | 建议 |
|---|---|---|---|---|
| **P2-1** | `validator.py:28` | `{obj.name: obj}` 同名覆盖 → 静默取末位；`AMBIGUOUS_TARGET` 未使用 | 歧义时随机扣减/移动，不可归因 | 检测同名多实体 → AMBIGUOUS_TARGET |
| **P2-2** | `validator.py:28,36` | 只按 `obj.name` 精确匹配，**忽略 `aliases`** | 与既有 `find_object_by_name` / `_find_inventory_object` 语义不一致；别名物品不可命中 | 复用既有匹配语义（name ∪ aliases ∪ id） |
| **P2-3** | `extractor.py:67-76` `_find_verb_match` | 单句只返回**一个**最长动词；跨类型并列时按 dict 顺序（CONSUME 优先）胜出 | `我做了面用了两个鸡蛋`（无逗号）只出 CONSUME，**丢掉 CREATE**；与设计"一条回复可多动作"不符 | 按句内动词**出现顺序**逐个匹配，或在取词前先按动词位置切分 |
| **P2-4** | `narrative.py:68-95` | 噪声守卫**过宽**（`别` 会让"特别/别的/别动"整句跳过）**且缺失**（`我给你`/`我给你做` 承诺句、半角 `?`、`是不是`、`吧`）；另有重复项（`吃掉了`×2、`放到`×3、`拿到了`×2） | 误杀 / 漏杀；当前承诺句只是被"动词需带 `了`"侥幸挡住，非设计保证 | 改为结构性守卫（否定/疑问/承诺/角色扮演分类）+ 去重 |
| **P2-5** | `extractor.py:99-116` | CREATE 回退把动词后文本 strip 后直接当实体名 | `我做了个梦` → **CREATE `梦`**（真实建实体）；`我做了个决定` → `决定` | CREATE 名词必须命中白名单（`NARRATIVE_OBJECT_NOUNS` / `OBJECT_CREATION_HINTS` / 可食用词表），否则丢弃 |
| **P2-6** | `world_repository.list_events` + `world_engine.py:529,843` | 事件窗口按 `due_at asc nullslast` 排序；`character_action` 事件 `due_at=None` 排最后，`limit=50` | 当带 `due_at` 的 completed 事件超过 50 条时，**最近的角色动作可能被排除** → `recent_world_changes` 与幂等窗口失真 | 新增按 `created_at` 倒序查询，或把 `type` 过滤下推到 SQL |
| **P2-7** | `extractor.py:155,156` | 形参 `current_location` / `world_notes` **传入但函数体从未使用**（死参数） | 说明"位置合理性 / 场景咨询"实际未接线；调用方以为已生效 | 要么接线（用于可达性/指代），要么删除并同步调用方 |

### P3（整洁性，可不急）

| ID | 位置 | 现象 |
|---|---|---|
| P3-1 | `validator.py:111` | `_check_move` 在校验地点**之前**就回填 `object_id`，被拒动作也带 object_id（无害） |
| P3-2 | `extractor.py:90-93` | MOVE 分支的 `if move_match: return None` 基本是死代码，意图不明 |
| P3-3 | `migrations/0035` | `drop_constraint/create_check_constraint` 在 SQLite 不可用（生产 Postgres，可接受，建议在 docstring 声明） |

---

## 5. 与设计的偏差（遗漏）

| 设计条目 | 实现状态 | 说明 |
|---|---|---|
| 零新表 / 零迁移 | ⚠️ **偏离** | 实现新增了迁移 `0035`（放宽 `world_events.source` 允许 `character`）。这是**合理且更正确**的选择（对应设计 ACTION-004 §事件来源方案 B），但需**回填设计文档**，避免文档与代码矛盾 |
| LLM 提取通道（默认关） | ❌ 未实现 | `v2_character_action_sync_llm_extract_enabled` 未落地；连带 `LOW_CONFIDENCE`、`channel=llm_assist` 分支为空 |
| scene_state 只读咨询 | ❌ 未接线 | extractor/validator 均未读 `scene_state`（对应设计 §4.2 的"待评审"项，实际等于选"不读"，需明确确认） |
| `.env.example` 登记新开关 | ❌ 遗漏 | 新 Flag 未进入示例文件 |
| 位置合理性校验 | ❌ 未实现 | 即 P1-4 |
| CREATE 产物同轮可引用 | ❌ 未实现 | 即 P1-2 |
| 同名实体拒绝 | ❌ 未实现 | 即 P0-2 |

---

## 6. 测试盲区

已覆盖（125 用例）：CONSUME 基础通过/数量不足/对象不存在/不可消耗/数量非法、MOVE 基本/NO_OP/地点非法/对象不存在、去重、顺序扣减、渲染、模型状态机。

**未覆盖**（正对应上面的缺陷）：

| 缺口 | 对应缺陷 |
|---|---|
| `DUPLICATE_ENTITY` | P0-2 |
| `LOCATION_UNREACHABLE` | P1-4 |
| `AMBIGUOUS_TARGET` | P2-1 |
| aliases 匹配 | P2-2 |
| 同轮 CREATE → CONSUME 引用 | P1-2 |
| `拿到`（无"了"）动词 | P1-3 |
| 承诺句 / `我做了个梦` | P2-4 / P2-5 |
| 总闸 OFF → 渲染逐字节不变（专用断言） | 依赖既有 `prompt_golden` 间接覆盖，建议补显式用例 |

---

## 7. 建议修复顺序（最小改动）

```text
第 1 批（不改逻辑，先能用）
  · .env / .env.example 登记 V2_CHARACTER_ACTION_SYNC_ENABLED
第 2 批（消假事实，最高性价比）
  · narrative.py：CONSUME 移除「拿了」；CREATE 名词白名单（P2-5）；动词表去重
  · validator.py：register_created 登记 name_to_obj（P1-2）
第 3 批（补设计要求的校验）
  · _check_create：同名实体 → DUPLICATE_ENTITY（P0-2）
  · 可达性判定 → LOCATION_UNREACHABLE（P1-4）
  · aliases 参与解析 + AMBIGUOUS_TARGET（P2-1/P2-2）
第 4 批（召回与窗口）
  · MOVE 动词补「拿到」等；确认是否新增 home.dining_area（P1-3）
  · 事件窗口改按 created_at 倒序（P2-6）
  · 单句多动作（P2-3）
第 5 批（真问题：grounding，独立立项）
  · 回复-库存一致性守卫（§3.4 第 3 步）
```

---

## 8. 验证记录

| 检查 | 结果 |
|---|---|
| CAS 模块用例（unit 5 文件 + integration 1 文件） | **125 passed** |
| `test_prompt_golden.py`（Flag OFF 字节不变量） | **9 passed** |
| 既有 World 用例（context_selector/interpreter/models/transitions/location/memory_bridge） | **42 passed** |
| 探针实测（提取器 / 校验器 / 渲染器） | 见 §2 |
| 未执行 | 全量 Fast Test（建议修复后跑一次作为收口） |

> Windows 下 pytest 需指定仓库内临时目录：`--basetemp=.tmp/pytest -p no:xdist`（系统 temp 目录存在 PermissionError，属既有环境问题）。

---

## 9. 附录：证据坐标

| 关注点 | 位置 |
|---|---|
| 总闸与上下文行数 | `app/core/settings/world.py:23-24` |
| 第 9 步编排与门控 | `app/application/post_process.py:329-331,447` |
| 提取器（动词/数量/对象/地点） | `app/services/character_action/extractor.py`（`_find_verb_match:67`、`_extract_object_name:79`、CREATE 回退:99） |
| 动词/数量/噪声词表 | `app/character/asuna/narrative.py`（CONSUME `拿了`:18；MOVE `拿到了`:38/44；噪声:68-95） |
| 校验器（WorkingView/三项检查） | `app/services/character_action/validator.py`（`WorkingView:23`、`register_created:42`、`_check_consume:71`、`_check_create:93`、`_check_move:103`） |
| 执行器（映射/回读/事件） | `app/services/character_action/mutator.py` |
| 事件落库与幂等窗口 | `app/application/world_engine.py:529 record_character_action_event`、`:592 merge_character_action_notes`、`:843 build_context` |
| 渲染与最近变化派生 | `app/services/world/context_selector.py:31,147,195` |
| 来源枚举放宽 | `app/models/world.py`（`EventSource.CHARACTER`）、`migrations/versions/0035_world_events_source_character.py` |
