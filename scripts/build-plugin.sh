#!/usr/bin/env bash
#
# build-plugin.sh — Build distributable plugin package
#
# Usage:
#   ./scripts/build-plugin.sh              # Build to dist/
#   ./scripts/build-plugin.sh --output dir # Build to custom directory
#   ./scripts/build-plugin.sh --version x  # Override version
#
set -euo pipefail

# ── Parse options ───────────────────────────────────────────────
OUTPUT_DIR="dist"
VERSION_OVERRIDE=""

while [[ $# -gt 0 ]]; do
    case "$1" in
        --output)
            if [[ -z "${2:-}" ]]; then echo "✗ --output requires a path argument"; exit 1; fi
            OUTPUT_DIR="$2"
            shift 2
            ;;
        --version)
            if [[ -z "${2:-}" ]]; then echo "✗ --version requires a version string"; exit 1; fi
            VERSION_OVERRIDE="$2"
            shift 2
            ;;
        -*)
            echo "✗ Unknown option: $1"
            echo "Usage: $0 [--output <dir>] [--version <version>]"
            exit 1
            ;;
        *)
            echo "✗ Unknown argument: $1"
            exit 1
            ;;
    esac
done

# ── Determine version ───────────────────────────────────────────
PROJECT_DIR="$(realpath "$(dirname "$0")/..")"
cd "$PROJECT_DIR"

# Normalize OUTPUT_DIR to absolute path
OUTPUT_DIR="$(realpath -m "$OUTPUT_DIR")"

if [[ -n "$VERSION_OVERRIDE" ]]; then
    VERSION="$VERSION_OVERRIDE"
