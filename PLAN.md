# SHOW AI USAGE — 开发计划

## 技术路线

**路线 A**: Python 后端 + QML 前端（Plasmoid）

```
┌─────────────────────────────────────────────────────┐
│                   KDE Plasma 6 Panel                 │
│  ┌──────────────────────────────────────────────┐   │
│  │  Plasmoid (QML + JavaScript)                 │   │
│  │  - 紧凑模式: 缩略进度条                       │   │
│  │  - 弹出模式: 完整表格 + 颜色编码               │   │
│  └──────────────┬───────────────────────────────┘   │
└─────────────────┬───────────────────────────────────┘
                  │ 读取 (定时轮询 JSON 文件)
                  ▼
┌─────────────────────────────────────────────────────┐
│  ~/.local/share/show-ai-usage/data.json              │
│  ~/.local/share/show-ai-usage/cache.db               │
└─────────────────────────────────────────────────────┘
                  ▲ 写入 (Python Poller)
┌─────────────────┴───────────────────────────────────┐
│  Python Poller (uv 管理的虚拟环境)                    │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌────────┐ │
│  │  Codex   │ │  Claude  │ │  Kimi   │ │MiniMax │ │
│  │ Provider │ │ Provider │ │ Provider│ │Provider│ │
│  └──────────┘ └──────────┘ └──────────┘ └────────┘ │
│         │          │          │          │          │
│         └──────────┴──────────┴──────────┘          │
│                      ▼                               │
│            Playwright (连接已有浏览器)                 │
└──────────┬──────────────────────────────────────────┘
           │ systemd timer 触发
           ▼
    systemd --user timer (show-ai-usage.timer)
    └── show-ai-usage.service
        └── uv run python poller/main.py --oneshot
```

## 目录结构

```
show_ai_usage_v2/
├── README.md
├── PLAN.md                          # 本文件
├── pyproject.toml                   # uv 管理 Python 项目
├── uv.lock                          # 依赖锁定
├── poller/
│   ├── __init__.py
│   ├── main.py                      # 入口: --oneshot / --daemon
│   ├── storage.py                   # JSON 读写 & 缓存策略
│   └── providers/
│       ├── __init__.py
│       ├── base.py                  # BaseProvider 抽象基类
│       └── codex.py                 # OpenAI Codex 实现
├── package/                         # Plasmoid 包
│   ├── metadata.json
│   └── contents/
│       ├── ui/
│       │   ├── main.qml             # 主界面
│       │   ├── CompactRepresentation.qml  # 面板紧凑显示
│       │   └── FullRepresentation.qml     # 弹出完整面板
│       └── config/
│           └── main.xml             # 配置界面 (可选)
├── scripts/
│   ├── install.sh                   # 安装脚本 (用户本地)
│   └── uninstall.sh                 # 卸载脚本
└── systemd/
    ├── show-ai-usage.service
    └── show-ai-usage.timer
```

## 开发阶段（6 步）

### 阶段 1：Python 项目初始化

- `uv init` 创建 `pyproject.toml`
- 添加依赖: `playwright`, `pydantic`（数据模型）
- 搭建 `poller/` 模块结构
- 实现 `BaseProvider` 抽象类

**BaseProvider 接口设计**:

```python
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime

@dataclass
class UsageData:
    provider: str           # "codex", "claude", ...
    window_5h_percent: float   # 0.0 - 100.0
    window_7d_percent: float   # 0.0 - 100.0
    remaining_credit: str | None  # 可选
    reset_in: str | None         # 可选, "4h 12m"
    fetched_at: datetime
    error: str | None = None

class BaseProvider(ABC):
    """所有 Provider 的基类"""
    @abstractmethod
    def fetch(self) -> UsageData:
        """执行抓取并返回结构化数据"""
        ...
```

**验证标准**: `uv run python -c "from poller.providers.base import UsageData; print('ok')"` 无报错。

### 阶段 2：Codex Provider

- 实现 Playwright 连接到用户已登录的 Chromium 浏览器
- 导航到 `https://chatgpt.com/codex/cloud/settings/analytics`
- 等待页面加载完成，解析 DOM 提取 5h / 7d 使用率
- 输出结构化的 UsageData
- 编写单次抓取验证脚本

**关键实现细节**:
- 通过 Playwright 的 `connect_over_cdp` 连接已有浏览器（需要用户先启动 Chrome/Chromium 并开启 remote debugging port）
- 或者直接启动 Chromium 并加载用户数据目录
- 需要处理登录态检测（如果未登录则报错提示）

**验证标准**: `uv run python -m poller.providers.codex` 能成功输出本次抓取结果。

### 阶段 3：Poller CLI

