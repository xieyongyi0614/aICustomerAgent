# Character Agent Debug Console 前端架构设计（Frontend Architecture）

> 目标：为 Character Agent 构建开发者调试控制台——左边「和亚丝娜聊天」，右边「观察亚丝娜为什么这样回答」。
> 定位：内部 Developer Tool，非产品 UI。
> 设计原则排序：正确性 > 可观察性 > 调试效率 > 易扩展 > UI 美观。

## 已确认的三项核心决策

| # | 决策 | 内容 |
|---|---|---|
| D-F1 | 技术栈 | **React + Vite + TypeScript（SPA）**，放弃 Next.js 的 Server 能力 |
| D-F2 | 观测数据通道 | 流只承载聊天内容；**State / Memory / Trace 等 Debug 数据在 done 之后经 REST 轮询获取**，不走流内推送 |
| D-F3 | 最小契约改动 | Phase 1 与后端约定**一行 `turn_meta` 事件**（首 token 前下发 RoleMode + TurnAnalysis），其余后端改动全部推迟到 Phase 2 |

### 已核实的后端事实（设计依据）

- 流式契约为 NDJSON over POST（`application/x-ndjson`），行格式 `{"delta":...}` / `{"done":true,"session_id":...}` / `{"detail":错误}`，session 经响应头 `X-Session-Id` 返回。
- V2 的 State Update / Memory Extractor 为流结束后的 fire-and-forget 后处理，「本轮完整观测数据」天然晚于回答完成到达。
- 后端暂无 debug 观测端点（`GET /api/v1/state` 列于 V2 P2 backlog）；Agent Trace 尚未采集。
- V2 存在四条静默降级链路（router 低置信→default、turn_analysis 失败→中性默认值、StateUpdater 失败→纯规则兜底、三表写入失败仅记日志），是本 Console 的重点观测对象。

---

## 1. 技术选型

**结论：React + Vite + TypeScript。**

| 维度 | React + Vite | Next.js |
|---|---|---|
| 定位匹配 | 单页面纯客户端工具，零 SEO/SSR 需求 | App Router / RSC / 文件路由价值全部用不上 |
| 与后端关系 | FastAPI 已是完整 API 服务，dev 用 Vite proxy 解决 CORS | 引入第二套服务端运行时，职责重叠 |
| Streaming | `fetch` + `ReadableStream` 读 NDJSON，框架无关 | Streaming 必须全放 Client Component，RSC 边界是负担 |
| 迭代速度 | HMR 快、配置少——调试工具最看重改起来快 | 构建链更重 |
| 部署 | `dist` 静态产物，可被 FastAPI StaticFiles 或任意静态服务器托管 | 需要 Node 运行时 |

未来扩展逐项判断：

- **API Proxy**：不需要。dev 由 Vite proxy 承担；生产同域部署由 FastAPI/nginx 承担。
- **Authentication**：Console 属内部工具。需要时由后端签发 token + 前端统一拦截器携带，与框架无关。
- **LangGraph**：纯后端事务，前端只消费数据。
- **重新评估信号**：Console 演变为面向最终用户的产品门户（需落地页 / SEO / 服务端鉴权）时再迁 Next.js。领域模型 / API 层 / 组件均保持框架无关，迁移成本可控。

React + Vite 下各问题的回答：

- **API 处理**：dev 环境 `vite.config.ts` 将 `/api` 代理到 `localhost:8000`；生产环境同域挂载或环境变量注入 baseURL。前端只有一层薄 API Client，没有 BFF。
- **Streaming 处理**：`fetch(POST)` → `response.body.getReader()` → 按 `\n` 切行 → JSON.parse → 归一化为类型化事件；`AbortController` 实现 Stop。
- **后续扩展成本**：低。状态层、领域模型、transport 接口均不绑定框架特性。

---

## 2. 产品定位

一句话：**把「亚丝娜为什么这样回答」从黑盒变成可归因的证据链。**

解决的具体问题：

