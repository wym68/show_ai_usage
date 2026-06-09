# SHOW AI USAGE

KDE Plasma 6 任务栏小部件，监控 **订阅制** AI 服务的使用额度和滚动窗口限制（ChatGPT Codex、Claude Code、Kimi、MiniMax Token Plan），而非按量付费的 API 调用。

---

## 🍴 关于本项目

1. **聚焦订阅模式，区分 API Key 计费** — 监控的是 **订阅制产品** 的滚动窗口额度，而非 API Key 按 token 计费
2. **以 AI 编程助手为主** — OpenAI Codex、Claude Code Pro/Max、Kimi、MiniMax
3. **浏览器自动化** — Playwright 拉起用户已登录的浏览器，抓取数据后自动退出
4. **本地安全** — 所有凭据和请求仅在本机处理，不上传第三方
5. **汉化优先** — 中文界面和中文文档

MIT 协议。

---

## 📦 项目结构

```
show_ai_usage_v2/
├── poller/                          # Python 后端
│   ├── main.py                      # CLI 入口
│   ├── config.py                    # TOML 配置管理
│   ├── browser.py                   # 隔离 Edge 浏览器管理
│   ├── storage.py                   # JSON 读写
│   └── providers/                   # 各平台抓取器
│       ├── base.py                  # UsageData + BaseProvider
│       ├── codex.py                 # OpenAI Codex
│       ├── claude.py                # Claude Code
│       ├── kimi.py                  # Kimi
│       └── minimax.py               # MiniMax
├── package/                         # KDE Plasmoid 包
│   ├── metadata.json
│   └── contents/
│       ├── config/main.xml          # 配置 schema
│       └── ui/
│           ├── main.qml             # 入口 + XHR 数据读取
│           ├── CompactRepresentation.qml  # 面板紧凑条
│           └── FullRepresentation.qml     # 弹出完整面板
├── systemd/                         # systemd 定时器单元
│   ├── show-ai-usage.service
│   └── show-ai-usage.timer
├── pyproject.toml                   # uv 项目配置
└── scripts/
    ├── install.sh                   # 安装脚本
    └── uninstall.sh                 # 卸载脚本
```

---

## ⚡ 快速开始

### 前置依赖

