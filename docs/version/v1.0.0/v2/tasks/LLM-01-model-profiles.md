# LLM-01 多模型 Profile 配置与切换

> 状态：✅ 已完成（2026-08-27）。V2 角色状态系统交付后的增量特性，跨前后端。

| 字段 | 内容 |
|---|---|
| Task ID | LLM-01 |
| Task Name | 多模型 profile 配置与切换（后端 profiles API + 会话级 profile 注入 + 前端选择器） |
| Type | BE + FE |
| Priority | P0 |

## Description

将单一 `OPENAI_API_KEY / BASE_URL / MODEL` 环境变量配置升级为多模型 profile 体系：后端从 `LLM_PROFILES_JSON` 加载多个 OpenAI 兼容服务商配置，暴露 `/api/v1/llm/profiles` 查询接口，并在 chat 流式接口支持按请求指定本次使用的模型；前端提供顶栏模型选择器，选择存 localStorage、随每条消息发送生效（消息级切换，无需刷新页面）；mock 模式通过 MSW 同步提供 profiles 接口。

## Scope

- 后端
  - `app/core/settings.py`：解析 `LLM_PROFILES_JSON`（数组，必填 id/label/base_url/model/api_key，可选 max_tokens、temperature、top_p、frequency_penalty、presence_penalty、extra_body_thinking）与 `DEFAULT_LLM_PROFILE`
  - `app/core/llm_factory.py`：按 profile 构建 ChatOpenAI 实例；`list_llm_profiles()` / 默认回落
  - `app/api/v1/schemas.py`：`ChatRequest.profile_id` 可选字段 + profiles 响应模型
  - `app/api/v1/llm.py` + 路由注册：`GET /api/v1/llm/profiles`
  - `app/api/v1/deps.py`：profile 解析优先级 **请求体 body.profile_id > 请求头 X-LLM-Profile > 查询参数 ?profile_id=**；未知 id 抛 `SettingsError` → HTTP 400（流开始前返回，不触 DB）
- 前端
  - `api/llm.ts` / `types/backend/llm.ts` / `api/query-keys.ts`：profiles API 与缓存键
  - `hooks/use-llm-profiles.ts`：react-query 拉取，失败静默降级为空列表
  - `lib/llm-profile-storage.ts`：localStorage 存取 + `resolveActiveLlmProfileId()`（失效 id 自动清除并回落 default）
  - `components/shell/llm-profile-select.tsx` + `top-bar.tsx`：顶栏选择器（profiles 为空不渲染，title 提示「下一条消息生效」）
  - `stores/chat-store-factory.ts`：send/retry 时附带 `profileId: readStoredLlmProfile()`
  - `mocks/fixtures.ts` + `mocks/msw-handlers.ts`：MSW 提供 profiles fixture（longcat default + minimax-m3）

## Out of Scope

- `_build_llm` 对不支持 `extra_body.thinking` 的服务商的条件化处理（已知限制，后续收敛）
- 按 profile 维度记录用量统计 / 追踪

## Dependencies

- 无（基于 V2 已完成基线，git tag `v2-checkpoint` 之后独立增量）

## Input

- 用户需求：修复前端所选模型在后端不生效的 P0 缺陷（body 中 profile_id 未被后端读取）

## Output

- 后端：上述 settings / llm_factory / api 改动 + `tests/test_llm_profiles.py`（11 个用例）
- 前端：上述组件 / hook / store / mock 改动 + `llm-profile-storage.test.ts`
- 文档：`apps/backend/README.md`、`docs/version/v1.0.0/frontend/deploy.md` 环境变量与 API 说明更新

## Business Rules

1. profile 解析优先级固定为 **body > header > query**，均缺省时用 default profile。
2. 未知 profile id 必须在流式响应开始前返回 400，不得触发任何 LLM / DB 调用。
3. chat 流式成功响应头回显实际使用的 profile（`X-LLM-Profile`），便于排查。
4. 前端仅在 profiles 非空且存在 activeProfileId 时渲染选择器；API 失败不阻塞聊天。
5. 切换语义为「消息级」：store 每次发消息时读取当前选择，下一条消息即生效，无需刷新。
6. 本地存储的 profile id 不在服务端列表中时自动清除并回落 default（防 stale 数据）。

## API Dependencies

- `GET /api/v1/llm/profiles` → `{ default: string, profiles: [{ id, label, model, default }] }`
- `POST /api/v1/chat/stream` 请求体新增可选 `profile_id`

## Data Dependencies

- 无

## Permission

- 无

## Error Handling

- 未知 profile → HTTP 400（detail 说明）
- `LLM_PROFILES_JSON` 非法 JSON / 缺字段 / `DEFAULT_LLM_PROFILE` 不在数组内 → 启动即抛错（fail fast）
- profiles 接口前端失败 → 选择器隐藏，使用默认链路兜底

## Subtask 拆分

- S1：settings 多 profile 解析 + fail fast 校验
- S2：llm_factory 按 profile 构建实例 + profiles 查询
- S3：chat 接口三来源 profile 解析依赖（deps.py）+ 400 语义
- S4：前端 storage / hook / 选择器 / store 发送链路接入
- S5：MSW handler + fixtures 同步
- S6：测试补齐（后端 4 类新用例 + 前端 storage 单测、msw 用例、TopBar QueryClientProvider 包装）
- S7：README / deploy.md 文档更正

## Acceptance Criteria

- 后端全量 pytest 通过（159 passed + 3 skipped PG 无实例）；其中 llm-profile 相关 11 项
- 前端相关 vitest 套件全过，`tsc -b` 零错误，改动文件 ESLint 零告警
- mock 模式顶栏出现模型选择器且可切换不报错；真实模式切换后下一条消息由新模型应答

## Test Requirements

- `tests/test_llm_profiles.py`：三来源优先级、default 回落、未知 profile 抛 400、TestClient 层 body 传未知 profile 返回 400 且不进 DB
- `src/lib/llm-profile-storage.test.ts`：无存储回落 default、有效值保留、失效值清除并回落
- `src/mocks/msw-handlers.test.ts`：profiles 接口返回含 default 标记的列表