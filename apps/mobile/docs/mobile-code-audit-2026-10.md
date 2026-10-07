# Flutter 客户端代码审计报告

>审计对象：`apps/mobile`（朝夕App Flutter 客户端）
> 规模：130 个 dart 文件 / 28,429 行 / 43 个测试文件
> 审计范围：数据层与网络、业务功能层、架构与工程质量
> 审计方式：静态代码走查（未修改任何文件，未运行真机/模拟器）
> 报告性质：只读审计结论 + 建议方向，不含实现代码

---

## 一、总体结论

这个项目的工程素养**明显高于同规模 Flutter 项目的平均水平**：有 lint 纪律、有静态架构守卫测试、有 golden 契约测试、配置 fail-closed、设计系统零硬编码色值、零跨 feature 耦合、零明文密钥。

但存在三处**"形式到位、实质欠缺"**的问题，最需要警惕：

| 问题 | 表现 | 本质 |
|---|---|---|
| **伪分层** | 6 个 feature 的 domain 目录完全为空，34 处presentation 直接调data 层 | 架构意图有了，业务规则没落地 |
| **伪状态管理** | 依赖 Riverpod 四件套，实际 `ref.watch` 仅 8 处、`setState` 167 处 | 依赖预算浪费，状态无法组合/测试 |
| **"设计完备但未接线"** | `LocalStores`、`DriftRetryStore`、`ChatHistoryCache`、`InMemoryRetryQueue` 全仓零调用；`openInMemory()` 唯一且进程退出即丢 | 离线补偿能力等于没有 |

真正的风险集中在**金额与数值的最后一公里**：传输层已用整数分，但解析层有两处独立实现的、都会**静默截断小数**的解析器 —— 存在"界面显示值 ≠ 实际入账值"的路径，且用户完全无从察觉。

---

## 二、P0 严重问题（会导致崩溃 / 数据错误 / 上架阻塞）

### A. 会崩溃

1. **相册超2000 张时，删除/移动照片必崩**
   `album_manage_page.dart:138` 的 `if (assets.length > 2000) break;` 截断了 `data.assets`，
   但 `_selected` 的预选来源是**全库** `scanSnapshots` 的 AI 分析结果。
   照片超2000 张时 `:193` / `:208` 的 `data.assets.firstWhere((a) => a.id == id)` 必然抛 `StateError`（无 `orElse`，两处方法均无 try/catch）。
   同页 `_allSelected` 也会永远为 false，标题「已选 N 张」大于网格总数。

2. **流式对话中返回页面 → 崩溃**
   `chat_page.dart:230` 定义了 `_disposed`，但 `send()` 内`:326`/`:340`/`:346` 三处 `state = ...` 全部漏了守卫（只有 `finally:348` 有）。
   用户在 AI 回复流式输出中返回 `/chat`，provider dispose 后写 state → `Bad state: Cannot use ref after dispose`。

3. **`photo_manager` 返回空列表时双重崩溃**
   `album_repository.dart:180,184` 的 `paths.firstWhere(..., orElse: () => paths.first)`，媒体库为空或权限边界时会抛 `StateError`。

4. **sqlite 迁移策略是空壳**
   `cache_db.dart:106` 的 `onUpgrade: (m, f, t) => m.createAll()` 只能建新表，**不会给已存在的表加列**。
   `schemaVersion` 已是 2，后续任何字段变更都会静默漂移，运行时以 `no such column` 崩溃，且 `wipeAllCaches` 已丢数据无法挽回。

### B. 会算错钱/算错数

5. **金额小数被静默截断（记账 + 车辆两处重复实现）**
   `ledger_add_page.dart:88` 与 `car_add_page.dart:471` 的
   `centsText.padRight(2, '0').substring(0, 2)`。
   `_onKey` 只限制「去掉小数点后 ≤8 位」（`:122`），**未限制小数位数**。
   输入 `12.345` → 界面显示 `12.345`，实际保存 `12.34`；`0.999` → 存 `0.99`。用户看不出任何异常。

6. **待确认账单的乐观回滚会让已确认条目复活 → 重复入账**
   `ledger_page.dart:142-163`：`_resolve` / `_ignore` 的 `snapshot` 是**整个 `_pending` 列表**。
   连续处理两笔（第一笔成功、第二笔网络失败）时，`_pending = snapshot` 会把第一笔（后端已确认、已入账）重新放回列表，用户再点确认即重复入账或收到 404。
   回滚必须是 `snapshot + [item]` 的差集，而非整体还原。

7. **幂等键被两条提交路径共用 → 第二笔被静默丢弃**
   `ledger_add_page.dart:25` 的 `late final String _idempotencyKey` 被 `_save()`（键盘模式，`:197`）和 `_confirmSay()`（语音模式，`:225`）共用。
   同一页面先键盘保存失败 → 切到「说给亚丝娜」再保存（金额/分类均不同）→ 服务端按同一 key 去重，第二笔**被丢弃且 UI 提示成功**。

