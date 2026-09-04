# Memory Retrieval

## 1. 背景

V1 检索是**字符级** tokenize 重叠率（`set(每个字符)`），中文语义区分度差且无权重。V4 重写打分。

## 2. 结论：第一版不需要 Vector DB

评估维度：

| 维度 | 现状/计划 | 判断 |
|---|---|---|
| 数据规模 | 单用户 active 记忆 ≤ 200 条（上限 + 失效回收） | 全量拉取内存打分毫无压力 |
| 查询形态 | 按当前输入找相关记忆 | 词面匹配 + 权重足够 |
| 多语言/改述 | 暂不追求（"咖啡"vs"拿铁"召回损失可接受） | 语义搜索收益有限 |
| 引入成本 | embedding 服务 + 向量库 + 检索链路 + 测试 | 远超 V4 收益 |

**决策：Structured Query + 加权打分。** 触发引入 Vector Retrieval 的条件（记录备查，不在 V4 实现）：
1. 单用户 active 记忆 > 500 条；
2. 出现大量"改述无法召回"的实际案例；
3. 需要跨长历史的情节级召回。

## 3. 打分设计（纯代码）

```text
score = 0.45 × lexical_overlap      # 分词级 jaccard（jieba/空格退化为单字，与现有一致但分词粒度升级）
      + 0.25 × importance           # 记忆自身权重
      + 0.20 × recency              # 基于 last_accessed_at 与 created_at 的时间衰减
      + 0.10 × type_affinity        # 用户问偏好时 user_preference 加成等（由 SceneIntent/关键词粗判）
门槛：score ≥ 0.15 才进入候选（settings.memory_min_score）
```

- 查询范围：`user_id = 当前用户 AND character_id IN (当前角色, '*') AND status = 'active'`（结构化过滤，DB 层完成）。
- 取 top_k（settings.memory_top_k，默认 5）。
- 召回成功后批量更新 `last_accessed_at`（异步，可容忍延迟）。
- `expires_at < now` 的记忆不召回，并由后台定期批量置 `invalidated`（回收，防膨胀）。

## 4. 边界情况

- 无相关记忆：返回空列表，Prompt memory 段省略。
- 检索失败：空列表降级，trace 记 error。
- 全部记忆被 top_k 挤掉时，保证至少 1 条最高 importance 的记忆兜底（若存在）。

## 5. 验收标准

- 同义改述召回不作为 V4 验收项（明确记录为已知限制）。
- 字面相关/高重要/近期记忆能正确排序。
- 失效记忆不出现在任何召回结果。
