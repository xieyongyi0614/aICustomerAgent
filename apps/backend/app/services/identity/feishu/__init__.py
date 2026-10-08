"""飞书身份提供方：授权登录与账号绑定（ADR-19）。

与 `app/channels/feishu/` 的分工是**刻意**的：
  - `channels/feishu/` = 消息通道（入站事件 / 出站投递），依赖面 fail-closed，
    **禁 `redis`、禁 `app.repositories`**，因此放不下本包的东西；
  - `services/identity/feishu/` = 飞书作为**身份提供方**（OAuth 换身份、state、
    登录与绑定编排），属身份域，可正常用 Redis 与仓储。

本包不含通道语义（`open_id → internal_user_id` 的映射是通道无关逻辑，在
`services/identity/channel.py`）。
"""