8. **里程会静默写入错误总里程**
   `car_add_page.dart:96-106`：`_odometerKm = (_profileOdometer ?? 0) + delta`，
   而 `_loadProfile()` 的 `catch (_) {}`（`:76`）吞掉所有异常且无提示。
   档案拉取失败时保存 300 km 行程 → `odometer_km` 被写成 `300`，后续百公里电耗、保养到期全部失真。应在 `_profileOdometer == null` 时阻断保存或显式提示。

9. **车辆档案：非法数值静默丢弃、负数照传**
   `car_profile_page.dart:126` 的 `put(..., numeric: true)` 用 `num.tryParse`，输入 `abc` 时写入 `null`，随后 `:140` 的 `payload.removeWhere((_, v) => v == null)` 把它删掉 —— 保存成功但用户输入的「总里程」根本没提交，界面无任何提示。
   同时 `num.tryParse('-5')` 合法，`odometer_km: -5` 会被真实写入档案。全表单无范围校验。

### C. 上架阻塞（Android 配置）

10. **release 构建使用 debug 签名**
    `build.gradle.kts:43` → `signingConfig = signingConfigs.getByName("debug")`（代码里 TODO(PLT-005) 自认未做）。
    应用无法上架，且任何持有 debug keystore 的人可伪造同包名更新包。

11. **包名仍是模板值**
    `build.gradle.kts:9,20` → `namespace` / `applicationId` 均为 `com.example.mobile`，唯一区分是 `applicationIdSuffix = ".dev"`。上架前必须改正式包名并同步隐私页/OAuth 回调配置。

12. **令牌可被 adb 备份提取，且无网络安全策略**
    `AndroidManifest.xml` 的 `<application>` 既无 `android:allowBackup="false"` 也无 `networkSecurityConfig`，仓库内**不存在任何 `res/xml/network_security_config.xml`**。
    `flutter_secure_storage` 的 token 在 Auto Backup 下可被 `adb backup` 提取。

13. **「一键清空」只删服务端，本地数据全部留存**
    `privacy_page.dart:78-84` 只发 `DELETE /life/data`，`catch (_) {}` 全吞，
    **从不调用 `LocalStores.clearLocalBusiness()`**（全仓确认 `LocalStores` 零运行时接线）。
    弹窗承诺「服务端与本地都会删除」，实际 SharedPreferences 里的 `album.*`、`chat.last_conversation_id`、`profile.nickname`、`health.consent_granted` 全部留存。

14. **退出登录未清内存态 → 上一账号数据串号**
    `profile_page.dart:149-164` 只清令牌 + `clearIdentity()`。
    `chatPageStateProvider` 是非 autoDispose 的全局 provider，上一账号的 `messages`/`streamingText` 会带进下一账号会话。

---

## 三、P1 重要问题（功能异常 / 明显性能问题）

### 状态一致性：缺少「页面返回即刷新」的统一约定

这是当前**最容易复现的用户可见缺陷**。做对了的：`ledger_page.dart:130-134`、`car_page.dart:66-70`（`await` push 后 `_load()`）。
漏掉的：

- `life_page.dart:404` —— 用户在子页新增备忘/任务后，「N 条备忘」「今日 N 项」「本月 ¥」全部停在旧值
- `album_page.dart:263`、`album_detail_page.dart:221` —— 删除 N 张照片后返回，网格与计数仍是删除前的数据

### 相册域三重风险

- **权限被错误归因**：`album_page.dart:106-109` 的 `catch (_) => _phase = _Phase.denied`，任何加载异常都被谎报为「没有相册权限」。更严重的是 `:79-86` 的 `coverProvider`/`thumbnailProvider` **没有 try/catch**，而 `album_repository.dart:107` 在资产被删时 `throw StateError` —— **一张扫描后被删的照片就会让整个相册页变成「无权限」**
- **权限永久拒绝后无出口**：`album_page.dart:60` 仅判 `denied`，`EmptyState` 的「去开启权限」再次调 `requestAccess()` 必然再次 denied，全程**没有任何 `openAppSettings()` 跳转**，形成永久死路
- **主 isolate 全量扫描**：`album_repository.dart:240-256` 的 `scanSnapshots` 未做 isolate 隔离（只有 `album_analysis.dart:76` 的 `analyzeChunk` 在 isolate 内），且 `resolvePath`（`AssetEntity.fromId` + `originFile`）与 `File.length()` 在循环里**串行 await**。`store.loadLastScanAt()`（`:257` 写入）**从未被读取用于跳过**，即每次进相册页都重跑一遍全库扫描 → 数千张时必然 ANR
- **2000 张缩略图一次性解码**：`album_manage_page.dart:126-141` 在主 isolate 串行 `await thumbnailProvider` 最多 2000 次，`:431-453` 再用 `shrinkWrap: true` + `NeverScrollableScrollPhysics` 强制全量布局
- **全分辨率解码无 cacheWidth**：`photo_view_page.dart:216` 的 `isOriginal: true` 未限制解码尺寸，4000×3000 原图 ≈ 48MB，多图缓存后 OOM 风险高

