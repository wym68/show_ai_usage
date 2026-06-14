# SHOW AI USAGE

**KDE Plasma 6 任务栏小部件**，通过浏览器自动化监控 **订阅制 AI 服务**（OpenAI Codex、Claude Code、Kimi、MiniMax Token Plan）的滚动窗口使用额度和剩余配额。

> 本项目监控的是 **订阅制产品**（如 ChatGPT Plus、Claude Pro、MiniMax Token Plan）的额度，而非 API Key 按 token 计费的模式。两者数据端点不同，不可混用。

---

## 📋 目录

- [项目目的](#项目目的)
- [功能特性](#功能特性)
- [架构设计](#架构设计)
- [项目结构详解](#项目结构详解)
- [前置依赖](#前置依赖)
- [快速开始](#快速开始)
- [配置说明](#配置说明)
- [CLI 命令参考](#cli-命令参考)
- [自动定时抓取（systemd timer）](#自动定时抓取systemd-timer)
- [Plasmoid 小部件](#plasmoid-小部件)
- [颜色编码](#颜色编码)
- [支持的订阅与数据来源](#支持的订阅与数据来源)
- [Provider 实现详解](#provider-实现详解)
  - [各 Provider 数据提取要点](#各-provider-数据提取要点)
  - [常见正则陷阱](#常见正则陷阱s-跨行问题)
- [开发指南](#开发指南)
- [常见问题](#常见问题)

---

## 项目目的

AI 编程助手普遍采用**订阅制 + 滚动窗口限制**的模式。例如：

- **OpenAI Codex** 在 5 小时滚动窗口内有使用次数限制，超过后被限速直到窗口重置
- **Claude Code Pro/Max** 同样有 5 小时会话限制和 7 天周限制
- **Kimi** 和 **MiniMax** 也有类似的滚动额度机制

现有的系统监视器（如 KDE System Monitor）只能监控系统资源，无法查看这些订阅服务的使用情况。**Show AI Usage** 填补了这一空白：

1. 通过 Playwright 自动化启动 Edge 浏览器
2. 用预先保存的登录态访问各平台的使用量页面
3. 提取 5 小时 / 7 天滚动窗口使用百分比、剩余额度、重置时间
4. 写入本地 JSON 文件
5. KDE Plasmoid 定时读取并显示在任务栏上
6. **所有凭据只在本地，不上传任何第三方**

---

## 功能特性

| 特性 | 说明 |
|------|------|
| **KDE 任务栏小部件** | Plasma 6 面板原生 Plasmoid，像系统托盘一样常驻 |
| **紧凑模式** | 面板上显示彩色圆角条，每根代表一个 provider 的 5h 使用率 |
| **弹出模式** | 点击展开完整面板：彩色进度条 + 百分比 + 剩余额度 + 重置时间 |
| **颜色编码** | 绿色/黄色/橙色/红色直观映射 0–100% 使用率 |
| **自动刷新** | Plasmoid 每 60 秒（可配置）重新读取 JSON 文件 |
| **数据过期提醒** | 数据超过阈值（默认 10 分钟）自动显示过期警告 |
| **手动刷新按钮** | 弹窗底部"刷新"按钮可立即重新加载数据 |
| **4 个 Provider** | Codex / Claude / Kimi / MiniMax，均可独立启停 |
| **隔离浏览器** | 项目内独立 Edge 配置文件，不污染系统浏览器 |
| **定时自动抓取** | systemd --user timer，默认每 5 分钟后台抓取一次 |
| **中文界面** | Plasmoid UI 和文档均以中文为主 |
| **配置面板** | 4 个标签页：General / Data Polling / Display / Advanced |
| **显示过滤** | 取消勾选提供商后，小部件即时隐藏该提供商（不依赖后台抓取） |
| **一键复制登录命令** | Data Polling 标签页中每个提供商右侧可直接复制登录命令 |
| **源码安装** | 通过 `./scripts/install.sh` 一键安装 |
| **CLI 操作** | --login / --oneshot / --daemon / --status / --debug 完整命令 |

---

## 架构设计

```
┌────────────────────────────────────────────────────────────┐
│                    KDE Plasma 6 面板                         │
│  ┌──────────────────────────────────────────────────────┐  │
│  │  Plasmoid (QML + JavaScript)                         │  │
│  │  ├─ CompactRepresentation: 彩色圆角条                  │  │
│  │  └─ FullRepresentation: 进度条 + 额度 + 重置时间        │  │
│  └──────────────────────┬───────────────────────────────┘  │
└─────────────────────────┬──────────────────────────────────┘
                          │ 读取 (每 60 秒轮询)
                          ▼
┌────────────────────────────────────────────────────────────┐
│  ~/.local/share/show-ai-usage/data.json                     │
│  JSON 格式: { fetched_at, providers: [{ ... }] }            │
└────────────────────────┬───────────────────────────────────┘
                         ▲ 写入 (每次 --oneshot)
┌────────────────────────┴───────────────────────────────────┐
│  Python Poller (uv 管理的 .venv)                             │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────────┐  │
│  │  Codex   │ │  Claude  │ │  Kimi   │ │   MiniMax    │  │
│  │ Provider │ │ Provider │ │ Provider│ │   Provider   │  │
│  └─────┬────┘ └─────┬────┘ └────┬───┘ └──────┬───────┘  │
│        │            │           │            │           │
│        └────────────┴───────────┴────────────┘           │
│                         │                                │
│               Playwright (Edge 浏览器自动化)                │
└────────────────────────┬──────────────────────────────────┘
                         │ 触发
┌────────────────────────┴───────────────────────────────────┐
│  systemd --user timer (show-ai-usage.timer)                 │
│  └── show-ai-usage.service                                  │
│      └── uv run python poller/main.py --oneshot             │
└────────────────────────────────────────────────────────────┘
```

**数据流：**

1. systemd timer 每 5 分钟触发 → 执行 `--oneshot`
2. Playwright 启动隔离 Edge → 依次访问各 provider 仪表盘
3. 正则提取页面文本中的百分比、额度、重置时间
4. 写入 `~/.local/share/show-ai-usage/data.json`
5. Plasmoid 通过 `XMLHttpRequest` 读取本地 JSON 文件
6. QML 渲染彩色进度条显示在面板上

---

## 项目结构详解

```
show_ai_usage/
├── README.md                          # 项目简介（用户面向）
├── Doc.md                             # 详细开发文档（本文件）
├── pyproject.toml                     # uv Python 项目配置
├── uv.lock                            # 依赖锁定文件
├── .gitignore                         # Git 忽略规则
│
├── poller/                            # ═══ Python 后端 ═══
│   ├── __init__.py                    # 包标记
│   ├── main.py                        # CLI 入口 + 命令分发
│   ├── config.py                      # TOML 配置加载/合并/初始化
│   ├── storage.py                     # JSON 数据文件读写
│   ├── browser.py                     # 隔离 Edge 浏览器管理
│   ├── logger.py                      # 日志系统
│   │
│   └── providers/                     # 各平台抓取器
│       ├── __init__.py                # Provider 注册表
│       ├── base.py                    # UsageData 模型 + BaseProvider 抽象基类
│       ├── codex.py                   # OpenAI Codex 抓取实现
│       ├── claude.py                  # Claude Code 抓取实现
│       ├── kimi.py                    # Kimi 抓取实现
│       └── minimax.py                 # MiniMax 抓取实现
│
├── package/                           # ═══ KDE Plasmoid 包 ═══
│   ├── metadata.json                  # Plasma 6 插件元信息
│   └── contents/
│       ├── config/
│       │   ├── main.xml               # 配置 schema (kcfg 格式)
│       │   └── config.qml             # 配置面板入口 (ConfigModel)
│       ├── ui/
│       │   ├── main.qml               # PlasmoidItem 入口 + 数据过滤 + 配置同步
│       │   ├── CompactRepresentation.qml  # 面板紧凑显示 (彩色圆角条)
│       │   ├── FullRepresentation.qml     # 弹出完整面板 (进度条+额度+设置)
│       │   └── config/
│       │       ├── GeneralConfig.qml   # 通用配置 (刷新间隔+过期阈值)
│       │       ├── PollingConfig.qml   # 数据抓取配置 (启用/间隔/提供商)
│       │       ├── DisplayConfig.qml   # 显示配置 (模式/标签/颜色)
│       │       └── AdvancedConfig.qml  # 高级配置 (路径/主题)
│       └── scripts/
│           └── sync_config.py         # Plasmoid ↔ poller 配置同步脚本
│
├── systemd/                           # ═══ systemd 单元文件 ═══
│   ├── show-ai-usage.service          # Oneshot 服务 (含 @@PROJECT_DIR@@ 模板)
│   └── show-ai-usage.timer            # 定时器 (每 5 分钟)
│
└── scripts/                           # ═══ 安装/构建脚本 ═══
    ├── install.sh                     # 源码安装脚本
    ├── uninstall.sh                   # 卸载脚本
    └── build-plugin.sh                # 插件打包脚本（开发者维护用）
```

### 各文件详解

#### `poller/main.py` — CLI 入口

Python 命令行入口，使用 `argparse` 解析参数。核心函数：

| 函数 | 作用 |
|------|------|
| `cli()` | 参数解析 + 命令分发 |
| `_handle_login(provider)` | 打开有头浏览器导航到指定平台首页，等待用户手动登录 |
| `_handle_oneshot()` | 执行一次完整抓取 → 写入 JSON |
| `_handle_daemon()` | 守护模式，按间隔循环抓取 |
| `_handle_status()` | 读取 `data.json` 并显示最新数据 |
| `_handle_debug_dump()` | 有头浏览器 + 保存页面 HTML/TXT/截图到 `/tmp/` |
| `_poll()` | 共享的浏览器生命周期：打开 Edge → 遍历 provider → 关闭 Edge |

**CLI 参数合并逻辑：** CLI 参数（`--interval`, `--providers`）会覆盖 TOML 配置文件中对应的值，未指定的参数使用配置文件的值。

#### `poller/config.py` — 配置管理

| 函数 | 作用 |
|------|------|
| `Config` | Pydantic 数据模型，定义所有配置字段和默认值 |
| `load_config()` | 读取 `~/.config/show-ai-usage/config.toml`，解析 TOML 为 `Config` 对象 |
| `merge_cli_overrides()` | CLI 参数覆盖配置文件：生成新的 Config 实例 |
| `init_default_config()` | 写入带注释的默认配置到 `config.toml` |

配置字段：

| 字段 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `interval` | int | 300 | 守护模式抓取间隔（秒，最小 30） |
| `enabled_providers` | string[] | ["codex","claude","kimi","minimax"] | 启用的 provider 列表 |
| `data_dir` | string | `~/.local/share/show-ai-usage` | JSON 数据文件目录 |
| `browser_data_dir` | string | ""（= 项目 browser-data/） | 隔离浏览器配置文件目录 |
| `timezone` | string | ""（= 自动检测系统时区） | 浏览器 IANA 时区 ID，如 "Europe/Brussels" |

#### `poller/browser.py` — 浏览器管理

`ManagedBrowser` 上下文管理器，封装 Playwright 的 `launch_persistent_context`：

- 使用 **Microsoft Edge**（`channel="msedge"`）
- 独立的 `browser-data/` 用户数据目录（与系统浏览器完全隔离）
- 中文 locale `zh-CN`、上海时区
- 自定义 User-Agent 模拟 Edge 148
- 禁用自动化检测标志 `--disable-blink-features=AutomationControlled`
- 反 Cloudflare 挑战配置

```python
with ManagedBrowser(headless=True, data_dir=...) as browser:
    context = browser.get_context()
    page = context.new_page()
    # ... 抓取逻辑 ...
```

#### `poller/storage.py` — 数据存储

| 函数 | 作用 |
|------|------|
| `save_results(results, data_dir)` | 写入 JSON：`{ fetched_at, providers: [...] }` |
| `load_results(data_dir)` | 读取 JSON，返回 dict 或 None |
| `get_data_file(data_dir)` | 返回 data.json 的完整路径（供 Plasmoid 使用） |

数据文件格式：

```json
{
  "fetched_at": "2026-06-09T14:39:03.192982+00:00",
  "providers": [
    {
      "provider": "codex",
      "window_5h_percent": 1.0,
      "window_7d_percent": 100.0,
      "reset_5h": "9:25",
      "reset_7d": "2026年6月12日 21:14",
      "fetched_at": "2026-06-09T14:39:03.066937Z",
      "error": null
    }
  ]
}
```

#### `poller/providers/base.py` — 抽象基类

`UsageData`（Pydantic BaseModel）：

| 字段 | 类型 | 说明 |
|------|------|------|
| `provider` | str | provider 标识，如 "codex"、"claude" |
| `window_5h_percent` | float (0-100) | 5 小时滚动窗口使用百分比 |
| `window_7d_percent` | float (0-100) | 7 天滚动窗口使用百分比 |
| `reset_5h` | str? | 5小时窗口重置时间，如 "31 分钟后重置" |
| `reset_7d` | str? | 7天/周窗口重置时间，如 "2026年6月12日 21:14" |
| `fetched_at` | datetime | 抓取时间（自动生成） |
| `error` | str? | 错误信息 |

`BaseProvider`（ABC）：

| 方法 | 说明 |
|------|------|
| `name` (property) | 返回 provider 标识符 |
| `fetch(context)` | 接收 Playwright `BrowserContext`，返回 `UsageData` |

#### `poller/providers/codex.py` — OpenAI Codex 抓取器

- **目标 URL：** `https://chatgpt.com/codex/cloud/settings/analytics`
- **导航策略：** 两阶段导航（先 ChatGPT 首页 → analytics 页面），绕过 Cloudflare 挑战
- **文本解析：** 正则匹配 `5 小时使用限额` / `每周使用限额` 后的百分比，`重置时间` 后的时间（第一个=5h，第二个=7d）
- **百分比语义：** 页面标注"剩余"，代码自动转换为使用百分比（`已用 = 100 - 剩余`）
- **DOM 回退：** 若文本解析失败，遍历页面中 `progress`、`[role=progressbar]`、`[class*=usage]` 等元素提取百分比

#### `poller/providers/claude.py` — Claude Code 抓取器

- **目标 URL：** `https://claude.ai/new#settings/usage`
- **解析策略：** 中文模式（5小时/每周）→ 英文模式（"You've used X%" / "used X%"）→ 通用双百分比 fallback
- 与 Codex 相同的 DOM 回退逻辑

#### `poller/providers/kimi.py` — Kimi 抓取器

- **目标 URL：** `https://www.kimi.com/code/console`
- **解析策略：** 中文模式（5小时/周使用量）→ 通用百分比 fallback

#### `poller/providers/minimax.py` — MiniMax 抓取器

- **目标 URL：** `https://platform.minimaxi.com/console/usage`
- **解析策略：** 中文模式（5小时/7天/本周）→ 英文模式（"5-hour" / "7-day" / "weekly" / "credits"）→ 通用 fallback

#### `package/metadata.json` — Plasmoid 元信息

```json
{
  "KPackageStructure": "Plasma/Applet",
  "KPlugin": {
    "Id": "showaiusage",
    "Name": "AI Usage Monitor",
    "Category": "Utilities",
    "Icon": "utilities-system-monitor"
  },
  "X-Plasma-API-Minimum-Version": "6.0"
}
```

- `KPackageStructure: "Plasma/Applet"` — 声明为 Plasma 小部件
- `Id: "showaiusage"` — 唯一标识符，用于 `kpackagetool6` 和 `plasmawindowed`
- `X-Plasma-API-Minimum-Version: "6.0"` — 声明 Plasma 6 兼容性

#### `package/contents/ui/main.qml` — Plasmoid 入口

`PlasmoidItem` 是根组件：

- **数据加载：** `Plasma5Support.DataSource` 通过 `cat` 命令读取本地 `data.json`
- **Provider 过滤：** 根据 `Plasmoid.configuration.enabledProviders` 过滤显示列表，取消勾选的提供商即时从 UI 消失
- **定时刷新：** `Timer` 每 `Plasmoid.configuration.refreshInterval` 秒（默认 60）触发重新读取
- **配置同步：** 当 Polling 配置变更时，自动调用 `sync_config.py` 同步到 poller 的 `config.toml`
- **`compactRepresentation`：** `CompactRepresentation` 组件
- **`fullRepresentation`：** `FullRepresentation` 组件，传 `usageData` / `providers` / `errorMessage` / `dataFileUrl`

路径解析：`StandardPaths.writableLocation(StandardPaths.GenericDataLocation)` 返回 `file:///home/user/.local/share`，拼接 `/show-ai-usage/data.json` 构成完整 URL。

#### `package/contents/ui/CompactRepresentation.qml` — 面板紧凑显示

- 每个 provider 显示一根**彩色圆角条（pill）**
- 条的右侧被半透明背景覆盖 `(100 - usage)%`，左侧彩色部分即为使用率进度
- 色彩按使用率分级（绿/黄/橙/红）
- 鼠标悬停显示 ToolTip：provider 名 + 百分比
- 无数据时显示 "⋯"

**尺寸设计要点：**

| 属性 | 值 | 说明 |
|------|----|------|
| `_pillH` | `Kirigami.Units.gridUnit` | 固定高度，基于主题常量，不随运行时值变化 |
| `implicitWidth` | `4 * gridUnit * 4 + 3 * smallSpacing` | 静态值，见下方「布局陷阱」说明 |
| RowLayout width | `root.width > 0 ? root.width : implicitWidth` | 自适应面板实际分配宽度 |
| pill 宽度 | `Layout.fillWidth: true` | 均分可用宽度，不写死 |

#### `package/contents/ui/FullRepresentation.qml` — 弹出完整面板

- **标题：** "🤖 AI 订阅用量追踪"
- **时间栏：** 显示相对时间（"3 分钟前"）+ 过期警告（"⚠ 数据已过期"）
- **provider 卡片：** 名称 + 5h 进度条 + 7d 进度条 + 剩余额度 + 重置时间
- **错误状态：** 红色边框 + 错误信息
- **空状态：** "等待数据… 请先运行 poller"
- **刷新按钮：** 触发 `Plasmoid.rootItem.loadUsageData()`
- **Provider 名映射：** `codex` → `OpenAI Codex`，`claude` → `Claude Code`，等

内联组件：
| 组件 | 用途 |
|------|------|
| `UsageRow` | 标签 + 彩色进度条 + 百分比文本 |
| `LabelLine` | 标签 + 值 |

#### `package/contents/config/main.xml` — 配置 schema

kcfg 格式，定义四个配置组：

| 组 | 配置项 | 类型 | 说明 |
|----|--------|------|------|
| **General** | `refreshInterval` | Int | 界面刷新间隔（秒，默认 60） |
| | `staleThreshold` | Int | 数据过期阈值（秒，默认 600） |
| **Display** | `displayMode` | Int | 显示模式：0=全部 / 1=仅5h / 2=仅7d |
| | `showProviderLabels` | Bool | 紧凑模式显示字母标签 |
| | `compactMaxProviders` | Int | 紧凑模式最大显示数 |
| **Polling** | `pollingEnabled` | Bool | 启用数据抓取 |
| | `pollingInterval` | Int | 抓取间隔（秒，默认 300） |
| | `enabledProviders` | String | 启用的提供商（逗号分隔） |
| **Advanced** | `dataFilePath` | String | 自定义数据文件路径 |
| | `colorTheme` | Int | 配色方案 |
| | `customColorLow/Mid/High/Critical` | String | 自定义颜色 |

#### `package/contents/config/config.qml` — 配置面板入口

`ConfigModel` 定义四个分类：General / Data Polling / Display / Advanced，分别指向对应的 QML 配置表单。

#### `package/contents/ui/config/PollingConfig.qml` — 数据抓取配置

- 启用/禁用抓取开关
- 抓取间隔 SpinBox
- Provider 复选框列表（每个带登录命令复制按钮）
- 使用 `property alias cfg_<name>` 自动绑定到 kcfg

#### `package/contents/ui/config/DisplayConfig.qml` — 显示配置

- 显示模式 ComboBox
- 紧凑标签 CheckBox
- 最大显示数 SpinBox

#### `package/contents/ui/config/AdvancedConfig.qml` — 高级配置

- 自定义数据路径 TextField
- 配色方案 ComboBox
- 自定义颜色输入框（带颜色预览矩形）

#### `systemd/show-ai-usage.service` — systemd oneshot 服务

```ini
[Service]
Type=oneshot
ExecStart=@@PROJECT_DIR@@/.venv/bin/python @@PROJECT_DIR@@/poller/main.py --oneshot
WorkingDirectory=@@PROJECT_DIR@@
User=%u
```

- `@@PROJECT_DIR@@` 是模板占位符，安装时被替换为实际路径
- `Type=oneshot`：执行一次即退出
- 依赖 `network-online.target`：确保网络就绪后再运行

#### `systemd/show-ai-usage.timer` — systemd 定时器

```ini
[Timer]
OnBootSec=2min        # 开机 2 分钟后首次触发
OnUnitActiveSec=5min   # 后续每次完成后 5 分钟再次触发
Persistent=true        # 休眠/睡眠后补跑
```

#### `scripts/install.sh` — 安装脚本

源码安装流程：
1. 检查系统依赖（uv、kpackagetool6、Edge、systemd）
2. `uv sync --project` 安装 Python 依赖
3. `kpackagetool6` 安装/升级 Plasmoid
4. `sed` 替换 `@@PROJECT_DIR@@` → 真实路径，复制 systemd 文件到 `~/.config/systemd/user/`
5. `systemctl --user daemon-reload`
6. `systemctl --user enable --now show-ai-usage.timer`
7. 显示安装摘要

#### `scripts/uninstall.sh` — 卸载脚本

```bash
./scripts/uninstall.sh          # 标准卸载（保留配置和数据）
./scripts/uninstall.sh --purge  # 清理配置和数据文件
./scripts/uninstall.sh --purge-all  # 彻底清理（含 .venv）
```

流程：
- 停止并禁用 timer
- 删除 systemd 单元文件 + `daemon-reload`
- 卸载 Plasmoid
- `--purge` 删除 `~/.config/show-ai-usage` 和 `~/.local/share/show-ai-usage`
- `--purge-all` 额外删除 `.venv/`

> 注意：卸载后面板上的小部件不会自动消失，需要手动移除或运行 `plasmashell --replace`

---

## 前置依赖

| 依赖 | 版本要求 | 用途 |
|------|---------|------|
| **Python** | ≥ 3.11 | 运行 poller 后端 |
| **uv** | ≥ 0.4 | Python 包管理 |
| **Microsoft Edge** | 任意版本 | Playwright 浏览器自动化 |
| **KDE Plasma** | ≥ 6.0 | Plasmoid 运行环境 |
| **kpackagetool6** | Plasma 6 自带 | Plasmoid 打包工具 |
| **plasmawindowed** | Plasma 6 自带 | Plasmoid 预览调试 |

---

## 快速开始

```bash
git clone https://github.com/wym68/show_ai_usage.git show-ai-usage
cd show-ai-usage
./scripts/install.sh
```

右键桌面 → **添加小部件** → 搜索 **AI Usage Monitor** → 拖到面板上

### 登录各平台

首次使用前，需在隔离浏览器中手动登录各 AI 平台。登录态保存在 `~/.local/share/show-ai-usage/browser-data/`（XDG 目录，与项目位置解耦）：

```bash
# 登录 OpenAI Codex
uv run python -m poller.main --login codex

# 登录 Claude Code
uv run python -m poller.main --login claude

# 登录 Kimi
uv run python -m poller.main --login kimi

# 登录 MiniMax
uv run python -m poller.main --login minimax
```

每个命令会弹出独立 Edge 浏览器窗口，手动完成登录后，回到终端按 **Enter** 保存登录态。

### 4. 手动抓取与查看

```bash
# 抓取所有启用的 provider
uv run python -m poller.main --oneshot

# 查看结果
uv run python -m poller.main --status

# JSON 格式
uv run python -m poller.main --status --json
```

---

## 配置说明

### Plasmoid 配置面板（推荐）

右键小部件 → **配置**，包含四个标签页：

| 标签页 | 配置项 | 说明 |
|--------|--------|------|
| **General** | 界面刷新间隔 | Plasmoid 多久重新读取一次 data.json（默认 60 秒） |
| | 数据过期阈值 | 超过此时间未更新显示 "⚠ 数据已过期"（默认 600 秒） |
| **Data Polling** | 启用数据抓取 | 是否启用 systemd 定时抓取 |
| | 抓取间隔 | 自动抓取间隔（默认 300 秒） |
| | 数据提供商 | 勾选要监控的平台，**即时生效** |
| **Display** | 显示模式 | 0=5h+7d 都显示 / 1=仅 5h / 2=仅 7d |
| | 紧凑标签 | 面板上是否显示 provider 字母（C/D/K/M） |
| | 最大显示数 | 紧凑模式最多显示几个 provider |
| **Advanced** | 自定义数据路径 | 自定义 data.json 位置 |
| | 配色方案 | 默认 / 色盲友好 / 自定义 |
| | 自定义颜色 | 各阈值区间的颜色（#RRGGBB 格式） |

**Data Polling 标签页中的登录命令：**
每个提供商右侧显示对应的登录命令（如 `uv run python -m poller.main --login codex`），点击「复制」可直接粘贴到终端执行。

### 配置文件（自动管理）

`~/.config/show-ai-usage/config.toml` 由 Plasmoid 自动同步，一般无需手动编辑：

```toml
[general]
interval = 300
enabled_providers = ["codex", "claude", "kimi", "minimax"]

[paths]
data_dir = "~/.local/share/show-ai-usage"
browser_data_dir = ""  # 空 = 使用 XDG 默认

[locale]
timezone = ""  # 空 = 自动检测
```

**CLI 参数覆盖：**
```bash
# 临时修改（不影响配置文件）
uv run python poller/main.py --oneshot --interval 600 --providers codex claude
```

---

## CLI 命令参考

```bash
# 登录（打开有头浏览器手动登录）
uv run python poller/main.py --login [provider]

# 一次性抓取所有数据
uv run python poller/main.py --oneshot
uv run python poller/main.py --oneshot --providers codex claude

# 守护模式（持续轮询）
uv run python poller/main.py --daemon --interval 300

# 查看最新缓存数据
uv run python poller/main.py --status
uv run python poller/main.py --status --json

# 调试模式（有头浏览器 + 页面内容保存到 /tmp/）
uv run python poller/main.py --debug --providers codex

# 配置管理
uv run python poller/main.py --init-config
uv run python poller/main.py --show-config
uv run python poller/main.py --show-config --interval 600

# 帮助
uv run python poller/main.py --help
```

---

## 自动定时抓取（systemd timer）

### 安装

```bash
mkdir -p ~/.config/systemd/user/
rm -f ~/.config/systemd/user/show-ai-usage.service
rm -f ~/.config/systemd/user/show-ai-usage.timer

# 替换 @@PROJECT_DIR@@ 为实际路径后写入
sed "s|@@PROJECT_DIR@@|$PWD|g" systemd/show-ai-usage.service \
    > ~/.config/systemd/user/show-ai-usage.service

cp systemd/show-ai-usage.timer ~/.config/systemd/user/

systemctl --user daemon-reload
systemctl --user enable --now show-ai-usage.timer
```

或者直接用安装脚本：

```bash
./scripts/install.sh
```

### 查看状态

```bash
# timer 状态
systemctl --user status show-ai-usage.timer
# → Active: active (waiting)
# → Trigger: 5分钟后自动触发

# 手动触发一次
systemctl --user start show-ai-usage.service

# 查看抓取日志
journalctl --user -u show-ai-usage.service --since "5 min ago"
```

### 卸载

```bash
systemctl --user stop show-ai-usage.timer
systemctl --user disable show-ai-usage.timer
rm -f ~/.config/systemd/user/show-ai-usage.service
rm -f ~/.config/systemd/user/show-ai-usage.timer
systemctl --user daemon-reload
```

或者用卸载脚本：

```bash
./scripts/uninstall.sh
```

---

## Plasmoid 小部件

### 安装

```bash
kpackagetool6 --type Plasma/Applet --install package/
```

### 升级（修改 QML 后）

```bash
kpackagetool6 --type Plasma/Applet --upgrade package/
```

### 预览调试

```bash
# 注意：QML XHR 读取本地文件需要此环境变量
env QML_XHR_ALLOW_FILE_READ=1 plasmawindowed showaiusage
```

### 添加到面板

1. 右键桌面 → 添加小部件
2. 搜索 "AI Usage Monitor"
3. 拖拽到面板上

### 配置

右键 Plasmoid → 配置（Configure），包含四个标签页：

- **General：** 界面刷新间隔、数据过期阈值
- **Data Polling：** 启用/禁用数据抓取、抓取间隔、选择监控的 AI 平台（带登录命令复制按钮）
- **Display：** 显示模式、紧凑标签、最大显示数
- **Advanced：** 自定义数据路径、配色方案

### Plasmoid 预览效果

面板紧凑模式：

```
  ████████░░   ██░░░░░░░   ████████░   ████░░░░░
  Codex 99%    Claude 15%   Kimi 85%    MiniMax 40%
```

弹出完整面板：

```
┌─────────────────────────────────────────┐
│ 🤖 AI 订阅用量追踪                       │
│ 更新时间: 3 分钟前                       │
├─────────────────────────────────────────┤
│ ┌─ OpenAI Codex ──────────────────────┐ │
│ │ 5h: ████████████████████░░░  99%   │ │
│ │ 7d: ░░░░░░░░░░░░░░░░░░░░░   0%    │ │
│ │ 剩余额度: 0                         │ │
│ │ 重置: 2026年6月12日 21:14           │ │
│ └────────────────────────────────────┘ │
│ ┌─ Claude Code ──────────────────────┐ │
│ │ 5h: ███░░░░░░░░░░░░░░░░░░░  15%   │ │
│ │ 7d: ██████████████████░░░░  85%   │ │
│ └────────────────────────────────────┘ │
│                         [ 🔄 刷新 ]   │
└─────────────────────────────────────────┘
```

---

## 颜色编码

| 颜色 | 使用率 | QML 颜色值 | 含义 |
|------|--------|-----------|------|
| 🟢 绿色 | 0% – 50% | `#4CAF50` | 健康，无需关注 |
| 🟡 黄色 | 50% – 80% | `#FFC107` | 注意，已过半 |
| 🟠 橙色 | 80% – 95% | `#FF9800` | 警告，即将限额 |
| 🔴 红色 | 95% – 100% | `#F44336` | 危险，很可能已被限速 |

---

## 支持的订阅与数据来源

| 提供商 | 订阅/计划 | 追踪内容 | 数据端点 |
|--------|----------|---------|---------|
| **OpenAI Codex** | ChatGPT Plus / Pro / Codex | 5小时滚动使用率、7天滚动使用率、剩余额度、重置时间 | [chatgpt.com/codex/.../analytics](https://chatgpt.com/codex/cloud/settings/analytics) |
| **Claude Code** | Claude Pro / Max / Team | 5小时使用率、7天周使用率、剩余配额、重置时间 | [claude.ai/new#settings/usage](https://claude.ai/new#settings/usage) |
| **Kimi** | Kimi 订阅计划 | 使用量、剩余额度、重置时间 | [kimi.com/code/console](https://www.kimi.com/code/console) |
| **MiniMax** | Token Plan (Plus / Max / Ultra) | 5小时滚动额度、7天滚动额度、剩余订阅积分 | [platform.minimaxi.com/console/usage](https://platform.minimaxi.com/console/usage) |

### 关于 Kimi / MiniMax / Claude 直抓 API（第一阶段）

> **阶段限制**：目前 **Kimi、MiniMax 与 Claude Code** 支持直接 API 抓取；**OpenAI Codex 仍保持 browser-backed（基于浏览器）抓取路径**，未提供直抓模式。

| 项 | 说明 |
|----|------|
| **Kimi 凭据** | `KIMI_CODE_ACCESS_TOKEN`（环境变量）或 `kimi_code_access_token`（`[general]` 配置） |
| **MiniMax 凭据** | `MINIMAX_API_KEY`（环境变量）或 `minimax_api_key`（`[general]` 配置） |
| **MiniMax 接口地址** | `MINIMAX_API_BASE_URL` / `minimax_api_base_url`，默认 `https://api.minimax.io`，可选 `https://api.minimaxi.com` |
| **Claude 凭据** | `CLAUDE_CODE_ACCESS_TOKEN`（环境变量）或 `claude_code_access_token`（`[general]` 配置）；未设置时读取 `~/.claude/.credentials.json` 中 `claudeAiOauth.accessToken`（或 `access_token`） |
| **直抓失败回退** | 由 `direct_fetch_browser_fallback` 控制，默认 `false`；为 `true` 时直抓失败会回退到浏览器抓取 |
| **MiniMax 积分余额** | 直抓返回的“mmx quota”/订阅积分与浏览器端一致，但第一阶段不区分订阅积分、充值积分、赠送积分 |

未配置对应凭据时，Claude / Kimi / MiniMax 直抓会报告缺少凭据；只有开启 `direct_fetch_browser_fallback = true` 时才会回退到浏览器抓取（与 Codex 一致）。`--show-config` 输出会自动脱敏这些凭据字段，避免泄露。

---

### Claude 直抓 API 架构（第一阶段）

Claude Code 除了浏览器抓取路径外，还支持直接调用 Anthropic 的 OAuth usage 端点。该端点**未经 Anthropic 官方文档公开，属于逆向工程所得，可能随时变更**，不保证长期稳定。

**端点与请求头**

- 端点：`https://api.anthropic.com/api/oauth/usage`
- 方法：`GET`
- 头部：
  - `Authorization: Bearer <oauth-access-token>`
  - `anthropic-beta: oauth-2025-04-20`
  - `Accept: application/json`
  - `User-Agent: show-ai-usage-poller/1.0`

**凭据解析顺序**

`_resolve_token()` 按以下顺序查找可用的 OAuth access token（第一个非空值生效）：

1. `config.claude_code_access_token`（对应环境变量 `CLAUDE_CODE_ACCESS_TOKEN`）
2. `~/.claude/.credentials.json` 中 `claudeAiOauth.accessToken`
3. `~/.claude/.credentials.json` 中 `claudeAiOauth.access_token`
4. `~/.claude/.credentials.json` 顶层 `accessToken`
5. `~/.claude/.credentials.json` 顶层 `access_token`

注意：第一阶段不会使用 `refreshToken` 刷新 access token；token 过期后需要重新登录 Claude Code 或手动更新配置。

**响应解析**

返回的 JSON 中：

- `five_hour.utilization` → `UsageData.window_5h_percent`（已用百分比，clamp 到 0–100）
- `five_hour.resets_at`（ISO 8601）→ 经 `_format_iso_reset_time()` 转换为 `UsageData.reset_5h`
- `seven_day.utilization` → `UsageData.window_7d_percent`
- `seven_day.resets_at`（ISO 8601）→ 经 `_format_iso_reset_time()` 转换为 `UsageData.reset_7d`

其它字段（如按模型细分的 `seven_day_sonnet`、`seven_day_opus`，以及 `extra_usage` 等）第一阶段暂不解析。

**ISO 重置时间转换**

`_format_iso_reset_time()` 接收带时区或 `Z` 结尾的 ISO 8601 时间，计算与 UTC 当前的差值，输出与现有 `format_reset_time()` 一致的中文相对时间，例如：

- `2026-06-13T10:00:00+00:00` → `2小时后重置`
- 已过期或不足 1 小时 → `即将重置`

**回退行为**

`fetch_direct()` 在缺少凭据、网络错误、鉴权失败或解析失败时返回带 `error` 字段的 `UsageData`，错误信息中不会包含 token 或上游响应体。当 `direct_fetch_browser_fallback = true` 时，poller 会再尝试浏览器抓取路径；默认 `false` 时直接上报错误。

## Provider 实现详解

每个 Provider 继承 `BaseProvider`，必须实现两个成员：

```python
class MyProvider(BaseProvider):
    @property
    def name(self) -> str:
        return "myprovider"

    def fetch(self, context: BrowserContext) -> UsageData:
        page = context.new_page()
        try:
            # 1. 导航到用量页面
            page.goto("https://...", ...)
            # 2. 等待页面加载（绕过 Cloudflare 等）
            self._wait_for_real_page(page)
            # 3. 解析页面文本提取数据
            raw_text = page.evaluate("document.body?.innerText")
            # 4. 正则匹配百分比、额度、重置时间
            # 5. 返回 UsageData
            return UsageData(provider="myprovider", ...)
        finally:
            page.close()
```

### Cloudflare 挑战处理

所有 Provider 共享 `_wait_for_real_page()` 方法：

```python
@staticmethod
def _wait_for_real_page(page: Page) -> None:
    deadline = time.time() + 45  # 最多等 45 秒
    while time.time() < deadline:
        title = page.title()
        # 挑战页面的标题固定为这些值
        if title not in {"请稍候…", "Just a moment...", "Please wait...", ""}:
            return
        time.sleep(1.5)
```

### 文本解析策略

每个 Provider 的 `_parse_from_text()` 使用多层 fallback：

1. **精确中文匹配**：`5\s*小?\s*时[^%\n]{0,200}?(\d+\.?\d*)\s*%`
2. **英文匹配**（Claude/MiniMax 等英文 UI）：`"You've used X%"`
3. **通用百分比 fallback**：找到页面中前两个 `X%` 格式的值
4. **DOM fallback**：扫描所有 `progress`、`[role=progressbar]`、`[class*=usage]` 等元素

### 各 Provider 数据提取要点

每个 AI 提供商后台展示的数据语义不同，提取策略需要针对页面结构定制：

#### Codex（chatgpt.com）

```text
5 小时使用限额
99%
剩余                    ← 标注"剩余"，是剩余百分比
重置时间：9:25

每周使用限额
0%
剩余                    ← 标注"剩余"，同样为剩余百分比
重置时间：2026年6月12日 21:14

剩余额度
0                       ← 这是剩余额度数值（非百分比）
```

- **数据类型**：页面标的是 **剩余百分比**，需转换为使用百分比：`已用 = 100 - 剩余`
- **`reset_5h`**：取自第一个"重置时间"（如 `2026年6月10日 3:53`，取决于浏览器时区）
- **`reset_7d`**：取自第二个"重置时间"（如 `2026年6月12日 15:14`，绝对时间）
- **时区敏感性**：Codex 的重置时间格式受浏览器 `timezone_id` 影响。北京时区下只显示 `9:25`（短时间格式），布鲁塞尔时区下显示完整日期 `2026年6月10日 3:53`。必须确保浏览器时区与用户实际时区一致，否则所有重置时间都会偏差

#### Claude（claude.ai）

```text
Plan usage limits
Pro
Current session
Starts when a message is sent
0% used                  ← 英文 UI，"Current session" = 5h 窗口
Weekly limits
Learn more about usage limits
All models
Resets Tue 5:00 AM
11% used                 ← "Weekly limits" = 7d 窗口
```

- **UI 语言**：Claude 页面始终渲染英文（不受浏览器 locale 影响），不要用中文模式解析
- **5h 窗口**：寻找 `Current session … X% used` 模式
- **7d 窗口**：寻找 `Weekly limits … X% used` 模式
- **`reset_5h`**：Claude 页面 **只在 5h 用量 > 0% 时**才显示对应的 5h 重置时间。用量为 0% 时该字段为 `null`（页面根本没有渲染重置时间），这是正常行为，不是解析遗漏
- **`reset_7d`**：`Resets Tue 5:00 AM` 格式，提取 `Tue 5:00 AM`
- **时区敏感性**：Claude 的 `reset_7d` 受浏览器 `timezone_id` 影响。北京时区显示 `Tue 5:00 AM`，布鲁塞尔时区显示 `Mon 11:00 PM`。必须与用户实际时区一致
- **导航注意**：目标 URL 使用 hash fragment（`/new#settings/usage`），必须**一步导航到完整 URL**，两步导航（先 home 再 hash）会导致 SPA 不处理路由变更

#### MiniMax（platform.minimaxi.com）

```text
5h 限额
31 分钟后重置            ← 重置倒计时
总额度 100%              ← 总额度（不是使用量，忽略）
已用 0%                  ← 实际使用，这才是目标值
周限额
4 天 19 小时后重置
总额度 150%              ← 周总额度 150%（注意：不是 100%）
已用 54%                 ← 实际使用
积分余额
订阅积分 + 充值积分 + 赠送积分 · 订阅配额用完后自动使用  ← 描述性文字，非数值
```

- **关键区别**：每个限额区间有两行百分比——"总额度 X%"（总配额）和"已用 X%"（实际使用）。必须同时提取两者并**归一化**：`normalized% = 已用 / 总额度 × 100`
- **总额度不是 100%**：周限额总额度是 150%，54% 已用 → 归一化为 `54 × 100 / 150 = 36%`
- **`reset_5h`**：取自 5h 限额区的倒计时（如 `10 分钟后重置`）
- **`reset_7d`**：取自周限额区的倒计时（如 `4 天 19 小时后重置`），注意是复合时长，正则需匹配从第一个数字到"重置"的完整文本（`\d[\d\s天小时分分钟hms]*\s*(?:后)?\s*(?:重置|到期)`），不能用只捕获一个数字的模式

#### Kimi（kimi.com）

```text
本周用量
更多额度
1%                     ← 本周用量百分比
163 小时后重置          ← 重置倒计时（"重置"在句尾）

频限明细
更多额度
5%                     ← 频限百分比
4 小时后重置            ← 重置倒计时
```

- **两个区间**：页面展示"本周用量"和"频限明细"两个独立区间，分别有各自的百分比和重置时间
- **`reset_5h`**：取自"频限明细"区的倒计时（较短，如 `4 小时后重置`）
- **`reset_7d`**：取自"本周用量"区的倒计时（较长，如 `163 小时后重置`）

### 常见正则陷阱：`\s*` 跨行问题

解析重置时间时，初始模式写为：

```python
re.search(r"(?:重置|到期|刷新)\s*[:：]?\s*([^\n]+)", text)
```

**问题**：`\s*` 在 Python regex 中匹配空白字符（包括换行符）。当"重置"位于行尾时，`\s*` 会消费后续的空白行，导致 `([^\n]+)` 捕获到下一行的无关内容（如 Kimi 的"频限明细"或 MiniMax 的"总额度 100%"）。

**解决方案**：改为从数字开头反向匹配：

```python
re.search(r"(\d+\s*(?:分钟?|小时?|天)\s*(?:后)?\s*(?:重置|到期))", text)
```

---

## 开发指南

### Plasmoid 面板布局陷阱

在 Plasma 6 面板中调整 CompactRepresentation 尺寸时，有三个常见陷阱：

#### 1. Layout 属性必须加在 `PlasmoidItem`，而不是 CompactRepresentation 内部

面板的布局引擎（RowLayout）直接管理的是 `PlasmoidItem`，而不是 CompactRepresentation 的根 Item。

```qml
// ✅ 正确：加在 main.qml 的 PlasmoidItem 上
PlasmoidItem {
    Layout.minimumWidth:  4 * Kirigami.Units.gridUnit * 3 + 3 * Kirigami.Units.smallSpacing
    Layout.preferredWidth: 4 * Kirigami.Units.gridUnit * 4 + 3 * Kirigami.Units.smallSpacing
    ...
}

// ❌ 无效：加在 CompactRepresentation.qml 的根 Item 上
Item {
    Layout.minimumWidth: ...   // 这一层不是面板 RowLayout 的直接子节点，面板忽略它
}
```

CompactRepresentation 的根 Item 上的 `Layout.*` 属性只作用于其父容器（Plasma 内部的 Loader/AppletItem），不会直接传递给面板的 RowLayout。`implicitWidth` 才会被 Plasma 内部机制传播，但 `Layout.minimumWidth` 等必须在 `PlasmoidItem` 一级设置。

#### 2. `implicitWidth` 必须是静态值，不能依赖运行时变量

Plasma 面板在 **小部件首次加载时** 评估 `implicitWidth`，并据此为其分配面板空间。如果此时 `implicitWidth` 依赖的变量还是初始值（如 `providers.length = 0` 或 `height = 0`），面板会锁定一个很小的宽度。**后续 `implicitWidth` 发生变化时，面板通常不会重新布局**。

```qml
// ❌ 错误：依赖 providers.length（初始为 0 → implicitWidth = 0 → 面板分配 0px）
implicitWidth: providers.length * _pillW + ...

// ❌ 错误：依赖 height（初始为 0 → _pillH = 0 → implicitWidth = 0）
readonly property real _pillH: height * 0.72
implicitWidth: 4 * _pillH * 3.2 + ...

// ✅ 正确：只用主题常量（gridUnit、smallSpacing 在 QML 启动时即固定）
implicitWidth: 4 * Kirigami.Units.gridUnit * 4 + 3 * Kirigami.Units.smallSpacing
```

`Kirigami.Units.gridUnit` 和 `Kirigami.Units.smallSpacing` 来自主题，在 QML 引擎启动时即为固定值，可以安全地用于 `implicitWidth`。

#### 3. 修改 QML 文件后需重启 plasmashell

Plasma 在启动时将 QML 文件编译缓存，运行期间**不会热重载**。

```bash
# 1. 升级已安装的 Plasmoid（从 package/ 目录同步到 ~/.local/share/plasma/plasmoids/）
kpackagetool6 --type Plasma/Applet --upgrade package/

# 2. 重启 plasmashell 使新 QML 生效
plasmashell --replace &
```

如果跳过第二步，即使文件已更新，运行中的 plasmashell 仍在使用旧的编译缓存，改动不会有任何效果。

#### 4. Tooltip 闪烁：不要在 CompactRepresentation 内用 `Controls.ToolTip`

在 Plasma 面板中，`Controls.ToolTip`（Qt Quick Controls 2 的 Popup 机制）会产生持续闪烁，根本原因是：

> Popup 出现时，其内部 Overlay 层会短暂拦截鼠标 hover 事件，导致触发 tooltip 的 `HoverHandler.hovered` 瞬间变为 `false` → tooltip 关闭 → hover 恢复 → 再次打开 → 循环。

这个循环无法通过加大 `delay`/`timeout`、改用 `HoverHandler`（替代 `MouseArea.containsMouse`）或增加 Timer 缓冲彻底解决，只是减慢了闪烁频率。

`PlasmaExtras.ToolTipArea`（Plasma 5 的传统方案）在 Plasma 6 的 `org.kde.plasma.extras` 中**已不存在**，不可用。

**正确做法：使用 `PlasmoidItem` 的内置 Tooltip 属性**

在 `main.qml` 的 `PlasmoidItem` 上设置 `toolTipMainText` / `toolTipSubText`，Plasma Shell 会用自己的 tooltip 窗口渲染，该窗口位于面板之外（正确显示在面板上方或下方），完全不参与 widget 内部的鼠标事件，不会闪烁。同时这也会覆盖 metadata 中自动生成的 "插件名 + 描述" 默认 tooltip：

```qml
// main.qml
PlasmoidItem {
    // 覆盖 metadata 默认 tooltip，替换为实时数据内容
    toolTipMainText: "AI 用量"
    toolTipTextFormat: Text.RichText
    toolTipSubText: {
        if (!providers || providers.length === 0)
            return errorMessage || "等待数据…"
        return providers.map(function(p) {
            var v5h = Math.round(Number(p.window_5h_percent) || 0)
            var v7d = Math.round(Number(p.window_7d_percent) || 0)
            return "<b>" + providerName(p) + "</b><br/>"
                 + "5小时: " + v5h + "%  " + (p.reset_5h || "–") + "<br/>"
                 + "7天:    " + v7d + "%  " + (p.reset_7d || "–")
        }).join("<br/>")
    }
}
```

`CompactRepresentation` 内不需要任何 tooltip 代码。

---

### 调试 Provider 的页面结构

```bash
# 打开有头浏览器 + 保存页面内容到 /tmp/show-ai-usage-debug/
uv run python poller/main.py --debug --providers claude
```

这会在 `/tmp/show-ai-usage-debug/` 下生成：
- `claude.html` — 完整页面 HTML
- `claude.txt` — 页面的纯文本内容
- `claude.png` — 页面截图

用这些文件分析页面结构，调整 `_parse_from_text()` 中的正则表达式。

### 添加新 Provider

1. 在 `poller/providers/` 下新建文件（如 `deepseek.py`）
2. 继承 `BaseProvider`，实现 `name`（返回 `"deepseek"`）和 `fetch(context)`
3. 在 `poller/providers/__init__.py` 的 `_get_registry()` 中注册
4. 在 `poller/main.py` 的 `LOGIN_URLS` 中添加登录入口
5. 在 `poller/main.py` 的 `PROVIDER_URLS` 中添加调试 URL
6. 在 `package/contents/ui/FullRepresentation.qml` 的 `displayName` 映射中添加显示名
7. 在 `package/contents/ui/config/PollingConfig.qml` 的 `providerList` 中添加新提供商
8. 在 `package/contents/ui/main.qml` 的 `_tipName` 映射中添加显示名

### 本地测试

```bash
# 单元测试风检查
uv run python -c "from poller.providers import get_enabled_providers; print(get_enabled_providers(['codex', 'claude', 'kimi', 'minimax']))"

# 配置转储
uv run python poller/main.py --show-config

# Plasmoid 预览
env QML_XHR_ALLOW_FILE_READ=1 plasmawindowed showaiusage
```

### 安装脚本测试

```bash
# 备份现有配置后测试
bash -n scripts/install.sh    # 语法检查
bash -n scripts/uninstall.sh  # 语法检查
```

---

## 常见问题

### Q: 为什么数据抓取失败？

A：最常见的原因是登录态过期。重新运行 `--login <provider>` 登录即可。如果登录后仍然失败，使用 `--debug` 查看页面内容：

```bash
uv run python poller/main.py --debug --providers codex
```

查看 `/tmp/show-ai-usage-debug/codex.txt` 分析页面结构。

### Q: Plasmoid 不显示数据，只显示 "等待数据…"

A：可能的原因：
1. 还没有运行过 `--oneshot`，`data.json` 不存在
2. `QML_XHR_ALLOW_FILE_READ=1` 环境变量未设置（只在 `plasmawindowed` 时需要）
3. 数据文件路径不对——检查 `data.json` 的位置

### Q: systemd timer 没有自动触发

```bash
# 检查 timer 状态
systemctl --user status show-ai-usage.timer

# 手动触发一次看日志
systemctl --user start show-ai-usage.service
journalctl --user -u show-ai-usage.service
```

### Q: Cloudflare 挑战过不去

A：`_wait_for_real_page()` 最多等待 45 秒。如果 Cloudflare 持续拦截，可能需要调整：
1. 增加 `_CHALLENGE_TIMEOUT`
2. 检查 User-Agent 是否被识别为机器人
3. 尝试使用 `--debug` 查看页面标题

### Q: 如何只监控部分 Provider？

A：右键小部件 → 配置 → **Data Polling** → 勾选/取消勾选需要监控的平台。**显示端会即时过滤**，无需等待下次抓取。

也可以编辑 `~/.config/show-ai-usage/config.toml`：

```toml
enabled_providers = ["codex", "claude"]
```

或通过 CLI 临时指定：

```bash
uv run python poller/main.py --oneshot --providers codex
```

### Q: 卸载后小部件还显示在面板上？

A：`kpackagetool6 --remove` 只卸载 Plasmoid 定义，面板上的实例不会自动消失。需要：
1. 右键点击面板上的小部件 → **移除**
2. 或运行 `plasmashell --replace` 重启面板

### Q: 登录态保存在哪里？卸载后需要重新登录吗？

A：登录态保存在 `~/.local/share/show-ai-usage/browser-data/`（XDG 目录）。
- 标准卸载（`./uninstall.sh`）：**保留**登录态，重新安装后无需重新登录
- 完全清理（`./uninstall.sh --purge`）：**删除**登录态，需要重新运行 `--login`

---

## 许可

[MIT License](LICENSE)
