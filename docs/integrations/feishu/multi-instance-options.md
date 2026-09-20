# 跨进程会话串行：可选方案与取舍（FEISHU-011 立项前的决策文档）

> 目的：把「多实例下同一会话不再串行」这个缺口，拆成**可以选的方案**，说清每个方案怎么做、能买到什么、要付什么代价。
> 前置阅读：`architecture.md` §7.3（多实例硬前置）、`review-v1.2.md` §2.1 与 §7.10。
> 当前状态：去重落库（FEISHU-010）✅ 已实现；**会话串行 ❌、出站幂等落库 ❌** —— 三项全齐前不得开多 worker。

---

## 1. 要解决什么

### 1.1 现状（单实例，正确）

`adapter.py` 的入站链是：

```text
SessionInbox（按 open_id 分桶：合并窗口 + FIFO 批次链 + 唯一 worker）
      ↓
_serialized(open_id)            ← 进程内 asyncio.Lock，同会话严格串行
      ↓
_run_inbound
   ├─ asyncio.to_thread(_resolve_identity)   身份解析（不占锁？占，锁在它外层）
   └─ async with _get_turn_gate()            全局并发闸门（Semaphore，默认 4）
          └─ _run_turn(...)                  LLM 流式，可能数秒
      ↓
_deliver_outcome               出站
```

关键事实：**会话锁是跨整轮持有的**（从身份解析到出站完成），而全局并发闸门 `feishu_max_concurrent_turns` 是**嵌在会话锁之内**的。

### 1.2 多实例下的缺口

| 缺口 | 后果 |
|---|---|
| 同一 `open_id` 的两个事件落到不同实例 | 两个实例**同时**跑同一会话的轮次 → 消息交错、`conversations`/`memory`/`character_state` 竞态写 |
| 合并窗口与 FIFO 链只在实例内 | 连发消息不被合并；跨实例顺序无法保证（即使串行也保不住「到达顺序」） |

### 1.3 约束（决定了方案空间）

| # | 约束 | 来源 |
|---|---|---|
| C1 | **`app/channels/**` 不得 import `app.repositories`**（fail-closed allowlist） | `test_feishu_boundary.py` |
| C2 | 连接池总容量 = `db_pool_size(5) + db_max_overflow(10)` = **15**；`feishu_max_concurrent_turns` 默认 **4** | `settings/database.py` / `settings/feishu.py` |
| C3 | **加一张表 = 一个迁移 = 22 个跨版本钉测要同批升级** | `review-v1.2.md` §7.10 实测 |
| C4 | 本机 **PG 不可用**（docker daemon 未运行、无 `docker compose`、5432 未监听）→ 任何 PG 专有机制在本机**无法验证**，只能靠 SQLite 等价物或留给 CI | 环境实测 |

---

## 2. 五个方案

### 方案 A：PG advisory lock + 专用连接（含「持锁数闸门」）

**怎么做**

1. 新增一个**持锁数闸门** `Semaphore`，容量取 `db_pool_size + db_max_overflow - 留白`（如 8），专门限制「同时被占用的会话锁连接数」。
2. 取锁流程：`持锁数闸门 → 从池里取一个独立连接 → SELECT pg_try_advisory_lock(hashtext(session_id))`，失败则退避重试（**排队等待**，不丢弃）。
3. 锁**跨整轮持有**；轮次结束后 `pg_advisory_unlock` 并把连接归还池。
4. 全局并发闸门 `feishu_max_concurrent_turns` 保持在内层不动（它管的是 LLM 并发，不是连接）。
5. 分派写在**组合根**（`api/v1/feishu.py` 或由它注入 adapter），因为 C1 禁止通道层 import `repositories`。

**得到什么**

- 互斥是**数据库保证**的，没有租约过期、没有时钟依赖、没有心跳。
- **不需要新表、不需要迁移** → 完全绕开 C3（advisory lock 是函数，不是 schema）。
- 实例崩溃时连接断开 → 锁由 PG 自动释放，无需清理。

**要付什么**

