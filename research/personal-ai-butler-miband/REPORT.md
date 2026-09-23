# 个人 AI 管家 App 接入小米手环 9 Pro 健康数据：可行性、产品与盈利调研

> Generated 2026-09-23 · depth: standard · 66 findings across 5 angles · workspace: research/personal-ai-butler-miband/

## Executive summary

- **小米手环 9 Pro 不在 Zepp OS 开放体系内**，配套 App 是 Mi Fitness（`com.xiaomi.wearable`，小米后端）；Zepp OS 官方健康外送（Device App → Side Service → Fetch）只覆盖 Amazfit，**不能**把 Zepp Console / Zepp OS API 当作本机型的接入方案 [1][5][10]。
- **未发现小米向个人开发者开放的自助云健康数据 API / OAuth**；Zepp Console 是合作伙伴向开放平台 + Mini Program 分发（需隐私政策、1–5 日审核），不是个人云健康 REST 接口 [9][14]。
- **个人开发者最现实的合规接入枢纽是 Android Health Connect**（或 iOS HealthKit）：官方 App / Gadgetbridge 把指标写入系统健康中枢，你的 App 只申请细粒度 `android.permission.health.READ_*` 读权限，数据默认留在本机 [7][8][13]。
- **逆向 auth_key / 抓私有云 API 不宜作主路径**：Mi Band 4+ 密钥由厂商服务端签发、解绑即失效；社区工具链存在 DMCA 下架（2017）与归档（huafetcher 2026-02）等断裂史 [12][6][14]。
- **产品差异化机会不在指标算法**，而在「角色化长期记忆 + 情绪/目标/行动」叠到中端手环时序数据上——对应 Whoop Coach / Oura Advisor 形态，但用你的 Agent Runtime + Memory + Goal/Action 能力做更深的个人生活管家 [12 in F3][2 in F3]。
- **合规硬边界**：健康数据在中国属敏感个人信息（单独同意 + PIPIA ≥3 年）[10][12 in F2]；App Store 1.4.1 禁止传感器-only 诊疗宣称、须提示就医 [5 in F2]；生成式 AI 暂行办法要求防沉迷、可能触碰健康相关行政许可 [8 in F3]。
- **盈利模型锚点**：iOS 数字解锁必须 IAP，SBP 抽成 15%（年 proceeds ≤ $1M）[1][2 in F4]；LLM 边际成本约 ¥8–15/月（重度）[7][8 in F4]；健康 App 付费渗透仅约 10%，但隐私/专业背书可抬 MWTP [10 in F4]；买断上限约 $15 可测、$30 封顶 [11 in F4]。
- **对现有项目**：V4.0「用户实体 + 账本域」方向正确；健康时序应作为**独立事实域**（同构账本三件套），经 Tool/External API 接入，**不进 memory**，并复用 Action/Goal/Proactive 做日报与异常预警。

## Background & scope

个人开发者（非企业）在现有「角色对话 Agent / Personal Life Agent」底座上，做个人 AI 管家 App 并接入小米手环 9 Pro：可行接入路径、产品差异化、合规与盈利。In：数据接入/合规/竞品/盈利/项目衔接。Out：企业销售、手环固件表盘、医疗资质申办细节。假设：中文市场为主、1 人团队、合规优先、机型为小米手环 9 Pro。日期 2026-09-23。

---

## 1. 项目现状：可复用资产与真实缺口

当前系统是完整的「角色生命模拟器」：Agent Runtime（Profile 唯一阶段序列）、Tool 执行五段、Memory2 + Reflection、Goal/Planning 七道闸、Action + 台账、World 旁路、Proactive + 飞书通道 [项目基线 2026-09-20 / V4.0 architecture]。