### 网络层

- **`createDio()` 无 401 处理、无重试拦截器**：`dio_client.dart:10-28`，`ErrorMappingInterceptor` 把 401 映射成 `AppError.unauthorized` 后**无人消费** → 令牌失效时用户卡在反复失败。且 `LedgerRepository`/`CarRepository` 等 8 处各自 `createDio()`（每页一个新实例 + 新 `SecureTokenStore`），连接池无法复用
- **流式超时常量定义后零引用**：`dio_client.dart:31-32` 的 `streamFirstTokenTimeout`(1500ms) / `streamIdleTimeout`(60s) 全仓无引用，流式请求沿用 `receiveTimeout: 15s` → AI 首字慢即被腰斩
- **`auth_interceptor.dart:11-20` 的 `void onRequest(...) async`**：若 `readAccessToken()` 抛异常，`handler.next` 永不调用 → 请求**永久挂起**直到超时。且每次请求都读一次 Keystore，无内存缓存
- **弱网串行累加**：`ledger_page.dart:66-69`（4 个端点）、`life_page.dart:71-83`（3 个）串行 await → 建议 `Future.wait`

### 数据类型与时区

- **大量 `as int?` 强转**：`ledger_repository.dart:184,189-190`、`car_repository.dart:31,117`、`life_repository.dart:118`。
  后端返回 `12.0` 这类 JSON double 时抛 `TypeError`，且这些强转**在 try 之外** → 页面整体进错误态。`expense_total_minor` 是**金额字段**，属账目显示崩溃
- **UTC 与本地日期混用 → 事件错一天（系统性）**：`life_repository.dart:51-52` 用 `DateTime.tryParse` 解析带 `Z` 的 ISO 得到 **UTC** DateTime，
  而 `life_page.dart:111` 的 `_isTodayOrUndated`、`schedule_page.dart:69` 的 `_dateOf`、`memo_page.dart:95` 直接取 `.year/.month/.day`。
  **北京时间 07:00 的提醒（UTC 前一天 23:00）会被归到前一天。全部缺 `.toLocal()`**
- **`double.tryParse(expense_text)`**：`life_repository.dart:118-123`、`life_page.dart:259`。后端若返回带千分位逗号（`"1,234.56"`）解析失败 → 当0 处理，「本月支出」整行静默消失

### 交互缺陷

- **「说给亚丝娜」取最后一个数字当金额**：`ledger_add_page.dart:94-105` 的 `_amountPattern` 全文 `allMatches` 后取 `matches.last`。
  `「35 元，2 个包子」` → 记 **2 元**；`「充话费 100 送 10」` → 记 10 元。示例 chips 恰好都是「金额在末尾」，掩盖了这个缺陷
- **预览请求乱序覆盖**：`ledger_add_page.dart:135-182` 的 `_refreshPreview` 无请求序号/取消机制，两个 in-flight 请求乱序返回会用旧结果覆盖新结果。
  `_onDirectionChanged`（`:108`）切换收支后**不取消在途预览** → `_confirmSay` 可能提交**上一方向的 categoryId**，直接导致错分类入账
- **日程时间线条目完全不可点**：`schedule_page.dart:294-306` 的 `ScheduleTimelineItem` 没有 `onTap`（只有「即将到来」的 `NextCard` 可点）→ **今天的待办无法在时间线上标记完成**，这是日程页的核心动作
- **今日待办数重复计数**：`schedule_page.dart:115` 的 `_todayItems` 末尾追加了未定日期的 open task，而 `:150-160` 用 `items.length` 说「今天 N 件事」，紧接着又说「另有 M 件还没定时间」—— M 已被计入 N
- **删除待办无二次确认**：`schedule_page.dart:183-187`，同项目 `memo_page.dart:115-131`、`album_manage_page.dart:175-191` 都有确认弹窗，此处是唯一例外
- **相册批量操作后未检查删除结果**：`photo_view_page.dart:110-112`，`deleteWithIds` 返回值未检查就 `pop()`，失败时用户以为已删；抛异常后 `_deleting` 永久为 `true`，按钮卡死
- **验证码流程两处断裂**：
  `auth_repository.dart:76-94` 的 `requestEmailCode` 包了 `AuthCodeException`，但 `verifyEmailCode` **没包** → 验证码错误/429 的 detail 全丢，用户只见「登录失败，请检查网络」
  `verify_code_page.dart:163` 的 `deviceId = DateTime.now().millisecondsSinceEpoch.toRadixString(36)` **每次登录都生成新设备 ID** → 设备绑定失效，且与 `SecureTokenStore.readDeviceId` 已有的持久化体系冲突
- **简报缓存读取无 try/catch → 永久转圈**：`briefing_page.dart:63` 的 `_initialLoad` 由 `initState` 以 fire-and-forget 调用，缓存 JSON 损坏即抛未捕获异常，`_loading` 永远为 `true`

