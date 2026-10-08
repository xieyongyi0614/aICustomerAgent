# 飞书接入人工冒烟回归清单（FEISHU-006）

> 适用：真实模型 + 真实飞书应用的上线前人工演练。
> 自动化测试无法替代本清单——它验证「真实飞书协议 + 真实模型」的端到端可用性。
> 执行环境：`apps/backend`，服务启动 `uv run uvicorn app.main:app --reload --port 8020`。

## 准备

- [ ] 飞书开放平台：创建应用 → 开启机器人能力 → 申请 `im:message`（或 `im:message:send_as_bot`）→ 订阅 `im.message.receive_v1`
- [ ] 配置回调 URL：`https://<公网域名>/api/v1/feishu/events`（内网穿透或测试环境），验证通过（challenge 回显成功）
- [ ] 配置 Verification Token / Encrypt Key（推荐配置 Encrypt Key，完整校验能力）；凭据写入 `.env`（**不提交**）
- [ ] 数据库：`uv run alembic upgrade head`，确认迁移链头为 `tests/support/schema_pins.py::MIGRATION_HEAD` 的当前值（钉测单点；**勿照抄历史编号**），且 `channel_identities` 表存在
- [ ] 启动服务；确认启动日志**无** SettingsError、无飞书相关报错；确认 `FEISHU_ENABLED=true` 生效
- [ ] `.env` 中 `FEISHU_APP_ID` / `FEISHU_APP_SECRET` / `FEISHU_VERIFICATION_TOKEN` 已填写

## 主链路（真模型）

- [ ] 飞书单聊发「你好」→ 数秒内收到角色回复（一条完整文本；超长则分段到达且内容连贯）
- [ ] 回复内容符合角色人设（亚丝娜口吻，非通用助手）——**真模型抽查项**
- [ ] 连续 3 轮对话 → 上下文连贯（追问前文能被正确回忆）
- [ ] 重启服务后再发一条 → 会话延续（同一 session_id，记忆不断裂；`channel_identities` 仍只有一行）

## 状态保持（真模型抽查项）

- [ ] 说到偏好（如「我讨厌香菜」）→ 下一轮提及相关话题时角色记得（Memory 生效）
- [ ] 提到家中物品/消耗行为（如「把鸡蛋拿去煎了」）→ DB `worlds` / `world_entities` 发生变化（World/Inventory 生效）
- [ ] 表达关系推进信号（如感谢/亲密对话）→ `relationship_state` 数值有变化
- [ ] `/api/v1/debug` 的 trace 查询能看到该轮次（飞书轮次与 Web 轮次同构可观测）

## 边界（负例）

- [ ] 群聊里 @机器人 → **不回复**（日志有「忽略群聊」记录，HTTP 侧 200）
- [ ] 发送图片 → **不回复**
- [ ] 发送纯空白文本 → **不回复**
- [ ] 同一事件被重放（重发相同 body 与 headers）→ 只收到一次回复（`event_id` 去重）
- [ ] 伪造 token → 401，无任何回复；篡改签名 → 403，无任何回复
- [ ] 时间戳超窗的重放请求 → 403
- [ ] Encrypt Key 未配置时（`FEISHU_ENCRYPT_KEY` 留空）发未加密消息 → 正常回复；启动日志有「安全性降级」warning
- [ ] 关闭 `FEISHU_ENABLED` 后重启服务再发消息 → 端到端静默（无回复、无异常堆栈；Web 对话不受影响）

## 多用户

- [ ] 第二个飞书账号（不同 open_id）对话 → 两账号的上下文/记忆/世界**互不串**
- [ ] 两账号同时发消息 → 各自回复正确、无交叉
- [ ] 查 `channel_identities` 表 → 恰好两行，`external_id` 为两个真实 open_id，`internal_user_id` 为**两个不同的雪花 ID 十进制串**（ADR-16 起不再由凭据派生；实际 ID 以表内值为准）

## 授权登录与账号绑定（2026-10-08 增量，ADR-19）