- **持锁期间占用一个连接**，整轮 LLM（数秒）都占着 → 必须靠第 1 步的闸门兜住，否则并发会话一多就压满池（C2）。代价是**总并发会话数被池容量限制**（吞吐上限从「无限」变成「≤ 8」）。
- **`hashtext` 有碰撞可能**：两个无关会话可能被同一把锁串起来 → 偶发排队，不影响正确性。
- **PG 专有**（C4）：本机无法验证，SQLite 没有 advisory lock → 单测需要替身实现，真机行为只能靠 CI/预发。
- 需要动 `_serialized` 的结构（把「进程内锁」换成「可注入的跨进程锁」），是本次三个前置里**改动最重**的一项。

---

### 方案 B：租约表（lease + 心跳）

**怎么做**

1. 新增表 `feishu_session_leases(session_id PK, owner, expires_at)` + 迁移（**+22 个钉测，见 C3**）。
2. 取锁：`INSERT ... ON CONFLICT DO NOTHING` 成功即拿到；失败则尝试「抢占已过期行」（`UPDATE ... WHERE session_id=? AND expires_at < now()`），`rowcount == 1` 即拿到。
3. 轮次进行中由后台任务按 `TTL/3` 续租（heartbeat）。
4. 释放：`DELETE WHERE session_id=? AND owner=?`。
5. 取锁/续租/释放**各自是短事务**，**不跨轮次持有连接**。
6. 时间一律用**数据库的 `now()`**，不用应用时钟（避免实例间时钟漂移）。

**得到什么**

- **不占连接**：整轮 LLM 期间连接已归还 → 不受 C2 的池容量约束，吞吐上限不受影响。
- **方言无关**：SQLite 也能跑 → **本机可验证**（绕开 C4），单测能覆盖抢占/续租/释放全路径。
- 顺带可以做「锁的可观测性」：谁持有、何时到期，直接查表。

**要付什么**

- **租约过期 vs 长轮次的根本张力**：若某轮超过 TTL 且心跳失败（事件循环被阻塞、实例被冻结/GC 暂停），另一实例会抢走锁 → **消息交错**，也就是我们本来要修的那个 bug。缓解手段（加长 TTL、心跳、只在「超期较多」时才抢）都只是降低概率，不能消除。
- **需要新表 + 迁移** → 撞 C3，22 个钉测要同批升级（已在 FEISHU-010 练过一次，但仍是成本）。
- 实现细节多（抢占判定、心跳任务生命周期、owner 标识、失败清理），是五个方案里**代码量最大**的。

---

### 方案 C：入口按 `open_id` 做粘性路由（不做分布式锁）—— **应用侧已实现，ingress 待落地**

**怎么做**

让「同一 `open_id` 的事件永远落到同一个实例」，于是进程内串行就够用。落地形态三选一：

| 形态 | 说明 | 谁来做 |
|---|---|---|
| C1 负载均衡器粘性 | 需按**请求体**里的 `open_id` 哈希，多数 LB 只能按 IP/Header，**做不到** | 基础设施 |
| C2 轻量 router | 自建一个小服务：收 webhook → 解析 `open_id` → 转发到固定实例 | 新增组件（要运维） |
| C3 分区队列 | webhook 只入队（按 `open_id` 分区），N 个 worker 各消费固定分区、顺序消费 | 新增基础设施（MQ/Redis Streams） |

**分片算法（ingress 必须逐字复刻）**

```text
shard = crc32(open_id.encode("utf-8")) % FEISHU_INSTANCE_COUNT
```

- 用标准库 `zlib.crc32`，取值稳定，且 nginx / Go / Node / Java 都有等价实现。
- **`open_id` 是飞书用户 open_id**，不是 `internal_user_id`，也不是 `session_id`（后者形如 `feishu:{open_id}`，对整串做哈希会得到不同结果）。
- 应用侧实现：`app/channels/feishu/shards.py`（`shard_of` / `owns`），golden 值锁定在 `tests/unit/test_feishu_shards.py::test_shard_values_are_frozen`——**算法一改该用例就红，提醒你必须同步改 ingress**。

**本仓库已交付的应用侧契约**（2026-09-20）

