# 证据索引 — 当前态架构可视化

> 快照：2026-10-23 · HEAD `e07669d7` · 分支 `feat/design-car-album`
> 置信度：**high** = 代码/配置/迁移/权威文档直接支持；**medium** = 多个部分信号一致；**low** = 命名/目录/归纳推断；**unknown** = 需要运行时或人工验证。

## 1. 容器与边界

| 结论 | 证据 | 置信度 |
|---|---|---|
| 后端是 Python 3.13 + FastAPI + LangChain + PostgreSQL 16 | `README.md:8-22`；`apps/backend/pyproject.toml:5-22` | high |
| 移动端是 Flutter + Riverpod + GoRouter + Dio + Drift | `apps/mobile/pubspec.yaml:14-40`；`README.md:10-12` | high |
| 前端是 React 19 调试控制台，不是产品 UI | `apps/frontend/package.json:10-28`；`README.md:3`；baseline §1.1 | high |
| Docker 单容器托管后端 + 前端 dist；启动先 `alembic upgrade head` | `Dockerfile:1-38` | high |
| Compose 提供 postgres + redis + console；制品卷 `asuna_releases` | `docker-compose.yml:1-56` | high |
| 发布制品根目录默认 `/srv/backend/releases` | `apps/backend/app/core/settings/app_release.py:8-17`；`docker-compose.yml:43,47` | high |
| 所有通道最终收敛到同一对话管线 | baseline §5.4；`app/api/v1/router.py:1-30`；`app/application/chat_pipeline.py:928` | high |

## 2. Run Profile 与运行链路

| 结论 | 证据 | 置信度 |
|---|---|---|
| 三条 Profile 的唯一声明处是 `profiles.py` | `app/application/agent_runtime/profiles.py:31-70` | high |
| `foreground_chat` 阶段序列与 LLM capable / critical 声明 | `profiles.py:34-51` | high |
| `autonomous_tick` 阶段序列与 `decision` 为唯一 LLM capable + critical | `profiles.py:52-68` | high |
| `event_driven` 只有 `event_pregate`，0 LLM | `profiles.py:69-70` | high |
| 前台整链包裹为 foreground Run，`open_foreground_run` 建台账 | `chat_pipeline.py:394`；baseline §4.1 | high |
| 上下文装配包含快照 / 世界 / 历史 / 记忆 / 场景 / 目标 | `chat_pipeline.py:451-543`；baseline §4.1 步骤 2-7 | high |
| 四链并行（router / turn_analyzer / scene_intent / intention） | `chat_pipeline.py:475-543`；baseline §4.1 步骤 7 | high |
| 流式协议：`turn_meta` → token → `done` | `chat_pipeline.py:673-706, 928-953`；baseline §5.2 | high |
| 后台后处理独立容错；调度在流式回答结束后 | `chat_pipeline.py:810-848`；baseline §2.2、§4.1 步骤 17-18 | high |
| life_loop 常驻循环先 sleep 后 tick | `app/application/life_loop.py:65-107` | high |
| tick 尾部维护步按间隔调度；`outbox_consume` 常开 | `life_loop.py:594-728`；baseline §4.2 | high |
| 其它常驻循环由 lifespan 启动 | `app/main.py:27-141`（job worker 78、life loop 89、retention 129、evolution 132） | high |
| baseline 提及的「memory reclaim」独立常驻循环 | `core/settings/memory.py:35,44` 只有设置字段，全 app 无读取点；`main.py` lifespan 无该任务 | **unknown**（需验证是否已合并进 job worker） |
| 六段认知循环是影子/测试实现；默认生产走 Profile 阶段序列 | `app/application/agent_runtime/loop.py:1-31, 117-138, 637-664`；baseline §4 开头裁决 | high |
| 计划七闸引擎尚未接管主路径 | baseline §3.4、`docs/agent-evolution-plan-2026-10.md` §1.2 D2 | high |
| 计划审批闸门已实现，默认 OFF | baseline §8.6；`plan_require_approval` | high |
| 计划澄清闸门规划中、未实现 | baseline §8.7 | high |

## 3. 数据与状态

| 结论 | 证据 | 置信度 |
|---|---|---|
| Schema 唯一真相 = Alembic 迁移链；基线 `0001` + 增量 `0002`~`0011` | `apps/backend/migrations/versions/`；baseline §6.1、ADR-14 | high |
| 当前 57 张表 | `app/core/db/` 的 57 个 `__tablename__`；`migrations/versions/0001_squashed_full_schema.py` + 增量 | high |
| 关系域账本 / 状态 / 快照三分离 | baseline §3.3、§6.1；`relationship_events` / `relationship_state` / `relationship_snapshots` | high |
| 记忆 7 规范类型 + 六态生命周期 + 1-hop 图谱 | baseline §3.6、§8.2；迁移 `0010` / `0011` | high |
| 四源摄取：Conversation / ActionRecord / WorldEvent / RelationshipEvent | baseline §3.6；`services/memory/sources.py` | high |
| 世界读写只经 `world_repository`，异常降级 | baseline §3.2、§2.2 | high |
| 计划落库只经 `goal_repository` 计划面 | baseline §3.4、§8.6 | high |
| 所有领域表以 `user_id` 归属（雪花 ID，VARCHAR 十进制串） | baseline §6.1、ADR-16 | high |
| ID 出 JSON 必须为字符串 | baseline §9（P1 硬约束） | high |

## 4. 外部系统

