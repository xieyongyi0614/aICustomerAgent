# Scheduler（V7 调度设计）

## 1. 结论：lifespan asyncio tick 循环（不引入 Celery/APScheduler）

现状盘点：项目无 Celery/APScheduler/Redis Queue；已有同模式先例——V4-011 的记忆回收循环（`main.py` lifespan + `run_memory_reclaim_loop`，`autonomy` 复刻它即可）。

```python
# app/application/autonomy_worker.py
async def run_autonomy_worker(tick_seconds: int | None = None) -> None:
    while True:
        await asyncio.sleep(tick or settings.autonomy_tick_seconds)
        try:
            await autonomy_engine.tick()   # 全量评估 + 执行
        except Exception:
            logger.exception("autonomy tick 失败，跳过本轮")
```

`main.py` lifespan 挂载（与 reclaim 循环并列），shutdown 时 cancel——与既有生命周期管理完全一致。

## 2. tick 语义

```text
每 tick：
1. 枚举候选用户：有会话记录的 user_id 集合（MVP 单用户 default-user，实现按集合遍历天然支持多用户）
2. 对每个用户：TriggerEvaluator → 有信号才进 Policy（无信号零成本跳过）
3. ACT → AutonomyEngine 组装 → 入队 → Executor 同 tick 处理
4. 已有非终态 action 的用户跳过（队列深度 1）
```

tick 间隔 60s 意味着"闲置 30 分钟"类阈值的最小粒度是分钟级——对关心类主动行为足够；秒级精度不属于本产品诉求。

## 3. scheduled_followup 的"调度"

不建 cron/定时器表：follow-up 到期判定在 tick 内比较 `due_at ≤ now`（惰性求值，与 V5 情绪衰减"读取侧惰性计算"同一哲学）。登记表 MVP 为内存 dict（低频、丢失可接受），若 V8 需要持久化登记再加列。

## 4. 拒绝的方案（记录理由）

| 方案 | 拒绝理由 |
|---|---|
| Celery + Redis | 引入 2 个中间件只为 60s 粒度循环；单进程部署无分布式需求 |
| APScheduler | 额外依赖；其 jobstore/错过触发等能力全部用不上 |
| 前端驱动（用户在线才 tick） | 违背"用户离开后主动"的核心诉求 |
| 每请求顺带评估 | 主动行为依赖"用户不在场"，请求驱动永远测不到闲置 |

## 5. 配置与开关

- `autonomy_enabled=False` → lifespan 不启动 worker（一键关停）；
- `autonomy_tick_seconds` 可调；测试中 worker 不随 TestClient 启动（fixture 控制 `autonomy_enabled`，单测直接调 `autonomy_engine.tick()` 驱动）。
