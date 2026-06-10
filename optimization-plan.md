# Show AI Usage — 项目优化方案

> 项目已基本跑通，以下是对配置参数、安装运行、卸载等环节的优化计划。

---

## 一、配置参数优化

### 1.1 新增配置项

| 配置 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `[general.log_level]` | string | `"INFO"` | 日志级别：DEBUG / INFO / WARNING / ERROR |
| `[general.concurrent]` | bool | `false` | 是否启用并发抓取（多个 provider 并行）|
| `[general.provider_timeout]` | int | `60` | 单个 provider 抓取超时（秒）|
| `[network.proxy]` | string | `""` | HTTP 代理地址，如 `"http://127.0.0.1:7890"` |
| `[network.browser_channel]` | string | `"msedge"` | 浏览器通道，可选 `"msedge"` / `"chrome"` / `"chromium"` |
| `[notifications.enabled]` | bool | `false` | 是否启用桌面通知 |
| `[notifications.warn_5h]` | int | `80` | 5h 用量超过此百分比时发送通知 |
| `[notifications.warn_7d]` | int | `80` | 7d 用量超过此百分比时发送通知 |
| `[locale.language]` | string | `"zh-CN"` | 浏览器 locale |

### 1.2 现有配置项改进

- **`enabled_providers` 默认值统一**：`config.py` 中 Pydantic 默认是 `["codex"]`，但 `--init-config` 生成的是全部四个，二者不一致。统一为全部四个。
- **`browser_data_dir` 默认路径迁移**：从项目目录下的 `browser-data/` 改为 `~/.local/share/show-ai-usage/browser-data/`，解除浏览器配置文件与项目目录的耦合。当前 browser-data 在项目内 gitignored，但卸载时 `--purge` 也无法清理。

---

## 二、安装流程优化

### 2.1 前置依赖检查

`install.sh` 增加执行前检查：

- `which msedge` 或 `which microsoft-edge-stable` — Edge 是否存在
- `which kpackagetool6` — Plasmoid 打包工具是否存在
- `which uv` — uv 包管理器是否存在
- `systemctl --user show-environment` — systemd --user 是否可用
- Playwright 浏览器是否已安装，必要时自动执行 `uv run python -m playwright install chromium`

依赖缺失时给出明确的安装指引，而不是执行到一半报错。

### 2.2 安装脚本选项扩展

```bash
./scripts/install.sh                      # 标准安装
./scripts/install.sh --no-timer           # 仅安装 Plasmoid，不配置 systemd
./scripts/install.sh --dry-run            # 预检模式，只检查不执行
./scripts/install.sh --prefix ~/myapp     # 自定义项目安装目录（目前绑定 $PWD）
```

### 2.3 systemd 服务改进

**替换硬编码的 venv Python 路径**：

当前：
```ini
ExecStart=@@PROJECT_DIR@@/.venv/bin/python @@PROJECT_DIR@@/poller/main.py --oneshot
```

改为：
```ini
ExecStart=uv run --directory @@PROJECT_DIR@@ python poller/main.py --oneshot
```

这样不依赖 `.venv` 的路径结构，与手动执行方式一致，避免 uv 升级后服务中断。

**加入重启策略和日志标记**：

```ini
[Service]
Type=oneshot
ExecStart=uv run --directory @@PROJECT_DIR@@ python poller/main.py --oneshot
WorkingDirectory=@@PROJECT_DIR@@
User=%u
Restart=on-failure
RestartSec=60
StandardOutput=journal
StandardError=journal
```

**timer 间隔调整**：从 5 分钟改为 10 分钟（`OnUnitActiveSec=10min`），减少对 provider 页面不必要的请求压力。

### 2.4 安装后验证

安装脚本末尾增加自动检查：

- `systemctl --user is-active show-ai-usage.timer` — 确认 timer 已运行
- `kpackagetool6 --type Plasma/Applet --show showaiusage` — 确认 Plasmoid 已安装
- 可选执行一次 `uv run python poller/main.py --oneshot` 验证抓取链路是否通畅（带 `--dry-run` 标记时跳过）

---

## 三、卸载流程优化

### 3.1 --purge 增强

当前 `--purge` 不清理项目目录下的 `browser-data/` 和 `.venv/`。