1. **归因**：为什么是这个 mode？（Role Router reason）为什么采取 comfort 行为？（Turn Analysis）为什么提起那条记忆？（Retrieval 打分）为什么语气温柔？（mood=worried + comfort 指令注入）
2. **验证状态系统正确性**：energy 衰减 / relationship delta / stage 迟滞迁移全是数值规则，肉眼聊天看不出来，需要数值可视化 + 阈值刻度。
3. **观测降级路径**：V2 的静默降级在正常聊天中完全不可见，但恰是最需要发现的 bug 来源。
4. **回归测试台**：改 prompt 或阈值后，用同一句话重放对比行为差异。

三条铁律：

- 不允许「看起来在回答但实际已降级」——降级必须有视觉标记；
- 任何展示的数据都能看到原始 JSON（可视化是索引，原始数据是真相）;
- Debug 面板永不阻塞或拖慢 Chat 主流程（某项数据加载失败只影响对应卡片）。

---

## 3. 页面信息架构

双栏结构，三个关键修正：

1. **全局 Header**：session 管理（新建/切换）、连接状态、Mock/Real 开关属全局关切，独立成 TopBar。
2. **右栏更宽**：Debug 信息密度更高，Debug ≈ 55–60%，支持整体折叠（折叠时 Chat 全宽）。
3. **Message ↔ Trace 双向联动**：每条 AI 消息挂「本轮徽章」（mode·behavior·耗时），点击消息 → 右侧切到该轮 Trace。这是把聊天记录和决策证据缝合成证据链的核心交互。

**Debug 面板分组（Tabs）**：

| Tab | 内容 | 默认 |
|---|---|---|
| Overview | RoleMode（mode/intent/confidence/reason）＋ TurnAnalysis（emotion/event/behavior）＋ 状态摘要条 ＋ 降级警告区 | 默认展示 |
| State | CharacterState 卡（mood/energy/topic/inner_state）＋ RelationshipCard（三维 Progress 带 stage 阈值刻度线）＋ 最近 emotion_history 迷你时间线 | Tab |
| Memory | 本轮检索命中 ⇄ 全量记忆切换；本轮 Extractor 决策（should_save/type/importance/去重） | Tab，列表项折叠详情 |
| Trace | 本轮 Waterfall 时间轴 ＋ 步骤详情（见第 10 节） | Tab，打开该轮时加载快照 |
| Raw | 整轮原始 JSON（请求、事件流、状态快照），一键 copy | Tab，默认收起 |

分组原则：**结构化状态用卡片可视化（看趋势），过程性数据用 JSON（查细节）**；每轮新数据默认可见，跨轮历史收纳。

---

## 4. UI Layout

```
┌─────────────────────────────────────────────────────────────────────────┐
│ TopBar  ◉ Asuna Debug Console │ Session▾ [+New] │ ●Connected │ Mock|Real │ ⚙ │
├──────────────────────────────────────┬──────────────────────────────────┤
│ ChatPane (flex-basis ≈42%)           │ DebugPane (≈58%，可整体折叠)      │
│ ┌──────────────────────────────────┐ │ ┌──────────────────────────────┐ │
│ │ ConvHeader: session_id·计数·清空   │ │ │ Tabs: Overview State Memory  │ │
│ ├──────────────────────────────────┤ │ │       Trace  Raw             │ │
│ │ MessageList (ScrollArea)         │ │ ├──────────────────────────────┤ │
│ │  [user]                          │ │ │                              │ │
│ │  [assistant] 流式文本 ▊           │ │ │        当前 Tab 内容          │ │
│ │   🏷 immersive·comfort·5.2s ←联动 │ │ │                              │ │
│ ├──────────────────────────────────┤ │ │                              │ │
│ │ InputBar                         │ │ │                              │ │
│ │ textarea (Enter 发送/Shift+换行)  │ │ │                              │ │
│ │ [Send/Stop] [Retry] [AutoScroll✓]│ │ │                              │ │
│ └──────────────────────────────────┘ │ └──────────────────────────────┘ │
└──────────────────────────────────────┴──────────────────────────────────┘
```

**UI 技术方案：Tailwind CSS + shadcn/ui**（Radix 底层随之引入，无需单独引入）。

- Ant Design：企业中后台视觉基因重，压成暗色高密度调试风成本高、体积大，排除。
- 裸 Radix：shadcn 已是 Radix + Tailwind 的最佳实践封装，裸用等于重造。
- shadcn 组件源码进仓库，可随意改造，零运行时主题黑盒。

**设计 Token 约定**：