| 结论 | 证据 | 置信度 |
|---|---|---|
| LLM 统一经 `core/llm_factory.get_llm()`；OpenAI 兼容 profile | `app/core/llm_factory.py:1-80`；`llm_profiles.example.json` | high |
| LLM 调用权经 Gateway 做预算 / 降级裁决 | `app/application/agent_runtime/llm_gateway.py:1-80`；baseline §4.2 | high |
| 飞书通道：Webhook、验签/解密、去重、排队、出站 | `app/channels/feishu/*`；baseline §5.2 | high |
| 飞书 OAuth 登录与账号绑定 | baseline §8.5；`services/identity/feishu/` | high |
| SMTP 验证码：`EmailSender` 协议 + SMTP 实现 | `core/settings/email.py:23-68`；baseline §8.4 | high |
| Open-Meteo 天气 / 地理编码 | `core/settings/weather.py:15-18` | high |
| 外部 API 工具：声明式清单 + 域名 allowlist | baseline §8.1；`TOOL_EXT_MANIFEST_PATH` / `TOOL_EXT_ALLOWED_HOSTS` | high |
| 移动系统能力：通知 / 相册 / 安装器 / 安全存储 | `apps/mobile/pubspec.yaml:24-40`；baseline ADR-20 | high |

## 5. 架构规则

| 规则 | 证据 | 置信度 |
|---|---|---|
| 分层单向依赖 `api → application → agent_runtime → services → repositories → core` | baseline §2.2 | high（文档规则） |
| `api` 禁止依赖 repositories / langchain | baseline §2.2 | high（文档规则） |
| `chains` 禁止依赖 repositories / services | baseline §2.2 | high（文档规则） |
| 业务层禁止直接操作 ORM，唯一 DB 访问面 = repositories | baseline §2.2、ADR-6/9 | high |
| 通道层不包含 Agent / Memory / World 逻辑 | baseline §5.4 | high |
| 世界旁路纪律：异常只 log + 降级 | baseline §3.2 | high |
| 能力只执行不做决策 | baseline ADR-10 | high |
| 前台 / 后台同一决策代码路径 | baseline ADR-11 | high |
| 前台 / 后台回退位已物理删除，回退 = git revert | baseline §4、§9 | high |

## 6. 业务能力证据

| 能力 | 证据 | 置信度 |
|---|---|---|
| 角色定义 / 人格 / 状态三层 | baseline §3.1；`character/asuna/`、`character_state`、`personality_state` | high |
| 情绪 8 值 + 能量/强度 + 按小时衰减 | baseline §3.1 | high |
| 六维关系 + 四阶段 + 冲突状态机 | baseline §3.3 | high |
| 目标分层 + 计划 + 决策管线 | baseline §3.4 | high |
| 六类内置行动能力 + 工具执行五段 | baseline §3.5、§8.1 | high |
| 世界模拟：状态 / 物品 / 时间 / 日计划 / 简报 | baseline §3.2 | high |
| 生活域：账本 / 车辆 / 任务 / 简报 | `app/api/v1/` 路由；baseline §6.1 | high |
| 评估：规则 + LLM Judge 双路 | baseline §11.3 | medium（文档描述为主） |
| 免商店更新：制品入库 / 版本检查 / 断点续传 / 签名校验 | baseline ADR-20 | high |

## 7. 业务能力地图的边界

`capability-map.dot` 是**产品能力归纳**，不是运行时调用图。其节点来自 `README.md`、`AGENTS.md` 与 baseline §1.2 / §3，用户价值归类属于 **medium** 置信度（文档归纳，不是代码直接断言）。

## 8. 假设、未知与验证动作

| 项目 | 类型 | 说明 / 验证动作 |
|---|---|---|
| 「禁止反向依赖」的实际执行情况 | unknown | 本图展示基线规则，不代表自动扫描通过；需要运行依赖扫描 / 架构测试（如 import graph 检查）确认 |
| 部分生活域端到端路径 | unknown | 账本 / 车辆 / 任务 / 简报的 UI → API → 服务 → 表全链路未逐一追踪；需要按域补 flow |
| 外部 LLM provider 可用性 / 配额 | runtime | 静态模型不包含；需运行时日志或 Gateway 指标 |
| Debug Console 多用户隔离 | known gap | baseline §9：调试面可指定 user_id；产品面已隔离 |
| 移动端 golden 基线漂移 | known gap | baseline §9：3 个 golden 在干净 HEAD 上失败（P1） |
| 飞书壳账号旧数据归并 | known gap | baseline §9：归并脚本未实现 |
| 计划澄清 / 审批超时 | not implemented | baseline §8.6 / §8.7 |
| 六段认知循环 | shadow | baseline §4；不要把它画成生产默认路径 |
| 计划七闸引擎 | optional | baseline §3.4；默认关闭的可选段 |

## 9. 生成与校验

```bash
# 确认快照
git rev-parse --short HEAD
git branch --show-current

# 迁移链 head
ls apps/backend/migrations/versions

# 表数量（ORM 模型）
grep -rhoE '__tablename__ = "[a-z_]+"' apps/backend/app/core/db | wc -l

# 若本机安装 Graphviz，可生成 SVG（当前环境未安装 dot）
# dot -Tsvg backend-module-dependencies.dot -o backend-module-dependencies.svg
```

**校验说明**：本环境未安装 Graphviz CLI，因此未生成 SVG；`.dot` 与 `.structurizr.dsl` 是规范源，建议用 Qoder 的 DOT / Structurizr DSL 格式查看器预览。若需纳入 CI，可加 `dot -Tsvg` 与 Structurizr CLI 校验。
