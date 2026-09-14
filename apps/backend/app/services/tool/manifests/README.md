# 外部 API 工具声明目录（TOOL-011）

把"接入一个新外部能力"降为"加一个声明文件"，零 Python 改动。

## 生效方式

```bash
V24_TOOL_SYSTEM_ENABLED=true
V24_TOOL_EXTERNAL_API_ENABLED=true
# 本目录（或你自己的声明目录）
V24_TOOL_EXT_MANIFEST_PATH=app/services/tool/manifests
# 域名白名单，逗号分隔；空 = 全禁（硬纪律）
V24_TOOL_EXT_ALLOWED_HOSTS=api.example.com,hooks.example.com
# 凭据只从环境变量读取，声明文件里只写变量名
EXT_API_WEATHER_TOKEN=...
EXT_API_HOOK_KEY=...
```

启动期逐条解析 `*.yaml` + 八项校验（tool_id / https+白名单 / 方法 / 凭据引用 /
`response_map` 表达式子集 / 权限下限 / `side_effects` / 长度预算）；
失败只告警跳过该条，**不阻塞启动**。加载报告见 `GET /api/v1/debug/tools/manifests`。

## 安全边界（机制非约定）

- **凭据零硬编码**：声明文件只写 `env: <VAR_NAME>`，值只从环境变量读取；不进日志、不进端点响应、不进台账。
- **域名白名单默认全禁**：`v24_tool_ext_allowed_hosts` 为空时一条都不加载；执行期还会二次校验（防加载后配置收窄）。
- **返回值不受信**：响应内容一律 `untrusted=True`，只作事实素材，不作指令进入决策。
- **无任意代码**：`response_map` 只支持 `$.a.b` / `$.a[0].b` 与 `:str` / `:num` / `:bool` 后缀，函数 / 运算 / 条件 / 通配一律在校验期拒绝。

## 本目录示例

| 文件 | 说明 |
|---|---|
| `weather_current.yaml` | GET + bearer 凭据，响应映射到 `weather.*` observations |
| `webhook_notify.yaml` | POST + apikey 头，响应映射到 `hook.*` observations |

示例域名（`api.example.com` / `hooks.example.com`）与变量名均为占位，**不含任何真实值**。
