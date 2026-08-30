# M5 Environment System

> 目标：天气、温度、光照、噪声、氛围——世界的"感觉层"。它们影响角色的语气与提议，但**永远不直接改写角色的情绪状态**。

## 1. EnvironmentContext 模型（每世界一行）

| 字段 | 类型 | 说明 |
|---|---|---|
| weather | str \| None | sunny / cloudy / rain / snow / windy / …（词表在资产） |
| temperature_c | float \| None | 18.0 |
| lighting | str \| None | bright / dim / dark / night_light |
| noise | str \| None | quiet / normal / noisy |
| atmosphere | str \| None | cozy / tense / fresh / …（氛围标签，叙事辅助） |
| updated_at / updated_by | datetime / str | updated_by: manual / interpreter / system |

- 全部可空：空值 → 选择器不渲染该字段（prompt 不出现"未知天气"）。
- 默认值策略：新世界 environment 全空 → prompt 无环境信息（等于 V7.8 现状，golden 安全）。

## 2. 更新渠道（白名单）

1. **manual**：/debug/world 端点（P0 主渠道——单机调试台，用户在界面/接口上设定"今天下雨"）。
2. **interpreter**：用户明确陈述（"外面下雨了"）→ 确定性迁移 weather=rain。
3. **time 派生**：lighting 随 part_of_day 自动建议（夜间 → dark），仅作为**建议值**写 environment（世界域内演化，合法），可被 manual 覆盖。
- **不实现真实天气 API**（V8 明令禁止）；WeatherProvider 接口预留（P0 只有 ManualWeatherProvider 一个实现）。

## 3. 效果标签（Effect Tags）：影响如何表达

环境对角色的影响**不是**状态写回，而是三层只读表达：

| 层 | 载体 | 例子 |
|---|---|---|
| Prompt 上下文 | WorldContext.environment → 【世界】段 | "外面在下雨，18℃，屋里灯光昏暗" |
| 行为合理性 | WorldContextSelector 把环境词表合并进 available 渲染 | 雨天 → "不适合出门" 附加 note |
| 自治事实 | world_facts（P1） → policy 裁决理由 | weather=rain → 提醒带伞成为候选理由 |

资产侧提供 `ENVIRONMENT_EFFECT_LEXICON`（环境→叙事提示词表，如 rain → "雨天说话可以更慵懒/体贴"），随环境段一起进 prompt——这是**措辞素材**，不是行为指令，V6.5 行为策略零改动。

## 4. 与 V5 情绪系统的关系（硬边界重申）

- V8 **禁止**根据天气写 emotion_history / character_state（"下雨→角色忧郁"是错误实现）。
- 正确链路：环境事实进 prompt → LLM 在既有角色人格约束下自然表达 → 既有 state_update 链照常评估情绪（V7.5 评估还会审计这次变化是否自然）。
- 这样环境的影响可解释、可被评估审计、且完全复用既有闭环。

## 5. 装配与选择

- EnvironmentContext 每世界一行，装配即读（有值才进 WorldContext）。
- 选择器规则：
  - weather/lighting/temp 有值 → 渲染一行摘要（≤80 字符）；
  - 无值 / 与当前叙事无关（全是默认）→ 整段省略；
  - "10 公里外的天气"问题不存在：单宅世界 environment 即所在环境（地点 traits 的 outdoor_exposed 只影响渲染措辞）。

## 6. 边界

- 不做天气模拟引擎（雨不会自己下起来；manual + 用户陈述是唯二来源）。
- temperature 只存数值，不做单位换算；不做微气候（每房间温度）——lighting 可随时间派生，温度全屋统一。
- atmosphere 是自由叙事标签，不参与任何逻辑判断（只进 prompt）。