| 能力 | 现状 | 对「AI 管家 + 健康」的意义 |
|---|---|---|
| Agent Runtime / Profile | 已实现 | 健康洞察走新 Profile 阶段，禁止第二套管线 |
| Tool + External API manifest | 已实现 | 健康数据源可写 `ext.api.*` 或 `builtin.health.*` |
| Action 台账 + 状态机 | 已实现 | 每次健康同步/提醒可审计 |
| Goal + Planning | 已实现 | 「睡眠目标 / 活动目标」= goal，不建新表 |
| Memory2 幂等候选 | 已实现 | 只借鉴范式；**时序指标不进 memory** |
| Proactive + Channel | 已实现（飞书） | 晨间健康简报、异常预警投递 |
| **用户实体** | V4.0 PLA-001~008 已部分实现 | 多用户归属前提 |
| **结构化事实域（账本）** | PLA-004 账本三表设计已定 | **健康时序应同构自建，而非塞进记忆** |
| 健康/穿戴域 | **完全缺失** | 需新建 `health_*` 事实域 + 同步工具 |

**核心判断**：接入手环不是「加个 API」，而是补**第三个结构化事实域**（继用户实体、账本之后）：精确、append-only、可对账、可纠正；LLM 只做解读与建议，**永不生成/复述测量数字**（延续账本铁律）。

---

## 2. 小米手环 9 Pro 数据接入路径

### 2.1 机型事实

- 官方配套 **Mi Fitness**，兼容 Android 8.0+ / iOS 12.0+；**不是** Zepp Life 主链 [1]。
- 官方指标：全天心率、血氧、睡眠分期/评分、全天压力、女性健康、日常活动、150+ 运动、GNSS 五星 [2]。
- 心率可配置 smart 或 1/10/30 分钟；血氧在久坐时采样；睡眠需 advanced monitoring [3]。粒度足以支撑「日报 + 异常提醒」，不足以做医疗级连续监测。

### 2.2 路径对比

| 路径 | 可得性 | 合规 | 稳定性 | 结论 |
|---|---|---|---|---|
| A. 小米/Zepp 云 API（个人 OAuth） | **未发现公开自助通道** [14][9] | 未知 | — | **不可作主路径** |
| B. Zepp OS Device→Side→Fetch | 仅 Amazfit，**不含本机** [4][5] | 高 | 高 | 机型不匹配 |
| C. **Health Connect / HealthKit** | 官方或桥接写入后可读 [7][13][8] | **高** | 高 | **主路径** |
| D. Mi Fitness CSV / GDPR 导出 | Huami GDPR 可得 HEARTRATE/SLEEP 等 CSV [10 in F5] | 中高 | 低频 | 兜底/冷启动 |
| E. Gadgetbridge BLE 本地同步 | Mi Band 9 Pro = Unknown/Experimental，需 auth_key [11][2 in F5] | 低（逆向邻域） | 中 | 极客旁路，**非产品主路径** |
| F. 逆向 auth_key + protobuf | 社区四条提取途径，密钥云端签发 [12][7][8 in F5] | **低** | 差 | **不推荐** |

### 2.3 推荐主路径（产品级）

```
小米手环 9 Pro
    ↓（用户日常用 Mi Fitness，或实验用 Gadgetbridge）
Mi Fitness / 桥接层
    ↓ 写入
Android Health Connect  |  Apple HealthKit
    ↓ 细粒度 READ_* / HealthKit 类型授权
你的 App Health Ingest（Tool: builtin.health.sync）
    ↓ 结构化落库（health_* 三件套，不进 memory）
Agent（解读 / 目标 / 提醒 / 日报）
    ↓
Proactive 投递（App 内 / 飞书 / 系统通知）
```

Health Connect 可读/写类型（Gadgetbridge 集成面佐证）：Steps、Distance、Heart Rate、SpO2、HRV、Skin/Body Temp、Respiratory rate、Resting HR、Sleep Sessions、Weight、VO2 Max、Exercise Sessions（可开 per-second workout）[13]。权限形如 `android.permission.health.READ_HEART_RATE` / `WRITE_STEPS`，并须处理隐私政策 rationale Intent；Android 14+ 需 `VIEW_PERMISSION_USAGE` + `HEALTH_PERMISSIONS` [8]。

