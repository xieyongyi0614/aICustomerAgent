# PLT-006 性能基线与测量口径

| 指标 | 目标 | 测量方式 |
|---|---|---|
| 冷启动首屏 | ≤ 2.5s | `flutter run --profile` + DevTools timeline，取 `Home` 首帧 |
| 首 token | ≤ 1.5s | 对话发出 → 首个 `token` 事件到达（客户端打点） |
| 列表 | 60fps | DevTools performance，滚动首页/对话 2s 窗口 |
| Orb 功耗 | 先建基线 | 前台静止 5 分钟电池曲线（`RepaintBoundary` + `TickerMode` 已隔离） |

Orb 功耗阈值（Q10）：**先测基线再定目标**，不发明数字。