elif git describe --tags --abbrev=0 &>/dev/null; then
    VERSION=$(git describe --tags --abbrev=0)
    VERSION=${VERSION#v}  # Remove 'v' prefix
else
    VERSION="0.1.0"
fi

echo "📦 Show AI Usage Plugin Builder"
echo "   Version: $VERSION"
echo "   Output:  $OUTPUT_DIR"
echo ""

# ── Update version in metadata.json ─────────────────────────────
echo "[1/5] Updating version in metadata.json ..."
METADATA_FILE="$PROJECT_DIR/package/metadata.json"
if [[ -f "$METADATA_FILE" ]]; then
    # Use Python to safely update JSON
    python3 -c "
import json
with open('$METADATA_FILE', 'r') as f:
    data = json.load(f)
data['KPlugin']['Version'] = '$VERSION'
with open('$METADATA_FILE', 'w') as f:
    json.dump(data, f, indent=2, ensure_ascii=False)
"
    echo "      ✓  Version set to $VERSION"
else
    echo "      ✗  metadata.json not found"
    exit 1
fi
echo ""

# ── Build Plasmoid package ──────────────────────────────────────
echo "[2/5] Building Plasmoid package ..."
PLASMOID_FILE="show-ai-usage-v${VERSION}.plasmoid"
mkdir -p "$OUTPUT_DIR"

cd "$PROJECT_DIR/package"
zip -r "$OUTPUT_DIR/$PLASMOID_FILE" . \
    -x "*.git*" \
    -x "*__pycache__*" \
    -x "*.swp" \
    -x "*.pyc"

cd "$PROJECT_DIR"
echo "      ✓  Built $PLASMOID_FILE"
echo ""

# ── Copy poller files ───────────────────────────────────────────
echo "[3/5] Copying poller files ..."
POLLER_DIR="$OUTPUT_DIR/poller"
mkdir -p "$POLLER_DIR"

# Copy Python package
cp -r poller "$POLLER_DIR/"

# Copy Python project files
cp pyproject.toml "$OUTPUT_DIR/"
cp uv.lock "$OUTPUT_DIR/" 2>/dev/null || true
cp .python-version "$OUTPUT_DIR/" 2>/dev/null || true

echo "      ✓  Poller files copied"
echo ""

# ── Copy install scripts ────────────────────────────────────────
echo "[4/5] Copying install scripts ..."
cp scripts/install.sh "$OUTPUT_DIR/"
cp scripts/uninstall.sh "$OUTPUT_DIR/"
cp -r systemd "$OUTPUT_DIR/"

echo "      ✓  Scripts copied"
echo ""

# ── Generate README for the package ─────────────────────────────
echo "[5/5] Generating package README ..."
cat > "$OUTPUT_DIR/README.txt" <<'README_EOF'
================================================================================
  Show AI Usage Plugin v${VERSION}
  KDE Plasma 6 AI 订阅用量监控插件
================================================================================

【功能简介】
  本插件是一个 KDE Plasma 6 任务栏小部件（Plasmoid），用于监控以下 AI 
  订阅服务的用量情况：
    - OpenAI Codex
    - Claude Code
    - Kimi
    - MiniMax

  插件通过 Playwright 自动化浏览器访问各平台的用量页面，提取数据后
  显示在任务栏上，帮助你实时掌握各服务的剩余配额。

================================================================================
【环境依赖】
================================================================================

  必需组件：
    1. KDE Plasma >= 6.0
       - 任务栏小部件运行环境
       - 包含 kpackagetool6 工具

    2. Python >= 3.11
       - 数据抓取脚本运行环境

    3. uv (Python 包管理器)
       - 安装地址: https://docs.astral.sh/uv/
       - 用于安装 Python 依赖和管理虚拟环境

    4. Microsoft Edge 浏览器
       - Playwright 使用 Edge 进行自动化浏览
       - 或者安装 Playwright 内置的 Chromium:
         uv run python -m playwright install chromium

    5. systemd --user
       - 用于后台定时抓取数据
       - 大多数现代 Linux 发行版已内置

  可选组件：
    - git: 用于从源码安装或更新

================================================================================
【安装步骤】
================================================================================

  方式一：从发布包安装（推荐）
  --------------------------------------------------------
    1. 解压发布包到任意目录，例如 ~/show-ai-usage/
    2. 打开终端，进入该目录
    3. 执行安装命令：

         ./install.sh

    4. 安装脚本会自动完成：
         - 检查系统依赖是否满足
         - 安装 Python 依赖 (uv sync)
         - 安装 KDE Plasma 小部件
         - 配置 systemd 定时任务（每 5 分钟自动抓取）

  方式二：从源码安装
  --------------------------------------------------------
    1. 克隆代码仓库：

         git clone <仓库地址> show-ai-usage
         cd show-ai-usage

    2. 执行安装命令：

         ./scripts/install.sh

================================================================================
【首次使用 - 登录各平台】
================================================================================

  注意: Plasmoid 小部件和 Python 轮询器是分开安装的——小部件通过
  kpackagetool6 安装到 ~/.local/share/plasma/plasmoids/，而 Python 项目
  留在你解压的目录里。因此所有 uv run python -m poller.main 命令都需要
  在项目目录下运行。

  首次使用前，需要在隔离浏览器中手动登录各 AI 平台：

    # 登录 OpenAI Codex
    uv run python -m poller.main --login codex

    # 登录 Claude Code
    uv run python -m poller.main --login claude

    # 登录 Kimi
    uv run python -m poller.main --login kimi

    # 登录 MiniMax
    uv run python -m poller.main --login minimax

  执行命令后会弹出浏览器窗口，手动输入账号密码完成登录，
  然后回到终端按 Enter 键保存登录态。

  登录态保存位置：
    ~/.local/share/show-ai-usage/browser-data/
    （包含 cookies、localStorage 等，与系统浏览器完全隔离）

================================================================================
【如何抓取数据】
================================================================================

  方式一：手动抓取（测试用）
  --------------------------------------------------------
    # 抓取所有已启用的平台
    uv run python -m poller.main --oneshot

    # 只抓取指定平台
    uv run python -m poller.main --oneshot --providers codex claude

  方式二：自动定时抓取（后台运行）
  --------------------------------------------------------
    安装时已自动配置 systemd 定时任务，每 5 分钟自动执行一次抓取。

    # 查看定时任务状态
    systemctl --user status show-ai-usage.timer

    # 手动触发一次抓取
    systemctl --user start show-ai-usage.service

    # 查看最近抓取日志
    journalctl --user -u show-ai-usage.service --since "10 min ago"

  方式三：通过小部件配置启用/禁用自动抓取
  --------------------------------------------------------
    右键点击任务栏小部件 → 配置 → Data Polling：
      - 启用/禁用数据抓取
      - 设置抓取间隔（默认 300 秒）
      - 选择要监控的 AI 平台

================================================================================
【数据存储位置】
================================================================================

  1. 抓取数据（JSON 格式）
     位置：~/.local/share/show-ai-usage/data.json
     说明：包含各平台的用量百分比、重置时间等信息

  2. 浏览器登录态
     位置：~/.local/share/show-ai-usage/browser-data/
     说明：Playwright 隔离浏览器配置，包含 cookies 等登录信息

  3. 插件配置
     位置：~/.config/show-ai-usage/config.toml
     说明：抓取间隔、启用的平台等配置

  4. 日志文件
     位置：~/.local/share/show-ai-usage/poller.log
     说明：抓取过程的详细日志，用于排查问题

================================================================================
【插件调用功能说明】
================================================================================

  本插件运行时会调用以下系统功能：

    1. Playwright (Python 库)
       - 启动 Microsoft Edge 浏览器（无头模式）
       - 访问各 AI 平台用量页面
       - 提取页面数据

    2. systemd --user
       - show-ai-usage.timer: 定时触发抓取
       - show-ai-usage.service: 执行抓取脚本

    3. kpackagetool6
       - 安装/升级/卸载 KDE Plasma 小部件

    4. 浏览器网络请求
       - https://chatgpt.com/codex/cloud/settings/analytics (OpenAI)
       - https://claude.ai/new#settings/usage (Claude)
       - https://www.kimi.com/code/console (Kimi)
       - https://platform.minimaxi.com/console/usage (MiniMax)

================================================================================
【卸载步骤】
================================================================================

  1. 执行卸载脚本：

       ./uninstall.sh

     这会：
       - 停止并禁用 systemd 定时任务
       - 卸载 KDE Plasma 小部件
       - 保留配置和数据文件（便于重新安装）

  2. 完全清理（删除所有数据）：

       ./uninstall.sh --purge

     这会额外删除：
       - ~/.config/show-ai-usage/     (配置文件)
       - ~/.local/share/show-ai-usage/  (数据和日志)

  3. 彻底清理（包含 Python 环境）：

       ./uninstall.sh --purge-all

     这会额外删除项目目录下的 .venv/ 虚拟环境。

  注意：卸载后任务栏上可能仍显示小部件（显示 N/A），需要手动：
    - 右键点击小部件 → 移除
    - 或重启 Plasma Shell: plasmashell --replace

================================================================================
【文件说明】
================================================================================

  - ${PLASMOID_FILE}  : KDE Plasma 小部件包
  - poller/           : Python 数据抓取脚本
    - main.py         : 主程序入口
    - config.py       : 配置管理
    - browser.py      : 浏览器管理
    - providers/      : 各平台数据提取器
  - install.sh        : 安装脚本
  - uninstall.sh      : 卸载脚本
  - systemd/          : systemd 定时任务配置
  - pyproject.toml    : Python 项目配置
  - uv.lock           : Python 依赖锁定文件

================================================================================
【常见问题】
================================================================================

  Q: 安装后小部件不显示数据？
  A: 1. 确认已运行 --login 登录各平台
     2. 手动运行 uv run python -m poller.main --oneshot 测试
     3. 检查 data.json 是否存在: ls ~/.local/share/show-ai-usage/

  Q: 数据抓取失败？
  A: 1. 检查日志: cat ~/.local/share/show-ai-usage/poller.log
     2. 可能是登录态过期，重新运行 --login <provider>
     3. 使用调试模式: uv run python -m poller.main --debug --providers codex

  Q: 如何修改抓取间隔？
  A: 右键小部件 → 配置 → Data Polling → 抓取间隔
     或编辑: ~/.config/show-ai-usage/config.toml

  Q: 支持哪些平台？
  A: 目前支持: OpenAI Codex, Claude Code, Kimi, MiniMax
     在配置面板的「Data Polling」标签页可以勾选启用/禁用

================================================================================
  更多信息: https://github.com/your/show-ai-usage
================================================================================
README_EOF

echo "      ✓  README.txt generated"
echo ""

# ── Generate checksum ───────────────────────────────────────────
echo "[Extra] Generating checksum ..."
cd "$OUTPUT_DIR"
sha256sum "$PLASMOID_FILE" > "$PLASMOID_FILE.sha256"
cd "$PROJECT_DIR"
echo "      ✓  SHA256 checksum generated"
echo ""

# ── Summary ─────────────────────────────────────────────────────
echo "✅  Build complete!"
echo ""
echo "   Output directory: $OUTPUT_DIR"
echo "   Files:"
ls -lh "$OUTPUT_DIR" | tail -n +2 | awk '{print "     - " $9 " (" $5 ")"}'
echo ""
echo "   To install:"
echo "     cd $OUTPUT_DIR && ./install.sh"
