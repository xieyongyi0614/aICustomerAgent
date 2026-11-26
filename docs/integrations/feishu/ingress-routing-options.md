# 方案 C 的 ingress 形态：**已选定 C2（轻量 router）**

> 前置阅读：`multi-instance-options.md`（五个方案对比，C 的定位）、`architecture.md` §7.3。
> 应用侧契约（分片算法 / 归属校验 / 就绪契约）见 `channels/feishu/shards.py` 与 `api/v1/feishu.py::_owns_shard`。

## 决策

| 形态 | 状态 |
|---|---|
| **C2 轻量 router** | ✅ **已选定并落地**（2026-09-20）。应用侧 + router 端点均已实现，见 §2 |
| C3 分区队列 | ⏸ **暂不实现**（已评估、登记）。理由见 §3 |
| ~~C1 LB 粘性~~ | ❌ **已排除，不再考虑**。理由见 §4 |

---

## 1. 两个共同前提（C2 的实现依据）

### 1.1 前提一：`open_id` 只在 body 里

`open_id` 位于 `body.event.sender.sender_id.open_id`，**不在任何请求头**里。飞书的头只有 `X-Lark-Request-Timestamp` / `X-Lark-Request-Nonce` / `X-Lark-Signature`——都是**请求级**的，不含用户标识。因此「按 header / cookie / 源 IP 做粘性」**做不到**按会话分流。

### 1.2 前提二：配了 Encrypt Key 时，body 是密文，必须解密才能分流

飞书加密事件的外层只有一个字段：

```json
{ "encrypt": "<base64(AES-256-CBC(iv + 密文))>" }
```

**除密文外没有任何业务字段**。所以 router 必须能解密——这也是它必须持有 Encrypt Key 的原因。

### 1.3 算法规格（router 与应用必须一致）

```text
shard = crc32(open_id.encode("utf-8")) % FEISHU_INSTANCE_COUNT
```

- `crc32` = **标准 CRC-32（IEEE 802.3，多项式 `0xEDB88320`）**，与 Python `zlib.crc32` 一致。
- ⚠️ `open_id` 是飞书用户 open_id 的**原始字符串**，不是 `internal_user_id`，也不是 `session_id`（后者形如 `feishu:{open_id}`，整串哈希结果不同）。
- 已知**不匹配**的常见组件：nginx `split_clients`（MurmurHash2）、`upstream hash ... consistent`（ketama）、多数 LB 的「会话保持」（IP/cookie）。

**C2 让这条前提自动成立**：router 直接 `from app.channels.feishu import shards` 调用 `shards.shard_of()`，与应用是**同一份代码**——不存在算法漂移。这是选 C2 的核心理由。

### 1.4 一致性自测（排障用）

```bash
cd apps/backend
python -m scripts.print_feishu_shard_vectors --count 2
```

```text
open_id                         crc32  shard
ou_e2e_alice               4070511795  1
ou_B_iso                      2464350  0
ou_1                       2093405011  1
ou_2                       3855581929  1
ou_demo_user               2058004976  0
ou_0000000000000000         497540959  1
ou_zzzzzzzzzzzzzzzz        2747821489  1
ou_测试用户                    4120490236  0
```

C2 下这张表主要用于**排障**（确认「事件落错分片」不是算法问题），而非配置依据。

### 1.5 一致性失败的后果

事件落到错误实例 → 应用侧 `_owns_shard()` 拒绝 → **503** → 飞书重投。应用侧已做抽样留痕（每 100 次一条 error，含期望分片与实例下标）：

```text
feishu event landed on wrong shard: open_id=... expected_shard=1 instance_index=0 ...
```

---

## 2. C2 的实现（已落地）

### 2.1 数据流

```text
飞书 ──POST──▶ router  POST /api/v1/feishu/ingress/events
                 ├─ 限长读体（复用 FEISHU_MAX_BODY_BYTES）→ 超限 413
                 ├─ 若 body 有 encrypt → events.decrypt(Encrypt Key)   ← 复用应用同一份代码
                 ├─ open_id = body.event.sender.sender_id.open_id
                 ├─ shard = shards.shard_of(open_id, FEISHU_INSTANCE_COUNT)  ← 同一份代码
                 └─ 转发**原始 body + 原始签名头** → {目标实例}/api/v1/feishu/events
                 ◀─ 原样回传下游响应（含状态码）
```

| 位置 | 内容 |
|---|---|
| `api/v1/feishu_ingress.py` | router 端点、`extract_open_id()`、`_forward()` |
| `api/v1/feishu_http.py` | 与 webhook 共用的 `read_body_limited()` / `reject()` |
| `core/settings/feishu.py` | `feishu_router_enabled` / `feishu_router_instance_urls` / `feishu_router_timeout_seconds` |
| `tests/unit/test_feishu_ingress_router.py` | 14 个用例 |

### 2.2 五条不可动摇的设计约束

1. **转发原始 body 与原始签名头**。飞书签名覆盖的是**密文 body**；若转发解密后的明文，下游验签必然失败（403）。router 只是「读一下」再原样转发。故只转发 `Content-Type` / `X-Lark-Request-Timestamp` / `X-Lark-Request-Nonce` / `X-Lark-Signature` 四个头。
2. **router 不做鉴权决策**。签名 / token / 新鲜度 / 去重全部留给下游实例——安全闸只有一处（应用），router 即使被伪造请求打也不会绕过它们。token 错的请求也照转，由下游拒绝。
3. **转发失败不得自行改投其他实例**。改投会破坏「同会话恒落同实例」这一方案 C 的前提，导致同会话并发。正确做法是返回 503 让飞书重投，等目标实例恢复。
4. **取不到 `open_id` 时固定转发 shard 0**。覆盖三种情形：challenge（与用户无关，任何实例都能应答）、结构非法、无 Encrypt Key 无法解密。这些请求要么无需精确路由，要么会在下游被校验拦下。
5. **应用侧归属校验保留**（`_owns_shard`）。router 分对了是正常路径；万一 router 配置错，应用侧的 503 + 抽样 error 是**最后一道可观测的防线**。