### 统计少报 / 显示不一致

- `album_analysis.dart:181-189` 的 `_mergeSameContent` 在 for 循环体内 `return`，一个 size group 内若有 3 组重复只报第 1 组
- `album_analysis.dart:130-136` 的「N 张可清理」`count: ids.length` 含保留的那一份，而 `totalBytes` 只算 `(len - 1)` → UI 上「200 张可清理，腾出 1.2 GB」自相矛盾
- `ledger_page.dart:457` 的分类金额 `.toStringAsFixed(0)` 把 35.50 显示成 **¥36**、0.40 显示成 **¥0**，与页头两位小数的口径不一致
- `briefing_page.dart:104` 的 `TextEditingController` 创建后从不 dispose，每开一次城市弹窗泄漏一个
- `home_page.dart:116` 的 `_nickname!.substring(0, 1)` 对 emoji 会截出半个代理对，显示豆腐块

---

## 四、P2 一般问题

- `album_analysis.dart:194-203`：`path == null` 时指纹退化为 `size + takenAt`，同秒拍摄同尺寸的不同照片会被误判重复
- `album_analysis.dart:76`：`Isolate.run` 每 200 条**新建并销毁一个 isolate**，5000 张 = 25 次启停
- `ndjson_parser.dart:21-25`：单行 JSON 解析失败 `yield ChatEvent.failure(...)` 后**继续解析**，`Done` 又覆盖为 done → **残缺回复被当成完整回复展示**
- `chat_page.dart:345-347`：流式异常时 `catch` 把 `streamingText: ''` 直接丢弃**用户已经看到的部分回复**，既不入 messages 也不保留展示
- `chat_page.dart:305-349` 连发两条消息的竞态：`send#2` 的 `_controller?.dispose()` 触发 `repo.cancel()` 取消 #1 → #1 走 catch 清空 `streamingText`，348行 finally 又覆盖 #2 的流式状态
- `chat_page.dart:223-238`：`chatPageStateProvider` 未声明 autoDispose → 离开页面后 dio 流继续接收、state 持续被写
- `errors/app_error.dart:73-78`：`429` 被归入 `badRequest`（retryable=false、用户文案「换个说法试试」），限流语义丢失；`badCertificate` 一律映射为 `networkUnreachable`，TLS 问题被误报为断网
- `log_redaction_interceptor.dart:51-63`：两个分支条件重叠（`!allowed && blocked` 与 `blocked` 结果相同），白名单逻辑实际无效
- `retry_store.dart:36-38`：`RetryOps` 无过期、无条数上限，`pending()` 全表读 → 一旦启用会无界增长
- `core/env/app_env.dart:6-13`：配置缺失直接 `throw StateError` → 用户看到启动崩溃黑屏而非可读提示
- `app/bootstrap.dart:35-42`：自建 `ProviderContainer` 从不 `dispose()`
- `app/state/dynamic_tab.dart:48-59`：`moveTo` 先改内存再 await 落盘，快速连拖时后写覆盖先写
- `car_profile_page.dart:99`：`_intervalMonthsController.text = ''` 恒置空、`:135` 也就永不提交 → **「保养周期月数」永远无法回显或编辑**（而相邻的 `service_interval_km` 有回显）
- `car_page.dart:414-422`：`_thousands` 对负数输出 `-,5000`（分隔符插在负号后）
- `memo_page.dart:154` 文案承诺「长按就能改或删」，但 `_delete`（`:113`）只实现删除，无编辑入口
- `memo_page.dart:173`、`schedule_page.dart:234`、`home_page.dart:126` 在 `push` 出的子页里用 `context.go` 返回，会重置导航栈、丢失上一页状态（`push` 应配 `pop`）
- `ledger_repository.dart:217-233`：`kind` 参数未下发，客户端过滤全量分类；`_loadCategories` 在收支切换时重复拉全量
- `chat_history_repository.dart:41-52`：`replaceMessages` 在事务内**逐条 await insert**（200 条 = 200 次往返）；同项目 `cache_db.dart:130` 已正确用 `batch(insertAll)` → 建议统一

---

## 五、架构问题

### P1 值得决策的三处「名义与实质偏差」

**1. domain 层被架空**
34 处越层 import，覆盖 10 个 feature 的全部页面（`ledger_page.dart` → `data/ledger_repository.dart`、`chat_page.dart` → `data/chat_stream_repository.dart` 等）。
`lib/features/*/domain` 仅 5 个文件 / 712 行，`briefing`/`health`/`home`/`life`/`memory`/`profile` 六个 feature 的 domain 目录**完全为空**。
后果：`ledger_add_page.dart:83-92` 的金额分单位换算就写在 Widget 里，不可复用、不可独立测试 —— 这正是第 5 条 P0（金额截断）的根因。
建议：要么把金额计算/解析规则抽为纯 Dart 函数与实体补足 domain，要么**删掉空的 domain 目录**消除伪分层。