> 前置（飞书开放平台，人工）：①复用机器人同一个自建应用并**开启「网页」能力**；②在「安全设置 > 重定向 URL」登记 `https://<公网域名>/api/v1/auth/feishu/callback`；③申请 OAuth 所需权限（获取用户基本信息 / 用户 ID）并**创建版本发布**（自建应用企业内生效）。
> 配置：`.env` 设 `FEISHU_OAUTH_REDIRECT_URI`（与后台登记**逐字一致**），可选 `FEISHU_OAUTH_SCOPE`；Redis 与 `AUTH_TOKEN_SECRET` 必须可用。

- [ ] 未配置 `FEISHU_OAUTH_REDIRECT_URI` 时调 `GET /api/v1/auth/feishu/authorize` → **503**（文案点名缺哪几项），不是 500
- [ ] 真机登录页点「飞书」→ 打开浏览器授权页 → 授权后浏览器显示「授权成功，请返回朝夕 App」→ 回到 App 自动进入首页（页面恢复后由 2s 轮询完成，最长 90s）
- [ ] 该飞书账号此前**未**私聊过机器人 → 首次飞书登录后 `channel_identities` 出现一行，`internal_user_id` 为新雪花 ID；再次飞书登录 → **不新建 users 行**（同一 `user_id`）
- [ ] 该飞书账号**已**私聊过机器人（自动建过壳账号）→ 飞书登录直接登进壳账号（`internal_user_id` 不变）
- [ ] 已用邮箱登录的账号在「我的 → 飞书账号」点「去绑定」→ 授权完成后该行变「已绑定 · 飞书里也能找到亚丝娜」
- [ ] 绑定后：在飞书里给机器人发消息 → 与该账号在 App 里的记忆/账本**同源**（例如 App 里记的账在飞书追问能答上）
- [ ] 绑定后：`/auth/bindings` 返回 `feishu.bound=true` 且 `bound_at` 非空；查表确认该 open_id 行的 `internal_user_id` 已等于 token 用户
- [ ] 绑定后主动消息可达：触发一条主动消息（或调试面 `send_proactive`）→ 目标用户的飞书收到（`resolve_recipient` 反查到 open_id）
- [ ] 冲突（同一 open_id 被另一个**有邮箱**的账号绑着）：另一账号发起绑定 → **409** + 「该飞书账号已绑定其他账号，如需合并请联系管理员」，且**不发生任何数据迁移**
- [ ] 「一人一飞书」：已绑 A 账号后再绑 B 账号 → **409** + 「已绑定其它飞书账号，请先解绑」
- [ ] 接管壳账号：已私聊过机器人的 open_id，用邮箱账号绑定 → 成功（`internal_user_id` 改为邮箱账号）；**同时确认**旧壳 `users` 行与其记忆仍在（本次不做数据归并——这是已知取舍，不是缺陷）
- [ ] 用户在授权页点「拒绝」→ App 提示「你在飞书侧取消了授权」，且不产生任何绑定/用户行
- [ ] state 复用：同一 state 领取成功后再次 `claim` → **400**（授权请求已失效）；等待期间重复 `claim` → **404 + `Retry-After: 2`**（不烧 state）
- [ ] 过期 state（等过 `FEISHU_OAUTH_STATE_TTL_SECONDS`）→ `claim` 返回 400，回调页显示「授权已过期」
- [ ] 解绑：「我的 → 飞书账号 → 解绑」二次确认后该行变「去绑定」，`channel_identities` 中该行**已删除**；再在飞书发消息 → 自动建**新**账号（与解绑前账号数据隔离）
- [ ] 全程日志/trace 中**不出现** `app_secret` / `user_access_token` / 授权码明文

**平台边界核对（不是缺陷，需如实告知）**：把授权链接发给**不在本飞书团队**的账号 → 授权页提示无企业权限、无法完成登录；对照 `architecture.md` §8.6。若要求外部用户可用，须上架 ISV 商店应用（企业认证），**不属本次范围**。

## 运维

- [ ] 限流：同账号快速连发超过 `CHAT_RATE_LIMIT_PER_MINUTE` → 收到「你发得太快了」兜底文案（**响应为 HTTP 200，不是 429**；侧记限流 warning 日志）
  - ⚠️ 该条为 FEISHU-009 的行为变更（`review-v1.2.md` · N-01）。若观察到 429，说明回退到了旧实现——飞书会重投同一 `event_id`，重投将被去重表静默吞掉，用户消息永久丢失