### 2.4 字段与产品能力边界

**可支撑管家场景**：静息/连续心率趋势、睡眠时长与分期、压力、活动步数、SpO2 趋势、运动记录。

**明确缺失/弱**（社区 protobuf 面）：VO2 Max、血压、训练负荷、睡眠呼吸率；部分机型无第三方实时心率 [4][15 in F5]。**产品文案不得宣称医疗级血压/血糖/血氧诊断能力**（另见合规）。

### 2.5 必做实机验证（Open）

Mi Fitness 国内版是否原生写入系统「健康互联/Health Connect」、可同步字段与延迟，一手文档未证实，**需真机验证** [14]。

---

## 3. 合规与上架边界

| 维度 | 硬约束 | 对策 |
|---|---|---|
| 敏感个人信息（PIPL） | 医疗健康信息 = 敏感 PI；单独同意；PIPIA 留存 ≥3 年 [10][12 in F2] | 首次开启健康同步时独立勾选同意；本地/用户可控存储；可导出可删除 |
| 出境 | 敏感 PI 年累计 ≥1 万人 → CAC 安全评估；不足 → 中国 SCC 备案 [11 in F2] | 个人阶段数据默认境内/本机；海外版隔离存储 |
| 长臂管辖 | 境外处理境内用户 PI 同样适用 PIPL [13 in F2] | 服务器在海外也不能逃避 |
| 生成式 AI | 暂行办法：防沉迷、防「健康」歧视、内容标识、可能需行政许可 [8 in F3] | 健康建议定位「生活方式教练」；显著免责声明；未成年人模式 |
| App Store | 禁传感器-only 测血压/血糖/血氧宣称；须提示就医；精度方法论可披露 [5][6 in F2] | 文案用「趋势/参考」；固定「非医疗建议，请咨询医生」 |
| HealthKit | 禁广告/出售健康数据；必须隐私政策 [3 in F2] | 盈利不做健康数据广告 |
| FTC（美） | Health Breach Notification Rule 覆盖 health apps / trackers [9 in F3] | 泄露通知流程 |
| 医疗边界 | Whoop 等自我限定「安全网、非医疗建议」[11 in F3] | 复制该措辞模式 |

**未闭合**：中国 App 备案细则、NMPA SaMD 分类、Google Play 健康政策、国内安卓商店健康资质——本轮缺一手文本（见 Open questions）。

---

## 4. 产品形态与差异化

四类交叉形态（F3 综合）：

1. **对话陪伴**（Replika：42M 用户，卖记忆/关系/情绪，不卖原始指标）[7 in F3]
2. **健康教练**（Whoop Coach GPT-4；Oura Advisor；PH-LLM：Gemini 微调穿戴时序，睡眠/健身考试 79%/88%）[1][5][6 in F3]
3. **日程/行动管家**（Whoop Daily Outlook 晨间主动推送）[2 in F3]
4. **量化自我**（Oura 50+ 指标）[5 in F3]

**独立开发者缝隙**：不要拼指标算法与硬件，拼「**有记忆、有情绪、有目标、会行动的角色化管家**」叠在小米手环 9 Pro 中端数据上。你的 Memory2 / Relationship / Goal / Action / Proactive 正是头部订阅卖点（长期记忆、个性化、主动推送）的技术底座 [2][12 in F3]。

失败教训：Tonal/Mirror 证明「硬件+订阅」若无法持续证明精准 + 长期趋势 + 个性化会崩 [4 in F3]。

---

## 5. 盈利思想（个人开发者，保留扩展）

### 5.1 成本侧