- `main.py` 实现 `--oneshot` 模式：一次性抓取所有启用的 Provider，写入 JSON
- `main.py` 实现 `--daemon` 模式：常驻后台按间隔轮询
- `storage.py` 实现 JSON 文件写入、读取、缓存有效期判断（5 分钟内不重复抓取）

**命令行**:

```bash
uv run python poller/main.py --login                  # 打开浏览器手动登录
uv run python poller/main.py --oneshot                # 一次性抓取所有 Provider
uv run python poller/main.py --oneshot --providers codex  # 只抓指定 Provider
uv run python poller/main.py --daemon --interval 300  # 守护模式（持续轮询）
uv run python poller/main.py --status                 # 显示最新缓存数据
uv run python poller/main.py --status --json          # JSON 格式输出
uv run python poller/main.py --debug                  # 调试模式（有头浏览器）
```

**验证标准**: `uv run python poller/main.py --oneshot` 生成 `~/.local/share/show-ai-usage/data.json`，内容格式正确。

### 阶段 4：systemd 单元文件

- 编写 `show-ai-usage.service`（调用 `uv run` 执行 poller）
- 编写 `show-ai-usage.timer`（默认每 5 分钟触发一次）
- 安装到 `~/.config/systemd/user/`
- `systemctl --user enable --now show-ai-usage.timer`

**验证标准**: `systemctl --user status show-ai-usage.timer` 显示 active，数据文件按预期更新。

### 阶段 5：Plasmoid 骨架

- `metadata.json` 配置小部件元信息
- `main.qml` + `CompactRepresentation.qml` + `FullRepresentation.qml`
- 紧凑模式：显示各 Provider 的缩略进度条，颜色编码
- 弹出模式：完整表格，Provider 标签切换
- 使用 `plasmapkg2 --install` 安装（用户本地）
- 使用 `plasmawindowed` 开发调试

**颜色编码规则**:

| 颜色 | 使用率 | QML 颜色值 |
|------|--------|-----------|
| 🟢 绿色 | 0% - 50% | `#4CAF50` |
| 🟡 黄色 | 50% - 80% | `#FFC107` |
| 🟠 橙色 | 80% - 95% | `#FF9800` |
| 🔴 红色 | 95% - 100% | `#F44336` |

**验证标准**: `plasmawindowed showaiusage` 能弹出窗口显示示例数据。

### 阶段 6：Widget 对接数据

- QML 通过 JavaScript 读取本地 JSON 文件
- 定时刷新（默认每 60 秒重新读取）
- 数据为空或过期时显示 "等待数据..." 或 "请先运行 Poller"
- 完善设置页面（选择启用的 Provider、刷新间隔等）

**验证标准**: Plasmoid 能正确读取 `data.json` 并渲染真实的 Codex 使用数据。

## 安装 & 卸载脚本设计

### 安装脚本 (`scripts/install.sh`)

```bash
#!/usr/bin/env bash
# 所有安装路径均为用户本地，不涉及系统级修改

INSTALL_DIR="$HOME/.local/share/show-ai-usage"
DATA_DIR="$HOME/.local/share/show-ai-usage"
SYSTEMD_DIR="$HOME/.config/systemd/user"

# 1. 复制 Python 项目到 INSTALL_DIR (或原地创建 venv)
# 2. uv sync 安装依赖
# 3. 通过 kpackagetool6 --install 安装 Plasmoid (用户模式)
# 4. 复制 systemd 单元文件
# 5. systemctl --user daemon-reload
# 6. 提示用户启用 timer: systemctl --user enable --now show-ai-usage.timer
```

### 卸载脚本 (`scripts/uninstall.sh`)

```bash
#!/usr/bin/env bash
# 完整逆向操作

# 1. systemctl --user stop show-ai-usage.timer && systemctl --user disable show-ai-usage.timer
# 2. 删除 systemd 单元文件
# 3. kpackagetool6 --remove 卸载 Plasmoid
# 4. 递归删除 INSTALL_DIR
# 5. 可选: 删除 DATA_DIR 数据
# 6. systemctl --user daemon-reload
```

## 非侵入开发原则

1. **Python 依赖**: 全部在项目 `.venv` 内，`uv sync` 管理，不动系统 Python
2. **Plasmoid 调试**: 优先用 `plasmawindowed` 独立窗口调试，无需安装到面板
3. **Plasmoid 安装**: `kpackagetool6 --install` 用户模式，文件在 `~/.local/share/plasma/plasmoids/`
4. **systemd 单元**: 用户级 `systemctl --user`，文件在 `~/.config/systemd/user/`
5. **数据文件**: 在 `~/.local/share/show-ai-usage/`
6. **安装任何新工具前**: 需用户审核确认