优化方向：

```bash
./scripts/uninstall.sh                     # 标准卸载，保留数据和配置
./scripts/uninstall.sh --purge             # 清理所有：config + data + browser-data
./scripts/uninstall.sh --purge-all         # 清理所有 + 删除 .venv
```

项目内目录清理的安全策略：
- 只删除已知的特定子目录（`.venv/`、`browser-data/`），不碰其他文件
- 删除前打印明确的目录清单供用户确认
- 先检查项目目录是否仍然存在

### 3.2 安全保护

卸载前检查项目目录：

```bash
if [ ! -f "$PROJECT_DIR/pyproject.toml" ]; then
    echo "Warning: Project directory seems to have moved or been deleted."
    echo "systemd unit files will still be removed, but project files cannot be cleaned."
fi
```

### 3.3 回滚指引

卸载完成后打印反向操作命令，方便误操作后恢复：

```
To reinstall:
  git clone <repo> && cd show-ai-usage && ./scripts/install.sh
```

---

## 四、运行时优化

### 4.1 日志系统

当前全用 `print()`，排查问题困难。改为 Python `logging` 标准库：

- 日志写入 `~/.local/share/show-ai-usage/poller.log`
- systemd 模式下同时输出到 journald（作为 service 的 stdout）
- `--debug` 模式下输出到 stderr
- 日志按大小轮转（10MB × 3 份）
- 每个 provider 的抓取过程有完整的 trace 日志

### 4.2 并发抓取

当前 4 个 provider 顺序执行，每个约 15-30s，总耗时 1-2 分钟。用 `concurrent.futures` 并发：

```python
with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
    futures = {pool.submit(provider.fetch, context): provider for provider in providers}
    for future in concurrent.futures.as_completed(futures):
        data = future.result(timeout=config.provider_timeout)
```

注意：Playwright `BrowserContext` 不是线程安全的，需为每个 provider 创建独立的 `BrowserContext`（共享同一个 browser 实例）。

### 4.3 浏览器生命周期优化

当前每次 `--oneshot` 都完整启动/关闭 Edge 浏览器（约 3-5s 开销）：

- `--daemon` 模式下浏览器维持运行，循环抓取不重启
- `--oneshot` 缩短超时等待，失败快速跳过

### 4.4 数据 JSON schema 版本化

在 `data.json` 顶层添加 `schema_version` 字段，为后续兼容性升级做准备：

```json
{
  "schema_version": 1,
  "fetched_at": "...",
  "providers": [...]
}
```

### 4.5 错误恢复增强

- **独立超时控制**：每个 provider 有独立的抓取超时，一个 provider 卡住不影响其他
- **自动重试**：失败后等待 5 秒重试一次
- **错误分类**：区分"网络错误"、"登录过期"、"页面结构变化"等错误类型，上报更清晰
- **Plasmoid 端**：在 UI 上区分"暂无数据"和"数据过期"和"抓取失败"三种状态

---

## 五、当前优先级与工作量（旧版，见第九章更新版）

| 优先级 | 项目 | 工作量 | 影响 |
|--------|------|--------|------|
| P0 | 日志系统（print → logging） | 小 | 排障能力大幅提升 |
| P0 | `enabled_providers` 默认值统一 | 极小 | 消除行为不一致 |
| P0 | systemd 服务内用 `uv run` 替换硬编码 venv 路径 | 极小 | 避免 uv 升级后服务中断 |
| P1 | 前置依赖检查（install.sh） | 小 | 避免安装到一半失败 |
| P1 | 新增 network/notifications 配置项 | 中 | 提升适用场景 |
| P1 | systemd timer 间隔改为 10 分钟 | 极小 | 减少 provider 侧限流风险 |
| P2 | browser-data 移到 XDG 目录 | 中 | 解耦项目位置 |
| P2 | 并发抓取 | 中 | 抓取耗时从 1-2 分钟降到 20-30s |
| P2 | 安装后验证 | 小 | 安装成功率可见 |
| P3 | 安装/卸载 `--dry-run` 等选项 | 小 | 用户体验优化 |
| P3 | 桌面通知 | 中 | 用户主动感知配额 |
| P3 | JSON schema 版本化 | 小 | API 兼容性 |

---

## 六、实施建议