| 项 | 锚点 |
|---|---|
| LLM | DeepSeek flash 谷时 $0.15/$0.60 per 1M；qwen-plus ¥2/¥8 per 1M；重度日 30 轮约 **¥8–15/月** 模型成本 [7][8 in F4] |
| 离线反思/日报 | Batch 半价，适合 life_loop 夜间任务 [8 in F4] |
| 商店抽成 | iOS SBP **15%**（≤$1M/年）；数字解锁必须 IAP [1][2 in F4] |
| 支付（安卓/官网） | 微信支付**小微商户**（身份证+辅助证明，无需执照）[9 in F4] |

### 5.2 收入侧（建议阶梯）

| 层 | 形态 | 定价锚 | 依据 |
|---|---|---|---|
| Free | 本地健康看板 + 有限对话 | ¥0 | 获客；付费渗透本就低（约 10% 曾购健康 App）[10 in F4] |
| Plus 订阅 | 健康日报 / 长期记忆 / 目标教练 / 异常提醒 | **¥15–30/月** 或 $5.99/月 对齐 Oura | Oura $5.99/mo；需覆盖 LLM 成本并留利润 [5 in F3][7 in F4] |
| 年订 | 折扣 + 专属人格/主题 | $40–70/年 | Oura $69.99/yr |
| 买断（可选） | 本地优先终身解锁（不含云 LLM） | **≤¥98（~$15）**，勿超 $30 | 以色列研究：$15 可接受、$150 拒绝 [11 in F4] |
| 增值 | 专业背书内容 / 教练模板 | 溢价 | 医生「非常支持」MWTP 最高 HK$183 [10 in F4] |

**抬价三杠杆（实证）**：隐私合规体系 > 专业背书 > 「非常有用」功能感 [10 in F4]。  
**禁止**：健康数据定向广告（iOS 明文禁止）[6 in F4]。

### 5.3 单位经济粗算（speculative）

假设 Plus ¥25/月、LLM+推理 ¥12/月、SBP 抽成 15% → 毛利约 ¥9.25/用户/月（未计服务器/客服）。必须用 **轻量模型路由 + 缓存 + Batch 反思** 压成本；免费层严格限额次。

---

## 6. 社区实践教训

- **主替代**：Gadgetbridge（AGPLv3、无云、F-Droid）；Mi Band 9 Pro = Experimental + Xiaomi token + protobuf [1][2 in F5]。
- **可同步字段**：HR/步数/卡路里/SpO2/压力/PAI/睡眠阶段；缺失 VO2Max/血压/训练负荷/睡眠呼吸率 [3][4 in F5]。
- **失败模式**：Mi Band 7 Pro 只能同步当天（官方不推荐）[5 in F5]；官方 App 与 Gadgetbridge **互斥**（抢连/清数据）[12 in F5]；深睡分期常在官方 App 后处理 [13 in F5]；无第三方实时心率 [15 in F5]。
- **法律/维护风险**：2017 DMCA 下架 5 周 [6 in F5]；huafetcher 2026-02 归档 [14 in F5]。
- **可借鉴管道**：本地 SQLite 真相源 → FIT/GPX/DB 自动导出 → Health Connect / 自托管 Endurain·Wanderer [9][11 in F5]；Huami GDPR CSV 冷启动 [10 in F5]。

**对产品的含义**：数据源层必须可替换（Health Connect 优先）；协议断裂是常态；产品价值绑在 Agent 解读与行动闭环，不绑单一私有协议。

---

## 7. 推荐落地路径（个人开发者）

### Phase 0（1–2 周）实机验证
真机确认 Mi Fitness → Health Connect/健康互联 的字段与延迟；决定 iOS 是否同步启动（HealthKit）。

### Phase 1（4–6 周）健康事实域 + 只读管家
- 新建 `health_sources` / `health_samples`（或时序表）/ `health_daily_rollups` 三件套（同构关系账本：账本 append-only + 当前态 + 快照）。
- Tool：`builtin.health.read_daily` / `builtin.health.explain`；External API manifest 可选。
- 对话注入「今日生理摘要」（结构化字段，不经 LLM 编数字）。
- 合规：敏感 PI 单独同意、隐私政策、导出/删除。