**2. Riverpod 形同虚设**
`ref.watch` 全项目仅 **8 处**，`@riverpod` 注解 **1 处**，而 `setState` 共 **167 处**。
页面自行 `late final LedgerRepository _repo = widget.repository ?? LedgerRepository();`（`ledger_page.dart:36`）。
依赖 `flutter_riverpod` + `riverpod_annotation` + `riverpod_generator` + `hooks_riverpod` 四个包（含 codegen）却几乎不用，`flutter_hooks` 仅 1 文件使用。
建议：真正推行（页面状态上提为 Notifier），或**砍掉后三个包**（约减少 3 个 codegen 依赖与 `*.g.dart` 生成负担）。

**3. 路由守卫是一次性的，且捕获所有异常为放行**
`app_router.dart:126-150`：`_entryGateChecked` 是一次性全局布尔；`_entryGateRedirect()` 内 `catch (_) { return null; }`（`:133-135`）意味着**存储层异常时直接放行进入 /home**；
`redirect` 对 28 条路由**只在首次触发**，登录态过期后不会再次拦截；`errorBuilder` 直接 `return const HomePage()`（`:145`）会把任意未知路由吞成首页。
建议：改为每次导航基于 token 有效性判断（**fail-closed**），错误路由用显式 404 页。

### P2 其他架构问题

- **`features → app` 反向依赖 36 处（分层倒挂）**：32 个页面 import `app/theme/theme_context.dart`，另加 `app/state/` 的 3 个全局 provider。主题上下文属设计系统职责，应下沉到 `design_system/`
- **超大文件集中**：8 个文件 > 600 行。
  `design_system/components/ledger_input.dart` **805 行内含 11 个 public 类**，实为组件文件而非单一组件；
  `features/life/life_page.dart` 732 行含 6 个类，`_LifePageState` 从 `:26` 延伸到 `:420`（≈395 行单方法状态类）；
  `verify_code_page.dart` 633 行含 13 处 setState
- **生成代码占比 19%（5,658 行）**：`cache_db.drift.dart` 单文件就占全项目 15.4% 行数。`core/scaffold_samples/`（3 个示例文件 675 行）是脚手架残留，可删
- **2,208 处中文文案硬编码**，`flutter_localizations` + `intl` 已声明但 `localizationsDelegates`/`AppLocalizations` **零命中**，`bootstrap.dart:50-56` 未挂任何 delegates → 无法国际化
- **无统一日志体系**：除 `core/analytics` 外散落 `debugPrint`/`print`，无分级日志
- **`snackBar` 仅 15 处 vs 34 个页面**，空 `catch (_) {}` 吞异常 3 处（`app_router.dart:139`、`car_add_page.dart:76`、`privacy_page.dart:83`）
- **无 feature flag 机制**：dev/prod 仅靠 `APP_FLAVOR` 编译期常量 + `dynamic_tab.dart` 硬编码模块顺序，灰度需发版

---

## 六、依赖与配置风险

1. **`dependency_overrides: sqlite3: 3.6.0` + `ghfast.top` 镜像，长期风险高**
   `pubspec.yaml:38-48`：3.7.0 起 sqlite3 改用 native-assets hook 从 GitHub 拉预编译产物，因本机网络不可达而回退到**第三方镜像代理 GitHub release**。
   风险：① 镜像成为供应链单点（虽有 sha256 校验，但 sha256 源与下载源同源，校验形同失效）；② **新人/CI 环境必然拉不到或拉到不一致产物，测试管线不可复现**；③ 注释自认「网络恢复后可整段移除」但无 TODO 编号，极易长期腐化

2. **依赖数量偏多且功能重叠**（`pubspec.lock` 161 个包）
   `photo_manager` + `photo_manager_image_provider`（两个 provider 包）；`drift` + `sqlite3_flutter_libs` + `sqlite3`（三条 SQLite 路径）；`flutter_hooks` 与 Riverpod 方案二选一却都留着

3. **原生权限缺口与过授权**
   - `flutter_local_notifications` 17.2.4 所需的 `POST_NOTIFICATIONS` / `SCHEDULE_EXACT_ALARM` 在 manifest 中**缺失**（grep 命中 0）→ **Android 13+ 定时通知将静默失效**
   - `health` 13.3.1 在 manifest 声明了 **17 项 `android.permission.health.*` 细粒度权限**，为探针一次性申请全部 → 若长期是内部工具，属**过授权**（隐私合规风险），应按 `health_connect_probe.dart:405` 的 `probeTypeSpecs` 收敛到实际采集项
   - 缺 Android 14+ 的 `READ_MEDIA_VISUAL_USER_SELECTED`，「部分照片授权」路径无法正确降级

4. **`.gitignore` 未覆盖 `.env*`、`*.jks`、`*.keystore`**（项目实际用 `dart_defines/*.json` 传配置，当前无密钥，但一旦有人加 `.env` 就会误提交）

