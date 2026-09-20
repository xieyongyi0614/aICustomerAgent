# 飞书接入人工冒烟回归清单（FEISHU-006）

> 适用：真实模型 + 真实飞书应用的上线前人工演练。
> 自动化测试无法替代本清单——它验证「真实飞书协议 + 真实模型」的端到端可用性。
> 执行环境：`apps/backend`，服务启动 `uv run uvicorn app.main:app --reload --port 8020`。

## 准备

- [ ] 飞书开放平台：创建应用 → 开启机器人能力 → 申请 `im:message`（或 `im:message:send_as_bot`）→ 订阅 `im.message.receive_v1`
- [ ] 配置回调 URL：`https://<公网域名>/api/v1/feishu/events`（内网穿透或测试环境），验证通过（challenge 回显成功）
- [ ] 配置 Verification Token / Encrypt Key（推荐配置 Encrypt Key，完整校验能力）；凭据写入 `.env`（**不提交**）
- [ ] 数据库：`uv run alembic upgrade head`，确认迁移链头为 `0036`（`channel_identities` 表存在）
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
- [ ] 查 `channel_identities` 表 → 恰好两行，`internal_user_id` 分别为 `feishu:ou_A` / `feishu:ou_B`（ou 为各账号真实 open_id）

## 运维

- [ ] 限流：同账号快速连发超过 `CHAT_RATE_LIMIT_PER_MINUTE` → 收到「你发得太快了」兜底文案（**响应为 HTTP 200，不是 429**；侧记限流 warning 日志）
  - ⚠️ 该条为 FEISHU-009 的行为变更（`review-v1.2.md` · N-01）。若观察到 429，说明回退到了旧实现——飞书会重投同一 `event_id`，重投将被去重表静默吞掉，用户消息永久丢失
- [ ] 明文新鲜度：伪造一个 `create_time` 早于 `FEISHU_SIGNATURE_WINDOW_SECONDS`（默认 300s）的明文事件 → 403 且零派发（N-02）
- [ ] 新鲜度拒绝日志含 `skew=<偏差秒数>`，可与服务器时钟漂移（NTP）建立联系
- [ ] 非文本反馈：私聊发一张图片或一个表情 → 收到「我目前只能读文字哦～」；**同样的内容发到群聊 → 无任何回复**（N-08）
- [ ] 非文本刷屏：快速连发表情超过 `CHAT_RATE_LIMIT_PER_MINUTE`（或 `FEISHU_RATE_LIMIT_PER_MINUTE`）后不再回复——兜底文案同样受限流约束
- [ ] 消息轰炸（超过 `FEISHU_SESSION_QUEUE_LIMIT`）→ 收到「消息有点多」过载提示，且此前已接受的消息仍按序回复
- [ ] 临时改错 `FEISHU_APP_SECRET` → 启动或首个事件日志出现明确错误分类（可定位是凭据问题）
- [ ] 临时改错 `FEISHU_ENCRYPT_KEY`（与平台不一致）→ 加密事件解密失败 → 400 且服务不崩
- [ ] 出站飞书 API 故障模拟（如临时撤回 `im:message:send_as_bot` 权限）→ 终败仅 error 日志，服务不崩、已落库事实不变；恢复权限后下一轮正常
- [ ] 全程日志中**不出现** `app_secret` / `encrypt_key` / `verification_token` / `tenant_access_token` 明文

## 完成标准

以上全部勾选后，P0 链（FEISHU-001~006）可视为「真实环境验收通过」。
任一项失败：记录现象与日志（脱敏后），回到对应 Task 的 Detail 排查，**不要**在本清单内就地改代码。