### Phase 2（4 周）主动性与目标
- 晨间简报（复用 Proactive + quiet hours）；睡眠/活动 goal；异常趋势预警（阈值，非诊断）。
- 夜间 Batch 反思：health rollup → Insight（不落原始明细进 Prompt）。

### Phase 3（商业）
- Plus 订阅解锁：长期记忆问答、教练计划、周报；iOS IAP + Android 微信小微。
- 文案全面「非医疗建议」；未成年人防沉迷开关。

### 架构纪律（继承项目铁律）
1. 健康数据**不进 memory**（时序精确性与记忆衰减冲突）。
2. 数字**永不**由 LLM 生成。
3. 同步 = 受治理 Action（台账 + 幂等键）。
4. 不新建第二套 Agent 管线。
5. 不新增功能开关阀门（参数可调）。

---

## 8. 对比总表

| 方案 | 接入 | 合规 | 成本 | 差异化 | 建议 |
|---|---|---|---|---|---|
| 小米云 API 逆向 | 高风险 | 差 | 低 | 无 | 否决为主路径 |
| Zepp OS 外送 | 机型不符 | 高 | 中 | 低 | 否决 |
| **Health Connect 中枢** | 中（依赖上游写入） | **优** | 低 | 高（可叠 Agent） | **主路径** |
| GDPR/CSV 冷启动 | 低频 | 中高 | 低 | 中 | 兜底 |
| Gadgetbridge 直连 | 实验 | 低 | 中 | 中 | 极客模式/可选 |

---

## Open questions

1. **Mi Fitness 国内版是否原生写 Health Connect / 小米健康互联？** 字段、延迟、是否需 root——必须真机验证 [F1 dead ends]。
2. 中国 App 备案、NMPA「软件医疗器械」是否覆盖 LLM 健康解读、国内安卓商店健康类资质——缺一手监管/商店文本。
3. Google Play 健康类政策与华为/应用宝个人开发者抽成与虚拟支付规则——官网未抓通。
4. 中文 AI 陪伴（星野/猫箱等）真实订阅定价——缺一手价。
5. OpenAI/Anthropic 2026 官方 token 价（区域限制）——中美双栈成本对照未完成。
6. 若自建 Gadgetbridge 桥：AGPL 传染与「辅助绕过配对」的 ToS/法律风险需专项评估。

## Sources