| 维度 | 约定 |
|---|---|
| 主题 | 暗色为唯一默认（调试工具惯例） |
| Typography | 正文系统 sans 栈；一切数值（时长/分数/能量/JSON/session_id）一律 mono；枚举值用 Badge 固定色板（同一枚举全局一色） |
| Spacing | 4px 基数；卡片内 12–16px，区块间 16–24px；密度优先 |
| Border/Card | 1px 中性边框 + 8px 圆角，无阴影或极浅阴影 |
| Badge | mode 三档 / 8 种 emotion / 7 种 behavior / 4 种 stage 各配固定色 |
| Progress | 细条渲染 0–1 数值，叠加阈值刻度线（stage 升级线 0.35/0.55/0.75 画竖标） |
| Tabs/Drawer/Dialog | Tabs 为 Debug 主导航；Drawer 用于窄屏 Debug 容器；Dialog 用于清空会话等破坏性确认 |
| Code/JSON Viewer | 自研轻量递归折叠树（等宽字体、按 key 折叠、一键 copy），不引第三方大件 |

**响应式阶梯**：最优 ≥1440px；<1200px Debug 收窄至固定 480px；<1024px Debug 转 Drawer（TopBar 唤起按钮）；<768px 顶部横幅提示使用桌面端，不做移动专属布局。

---

## 5. Component Tree

```
<App>
 ├─ <Providers>                      QueryClientProvider + ThemeProvider + TransportProvider(mock|real)
 ├─ <TopBar>                         session 切换/新建、连接状态灯、Mock 开关、设置 Dialog
 └─ <Workbench>                      双栏布局壳 + 折叠状态
     ├─ <ChatPane>
     │   ├─ <ConversationHeader>     session_id、消息计数、清空(Dialog 确认)
     │   ├─ <MessageList>            滚动容器；AutoScroll(用户上滚暂停跟随 + 回到底部浮标)
     │   │   └─ <MessageItem>*n      按 role 分支渲染；AI 消息含 <TurnBadge>(mode·behavior·耗时)
     │   │       └─ <StreamingText>  streaming 态光标、增量追加
     │   └─ <ChatInputBar>
     │       ├─ <MessageInput>       textarea，Enter/Shift+Enter
     │       └─ <SendControls>       Send ⇄ Stop(Abort)；Retry(重发上一条 user 消息)
     └─ <DebugPane>
         ├─ <DebugTabs>              Tab 导航 + 整体折叠
         ├─ <OverviewPanel>          <RoleModeCard> <TurnAnalysisCard> <DegradationAlerts> <StateSummaryBar>
         ├─ <StatePanel>
         │   ├─ <CharacterStateCard> mood(Badge)+energy(Progress+刻度)+topic+inner_state
         │   ├─ <RelationshipCard>   三维 Progress(带阈值刻度)+stage Badge+距下一阶段提示
         │   └─ <EmotionHistoryStrip> 最近 N 轮 emotion/event 迷你时间线
         ├─ <MemoryPanel>
         │   ├─ <MemoryList>         命中/全量切换；<MemoryItem>(type Badge+importance 进度+时间)
         │   └─ <ExtractorDecisionCard> 本轮 should_save/去重结果
         ├─ <TracePanel>             <TraceWaterfall> + <TraceStepDetail>（见第 10 节）
         ├─ <RawPanel>               <JsonViewer>(整轮原始数据)
         └─ shared                   <StatDot> <KeyValueRow> <SectionCard> <CopyButton>
```

**Chat 区域能力分诊**：

| 能力 | 判定 |
|---|---|
| ConversationHeader、MessageList、User/Assistant/Streaming Message、Input、Send、Stop、Auto Scroll | **MVP 必须**（Stop 即 AbortController，是调试卡死流的基本工具；AutoScroll 必须带上滚暂停） |
| Retry、Clear Conversation、Avatar（静态图）、TurnBadge 联动 | 应该做（MVP 后立即补） |
| 消息编辑/删除、对话分支、搜索、导出、打字机动效 | 暂时不做 |

---

## 6. Domain Model

分两层：`types/backend/`（镜像后端 Pydantic，字段全可选以容忍演进）与 `types/domain/`（前端消费模型 = 后端数据 + UI 状态）。来源列 B=后端、F=前端。