1. **先做 P0**：日志系统、默认值统一、systemd 路径修复 — 这三项风险最低、收益明确，可以立刻开始。
2. **再做 P1**：依赖检查、配置项扩展、timer 间隔调整 — 提升安装成功率和适用范围。
3. **最后 P2/P3**：并发抓取、browser-data 解耦、桌面通知等 — 需要更多测试，排在后面。

每个 P0/P1 任务可独立实施，互不阻塞，适合并行推进。

---

## 七、Plasmoid 打包发布

### 7.1 打包方式

当前只能通过 `kpackagetool6 --install package/` 从本地源码目录安装，无法分发。

Plasma 小部件的标准分发格式是 `.plasmoid` 文件（本质上是一个 ZIP 压缩包），Plasma 6 也支持 KPackage 格式的手工安装。

**方案：新增构建脚本**

```bash
./scripts/build-plasmoid.sh              # 生成 show-ai-usage-v0.1.0.plasmoid
./scripts/build-plasmoid.sh --output dist # 指定输出目录
```

构建脚本逻辑：
1. 从 `package/metadata.json` 读取版本号
2. 压缩 `package/` 目录为 `.plasmoid` ZIP 包（排除非必要文件）
3. 可选同时生成 SHA256 校验和

```bash
# 核心命令
cd package && zip -r ../dist/show-ai-usage-v0.1.0.plasmoid . \
    -x "*.git*" -x "*__pycache__*" -x "*.swp"
```

### 7.2 发布到 KDE Store