[1] Xiaomi Smart Band 9 Pro 产品页 — https://www.mi.com/global/product/xiaomi-smart-band-9-pro (accessed 2026-09-23)  
[2] Zepp OS Architecture / post-health-data — https://docs.zepp.com/docs/guides/architecture/arc/ (accessed 2026-09-23)  
[3] Zepp OS HeartRate Sensor API — https://docs.zepp.com/docs/reference/device-app-api/newAPI/sensor/HeartRate/ (accessed 2026-09-23)  
[4] Zepp OS Device List — https://docs.zepp.com/docs/reference/related-resources/device-list/ (accessed 2026-09-23)  
[5] Zepp OS getSportData — https://docs.zepp.com/docs/reference/device-app-api/newAPI/app-access/getSportData/ (accessed 2026-09-23)  
[6] Zepp Distribute / Console — https://docs.zepp.com/docs/distribute/ (accessed 2026-09-23)  
[7] Gadgetbridge Xiaomi pairing / server — https://gadgetbridge.org/basics/pairing/huami-xiaomi-server/ (accessed 2026-09-23)  
[8] Gadgetbridge Xiaomi wearables — https://gadgetbridge.org/gadgets/wearables/xiaomi/ (accessed 2026-09-23)  
[9] Gadgetbridge Health Connect — https://gadgetbridge.org/basics/integrations/health-connect/ (accessed 2026-09-23)  
[10] Gadgetbridge Xiaomi protobuf — https://gadgetbridge.org/basics/topics/xiaomi-protobuf/ (accessed 2026-09-23)  
[11] Gadgetbridge auto-export — https://gadgetbridge.org/internals/automations/auto-export/ (accessed 2026-09-23)  
[12] Gadgetbridge data-management (Huami GDPR CSV) — https://gadgetbridge.org/internals/development/data-management/ (accessed 2026-09-23)  
[13] Gadgetbridge online fitness trackers — https://gadgetbridge.org/basics/integrations/online-fitness-trackers/ (accessed 2026-09-23)  
[14] Gadgetbridge DMCA blog — https://gadgetbridge.org/blog/category/dmca/ (2017-06/07, accessed 2026-09-23)  
[15] Gadgetbridge activities / sleep — https://gadgetbridge.org/basics/features/activities/ (accessed 2026-09-23)  
[16] Gadgetbridge sync — https://gadgetbridge.org/basics/features/sync/ (accessed 2026-09-23)  
[17] huafetcher archived — https://codeberg.org/vanous/huafetcher (archived 2026-02-15)  
[18] Apple HealthKit — https://developer.apple.com/documentation/healthkit.md (accessed 2026-09-23)  
[19] Apple HealthKit Privacy — https://developer.apple.com/documentation/healthkit/protecting-user-privacy.md (accessed 2026-09-23)  
[20] Apple Authorizing Health Data — https://developer.apple.com/documentation/healthkit/authorizing-access-to-health-data.md (accessed 2026-09-23)  
[21] App Store Review Guidelines — https://developer.apple.com/app-store/review/guidelines/ (accessed 2026-09-23)  
[22] Android health-samples — https://github.com/android/health-samples (accessed 2026-09-23)  
[23] HealthConnectSample AndroidManifest — https://github.com/android/health-samples/blob/main/health-connect/HealthConnectSample/app/src/main/AndroidManifest.xml (accessed 2026-09-23)  
[24] DLA Piper Data Protection China (PIPL) — https://www.dlapiperdataprotection.com/index.html?t=law&c=CN (2026-02-13, accessed 2026-09-23)  
[25] 36kr Whoop Coach 深度稿 — https://www.36kr.com/p/3542784718336128 (2025-11-07)  
[26] Oura Membership — https://ouraring.com/membership (accessed 2026-09-23)  
[27] PH-LLM arXiv:2406.06474 — https://arxiv.org/abs/2406.06474 (2024-06-10)  
[28] Replika — https://www.replika.com/ (accessed 2026-09-23)  
[29] 生成式人工智能服务管理暂行办法 — https://www.cac.gov.cn/2023-07/13/c_1690898327029107.htm (2023-07-13)  
[30] FTC withdraws obsolete policy statement — https://www.ftc.gov/news-events/news/press-releases/2026/09/ftc-withdraws-obsolete-policy-statement (2026-09-09)  
[31] Apple Small Business Program — https://developer.apple.com/app-store/small-business-program/ (accessed 2026-09-23)  
[32] DeepSeek Pricing — https://api-docs.deepseek.com/quick_start/pricing (accessed 2026-09-23)  
[33] 阿里云百炼计费 — https://help.aliyun.com/zh/model-studio/billing-for-model-studio (accessed 2026-09-23)  
[34] 微信支付商户开户 — https://pay.weixin.qq.com/static/help_guide/business_registration.shtml (accessed 2026-09-23)  
[35] mHealth 2023;9:21 健康 App 支付意愿 — https://pmc.ncbi.nlm.nih.gov/articles/PMC10364011/ (2023-07-03)  
[36] JMIR Form Res 2021;5(10):e26125 mHealth WTP — https://pmc.ncbi.nlm.nih.gov/articles/PMC8527382/ (2021-10-05)  

---

## 项目内部依据（非 URL 来源）

- `docs/current-system-architecture-baseline.md`（2026-09-20）
- `docs/version/v4.0.0/architecture.md` / `tasks.md` / `reviews/personal-life-agent-architecture-review.md`
- `docs/version/v3.0.0/` Agent Runtime