| 内容 | 位置 |
|---|---|
| 分片算法与归属判定（纯函数，无状态、无 IO） | `channels/feishu/shards.py` |
| 实例身份 | `FEISHU_INSTANCE_INDEX`（0-based，须 `< FEISHU_INSTANCE_COUNT`） |
| ingress 已分流的**运维声明** | `FEISHU_INGRESS_SHARDED_ROUTING_ENABLED=true` |
| **归属校验**：非本分片 → `503`（可重试）并抽样记 error | `api/v1/feishu.py::_owns_shard` |
| 多实例**就绪契约**：`count>1` 时必须同时声明「ingress 已分流」+「跨进程去重已开」 | `settings/feishu.py::_assert_multi_instance_ready` |

**两处关键设计**：

1. **归属校验在去重之前**，且非本分片返回 **503 而非 200**。理由：503 让飞书重投、有机会落到正确实例；而因为在去重之前判定，重投不会被去重表吞掉（这正是 FEISHU-009 修过的坑）。若返回 200 静默丢弃，消息会永久丢失且无任何可观测信号。
2. **`FEISHU_DEDUPE_PERSISTENT_ENABLED` 是就绪契约的一部分**（不是可选项）：它是 ingress 配错时的**兜底**——即使同一 `event_id` 被两个实例收到，也只有一次会真正处理。

**得到什么**

- **应用侧几乎零改动**：现有 `SessionInbox` + `_serialized` 原样保留。
- **一次解决两个缺口**：不仅会话串行，连「连发合并窗口只在实例内」也一并解决（同会话永远同实例）。
- 不需要分布式锁，没有租约/碰撞/连接占用等一切复杂度。
- 不需要新表、不需要迁移（绕开 C3 的 22 钉测成本）。

**要付什么**

- **依赖你能否控制入口**。当前是单 URL webhook，若无入口控制权，C1 直接不可行，只能上 C2/C3，而那是**新组件 + 新运维面**。
- 实例故障时其负责的会话需要**重新归属**（C2 要 router 感知健康；C3 由分区再均衡承担）。重新归属期间 `crc32` 取模会变化 → 部分会话暂时落到新实例；此时**跨进程去重兜底**保证不会重复处理。
- 不解决「同一事件被投递两次」——那由 FEISHU-010 的去重承担，两者互补。
- ⚠️ **翻开关前必须验证 ingress 真的在分流**：否则事件会大量落到错误分片 → 503 → 飞书重投 → 重试风暴。应用侧已抽样记 error（每 100 次一条）供发现。

**ingress 落地示例**

```nginx
# nginx 1.9+ ：split_clients 按 open_id 分流（需 lua 或 OpenResty 解析请求体）
# 更常见的做法是在 LB / 网关层用支持一致性哈希的插件，或自建 C2 router：
#   收 POST /api/v1/feishu/events → 解析 body.event.sender.sender_id.open_id
#   → shard = crc32(open_id) % FEISHU_INSTANCE_COUNT → 转发到实例 shard
```

---

### 方案 D：忙则拒收（不排队）

**怎么做**

1. 复用方案 B 的表（或一个更简的 `busy_until` 列），但**不做等待**：取不到锁就立刻放弃。
2. 放弃时走已有的 `adapter.reject_inbound_message`，回一句「你发得太快了」并返回 200（复用 FEISHU-009 的兜底路径，**不返回 4xx**）。

**得到什么**

- **实现最省**：无心跳、无等待队列、无退避逻辑，十几行。
- 语义上比「静默交错」好得多：用户至少收到反馈，而不是两条回复互相打断。

**要付什么**

- **用户可见行为降级**：同一会话的并发消息会被拒收，而不是像今天那样排队后按序处理。用户「连发两条」在恰好落到不同实例时可能只得到一条回复 + 一句「发太快」。
- 仍需要表 + 迁移（C3 的 22 个钉测成本）。
- 只是**把并发冲突显式化**，并没有真正实现串行 —— 属于「止血」而非「治好」。

---

### 方案 E：明确不支持多实例，改成启动期硬闸（**已落地，2026-09-20**）

**怎么做**