- Python 3.11+
- [uv](https://docs.astral.sh/uv/)（Python 包管理器）
- Microsoft Edge 浏览器（用于 Playwright 自动化）
- KDE Plasma 6（小部件需要）

### 1. 安装项目依赖

```bash
uv sync
```

### 2. 初始化默认配置

```bash
uv run python poller/main.py --init-config
```

生成的配置文件在 `~/.config/show-ai-usage/config.toml`，可按需编辑。

### 3. 登录各平台

每个平台需要先用浏览器登录一次，登录态会保存在项目隔离的 `browser-data/` 目录中：

```bash
# 登录 OpenAI Codex（已有登录态可跳过）
uv run python poller/main.py --login codex

# 登录 Claude Code
uv run python poller/main.py --login claude

# 登录 Kimi
uv run python poller/main.py --login kimi

# 登录 MiniMax
uv run python poller/main.py --login minimax
```

每个命令会弹出独立的 Edge 浏览器窗口，登录完毕后回到终端按 Enter 保存。

### 4. 手动抓取一次

```bash
# 抓取所有已启用的 provider
uv run python poller/main.py --oneshot

# 或只抓取指定 provider
uv run python poller/main.py --oneshot --providers codex claude
```

抓取结果写入 `~/.local/share/show-ai-usage/data.json`。

### 5. 查看结果

```bash
# 人类可读格式
uv run python poller/main.py --status

# JSON 格式
uv run python poller/main.py --status --json
```

---

## ⏱️ 自动定时抓取（systemd timer）

### 安装 timer

```bash
mkdir -p ~/.config/systemd/user/
ln -sf "$PWD/systemd/show-ai-usage.service" ~/.config/systemd/user/
ln -sf "$PWD/systemd/show-ai-usage.timer"   ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now show-ai-usage.timer
```

### 验证

```bash
systemctl --user status show-ai-usage.timer
# → Active: active (waiting)

# 查看最近一次抓取日志
journalctl --user -u show-ai-usage.service
```

默认每 5 分钟抓取一次，开机 2 分钟后首次触发。

---

## 🧩 KDE Plasmoid 小部件

### 安装

```bash
kpackagetool6 --type Plasma/Applet --install package/
```

### 升级（文件修改后）

```bash
kpackagetool6 --type Plasma/Applet --upgrade package/
```

### 预览调试

```bash
env QML_XHR_ALLOW_FILE_READ=1 plasmawindowed showaiusage
```

### 添加到面板

1. 右键桌面 → 添加小部件
2. 搜索 "AI Usage Monitor"
3. 拖到面板上

小部件每 60 秒自动刷新数据（可在设置中调整），点击后展开完整面板，含 5h/7d 彩色进度条、剩余额度、重置时间。

---

## ⚙️ 配置

编辑 `~/.config/show-ai-usage/config.toml`：

```toml
[general]
# 守护模式下的抓取间隔（秒，最小 30）
interval = 300

# 启用的 provider 列表
enabled_providers = ["codex", "claude", "kimi", "minimax"]

[paths]
# 数据文件目录（可选，默认如下）
# data_dir = "~/.local/share/show-ai-usage"

# 浏览器配置文件目录（可选，默认项目 browser-data/）
# browser_data_dir = ""
```

CLI 参数可覆盖配置文件：

```bash
uv run python poller/main.py --oneshot --interval 600 --providers codex claude
```

---

## 🎨 颜色编码

| 颜色 | 使用率 | 含义 |
|------|--------|------|
| 🟢 `#4CAF50` | 0% – 50% | 健康 |
| 🟡 `#FFC107` | 50% – 80% | 注意 |
| 🟠 `#FF9800` | 80% – 95% | 警告 |
| 🔴 `#F44336` | 95% – 100% | 危险 / 已限额 |

---

## 📊 支持的订阅

| 提供商 | 订阅/计划 | 追踪内容 | 数据端点 |
|--------|----------|---------|---------|
| **OpenAI Codex** | ChatGPT Plus / Pro / Codex | 5h + 7d 滚动窗口 | https://chatgpt.com/codex/cloud/settings/analytics |
| **Claude Code** | Claude Pro / Max / Team | 5h + 7d 滚动窗口 | https://claude.ai/new#settings/usage |
| **Kimi** | Kimi 订阅计划 | 使用量 + 额度 | https://www.kimi.com/code/console |
| **MiniMax** | Token Plan (Plus / Max / Ultra) | 5h + 7d + 剩余积分 | https://platform.minimaxi.com/console/usage |

---

## 🔧 开发

### 调试新 provider

`--debug` 模式打开有头浏览器并保存页面 HTML / 截图到 `/tmp/show-ai-usage-debug/`：

```bash
uv run python poller/main.py --debug --providers claude
```

### 添加新 provider

1. 在 `poller/providers/` 下新建文件，继承 `BaseProvider`，实现 `name` 和 `fetch()`
2. 在 `poller/providers/__init__.py` 中注册
3. 在 `poller/main.py` 的 `LOGIN_URLS` 和 `PROVIDER_URLS` 中添加 URL
4. 在 `package/contents/ui/FullRepresentation.qml` 的 `displayName` 映射中添加显示名

### CLI 命令参考

```bash
# 登录
uv run python poller/main.py --login [provider]

# 一次性抓取
uv run python poller/main.py --oneshot [--providers ...]

# 守护模式
uv run python poller/main.py --daemon [--interval 300]

# 查看缓存状态
uv run python poller/main.py --status [--json]

# 调试页面结构
uv run python poller/main.py --debug [--providers ...]

# 配置管理
uv run python poller/main.py --init-config
uv run python poller/main.py --show-config [--interval ...] [--providers ...]
```
