# Memory Policy

## 1. 背景

V1 的保存过滤只有 importance 阈值 + 字符串包含去重，无法阻止推测入库与低价值信息堆积。

## 2. 原则

> Policy 是纯代码硬规则，不信任 LLM 的 should_save 判断。LLM 只负责产出 Candidate，保存与否由 Policy 决定。

## 3. 应该记

| 类型 | 记 | 示例 |
|---|---|---|
| user_preference | 稳定好恶 | "用户不喝咖啡""喜欢深夜聊天" |
| user_fact | 稳定客观事实 | "用户在深圳工作""养了一只猫" |
| important_event | 对用户有持续影响的事件 | "用户通过了面试""下周要搬家" |
| relationship_event | 用户与角色间的标志性互动 | "用户送过生日礼物""一起看流星" |

## 4. 不应该记（丢弃规则，按序执行）

```text
R1 source == ai_inferred            → discard   # AI 推测永不成为事实（最高优先级）
R2 action == suppress               → 本轮全部 discard（用户说"不要记住"）
R3 action == forget                 → 转隐私处理，不走保存（privacy.md）
R4 type 为一次性信息特征            → discard（"今天吃了拉面""马上回来"）
R5 confidence < 0.6                 → discard   # settings.memory_min_confidence
R6 importance < 0.5                 → discard   # 沿用 settings.memory_importance_threshold
R7 content 与既有 active 记忆完全重复 → discard（转 Conflict Resolver 判定是否 update）
R8 content 含未消解指代（它/那个/他）→ discard   # 提取器已要求去语境化，此处兜底正则
```

## 5. 反例清单（写入 extractor prompt + 测试断言）

- ❌ "用户一定很开心"（推测心理）
- ❌ "用户看起来累了"（外观猜测，除非用户自己说累且为长期状态）
- ❌ "用户想喝奶茶"（本轮即时需求，非长期偏好）
- ❌ "用户可能是程序员"（confidence 不足的猜测）
- ✅ "用户说自己最近在准备考试"（user_stated，important_event）

## 6. 边界情况

- user_stated 但内容涉及敏感隐私（身份证号、住址门牌等）：V4 第一版照常保存（本地库），隐私分级列为 P2。
- Policy 规则冲突（如高 importance 但 ai_inferred）：R1 优先，推测一律不入库。

## 7. 验收标准

- 10 项测试中 Case 3（闲聊不保存）、Case 4（AI 猜测不保存）由 Policy 纯代码单测覆盖。
- 每条规则至少 1 个正例 + 1 个反例测试。
