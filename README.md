# SHOW AI USAGE

## 本项目目的
开发一个KDE Plasma 6 任务栏小部件，监控 **订阅制** AI 服务的使用额度和窗口限制（如 ChatGPT Plus、Claude Pro、MiniMax Token Plan），而非按量付费的 API 调用。


## 🍴 关于本项目

1. **聚焦订阅模式，区分 API Key 计费** — 监控的是 **订阅制产品**（如 ChatGPT Plus、Claude Pro、Claude Max、MiniMax Token Plan）的滚动窗口额度，而非 OpenAI API Key 按 token 计费的普通 API 调用。两种模式来自不同的数据端点，不可混用。
2. **以 AI 编程助手为主** — 目前覆盖 OpenAI Codex、Claude Code Pro、Kimi、MiniMax，均为常见的 AI 编程订阅服务。
3. **保持可扩展性** — 保持可以扩展其他ai服务提供商
4. **汉化优先** — 提供中文界面和中文文档为主。

所有代码改动都在 MIT 协议下进行
---

## ✨ 功能特性

- **KDE 任务栏小部件** — 可放置在 Plasma 面板（Panel）上，像系统托盘一样常驻
- **编程订阅追踪** — 专门追踪 AI 编程助手的订阅配额，而非普通 API 调用
- **多平台支持** — OpenAI Codex、Claude Code Pro/Max、Kimi、MiniMax Token Plan
- **浏览器自动化运行** — 后台 poller 短时间拉起用户已登录的浏览器，抓取后生成摘要
- **颜色编码进度条** — 绿色/黄色/橙色/红色直观显示剩余额度
- **本地安全** — 所有凭据和请求仅在本机处理，不上传第三方

---

## 📊 支持的订阅

| 提供商 | 订阅/计划 | 追踪内容 | 
|--------|----------|---------|
| **OpenAI Codex** | ChatGPT Plus / Pro / Codex 订阅 | 5小时滚动窗口、7天滚动窗口|
| **Claude Code** | Claude Pro / Max / Team | 5小时会话窗口、7天周窗口|
| **Kimi** |  
| **MiniMax** | Token Plan (Plus / Max / Ultra) | 5小时滚动额度、7天滚动额度、剩余订阅积分 |

### 数据端点（均通过了浏览器自动化直接查询）

| 提供商 | 端点 
|--------|------
| **OpenAI Codex** | https://chatgpt.com/codex/cloud/settings/analytics
| **Claude Code** | https://claude.ai/new#settings/usage
| **Kimi** | https://www.kimi.com/code/console
| **MiniMax** | https://platform.minimaxi.com/console/usage

---

## ⚙️ 配置说明

```
面板:  [🤖 65%,🤖 65%,🤖 65%,🤖 65%]     ← 展示各个ai提供商5h使用量
```

点击后展开完整弹窗：

```
┌─────────────────────────────────────────┐
│ 🤖 AI Coding Subscriptions Tracker     │
├─────────────────────────────────────────┤
│ [Codex] [Claude] [Kimi] [MiniMax]      │
├─────────────────────────────────────────┤
│ 🟢 OpenAI Codex                         │
│    5h:   15% ███⬜⬜⬜⬜⬜⬜⬜⬜      │
│    7d:    8% █⬜⬜⬜⬜⬜⬜⬜⬜       │
│    积分:  $150.00                       │
│    重置:  4h 12m                        │
│                                         │
├─────────────────────────────────────────┤
│ ⚙️ 设置    🔄 刷新摘要                 │
└─────────────────────────────────────────┘
```

### 颜色含义

| 颜色 | 使用率范围 | 状态 |
|------|-----------|------|
| 🟢 绿色 | 0% - 50% | 健康 |
| 🟡 黄色 | 50% - 80% | 注意 |
| 🟠 橙色 | 80% - 95% | 警告 |
| 🔴 红色 | 95% - 100% | 危险 / 已限额 |