| 模型 | 字段（名：类型） | 来源 | 职责 |
|---|---|---|---|
| Conversation | sessionId: string(B)；createdAt/updatedAt: datetime(B)；messageCount: number(F) | B+F | 会话元数据；sessionId 即后端 conversation 主键 |
| ChatMessage | id: string(F)；role: 'human'\|'ai'(B)；content: string(B)；status: 'pending'\|'streaming'\|'complete'\|'stopped'\|'error'(F)；turnId?: string(F)；createdAt: datetime | B+F | 消息渲染单元；status 驱动流式光标/错误样式，turnId 是消息↔Trace 联动的钥匙 |
| RoleMode | mode: 'professional'\|'default'\|'immersive'；intent: 5 值枚举；confidence: number[0,1]；reason: string | B(router) | 语言风格决策依据；低置信显示「已降级 default」标记 |
| UserEmotion | emotion: 8 值枚举(happy/calm/sad/anxious/angry/tired/excited/neutral)；event: 9 值枚举(achievement/setback/share_goal/seek_help/help_given/complaint/conflict/daily/farewell) | B(turn_analysis) | 用户情绪/事件识别，relationship delta 的根因 |
| BehaviorDecision | behavior: 7 值枚举(normal_reply/comfort/encourage/celebrate/show_concern/recall_memory/ask_followup)；reason: string | B(turn_analysis) | 本轮行为意图（Prompt 第 11 段指令来源） |
| TurnAnalysis | userEmotion: UserEmotion；behavior: BehaviorDecision；degraded: boolean(F) | B+F | 后端一次结构化输出的两半；degraded 由前端按默认值推断 |
| CharacterState | mood: 8 值枚举(happy/calm/worried/sad/shy/excited/tired/angry)；energy: number[0,1]；currentTopic/innerState: string；updatedAt: datetime | B(character_state 表) | 角色「现在是什么状态」 |
| RelationshipState | intimacy/trust/familiarity: number[0,1]；stage: 4 值枚举(stranger/friend/close_friend/partner) | B(relationship_state 表) | 关系演化；前端内置阈值常量画刻度线 |
| MemoryItem | id/userId: string；memory: string；memoryType: 5 值枚举(preference/fact/goal/experience/relationship)；importance: number；createdAt: datetime(B)；hitThisTurn: boolean/score?: number(F) | B+F | hitThisTurn 区分本轮命中列表与全量列表 |
| TraceStep | name: string(固定步骤名枚举，见附录 A3)；status: 'ok'\|'warn'\|'error'(F)；durationMs: number；input/output: unknown(F)；error?: string | F(由 REST 快照组装) | 单个流水线步骤记录；name 与未来 LangGraph node 同构 |
| TurnTrace | turnId: string；steps: TraceStep[]；totalMs: number；degradedSteps: name[](F) | F | 一轮完整证据链，steps 按 duration 排布即 waterfall |
| StreamEvent | 判别联合：delta / turn_meta / done / error（见第 8 节） | F(契约层) | 前端唯一感知传输格式的位置 |
| UiSessionState | connectionStatus / activeTab / selectedTurnId / selectedStepId / autoScroll / apiMode | F | 纯视图状态 |

原则：后端镜像类型允许缺字段不炸（全可选）；前端渲染永远走 domain 类型；后端加字段只改镜像层一处。

---

## 7. State Management

**结论：TanStack Query（服务端资源缓存） + Zustand（实时聊天流） + useState（局部 UI）。不用 Redux，不用 Context 传业务数据。**

| 数据类别 | 方案 | 理由 |
|---|---|---|
| Debug 数据（State/Memory/TurnTrace 快照）、会话列表、历史消息 | **TanStack Query** | 缓存/失效/轮询/手动刷新开箱即用；done 后的有界轮询正是其能力范围 |
| messages、streaming 缓冲、AbortController、连接状态 | **Zustand 单 store**（chatSlice 为主，sessionSlice 辅） | 流式循环发生在 React 生命周期外（async reader loop），需组件外可写的 store；流式高频更新经 selector 隔离，不波及其他面板 |
| 输入草稿、卡片 hover/折叠 | useState | 就地管理 |

