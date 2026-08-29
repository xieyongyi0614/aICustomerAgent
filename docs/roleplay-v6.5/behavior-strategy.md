# Behavior Strategy

## 1. 定位

V6.5 核心。在 Intention（这一轮准备做什么）与 Response（怎么说出来）之间插入**表现策略层**：

```text
V6：  Goal → Intention → Response
V6.5：Goal → Intention → BehaviorStrategy → Response
```

Intention 回答「做什么」，Strategy 回答「用什么方式做」。同一个 `comfort_user` 意图，可以是安静陪着（低能量、深夜），也可以是直接开口关心（日常、高亲密度）——这个「方式」必须由代码决定，不能交给 LLM 每轮现场发挥。

设计原则落地：

- **Strategy 由代码解析，零 LLM**：`intention → 基础策略` 是确定性映射，上下文只做**修饰**（换档，不发明新策略）。与 goal_service「LLM 出信号、策略全在代码」的既有哲学一致。
- **不重新设计 Runtime**：Strategy 解析是 intention_policy.enforce 之后的下一个纯函数步骤，插在 chat_pipeline 现有缝隙里。

## 2. 策略枚举（12 值，为亚丝娜定制）

不是照搬题设示例，从 12 个 IntentionType 的表达形态 + V2 behavior 7 值的语义收编而来：

```python
# app/models/behavior_strategy.py
BehaviorStrategyType = Literal[
    "focused_assistance",      # 专注协助：技术/工作问题，先解决问题再体现角色
    "natural_continuation",    # 自然延续：平常对话，顺话题接话
    "direct_support",          # 直接支持：正面接住问题，明确表达关心与建议
    "quiet_companion",         # 安静陪伴：先陪后问，不急着给方案
    "gentle_redirect",         # 温和转移：劝休/止损，把注意力引向照顾自己
    "warm_celebration",        # 一起高兴：为用户成就由衷雀跃
    "playful_tease",           # 轻松调侃：善意揶揄，活跃气氛
    "affectionate_expression", # 亲昵表达：关系升温的直率表达
    "reserved_distance",       # 克制距离：tension 高/被冒犯时收着说话
    "sincere_repair",          # 真诚修复：承认、解释、修复关系裂痕
    "curious_inquiry",         # 好奇追问：对用户的展开表现出兴趣
    "self_disclosure",         # 自我袒露：分享自己的感受/经历（SAO 记忆等）
]
```

每个策略在角色资产中带**表现指令**（behavior-policy 之外的策略参数表，同文件声明）：

```python
STRATEGY_INSTRUCTIONS: dict[str, str] = {
    "quiet_companion": "先安静地陪着，接住情绪；不急着给建议，问一句「想聊聊吗」就好。",
    "direct_support":  "明确说出关心，可以给一个具体的小建议；语气认真不放空。",
    "playful_tease":   "顺着他刚说的话轻描淡写地调侃一句，点到为止，不连环逗。",
    "gentle_redirect": "把话题温和地引向让他休息/照顾自己，用商量的语气不命令。",
    # ... 其余 8 条同风格，每条 ≤40 字
}
```

## 3. 解析规则（Behavior Engine 核心表）

### 3.1 基础映射（intention → strategy）

```python
INTENTION_STRATEGY_MAP: dict[str, BehaviorStrategyType] = {
    "comfort_user":        "quiet_companion",
    "suggest_rest":        "gentle_redirect",
    "encourage_user":      "direct_support",
    "celebrate_with_user": "warm_celebration",
    "express_affection":   "affectionate_expression",
    "tease_user":          "playful_tease",
    "maintain_distance":   "reserved_distance",
    "repair_rapport":      "sincere_repair",
    "continue_topic":      "natural_continuation",
    "ask_followup":        "curious_inquiry",
    "share_own_feeling":   "self_disclosure",
    "lighten_mood":        "playful_tease",
}
```

### 3.2 上下文修饰（换档规则，按序应用，命中即替换）

| 优先级 | 条件（全部代码可得） | 修饰结果 | 动机 |
|---|---|---|---|
| 1 | mode == professional | `focused_assistance` | 专业模式压平一切表现策略 |
| 2 | tension > 0.5 | → `reserved_distance`（除非 intention 是 repair_rapport） | 紧张期收着说，修复意图除外 |
| 3 | intention == comfort_user 且 character.energy ≥ 0.7 且 stage ≥ close_friend | → `direct_support` | 有能量且够亲：从陪着升级为直接关心 |
| 4 | mood ∈ {tired, sad} 且策略 ∈ {playful_tease, warm_celebration} | → `natural_continuation` | 低能量时不硬撑着逗乐 |
| 5 | scene_pending 存在（V3 待完成动作） | → `natural_continuation` | 场景动作优先，表现收束 |
| 6 | intensity ≥ 0.8（强情绪） | 保持基础策略，但 Budget 强制 0 动作 | 强情绪用语言，不用动作堆叠 |

修饰规则是**白名单表驱动**，每条规则带 `rule_id` 便于 trace 归因与测试矩阵断言。

### 3.3 输出模型

```python
class BehaviorStrategy(BaseModel):
    strategy: BehaviorStrategyType
    base_strategy: BehaviorStrategyType        # 修饰前（归因用）
    applied_rules: list[str] = []              # 命中的修饰规则 id
    instruction: str = ""                      # STRATEGY_INSTRUCTIONS 渲染值
    mood_tone: str = ""                        # policy 的 mood tone_directive
    degraded: bool = False                     # True 时回落 V2 behavior 段
```

## 4. 与 V2 behavior 层的收编

| 场景 | 行为 |
|---|---|
| intention 链成功、Strategy 解析成功 | 【表现方式】段（Strategy + Budget + Habit）注入；V2【本轮行为指令】段跳过 |
| intention 降级（链失败/非法） | Strategy.degraded=True → 渲染回落到 V2 `BEHAVIOR_INSTRUCTIONS[analysis.behavior]` |
| 二者都失败 | 回落 `normal_reply` 指令（等价现网 default 路径） |

`INTENTION_BEHAVIOR_MAP`（V6）保留并继续由 intention_policy 使用，负责的是【本轮行为指令】fallback 段；Strategy 是并行的新层，两者不互相改写。

## 5. 稳定性保证（解决「风格漂移」的机制说明）

问题 2 的根因是：表现方式完全由 LLM 在无约束空间里现场生成。Strategy 层提供三重稳定：

1. **映射确定性**：同一 (intention, context) 永远产出同一 strategy——纯函数，无随机。
2. **修饰白名单**：上下文只能映射表内换档，不能发明新方式。
3. **指令短句化**：注入的是 ≤40 字方向指令 + Budget 硬上限，LLM 在收窄空间内自由表达，方向由代码锚定。

跨轮一致性由测试矩阵验证（testing.md §Behavior Consistency）：同一角色在不同输入序列下，strategy 轨迹必须可复现（FakeLLM 全确定）。

## 6. 失败降级

- Strategy 解析抛异常 → `BehaviorStrategy(strategy="natural_continuation", degraded=True)`，渲染层回落 V2 行为段，answer 不受阻。
- `INTENTION_STRATEGY_MAP` 缺键（未来新增 intention 未同步）→ 兜底 `natural_continuation` + 配置告警日志。
