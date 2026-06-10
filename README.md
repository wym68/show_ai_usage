# Show AI Usage

KDE Plasma 6 任务栏小部件，监控 **OpenAI Codex、Claude Code、Kimi、MiniMax** 订阅制 AI 服务的滚动窗口用量，实时显示在面板上。

> 详细的开发文档、架构说明和 Provider 实现细节见 [Doc.md](Doc.md)。

---

## 项目目的

AI 编程助手普遍采用订阅制 + 滚动窗口限流的模式（5 小时会话限制、7 天周限制），超额后即被限速。本项目通过浏览器自动化抓取各平台的用量页面，将数据写入本地 JSON 文件，由 KDE 任务栏小部件实时读取展示，让你在编程时随时掌握各服务的剩余配额。

---

## 实现逻辑

```
systemd timer（每 5 分钟）
    └─▶ Python Poller（Playwright + Edge）
            └─▶ 访问各平台用量页面 → 提取 5h/7d 百分比 + 重置时间
                    └─▶ 写入 ~/.local/share/show-ai-usage/data.json
                                └─▶ KDE Plasmoid（每 60 秒读取）
                                        └─▶ 面板彩色进度条 + 悬停 Tooltip
```

1. **Python Poller**（`poller/`）：使用 Playwright 控制隔离的 Edge 浏览器（独立 `browser-data/` 目录，不影响系统浏览器），依次访问各平台用量页面，正则提取数据，写入 JSON。
2. **KDE Plasmoid**（`package/`）：QML 小部件每 60 秒通过 `Plasma5Support.DataSource` 读取 JSON，在面板上显示 4 根彩色圆角进度条，鼠标悬停显示各服务的详细用量与重置时间。

### 面板显示

| 颜色 | 用量 | 含义 |
|------|------|------|
| 🟢 绿 | 0–50% | 健康 |
| 🟡 黄 | 50–80% | 注意 |
| 🟠 橙 | 80–95% | 警告 |
| 🔴 红 | 95–100% | 即将限速 |

进度条字母含义：`C` = OpenAI Codex，`D` = Claude Code，`K` = Kimi，`M` = MiniMax。

---

## 前置依赖

- Python ≥ 3.11 + [uv](https://docs.astral.sh/uv/)
- Microsoft Edge（Playwright 驱动）
- KDE Plasma ≥ 6.0

---

## 安装

### 1. 安装 Python 依赖

```bash
uv sync
```

### 2. 初始化配置

```bash
uv run python -m poller.main --init-config
```

配置文件生成于 `~/.config/show-ai-usage/config.toml`。

### 3. 登录各平台

每个平台首次使用前需在隔离浏览器中手动登录一次，登录态保存在 `browser-data/` 中：

```bash
uv run python -m poller.main --login codex
uv run python -m poller.main --login claude
uv run python -m poller.main --login kimi
uv run python -m poller.main --login minimax
```

### 4. 测试抓取

```bash
uv run python -m poller.main --oneshot
uv run python -m poller.main --status   # 查看结果
```

### 5. 安装 Plasmoid 和 systemd 定时任务

```bash
./scripts/install.sh
```

脚本会自动安装 Plasmoid 并启动 systemd timer（每 5 分钟自动抓取）。

安装后，右键桌面 → **添加小部件** → 搜索 "AI Usage Monitor" → 拖到面板上。

---

## 卸载

```bash
./scripts/uninstall.sh          # 停止 timer + 卸载 Plasmoid
./scripts/uninstall.sh --purge  # 同上 + 删除配置文件和数据文件
```

---

## 配置

`~/.config/show-ai-usage/config.toml`：

```toml
[general]
interval = 300                                          # 守护模式抓取间隔（秒）
enabled_providers = ["codex", "claude", "kimi", "minimax"]  # 启用的服务

[locale]
# timezone = "Asia/Shanghai"  # 浏览器时区，留空自动检测
```

Plasmoid 内置配置（右键小部件 → 配置）：
- **界面刷新间隔**：重新读取 JSON 的频率，默认 60 秒
- **数据过期阈值**：超过此时间未更新则显示 ⚠ 警告，默认 600 秒

---

## 常用命令

```bash
# 手动抓取一次
uv run python -m poller.main --oneshot

# 查看最新数据
uv run python -m poller.main --status

# 调试某个 provider（有头浏览器 + 保存页面到 /tmp/）
uv run python -m poller.main --debug --providers codex

# 查看/手动触发 systemd timer
systemctl --user status show-ai-usage.timer
systemctl --user start show-ai-usage.service

# 更新 Plasmoid（修改 QML 后）
kpackagetool6 --type Plasma/Applet --upgrade package/
plasmashell --replace &
```