KDE 小部件可通过 [KDE Store](https://store.kde.org/) 分发，用户从"添加小部件"对话框即可搜索安装。

**发布步骤：**
1. 在 KDE Store 注册开发者账号
2. 在 metadata.json 中完善作者信息、截图 URL、捐赠链接等元数据：

```json
{
  "KPlugin": {
    "Authors": [{
      "Name": "...",
      "Email": "..."
    }],
    "Category": "Utilities",
    "Description": "...",
    "Icon": "utilities-system-monitor",
    "Id": "showaiusage",
    "License": "MIT",
    "Name": "AI Usage Monitor",
    "Version": "0.1.0",
    "Website": "https://github.com/your/project"
  },
  "X-Plasma-API-Minimum-Version": "6.0"
}
```

3. 上传 `.plasmoid` 包到 store.kde.org
4. 版本更新时在 metadata.json 中标记 `Version`，重新上传

**注意事项：**
- 上传后 KDE Store 审核可能需要几天
- 用户安装后，Plasma 内置的"Get New Widgets"功能会自动检查更新
- 包内不应包含 Python poller — 用户仍需通过 git clone + install.sh 安装后端。需要在 store 页面和包描述中清楚说明

### 7.3 Release 自动化（GitHub Actions）

```yaml
# .github/workflows/release-plasmoid.yml
on:
  push:
    tags: ["v*"]
jobs:
  build:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - run: ./scripts/build-plasmoid.sh --output dist
      - uses: softprops/action-gh-release@v2
        with:
          files: dist/*.plasmoid
```

每次打 `v0.1.0` 等标签时自动构建 `.plasmoid` 并附加到 GitHub Release。

### 7.4 版本管理规范

| 位置 | 当前问题 | 改进方案 |
|------|---------|---------|
| `package/metadata.json` | 有 `Version` 字段，但手动维护 | 发布脚本自动从 git tag 读取版本号注入 |
| `pyproject.toml` | 有 `version = "0.1.0"` | 与 plasmoid 版本同步，或统一到一个来源 |
| git tag | 无发布 tag | 遵循 `v0.1.0` / `v0.2.0` 语义化版本 |

建议统一版本号来源为 git tag，发布脚本自动提取并写入 metadata.json：

```bash
VERSION=$(git describe --tags --abbrev=0 2>/dev/null || echo "v0.1.0")
VERSION=${VERSION#v}  # 去掉 v 前缀
```

### 7.5 多 Plasma 版本兼容

当前仅支持 Plasma ≥ 6.0。如果将来需要在 Plasma 5 上运行：
- `X-Plasma-API-Minimum-Version` 设为 `"5.0"`（但 Plasma 5 的 API 不兼容）
- Plasma 5 中使用 `PlasmaCore.DataSource`（Plasma 6 用 `Plasma5Support.DataSource`）
- 建议保持 Plasma 6 独占，不引入向下兼容的复杂度

---

## 八、插件配置选项优化

### 8.1 当前配置现状

Plasmoid 右键 → 配置 只有两个选项：

| 配置项 | 类型 | 范围 | 默认值 |
|--------|------|------|--------|
| 界面刷新间隔（秒） | Int | 10–3600 | 60 |
| 数据过期阈值（秒） | Int | 60–86400 | 600 |

两个配置均通过 `kcfg` 框架自动绑定到 QML `Plasmoid.configuration.*`。配置变更后通过 Timer 的响应式绑定自动生效（`interval: (Plasmoid.configuration.refreshInterval || 60) * 1000`）。

### 8.2 新增配置项

在 `main.xml` 和 `GeneralConfig.qml` 中扩展：

| 配置项 | 类型 | 范围 | 默认值 | 说明 |
|--------|------|------|--------|------|
| `dataFilePath` | String | — | `auto` | 自定义 data.json 路径，`auto` = 使用 StandardPaths 默认值 |
| `displayMode` | Int (combo) | 0/1/2 | 0 | 显示模式：0=5h+7d 都显示，1=仅 5h，2=仅 7d |
| `showProviderLabels` | Bool | true/false | true | 紧凑模式下是否显示 provider 字母标签 |
| `compactMaxProviders` | Int | 1–8 | 4 | 紧凑模式最多显示多少个 provider（超出折叠） |
| `colorTheme` | Int | 0/1 | 0 | 配色方案：0=默认（绿/黄/橙/红），1=色盲友好 |
| `customColorLow` | String | — | `"#4CAF50"` | 低用量颜色（0–50%） |
| `customColorMid` | String | — | `"#FFC107"` | 中用量颜色（50–80%） |
| `customColorHigh` | String | — | `"#FF9800"` | 高用量颜色（80–95%） |
| `customColorCritical` | String | — | `"#F44336"` | 临界用量颜色（95–100%） |

**注意**：自定义颜色是进阶功能，默认不暴露在配置面板主界面，可通过"高级"折叠区域显示。

### 8.3 配置面板 UI 改进

当前配置面板（`GeneralConfig.qml`）布局简单，优化方向：

```
┌─ General ─────────────────────────────┐
│  界面刷新间隔:  [60] 秒              │
│  数据过期阈值:  [600] 秒              │
├─ Display ─────────────────────────────┤
│  显示模式:      [ 5h + 7d    ▼ ]     │
│  紧凑标签:      [✓] 显示字母标签      │
│  最大显示数:    [4] 个 provider       │
├─ Advanced ────────────────────────────┤
│  自定义数据路径: [auto          ]     │
│  ┌── Color Customization ───┐         │
│  │ [0–50%]   ■ [拾色器...]   │         │
│  │ [50–80%]  ■ [拾色器...]   │         │
│  │ [80–95%]  ■ [拾色器...]   │         │
│  │ [95–100%] ■ [拾色器...]   │         │
│  └──────────────────────────┘         │
└────────────────────────────────────────┘
```

实现方式：
- `GeneralConfig.qml` 用 `Kirigami.FormLayout` + 折叠区域（`Kirigami.OverlaySheet` 或 `Expandable`）
- 色盲友好方案：在 `colorTheme=1` 时使用预设的蓝/橙/红/紫配色，用户不可单独调整
- 自定义颜色仅在 `colorTheme=2`（自定义）时启用

### 8.4 配置变更即时生效

当前 Timer 依赖 `interval` 的响应式绑定：

```qml
Timer {
    interval: (Plasmoid.configuration.refreshInterval || 60) * 1000
    onTriggered: root.loadUsageData()
}
```

这已经能在配置变更时自动调整定时器间隔。但还有几个场景需要优化：

**1. 数据文件路径变更**

如果用户在配置中修改了 `dataFilePath`，需要重新触发一次数据加载：

```qml
onConfigurationChanged: {
    root.loadUsageData()
    // 如果 dataFilePath 变了，之前的 Timer 仍在用旧路径轮询
    // 需要确保 loadUsageData 使用最新的配置路径
}
```

**2. 显示模式变更即时刷新**

`displayMode`、`showProviderLabels` 等显示相关的配置变更后，FullRepresentation 和 CompactRepresentation 需要立刻重绘。在 `main.qml` 中监听：

```qml
onConfigurationChanged: {
    // 强制重新计算 providers 的绑定属性
    providers = usageData && usageData.providers ? usageData.providers : []
}
```

**3. 配置界面关闭时触发一次数据重载**

用户修改配置后关闭配置窗口，Plasmoid 应立刻用新配置刷新一次（而不是等到下一个 Timer 周期）：

```qml
// GeneralConfig.qml 或 main.qml 中
Plasmoid.configuration.configurationChanged.connect(function() {
    refreshTimer.restart()  // 立即重启 Timer，触发一次抓取
})
```

### 8.5 配置面板的国际化（i18n）

当前配置面板 UI 文字全部硬编码为中文。如果要发布到 KDE Store 面向国际用户，需要接入 Plasma 的 i18n 系统：

```qml
// GeneralConfig.qml
import org.kde.i18n as KDi18n

// 使用 i18n() 函数
Kirigami.FormData.label: i18n("Refresh interval (seconds):")
```

但当前 Plasmoid 面向中文用户为主，国际化可列为 P3 优先级。

### 8.6 配置面板单元测试

QML 配置面板的测试方式：
- 使用 `plasmawindowed showaiusage --config` 预览配置面板
- 修改配置值后，通过 `Plasmoid.configuration.*` 验证绑定是否正确
- 在 `Doc.md` 中补充配置面板的测试流程文档

---

## 九、优先级更新

更新后的优先级表（新增项以 `[新]` 标记）：

| 优先级 | 项目 | 工作量 | 影响 |
|--------|------|--------|------|
| P0 | 日志系统（print → logging） | 小 | 排障能力大幅提升 |
| P0 | `enabled_providers` 默认值统一 | 极小 | 消除行为不一致 |
| P0 | systemd 服务内用 `uv run` 替换硬编码 venv 路径 | 极小 | 避免 uv 升级后服务中断 |
| P1 | 前置依赖检查（install.sh） | 小 | 避免安装到一半失败 |
| P1 | 新增 network/notifications 配置项 | 中 | 提升适用场景 |
| P1 | systemd timer 间隔改为 10 分钟 | 极小 | 减少 provider 侧限流风险 |
| P1 | [新] 配置面板 UI 改进（分组、折叠高级选项） | 中 | 用户体验提升 |
| P1 | [新] 配置变更即时生效（onConfigurationChanged） | 小 | 用户操作反馈及时 |
| P2 | browser-data 移到 XDG 目录 | 中 | 解耦项目位置 |
| P2 | 并发抓取 | 中 | 抓取耗时从 1-2 分钟降到 20-30s |
| P2 | 安装后验证 | 小 | 安装成功率可见 |
| P2 | [新] 新增 Plasmoid 配置项（dataFilePath, displayMode, 颜色等）| 中 | 功能灵活度提升 |
| P2 | [新] Plasmoid 构建脚本（build-plasmoid.sh） | 小 | 可分发的基础 |
| P3 | 安装/卸载 `--dry-run` 等选项 | 小 | 用户体验优化 |
| P3 | 桌面通知 | 中 | 用户主动感知配额 |
| P3 | JSON schema 版本化 | 小 | API 兼容性 |
| P3 | [新] KDE Store 发布 + CI/CD 自动化 | 中 | 分发渠道打通 |
| P3 | [新] 配置面板国际化 i18n | 中 | 国际用户使用 |

## 十、实施建议（更新）

1. **先做 P0**：日志系统、默认值统一、systemd 路径修复 — 三项风险最低、收益明确。
2. **再做 P1**：依赖检查、配置项扩展、timer 间隔调整、**配置面板 UI 优化**、**配置变更即时生效** — 提升安装成功率和用户体验。
3. **P2 可并行**：并发抓取、Plasmoid 新配置项、构建脚本、browser-data 解耦 — 这几项互不依赖，可同时推进。
4. **最后 P3**：发布到 KDE Store、国际化、桌面通知 — 需要更多准备工作，适合作为里程碑。

每个 P0/P1 任务可独立实施，互不阻塞，适合并行推进。
