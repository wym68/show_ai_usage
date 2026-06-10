# Show AI Usage

KDE Plasma 6 任务栏小部件，监控 **OpenAI Codex、Claude Code、Kimi、MiniMax** 订阅制 AI 服务的滚动窗口用量，实时显示在面板上。

> 详细的开发文档、架构说明和 Provider 实现细节见 [Doc.md](Doc.md)。

**注意本项目完全由AI开发,请自行注意保护个人隐私!**

---

## 项目目的

AI 编程助手普遍采用订阅制 + 滚动窗口限流的模式（5 小时会话限制、7 天周限制），超额后即被限速。本项目通过浏览器自动化抓取各平台的用量页面，将数据写入本地 JSON 文件，由 KDE 任务栏小部件实时读取展示，让你在编程时随时掌握各服务的剩余配额。

---

## 实现逻辑

```
systemd timer（每 X 分钟）
    └─▶ Python Poller（Playwright + Edge）
            └─▶ 访问各平台用量页面 → 提取 5h/7d 百分比 + 重置时间
                    └─▶ 写入 ~/.local/share/show-ai-usage/data.json
                                └─▶ KDE Plasmoid（每 60 秒读取）
                                        └─▶ 面板彩色进度条 + 悬停 Tooltip
```

1. **Python Poller**（`poller/`）：使用 Playwright 控制隔离的 Edge 浏览器（独立 `browser-data/` 目录，不影响系统浏览器），依次访问各平台用量页面，正则提取数据，写入 JSON。
2. **KDE Plasmoid**（`package/`）：QML 小部件每 60 秒通过 `Plasma5Support.DataSource` 读取 JSON，在面板上显示 4 根彩色圆角进度条，鼠标悬停显示各服务的详细用量与重置时间。

### 面板显示

![效果图](fig/效果图.png)

### 面板显示

| 颜色 | 用量 | 含义 |
|------|------|------|
| 🟢 绿 | 0–50% | 健康 |
| 🟡 黄 | 50–80% | 注意 |
| 🟠 橙 | 80–95% | 警告 |
| 🔴 红 | 95–100% | 即将限速 |

进度条字母含义：`O` = OpenAI Codex，`C` = Claude Code，`K` = Kimi，`M` = MiniMax。

彩色用量条右上角的圆圈表示当前显示的是7天用量。当7天用量超过85%时会自动切换为显示7天用量，否则为自动显示5小时用量。
---

## 前置依赖

- Python ≥ 3.11 + [uv](https://docs.astral.sh/uv/)
- Microsoft Edge（Playwright 驱动）
- KDE Plasma ≥ 6.0
- systemd --user（用于后台定时抓取）

---

## 安装

### 方式一：从发布包安装（推荐）

1. 下载并解压发布包(dist目录)到任意目录（如 `~/show-ai-usage/`）
2. 进入目录并运行安装脚本：

```bash
cd ~/show-ai-usage
./install.sh
```

3. 安装后，右键桌面 → **添加小部件** → 搜索 "AI Usage Monitor" → 拖到面板上

### 方式二：从源码安装

```bash
git clone <仓库地址> show-ai-usage
cd show-ai-usage
./scripts/install.sh
```

### 首次使用 — 登录各平台

> **安装路径说明**：Plasmoid 小部件和 Python 轮询器是分开安装的——小部件通过 `kpackagetool6` 安装到 `~/.local/share/plasma/plasmoids/`，而 Python 项目留在你解压的目录里。因此所有 `uv run python -m poller.main` 命令都需要在**项目目录**下运行。

首次使用前，需在隔离浏览器中手动登录各 AI 平台（登录态保存在 `~/.local/share/show-ai-usage/browser-data/`）：

```bash
uv run python -m poller.main --login codex
uv run python -m poller.main --login claude
uv run python -m poller.main --login kimi
uv run python -m poller.main --login minimax
```

执行命令后会弹出浏览器窗口，手动完成登录后，回到终端按 **Enter** 保存登录态。

### 测试抓取

```bash
# 手动抓取一次
uv run python -m poller.main --oneshot

# 查看最新数据
uv run python -m poller.main --status
```

---

## 卸载

```bash
./scripts/uninstall.sh          # 停止 timer + 卸载 Plasmoid（保留配置和数据）
./scripts/uninstall.sh --purge  # 同上 + 删除配置文件和数据文件
```

> **注意**：卸载后任务栏上的小部件可能仍会显示（显示 N/A），需要手动右键小部件 → **移除**，或运行 `plasmashell --replace` 重启面板。

---

## 配置

### Plasmoid 配置面板

右键小部件 → **配置**，包含四个标签页：

| 标签页 | 配置项 |
|--------|--------|
| **General** | 界面刷新间隔（秒）、数据过期阈值（秒） |
| **Data Polling** | 启用/禁用数据抓取、抓取间隔、选择监控的 AI 服务商 |
| **Display** | 显示模式（5h+7d / 仅5h / 仅7d）、紧凑标签、最大显示数 |
| **Advanced** | 自定义数据路径、配色方案、自定义颜色 |

在 **Data Polling** 标签页中：
- 勾选「启用自动数据抓取」后，插件会按设定间隔自动抓取
- 勾选/取消勾选提供商会**即时生效**（显示端自动过滤，后台配置自动同步）
- 每个提供商右侧显示对应的登录命令，点击「复制」可直接粘贴到终端执行

### 配置文件

`~/.config/show-ai-usage/config.toml`（由 Plasmoid 自动管理，一般无需手动编辑）：

```toml
[general]
interval = 300                                          # 抓取间隔（秒）
enabled_providers = ["codex", "claude", "kimi", "minimax"]  # 启用的服务

[locale]
# timezone = "Asia/Shanghai"  # 浏览器时区，留空自动检测
```

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

# 构建发布包（生成 dist/ 目录）
./scripts/build-plugin.sh
```