5. **配置纪律良好（无问题）**：`app_env.dart:3-10` 用 `String.fromEnvironment` 且**缺失时 fail-closed 抛 StateError**，配 `test/scaffold/app_env_test.dart` 反向断言「必须抛错」；全仓无明文 api_key/secret/token，无 HTTP 明文 URL

---

## 七、测试与可维护性评估

### 值得肯定

- **分层被静态测试守住**：`test/scaffold/layer_guards_test.dart` 做目录存在性 + **跨 feature import 静态断言**，实测 130 文件 **0 处横向耦合**—— 这在 10 个 feature 的项目里相当难得
- **design_system 完全自包含**：对 `lib/` 其余部分**零出向 import**，全项目 `Color(0x...)` 在 tokens 目录外**命中 0 次**
- **测试有「诚实性」意识**：`ledger_auto_page_test.dart:168,177,216` 断言「不渲染同步计数」「不宣称能控制同步」—— 把产品边界写成回归测试，防止功能被悄悄夸大
- **路由元数据集中治理**：`RouteChrome` + `chromeByPath` 把 Tab 隐藏/状态栏样式收进壳层；`ShellTab.forLocation` 用**段级匹配**替代 `startsWith` 链并显式防止 `/lifestyle` 误命中 `/life`
- **lint 规则务实**：`avoid_print`/`avoid_dynamic_calls`/`unawaited_futures`/`prefer_final_locals` 全开，且注释解释了为何不启用某些规则

### 未覆盖的关键路径

- **无 repository 层测试**：`test/features/` 下仅 `album_repository_test.dart` 一个，`ledger_repository.dart`(347 行)、`car_repository.dart`、`memory_repository.dart` 均**无单测**
- **金额计算无纯函数测试**：`_amountMinor`（`ledger_add_page.dart:83-92`）的字符串→分换算、`_amountPattern`（`:22`）正则解析，仅通过 widget 测试间接覆盖，**边界值（超大金额、8 位上限、空串、`"0."`）无用例**—— 这直接对应第 5 条 P0
- **`car` 领域计算无测试**：`car/domain/car_models.dart` 232 行（里程/油耗等）无对应 domain 测试
- **`network` 仅测 `ndjson_parser` 与 `error_log`**，`dio_client` / 拦截器链无测试

### 量化指标

| 指标 | 数值 | 评价 |
|---|---|---|
| 源文件 / 行数 | 130 / 28,429 | — |
| 测试文件 / 行数 | 43 / ~8,250 | 测试:源码 ≈ 1:3.4，偏健康 |
| `setState` / `ref.watch` | 167 / 8 | 状态管理失衡 |
| 越层 import | 34 处 | 伪分层 |
| 生成代码占比 | 19%（5,658 行） | 偏高 |
| > 600 行文件 | 8 个 | 产能瓶颈 |
| 硬编码中文文案 | 2,208 处 | 无法国际化 |

---

## 八、修复优先级建议

### 第一批：低改动量、高收益（建议本周内）

| 序 | 问题 | 位置 |
|---|---|---|
| 1 | 金额解析统一为唯一的 `AmountBuffer`（限制小数位、拒绝非法输入），`_save` 前加「显示串 → 落库值」一致性断言 | `ledger_add_page.dart:88`、`car_add_page.dart:471` |
| 2 | 相册 `firstWhere` 加 `orElse` + 跳过不在 `data.assets` 中的 id | `album_manage_page.dart:193,208` |
| 3 | `send()` 三处 `state =` 补 `_disposed` 守卫 | `chat_page.dart:326,340,346` |
| 4 | 回滚改为差集而非整体快照还原 | `ledger_page.dart:142-163` |
| 5 | 幂等键改为每次提交动作生成独立 key | `ledger_add_page.dart:25` |
| 6 | `_loadProfile` 失败时阻断里程保存并提示 | `car_add_page.dart:76,96` |
| 7 | release 签名 + 正式包名 + `allowBackup=false` + `networkSecurityConfig` | `build.gradle.kts`、`AndroidManifest.xml` |
| 8 | 「一键清空」接入 `LocalStores`；登出时 invalidate 内存态 provider | `privacy_page.dart:78`、`profile_page.dart:149` |

### 第二批：架构收敛（1-2 周，零架构改动）

1. 路由守卫改 fail-closed（去掉 `catch → return null` 放行），`errorBuilder` 换显式 404
2. 补齐 `POST_NOTIFICATIONS` / `SCHEDULE_EXACT_ALARM` 权限；按实际采集项收敛 17 项 health 权限
3. 决策并执行：Riverpod 与 hooks 二选一，砍掉未用的三个包
4. 抽 `_amountMinor` 为 domain 纯函数并补边界单测（≤8 位、`"0."`、空串、超大额）
5. 统一「页面返回即刷新」约定（`life_page.dart:404`、`album_page.dart:263`、`album_detail_page.dart:221`）
6. 一次性扫全 `DateTime.tryParse` 调用点统一 `.toLocal()`（`life_repository.dart:51-52` 及 3 处消费点）
7. `as int?` 统一为 `(v as num?)?.toInt()`；串行多端点改 `Future.wait`
8. `.gitignore` 补 `.env*`、`*.jks`、`*.keystore`

