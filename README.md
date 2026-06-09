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
show_ai_usage_v2/
├── README.md                          # 本文件
├── PLAN.md                            # 开发计划文档
├── pyproject.toml                     # uv Python 项目配置
├── uv.lock                            # 依赖锁定文件
├── .gitignore                         # Git 忽略规则
├── .python-version                    # Python 版本声明
│
├── poller/                            # ═══ Python 后端 ═══
│   ├── __init__.py                    # 包标记
│   ├── main.py                        # CLI 入口 + 命令分发
│   ├── config.py                      # TOML 配置加载/合并/初始化
│   ├── storage.py                     # JSON 数据文件读写
│   ├── browser.py                     # 隔离 Edge 浏览器管理
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
│       └── ui/
│           ├── main.qml               # PlasmoidItem 入口 + XHR 数据加载 + Timer
│           ├── CompactRepresentation.qml  # 面板紧凑显示 (彩色圆角条)
│           ├── FullRepresentation.qml     # 弹出完整面板 (进度条+额度+设置)
│           └── config/
│               └── GeneralConfig.qml  # 配置表单 (刷新间隔+过期阈值 SpinBox)
│
├── systemd/                           # ═══ systemd 单元文件 ═══
│   ├── show-ai-usage.service          # Oneshot 服务 (含 @@PROJECT_DIR@@ 模板)
│   └── show-ai-usage.timer            # 定时器 (每 5 分钟)
│
├── scripts/                           # ═══ 安装脚本 ═══
│   ├── install.sh                     # 安装: uv sync + Plasmoid + systemd
│   └── uninstall.sh                   # 卸载: 停止 timer + 移除 Plasmoid
│
└── browser-data/                      # 隔离 Edge 浏览器配置文件
    ├── Default/                       # 浏览器默认配置 (含 cookies, 登录态)
    ├── Cookies                        # 登录 cookies (自动生成)
    └── ...                            # 其他 Edge 内部文件
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

- **XHR 数据加载：** `XMLHttpRequest` 请求 `file://` 协议的 `data.json`
- **定时刷新：** `Timer` 每 `Plasmoid.configuration.refreshInterval` 秒（默认 60）触发重新读取
- **配置响应：** `interval` 绑定采用 QML 反应式表达式，配置变更自动更新
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

kcfg 格式，定义两个配置项：

```xml
<entry name="refreshInterval" type="Int">
  <label>界面刷新间隔（秒）</label>
  <default>60</default>
  <min>10</min>
  <max>3600</max>
</entry>
<entry name="staleThreshold" type="Int">
  <label>数据过期阈值（秒）</label>
  <default>600</default>
  <min>60</min>
  <max>86400</max>
</entry>
```

#### `package/contents/config/config.qml` + `config/GeneralConfig.qml` — 配置面板

- `config.qml`：`ConfigModel` 定义"General"分类，指向 `config/GeneralConfig.qml`
- `GeneralConfig.qml`：`KCM.AbstractKCM` + `Kirigami.FormLayout`，两个 `SpinBox` 控件
- 使用 `property alias cfg_<name>` 自动绑定到 `Plasmoid.configuration.<name>`

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

1. 验证项目结构（`pyproject.toml` + `package/`）
2. `uv sync --project` 安装 Python 依赖
3. `kpackagetool6` 安装/升级 Plasmoid
4. `sed` 替换 `@@PROJECT_DIR@@` → 真实路径，复制 systemd 文件到 `~/.config/systemd/user/`
5. `systemctl --user daemon-reload`
6. `systemctl --user enable --now show-ai-usage.timer`
7. 显示安装摘要

#### `scripts/uninstall.sh` — 卸载脚本

- 停止并禁用 timer
- 删除 systemd 单元文件 + `daemon-reload`
- 卸载 Plasmoid
- 可选 `--purge` 删除 `~/.config/show-ai-usage` 和 `~/.local/share/show-ai-usage`

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

### 1. 克隆并安装依赖

```bash
git clone <仓库地址> show-ai-usage
cd show-ai-usage
uv sync
```

### 2. 初始化配置

```bash
uv run python poller/main.py --init-config
```

这会在 `~/.config/show-ai-usage/config.toml` 生成默认配置，默认启用全部 4 个 provider。

### 3. 登录各平台

每个平台需要先在隔离浏览器中登录一次，登录态会保存在 `browser-data/` 目录中：

```bash
# 登录 OpenAI Codex
uv run python poller/main.py --login codex

# 登录 Claude Code
uv run python poller/main.py --login claude

# 登录 Kimi
uv run python poller/main.py --login kimi

# 登录 MiniMax
uv run python poller/main.py --login minimax
```

每个命令会弹出独立 Edge 浏览器窗口，导航到对应平台的首页。手动输入账号密码完成登录后，回到终端按 **Enter** 保存登录态。

### 4. 手动抓取一次

```bash
# 抓取所有启用的 provider
uv run python poller/main.py --oneshot

# 只抓取指定 provider
uv run python poller/main.py --oneshot --providers codex claude
```

抓取过程：
1. 启动无头 Edge 浏览器
2. 依次访问各 provider 的用量页面
3. 等待页面加载（绕过 Cloudflare 挑战）
4. 解析页面文本提取数据
5. 写入 `~/.local/share/show-ai-usage/data.json`

### 5. 查看结果

```bash
# 可读格式
uv run python poller/main.py --status

# 输出示例：
#   codex
#     5h: 99%
#     7d: 0%
#     剩余额度: 0
#     重置: 2026年6月12日 21:14

# JSON 格式
uv run python poller/main.py --status --json
```

### 6. 安装 Plasmoid

```bash
kpackagetool6 --type Plasma/Applet --install package/
```

然后右键桌面 → 添加小部件 → 搜索 "AI Usage Monitor" → 拖到面板上。

---

## 配置说明

配置文件位于 `~/.config/show-ai-usage/config.toml`：

```toml
[general]
# 守护模式下的抓取间隔（秒，最小 30）
interval = 300

# 启用的 provider 列表
# 可用值: "codex", "claude", "kimi", "minimax"
enabled_providers = ["codex", "claude", "kimi", "minimax"]

[paths]
# 数据文件输出目录（可选）
# data_dir = "~/.local/share/show-ai-usage"

# 浏览器配置文件目录（可选，留空 = 项目 browser-data/）
# browser_data_dir = ""

[locale]
# 浏览器时区（IANA ID，如 "Europe/Brussels"）。
# 空值 = 自动检测系统时区。这会影响各平台页面中重置时间的显示。
# 如果重置时间与你的实际时区不符，请在此处手动指定。
# timezone = "Europe/Brussels"
```

**CLI 参数覆盖：** 任何 CLI 参数都会覆盖对应配置值：

```bash
# 临时修改间隔和 provider（不影响配置文件）
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

右键 Plasmoid → 配置（Configure）→ General：
- **界面刷新间隔（秒）：** 控制 Plasmoid 多久重新读取一次 data.json（默认 60）
- **数据过期阈值（秒）：** 超过此时间未更新数据显示 "⚠ 数据已过期" 警告（默认 600）

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

---

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

A：编辑 `~/.config/show-ai-usage/config.toml`，在 `enabled_providers` 中只保留需要的：

```toml
enabled_providers = ["codex", "claude"]
```

或者通过 CLI 临时指定：

```bash
uv run python poller/main.py --oneshot --providers codex
```

---

## 许可

[MIT License](LICENSE)