否决理由：Redux 对此规模是纯模板税；Context 放高频流数据引发整树重渲；「完全不用库」在跨面板联动（消息↔Trace 选中态）场景下性能优化会很痛苦。D-F2 定稿后 Zustand 职责收窄到纯聊天流，分工比早期方案更干净。

---

## 8. API Architecture

分层严格单向：`Component → Hook → API Client → Backend`。Hook 是唯一发起网络请求和写 store 的层；组件只读 store + 调 hook 动作。

### 8.1 聊天通道（唯一实时流）

沿用 NDJSON over POST fetch（不用 SSE：EventSource 不支持 POST，且后端现契约即 NDJSON）。抽象 `ChatStreamTransport` 接口：`send(request, { onEvent, signal })`。

**最终事件契约**（D-F3 的最小改动仅为新增一行 `turn_meta`，向后兼容：旧客户端忽略未知行，前端在 turn_meta 缺失时优雅降级为 Overview 待 REST 回填）：

| 事件 | 字段 | 到达时机 | 说明 |
|---|---|---|---|
| `turn_meta` | role_mode(RoleMode)，analysis(TurnAnalysis) | **首个 delta 之前**（新增行） | 预侧并发结果（router ∥ turn_analysis 在首字前已完成）；使 Overview 在回答开始前即可展示。降级轮也照发（内容为默认值），前端据 confidence/reason 显示降级徽章 |
| `delta` | text | 流中 | 增量 token（现契约不变） |
| `done` | session_id，turn_id? | 流末 | turn_id 用于定位该轮 Debug 快照（见附录 A2/A3） |
| `error` | detail，code? | 任意时刻 | 兼容现行 `{"detail":...}` 行，语义不变 |

### 8.2 Debug 数据通道（REST，done 后获取）

后端补 4 个只读端点（详见附录 A2）。前端获取策略（D-F2）：

1. **有界轮询**：`done` 后启动，间隔约 800ms，最多约 6 次，读到 `status=complete` 即停（后处理未落库时端点返回 `pending`）；
2. **惰性刷新**：点击消息徽章 / 切换 Tab 时按 turnId 取数（用户操作天然滞后于后处理，竞态基本消失）；
3. **手动刷新按钮**：任何面板随时可用。

三者都收敛在 TanStack Query（refetchInterval 有界 + refetchOnMount + manual refetch），Hook 内实现，组件无感。

---

## 9. Mock Architecture

目标：**UI 组件永远不知道自己在跟谁说话**，切换粒度 = 一个环境变量。

```
              VITE_API_MODE = real | mock
                         ↓
            api/index.ts 工厂（唯一分支点）
            ┌─────────────┴─────────────┐
     RealTransport / RealRest      MockTransport / MSW
     (fetch → vite proxy → :8000)  (fixtures + 脚本流)
            └─────────────┬─────────────┘
              同一套接口签名 + 同一套 Domain Model
                         ↓
                  Hooks / Components
```

- **REST Mock**：MSW（Mock Service Worker）拦截 rest 请求，handlers 按场景返回 fixtures（空记忆 / 富记忆 / 状态濒临升级 三套 persona）。
- **流式 Mock**：`MockChatStreamTransport` 实现相同接口，按剧本逐行发射：turn_meta（指定 mode/emotion/behavior）→ 逐字 delta（可配延迟模拟 LLM）→ done。剧本至少覆盖：日常闲聊、诉苦（sad/setback→comfort）、报喜（excited/achievement→celebrate）、LLM 报错流、turn_meta 缺失的旧契约兼容流。
- **硬约束**：mocks/ 只允许被 `api/index.ts` 工厂 import；fixtures 必须通过 domain 类型校验——mock 是类型契约的第一个消费者。

收益：Phase 1 在后端零改动下全量开工；联调期一键切 real 定位问题归属。

---

## 10. Debug Trace UI

主体：垂直 Waterfall 时间轴（渲染自 REST 拉取的整轮快照，非实时生长；加载中显示骨架行）。