1. 把 `feishu_instance_count` 从「仅用于容量校验折算」升级为**硬闸**：`FEISHU_ENABLED=true` 且 `FEISHU_INSTANCE_COUNT > 1` 时，**启动期直接抛 `SettingsError`**（fail-fast），而不是记 warning 后继续跑。
2. 错误信息里给出三项前置的清单与当前进度，指向本文件。
3. 文档层面把「多实例」从「预留」改为「未支持，且有闸门拦着」。

**得到什么**

- 把**静默的正确性风险**换成**显式的启动失败**。今天的问题是：谁要是直接开 3 个 worker，不会有任何东西拦住他，只会偶发消息交错 —— 那是极难排查的故障。加了硬闸，这条路被物理封死。
- **零持续成本**：不需要新表、不需要迁移、不需要新组件、不需要跨进程锁。
- 顺带把 `feishu_instance_count` 的语义说清（它此前只影响一条 warning，容易被误读为「已经支持多实例」）。

**要付什么**

- **横向扩展能力暂时为零**：只能纵向扩（单实例内调 `feishu_max_concurrent_turns` / 池容量）。
- 若业务确实需要多实例，方案 E 只是把问题推后，仍需在 A/B/C/D 中选一个。

**落地位置**：`app/core/settings/feishu.py` 的 `validate_feishu_config`（在 `feishu_enabled` 分支内，紧随凭据校验）；用例见 `tests/unit/test_feishu_settings.py`；语义见 `architecture.md` §5.1 与 §7.3。

---

## 3. 对比

| 维度 | A advisory lock | B 租约表 | C 粘性路由 | D 忙则拒收 | E 硬闸 |
|---|---|---|---|---|---|
| 真正实现跨实例串行 | ✅ | ⚠️ 有租约过期风险 | ✅ | ❌ 只是拒收 | ❌（显式不支持） |
| 需要新表 + 迁移（C3 的 22 钉测） | **不需要** | 需要 | 不需要 | 需要 | 不需要 |
| 整轮占用 DB 连接（受 C2 约束） | **是**（需加持锁数闸门） | 否 | 否 | 否 | — |
| 本机可验证（C4） | ❌ PG 专有 | ✅ SQLite 可跑 | ✅ | ✅ | ✅ |
| 是否新增基础设施/组件 | 否 | 否 | **是**（C2/C3 形态） | 否 | 否 |
| 顺带解决「连发合并跨实例」 | ❌ | ❌ | ✅ | ❌ | — |
| 用户可见行为变化 | 无 | 无 | 无 | **有**（会收到「发太快」） | 无（启动期失败） |
| 相对工作量 | 中 | 高 | 低（应用侧）/ 高（组件侧） | 低 | **极低** |
| 适合的场景 | 必须无状态多实例、且不能控入口 | 同上，但连接池紧张 | **能控制入口**（有网关/队列） | 过渡止血 | **当前阶段** |

---

## 4. 建议

**分两步，而不是一次选一个终局方案：**

### 现在：方案 E 的**闸门形态保留、语义升级为「就绪契约」** —— ✅ 已落地（2026-09-20）

三项前置只完成 1/3 时，直接开多 worker 必然出事；E 把「无人拦截的静默风险」变成「启动就报错」。

选定方案 C 后，闸门语义升级为**多实例就绪契约**：`count>1` 时不再无条件拒绝，而是要求显式声明两件事——`FEISHU_INGRESS_SHARDED_ROUTING_ENABLED=true`（ingress 已按分片算法分流）与 `FEISHU_DEDUPE_PERSISTENT_ENABLED=true`（跨进程去重兜底）。缺任一项即启动期失败。

### 将来：方案 C —— ✅ **已选定**，应用侧已落地，ingress 待落地

**为什么是 C**：一次解决会话串行 + 跨实例连发合并两个缺口，且不需要分布式锁的一切复杂度（无租约窗口、无连接占用、无碰撞、无新表新迁移）。

**落地进度**：