### 第三批：中期演进（1-2 季度）

1. **补足 domain 层**：金额/解析、油耗里程等业务规则从 Widget 抽出为纯 Dart 实体与函数，presentation 只做渲染 —— 这一步同时解决「超大文件」与「关键逻辑无测试」两个问题，**收益最高**
2. **按业务拆文件**：`ledger_input.dart`(805 行/11 类) 拆为 `ledger/{seg,amount,pad,say_box,parse_card,save_button}.dart`；`life_page.dart` 的 `_LifePageState`(395 行) 拆子组件。目标单文件 < 300 行，可在 `layer_guards_test.dart` 加「文件行数 < 400」静态断言
3. **统一依赖注入**：Repository 由 provider 提供而非 `widget.repository ?? Repository()`，消灭手工 `new`，页面即可脱离 Widget 测试
4. **偿还 sqlite3 workaround**：升级 3.7+、删除 `dependency_overrides` 与 `ghfast.top` 镜像段，改为 CI 缓存，恢复可复现构建
5. **接入 l10n**：`gen_l10n` + ARB，按 feature 收敛 2,208 处硬编码文案
6. **补齐 repository 层与网络拦截器链测试**；引入分级日志替换散落 `debugPrint`
7. **接线已存在但未使用的组件**：`LocalStores`、`DriftRetryStore`、`ChatHistoryCache` —— 这是把「离线补偿」从设计变成能力的唯一路径
8. `theme_context.dart` 下沉至 `design_system/`，全局 provider 上移 `core/`，消除 36 处反向依赖

---

## 九、审计方法与局限

- 本次为**静态代码走查**，全部结论基于真实代码，已抽样复核关键 P0 的原始代码行
- **未运行真机/模拟器**，因此运行时行为（实际渲染性能、真实网络异常路径、并发时序）未实测
- `flutter analyze` / `dart analyze` 在本机因 Windows 管道句柄耗尽（`OS error code 231`）无法输出，**缺少 lint 层面的补充数据**；建议在 CI 或正常环境下补跑一次
- 未审计后端（`apps/backend`）与本次 Flutter 客户端的接口契约一致性
- 结论中的行号基于审计时的工作区状态，代码变更后需重新定位

---

## 十、整改进度（2026-10-07）

> 审计发现已按「第一批 P0 → 第二批 P1」组织执行并登记于此；行号均以执行时工作区为准。P0 见提交 `c1274eb5`，P1 随本提交入库。

### 核实修正（与本报告原文的出入）

执行前对全部 P0 与关键 P1 逐条比对过源码，以下条目需修正口径：

- **金额截断（原 §2-B5）**：ledger 键盘路径有 `AmountInputFormatter`（限 `^\d{0,8}(\.\d{0,2})?$`）兜底，实际可达的静默截断在 **car 页**（无 formatter）；所称 `_onKey` 位于 car 页而非 ledger 页。
- **chat 无守卫处（原 §2-A2）**：实为 **5 处**（`:295/:308/:327/:341/:346`），不止 3 处。
- **createDio 散落（原 §3 网络层）**：实为 **14 处调用 / 13 个文件**，比报告的 8 处更严重。
- **health 权限（原 §6-3）**：项目 manifest 中 health.* 一条都未声明（「声明 17 项」不属实，或指插件合并清单）；health 模块已由并行提交 `55031078` 整体移除，过授权项随之消解。
- 相册「全选永远 false」不成立（点全选后恢复，且此时删除不会崩）；briefing 缓存转圈为**潜伏缺陷**（`BriefingRepository` 默认 cache 为 null，接线后才触发）；ledger 待办回滚问题的触发条件是**两个动作在途重叠**（快速连点），非严格串行。

### 第一批 P0（12 项，全部完成 → `c1274eb5`）

| 序 | 处理 |
|---|---|
| 1 | 新增 `core/format/money.dart#parseAmountMinor` 为唯一「显示串→分」入口（非法输入返回 null 拒绝）；car 键盘限两位小数；边界单测覆盖 |
| 2 | 相册管理页预选与视口资产求交集 + 删除/移动按 map 查找缺失即跳过 |
| 3 | `_pathOf` 对空 paths 返回 null |
| 4 | chat 5 处 `state =` 全部补 `_disposed` |
| 5 | `onUpgrade` 改分版本 switch 迁移（v1→v2 建 `brief_contents`），新增迁移测试 |
| 6 | 待确认回滚只还原失败那条（差集），不再整体快照还原 |
| 7 | ledger 与 car 幂等键均改「内容指纹绑定」：重试复用同 key，换内容/换路径换新 key |
| 8 | 里程 baseline 未知阻断保存并区分提示，`?? 0` 与 `catch (_) {}` 移除 |
| 9 | 车辆档案数值字段逐一客户端校验（拒绝非法/负数）；保养周期月数从档案回显 |
| 10 | 包名 `com.example.mobile` → `com.zhaoxi.app`；release 签名走 `android/key.properties`（缺失回退 debug 保本地构建） |
| 11 | `allowBackup=false` + `network_security_config.xml`（禁明文、放行模拟器回环）；**另发现并修复 release 变体缺 INTERNET 权限** |
| 12 | 一键清空服务端成功后清偏好与 `album.*` 私有键、失败显性报错；登出经 `app/state/auth_epoch.dart` 纪元位重建会话内存态（避免跨 feature import） |