### 2.3 配置

```bash
FEISHU_ROUTER_ENABLED=true
# 逗号分隔的实例基址，顺序即分片下标 0..N-1；个数必须等于 FEISHU_INSTANCE_COUNT
FEISHU_ROUTER_INSTANCE_URLS=https://i0.internal,https://i1.internal
FEISHU_ROUTER_TIMEOUT_SECONDS=5.0
```

- 飞书的回调地址指向 router：`https://<router 域名>/api/v1/feishu/ingress/events`。
- **`FEISHU_ROUTER_ENABLED` 本身即是「ingress 已分流」的声明**，无需再开 `FEISHU_INGRESS_SHARDED_ROUTING_ENABLED`（就绪契约接受二者之一）。
- router **无状态**，可多副本 + 普通轮询 LB（**不需要粘性**，因为它自己不持有会话）。

### 2.4 失败模式

| 场景 | 行为 |
|---|---|
| 目标实例不可达 | `503` → 飞书重投；用户侧表现为「机器人暂时没反应」 |
| 下游返回 401/403/413 | 原样回传（router 不解释、不改写） |
| router 挂掉 | 多副本 + LB；无状态，重启无损 |
| Encrypt Key 轮换 | router 与所有实例都要换 |
| 扩缩容 | 只需改 router 的实例列表，**不需要改 LB** |

### 2.5 验证

- `tests/unit/test_feishu_ingress_router.py`：**14 passed**。覆盖分片选择、原始 body/签名头转发、router 不鉴权、无 open_id → shard 0、无密钥/解密失败 → shard 0、加密体按解密后的 open_id 分流、超限 413、下游响应原样回传、传输失败 → 503 且零改投。
- **反向验证**：把 `api/v1/feishu.py` 回退到 HEAD（分片校验移除）→ 3 个分片用例失败；恢复后 md5 一致。

---

## 3. C3 分区队列：已评估，**暂不实现**

**形态**：webhook 只做「校验 + 入队」，N 个 worker 各消费固定分区；亲和性由队列分区承担，因此 **LB 可以是最蠢的轮询**，不需要解析 body、不需要解密。

**暂不实现的理由**：C2 已解决同一个问题（同会话恒落同实例），而 C3 的增量收益主要是「重试 / 死信 / 崩溃恢复由队列承担」与「worker 可独立扩缩」——这两点在当前规模下不构成瓶颈，却要付出**改造 `SessionInbox`（合并窗口改为按入队时间戳聚合）+ 一整套 ack / 可见性超时 / 死信 + 新基础设施**的代价。

**登记为后续演进选项**，当出现下列任一信号时再启动：

- 需要按会话量弹性扩缩 worker（而不是按整机扩缩）；
- 飞书重投的不可控性成为实际运维痛点（需要队列内的可控重试与死信）；
- 已经在别处引入了 MQ，边际成本下降。

**载体备选**（届时再选）：Kafka（topic 多分区 + `open_id` 作 key，语义最标准）、Redis Streams（多 stream + `XREADGROUP`，轻量）、PG 队列表（`SELECT ... FOR UPDATE SKIP LOCKED`，零新组件但等于手写半个 MQ）。

---

## 4. C1 LB 粘性：已排除，不再考虑

**形态**：让 LB / 网关直接读 body、算分片、选实例。

**排除理由（三条全中）**：

1. **LB 必须持有 Encrypt Key 并实现 AES-256-CBC**——因为 `open_id` 只在（加密的）body 里（§1.2）。这把 LB 从「转发组件」变成「持密钥 + 做加解密 + 实现哈希」的组件，安全面与故障面都显著变大。
2. **算法漂移风险最高**——LB 的默认哈希几乎都不是 CRC-32（§1.3）。一旦不一致，事件会大量落到错误分片，表现为偶发 503 与重投风暴，且**不会崩溃**，只会静默错。
3. **扩缩容要求跨系统原子变更**——改 `FEISHU_INSTANCE_COUNT` 时必须同时改 LB 分流配置与所有实例的配置；滚动重启期间新旧映射并存 → 大量 503。

C2 用「多一跳 HTTP（同机房 ~1ms）」换掉了全部三条，**这笔交易明显划算**。

---

## 5. 上线检查清单（C2）

- [ ] 飞书开放平台的回调地址已改为 `/api/v1/feishu/ingress/events`
- [ ] `FEISHU_ROUTER_INSTANCE_URLS` 的个数 == `FEISHU_INSTANCE_COUNT`，顺序与实例下标一致（启动期会校验）
- [ ] router 与所有实例的 `FEISHU_ENCRYPT_KEY` 一致（否则 router 解不出 `open_id`，全部落到 shard 0）
- [ ] 就绪契约两项齐备（`FEISHU_ROUTER_ENABLED` + `FEISHU_DEDUPE_PERSISTENT_ENABLED`）；出站幂等无开关，由组合根无条件安装
- [ ] 灰度期盯 `feishu event landed on wrong shard`（应为 0）
- [ ] 变更手册写明：**改 `FEISHU_INSTANCE_COUNT` 必须同步改 router 的 URL 列表**——取模基数一变，几乎所有会话都会换实例