| 部分 | 状态 |
|---|---|
| 应用侧契约（分片算法 / 实例身份 / 归属校验 / 就绪契约） | ✅ 已实现（见上文） |
| ingress 侧分流（C1 LB / C2 router / C3 分区队列） | ❌ 待落地 —— **不在本仓库**，属部署与运维 |
| 三项前置：去重落库 | ✅ |
| 三项前置：跨进程会话串行 | ✅ 由 C 承担（前提是 ingress 真的分流） |
| 三项前置：出站幂等落库 | ⚠️ 未做。**在 C 下风险大幅降低**（同会话只由一个实例处理），但 `send_proactive`（Autonomy 主动消息）不走会话锁 → **Autonomy 接入飞书前必须补**（FEISHU-008） |

> ⚠️ **翻开关前必须验证 ingress 真的在分流**：否则事件大量落到错误分片 → 503 → 飞书重投 → 重试风暴。应用侧已抽样记 error（每 100 次一条，含期望分片与实例下标）供发现。
>
> ⚠️ **改 `FEISHU_INSTANCE_COUNT` 会改变分片映射**：`crc32 % count` 的取模基数变了，几乎所有会话都会换实例。变更时**必须同时改 ingress 的分流配置**，并预期一段「会话重新归属」窗口（跨进程去重兜底保证不重复处理）。

---

## 5. 选定后各自要做的清单（便于估工）

| 方案 | 清单 |
|---|---|
| **E** | ✅ 已完成：① `settings/feishu.py` 就绪契约（`feishu_enabled` 分支内）；② architecture §5.1 / §7.3 语义；③ 设置测试（含「不含凭据明文」断言）；④ `tasks.md` FEISHU-011 登记 |
| **C** | 应用侧 ✅ 已完成：① `channels/feishu/shards.py`（分片算法 + 归属判定 + 错分片抽样留痕）；② `FEISHU_INSTANCE_INDEX` 配置与 `index < count` 校验；③ `api/v1/feishu.py::_owns_shard`（在去重之前判定，非本分片 → 503）；④ 就绪契约要求 `FEISHU_INGRESS_SHARDED_ROUTING_ENABLED` + `FEISHU_DEDUPE_PERSISTENT_ENABLED`；⑤ 20 个新用例（分片 golden / 分布 / 归属 503 / 重投不被吞 / challenge 不受检）；⑥ 文档。<br>ingress 侧 ❌ 待落地：⑦ 选形态（C1/C2/C3）；⑧ 按 `crc32(open_id) % FEISHU_INSTANCE_COUNT` 配置分流；⑨ 健康探测与实例故障时的会话再归属；⑩ 翻开关前验证分流生效 |
| **A** | ① 定义可注入的跨进程锁接口（通道层只依赖抽象）；② 组合根注入 PG advisory lock 实现（专用连接 + `pg_try_advisory_lock` + 退避）；③ 新增「持锁数闸门」并纳入容量校验；④ SQLite 替身实现 + 单测；⑤ PG 集成测试（CI 跑）；⑥ 文档 |
| **B** | ① 表 + 迁移 `0051`；② **同批升级 22 个跨版本钉测**（照 FEISHU-010 §7.10 的五类处理）；③ 仓储（抢占/续租/释放）；④ 心跳任务生命周期；⑤ 单测（SQLite 全路径）；⑥ 文档 |
| **D** | ① 表 + 迁移（同 B 的 C3 成本）；② 取锁失败 → `reject_inbound_message`；③ 单测；④ 行为变更登记 |

---

## 6. 决策状态

| # | 问题 | 状态 |
|---|---|---|
| 1 | 现在是否落方案 E？ | ✅ **已落**（2026-09-20），并升级为「多实例就绪契约」 |
| 2 | 将来横向扩展选哪个方案？ | ✅ **已选 C**（入口按 `open_id` 粘性路由）；应用侧已落地，ingress 待落地 |
| 3 | ingress 采用哪种形态（C1 LB / C2 router / C3 分区队列）？ | ⏳ **待定**（部署形态未定） |
| 4 | 出站幂等落库何时补？ | ⏳ 登记：**Autonomy 接入飞书（FEISHU-008）前必须补** —— 否则主动消息在多实例下可能重复投递 |