### 第二批 P1（完成 9 项，跳过 4 个子项）

已完成：返回即刷新（life/album/album_detail）；相册权限归因、`openAppSettings` 出口、扫描批内并行 + 30min TTL 跳过、删除结果检查、原图降采样；`createDio` 单例化、令牌内存缓存、401 统一收口（清凭据→纪元重建→跳登录）、拦截器防悬挂、流式超时接线、多端点 `Future.wait`；life_repository 解析层统一 `toLocal`；24 处 `as int?` → `num?.toInt()`；语音金额「单位优先、否则取首个数字」+ 预览请求序号防乱序；`verifyEmailCode` 异常包装 + `deviceIdentity()` 持久化；重复照片 `_mergeSameContent` 漏报修复 + `count` 与 totalBytes 同口径（可删副本数，`assetIds` 保持候选全集）；头像 emoji 按 grapheme 截取；manifest 补 `POST_NOTIFICATIONS` / `SCHEDULE_EXACT_ALARM` / `READ_MEDIA_VISUAL_USER_SELECTED`。

曾跳过（当时文件被并行会话占用）→ **已于第三批收口，见本节末**：

- **P1-7** 日程时间线交互（`schedule_page.dart`）
- **P1-11** 路由守卫 fail-closed（`app_router.dart`）
- **P1-9 子项** briefing_page 缓存读取兜底（TextEditingController 泄漏已由 `pickers.dart` 的 `dispose` 收口）
- **P1-2 子项** manage 页缩略图网格 sliver 化懒加载

### 遗留测试红（非整改产物）

以下 10 个测试红在整改开始前即存在（stash 隔离验证），归属并行会话工作，未代为修改：life_page ×6（健康模块移除未同步测试）、profile_renders（断言「设备连接」行而页面没有）、prefs_keys_centralized（allKeys 9→8 未同步断言）、goldens ×2（spend_summary / ledger_components）。

### 第三批：跳过项与红测收口（2026-10-07）

| 项 | 处理 |
|---|---|
| P1-7 日程时间线 | `ScheduleTimelineItem` 加 `onTap`（`PressScale` 包裹）→ 点卡弹动作条「标记完成 / 删除」，删除补二次确认；AI 结论卡「今天 N 件事」**只数已定时间项**，未排期项单列「另有 M 件」（原 `items.length` 把两者算一起） |
| P1-11 路由守卫 | 去掉 `_entryGateChecked` 一次性闸：**每次导航**按令牌现状判断，令牌 / 偏好读取异常一律按未登录处理（fail-closed）；已登录访问 `/login`、`/verify` 回首页；`errorBuilder` 由 `HomePage` 换显式 `NotFoundPage` |
| P1-9 子项 | `briefing_page._initialLoad` 的缓存读取加 try/catch：缓存损坏继续走网络刷新，不再停在骨架态（TextEditingController 泄漏此前已由 `pickers.dart` `dispose` 收口） |
| P1-2 子项 | 缩略图改**分批并发**（每批 16，去掉逐张串行 await）；分组网格改 `CustomScrollView` + `SliverGrid` 懒加载，去掉 `shrinkWrap: true` + `NeverScrollableScrollPhysics` 的全量布局 |
| 红测同步 | life_page ×5（宫格五卡、Hero「5 个」、健康摘要 / trend 断言移除、悬空入口循环）、`profile_renders`（去「设备连接」「数据授权」断言）、`prefs_keys_centralized`（实现侧漏登记：`keyFirstUsedAt` 补进 `PrefsStore.allKeys`，它在用 —— profile 页据此算「相识 N 天」） |

**仍未完成（需可用 Flutter 环境）**：`test_life_page_golden`（`goldens/life_page_modules.png` 是六卡快照，宫格改五卡后必 diff）与 audit §10 旧列的 `spend_summary` / `ledger_components` 两个 golden —— 本机 `flutter test` 因 Windows 管道句柄耗尽不可用，需跑 `flutter test --update-goldens` 后再人工确认。

设计侧同批：`components.md` A40 补「时间线条目可点（删除二次确认）」、B4b 补「今日计数只数已定时间项」；`design-alignment-report.md` 新增 **DEV-07**（健康模块移除 → 生活宫格 6→5 格、我的页去「设备连接」行与健康同意入口「数据授权」行）。