```
Turn #47 · 总耗时 5.81s · ⚠1 项降级                    [刷新]
─────────────────────────────────────────────
Role Router        ██ 120ms    ok
Turn Analyzer      ████ 280ms  ok        ← 与 Router 并发，起始 x 相同
Memory Retrieval   █ 35ms      ok
Context Builder    ▌8ms        ok
Prompt Builder     ▌10ms       ok
LLM (streaming)    ████████████ 4820ms ok ← 首字节 380ms / 完成 4820ms
State Update LLM   ████ 300ms  ⚠ degraded ← 虚线段 = done 之后异步完成
Memory Extractor   █████ 300ms ok
─────────────────────────────────────────────
```

要点：

- 时长条用 **sqrt 缩放**（否则 LLM 数秒会把其他步骤压成细线），hover 显精确值；
- **并发步骤共享起始坐标**，直观传达 gather 并发设计；
- 后处理步骤虚线边框 + 分隔，明确表达发生在回答之后、失败不影响回答；
- 状态色：ok 绿 / **warn 黄 + degraded 徽章**（router 低置信、analysis 取默认值、StateUpdater 规则兜底）/ error 红；降级可视化第一优先；
- 点击步骤 → 详情区：Input（JsonViewer；prompt 类步骤提供渲染后完整 system 原文 + copy）、Output、Duration、Status（warn 附原因）、Error（红块 + copy）；
- 多轮组织：顶部 turn 切换器与左侧消息联动选中；Raw Tab 存整轮原始终稿。

面向 LangGraph 的预留（只留钩子）：`TraceStep.name` 即未来 Graph node 名；并行分支表现为相同起始时刻；Tool Call 未来只是 `name="tool:xxx"` 的普通步骤。现在不做 DAG 视图，届时只需新增布局渲染器，数据模型不动。

---

## 11. Directory Structure

```
apps/frontend/
├── index.html
├── package.json / tsconfig.json / vite.config.ts   # proxy: /api → localhost:8000
├── .env                    # VITE_API_MODE=real|mock, VITE_API_BASE_URL
└── src/
    ├── main.tsx
    ├── app/                        # App 装配 / providers(QueryClient/Theme/Transport)
    ├── components/
    │   ├── chat/                   # ChatPane / ConversationHeader / MessageList /
    │   │                           # MessageItem / StreamingText / ChatInputBar / TurnBadge
    │   ├── debug/                  # DebugPane / DebugTabs / OverviewPanel / CharacterStateCard /
    │   │                           # RelationshipCard / EmotionHistoryStrip / MemoryPanel /
    │   │                           # TracePanel / TraceWaterfall / TraceStepDetail / RawPanel
    │   ├── shell/                  # TopBar / Workbench
    │   └── ui/                     # shadcn 生成物(button/tabs/dialog/drawer/badge/progress/scroll-area)
    ├── features/json-viewer/       # 自研 JsonViewer
    ├── hooks/                      # useChat / useConversations / useMemories /
    │                               # useCharacterState / useTurnTrace / useAutoScroll
    ├── api/
    │   ├── http.ts                 # fetch 封装、ApiError 归一化
    │   ├── transport.ts            # ChatStreamTransport 接口
    │   ├── chat-stream.ts          # Real 实现：NDJSON reader + parseStreamEvent
    │   ├── rest.ts                 # conversations/memories/state/turn-trace 端点
    │   └── index.ts                # 按 VITE_API_MODE 选实现的工厂（唯一分支点）
    ├── stores/                     # zustand: chatSlice / sessionSlice
    ├── types/
    │   ├── backend/                # Pydantic 镜像（全可选字段）
    │   └── domain/                 # 第 6 节领域模型
    ├── lib/                        # formatDuration / relativeTime / copy / enumColorMaps
    └── mocks/                      # msw handlers / fixtures(personas) / stream-scripts
```

职责红线：components/ 不许出现 fetch；api/ 不认识 React；stores/ 只存状态不发起请求（动作由 hooks 编排）；types/backend 与 types/domain 分离。

---

## 12. V1 前端 MVP 功能边界

**必须做（Phase 1 出口标准）**

- 双栏布局壳 + TopBar（session 新建/显示、连接状态、Mock 开关）
- 聊天闭环：发送 → NDJSON 流式渲染 → Stop(Abort) → 错误展示；session 自动创建与 `X-Session-Id` 回填
- turn_meta 到达即渲染 Overview（RoleMode + Emotion + Behavior + 降级徽章）；缺失时优雅降级
- Mock 流剧本 ≥5 条（含旧契约兼容流）
- AutoScroll（上滚暂停）+ 暗色主题 + 设计 token 基础版