- [ ] 明文新鲜度：伪造一个 `create_time` 早于 `FEISHU_SIGNATURE_WINDOW_SECONDS`（默认 300s）的明文事件 → 403 且零派发（N-02）
- [ ] 新鲜度拒绝日志含 `skew=<偏差秒数>`，可与服务器时钟漂移（NTP）建立联系
- [ ] 非文本反馈：私聊发一张图片或一个表情 → 收到「我目前只能读文字哦～」；**同样的内容发到群聊 → 无任何回复**（N-08）
- [ ] 非文本刷屏：快速连发表情超过 `CHAT_RATE_LIMIT_PER_MINUTE`（或 `FEISHU_RATE_LIMIT_PER_MINUTE`）后不再回复——兜底文案同样受限流约束
- [ ] **多实例就绪契约**：临时设 `FEISHU_ENABLED=true` + `FEISHU_INSTANCE_COUNT=2` → **服务启动失败**，错误信息含「多实例就绪契约未满足」、缺哪一项声明、以及 `multi-instance-options.md` 路径（FEISHU-011）
  - ⚠️ 该条是**预期失败**：见到启动报错说明契约生效。若服务照常启动，说明契约被回退了
  - 再补上 `FEISHU_INGRESS_SHARDED_ROUTING_ENABLED=true` + `FEISHU_DEDUPE_PERSISTENT_ENABLED=true` → 应能正常启动
- [ ] **C2 router 转发**（多实例）：把飞书回调指向 `/api/v1/feishu/ingress/events` 后，普通消息能正常收到回复；router 日志中目标 URL 的分片下标与该账号的 `shard_of` 一致
- [ ] **router 不鉴权**：故意用错误的 `token` 构造事件 → router **照转**（返回下游的 401），而不是 router 自己拒绝——校验必须只有一处
- [ ] **router 失败不改投**：停掉目标实例 → router 返回 **503**，且**没有**把请求转给其他实例（否则会破坏同会话串行）
- [ ] **出站幂等落库**（多实例，无开关）：同一条回复在实例 A 发出后，实例 B 对同一逻辑消息不再重复发送（占位落在 `feishu_deliveries`）
- [ ] **出站幂等 fail-open**：停掉 DB 后仍能正常回复用户（记 `fail-open` warning），不得出现「用户收不到回复」
- [ ] **就绪契约两项**：`FEISHU_ENABLED=true` + `FEISHU_INSTANCE_COUNT=2` 时，缺任一项声明（router/分流、跨进程去重）都应**启动失败**并点名缺的那一项
- [ ] **分片归属（仅多实例时）**：`FEISHU_INSTANCE_COUNT=2` + `FEISHU_INSTANCE_INDEX=0`，用归属 shard 1 的账号发消息 → 收到 **503**，且日志出现 `feishu event landed on wrong shard`（抽样）；把该实例设为 `INDEX=1` 后同一账号正常受理
  - ⚠️ 若上线后持续看到 `wrong shard` error，说明 **ingress 没有按 `crc32(open_id) % FEISHU_INSTANCE_COUNT` 分流**——先修 ingress，不要靠改应用绕过
- [ ] 消息轰炸（超过 `FEISHU_SESSION_QUEUE_LIMIT`）→ 收到「消息有点多」过载提示，且此前已接受的消息仍按序回复
- [ ] 临时改错 `FEISHU_APP_SECRET` → 启动或首个事件日志出现明确错误分类（可定位是凭据问题）
- [ ] 临时改错 `FEISHU_ENCRYPT_KEY`（与平台不一致）→ 加密事件解密失败 → 400 且服务不崩
- [ ] 出站飞书 API 故障模拟（如临时撤回 `im:message:send_as_bot` 权限）→ 终败仅 error 日志，服务不崩、已落库事实不变；恢复权限后下一轮正常
- [ ] 全程日志中**不出现** `app_secret` / `encrypt_key` / `verification_token` / `tenant_access_token` 明文

## 完成标准

以上全部勾选后，P0 链（FEISHU-001~006）与「授权登录与账号绑定」增量（ADR-19）可视为「真实环境验收通过」。
任一项失败：记录现象与日志（脱敏后），回到对应 Task 的 Detail 排查，**不要**在本清单内就地改代码。