**应该做（Phase 2）**

- State / Memory / Trace 面板 + done 后有界轮询装配 + 手动刷新
- Message ↔ Trace 联动（TurnBadge）、Retry、Clear（Dialog 确认）
- JsonViewer、降级徽章体系完整版、EmotionHistoryStrip

**暂时不做（明确出界）**

- 移动端专属布局、Auth、多角色切换 UI、语音、主动性消息、消息编辑/分支、prompt 在线热编辑、i18n、复杂动画/二次元演出、本地持久化（至多 localStorage 存 UI 偏好）

---

## 13. 后续开发阶段（任务规划，不含实现）

### Phase 1 — 骨架与聊天闭环（前端独立推进，后端仅一处一行改动）

- 前端：脚手架（Vite + TS + Tailwind + shadcn）→ 设计 token / 布局壳 → ChatStreamTransport 接口 + Mock 流 → 聊天闭环（send/stream/stop/error/session 回填）→ turn_meta 渲染 Overview（含缺失降级）→ AutoScroll / 暗色主题
- 后端协作（D-F3）：`/chat/message` 流内在首个 delta 前**追加一行 `turn_meta`**（向后兼容，见附录 A1）；建议顺带在 done 行加 `turn_id`
- 验收：纯 Mock 全流程演示；切 real 后真实对话可用；turn_meta 缺失不炸

### Phase 2 — 可观察性完整版（前后端协同）

- 后端：trace 采集器（各步骤耗时/状态随 turn 记录）+ 4 个 debug 只读端点（附录 A2）
- 前端：State/Memory/Trace 面板、done后有界轮询 + 惰性刷新 + 手动刷新、Message↔Trace 联动、Retry/Clear、JsonViewer、EmotionHistoryStrip
- 验收：「为什么这样回答」每环节 3 次点击内可达；人为制造降级可见黄色标记

### Phase 3 — 打磨与扩展预留

- MSW 剧场完善（降级/错误/边界剧本）→ stage 阈值刻度与「距下一阶段」提示 → 部署（静态产物 + FastAPI StaticFiles 挂载或 nginx）→ LangGraph 事件预留评审（TraceStep 泛化 checklist）→ 长会话虚拟滚动（视需要）

---

## 附录 A：后端协作契约

### A1 turn_meta 行（D-F3，Phase 1 唯一后端改动）

- 时机：`stream_chat` 预侧 `asyncio.gather` 完成后、首个 delta 之前，yield 一行：
  `{"type":"turn_meta","role_mode":{...RoleMode},"analysis":{"user_emotion":{...},"behavior":{...}}}`
- 兼容性：新增行带 `type` 字段，现有前端（只认 delta/done/detail）天然忽略；新前端在整轮无 turn_meta 时按「旧契约」处理，Overview 等 REST 回填并显示「数据滞后」提示。
- 降级轮照发：router/analysis 各自已有默认值降级，turn_meta 内容即为实际生效值，前端据 confidence/reason 渲染降级徽章。

### A2 debug 只读端点（Phase 2）

| 端点 | 返回 |
|---|---|
| `GET /api/v1/state` | character_state + relationship_state + 最近 emotion_history（复用 P2 backlog 既有规划） |
| `GET /api/v1/conversations/{id}/messages` | 历史消息（会话恢复用） |
| `GET /api/v1/memories?user_id=` | 全量记忆列表（可选参数标注本轮命中） |
| `GET /api/v1/debug/turns/{turn_id}/trace` | 该轮 RoleMode + TurnAnalysis + TraceSteps + `status: pending\|complete` |

turn_id 定位方案（择一，倾向前者）：本轮 AI message 的自增 id；或编排层生成 uuid 并随 done 行下发。

### A3 trace 步骤名约定（前端 waterfall 依赖此枚举）

`role_router` / `turn_analyzer` / `memory_retrieval` / `context_builder` / `prompt_builder` / `llm`（附 first_token_ms）/ `state_update` / `memory_extractor`。每步含 `durationMs` 与 `status: ok|degraded|error`；input/output 先存摘要或省略，避免膨胀。步骤名刻意与未来 LangGraph node 命名同构。
