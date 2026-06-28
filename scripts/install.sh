#!/usr/bin/env bash
#
# install.sh — Install Show AI Usage (user-local, no root required)
#
# Usage:
#   ./scripts/install.sh                          # standard install
#   ./scripts/install.sh /path/to/project         # install from specified path
#   ./scripts/install.sh --no-timer               # install plasmoid only, skip systemd
#   ./scripts/install.sh --dry-run                # pre-check only, no changes
#   ./scripts/install.sh --prefix ~/myapp         # custom project directory
#
set -euo pipefail

# ── Parse options ───────────────────────────────────────────────
NO_TIMER=false
DRY_RUN=false
NO_ONBOARD=false
PROJECT_DIR=""

while [[ $# -gt 0 ]]; do
    case "$1" in
        --no-timer)   NO_TIMER=true;   shift ;;
        --dry-run)    DRY_RUN=true;    shift ;;
        --no-onboard) NO_ONBOARD=true; shift ;;
        --prefix)
            if [[ -z "${2:-}" ]]; then echo "✗ --prefix requires a path argument"; exit 1; fi
            PROJECT_DIR="$(realpath "$2")"
            shift 2
            ;;
        -*)
            echo "✗ Unknown option: $1"
            echo "Usage: $0 [--no-timer] [--dry-run] [--no-onboard] [--prefix <path>] [<project-dir>]"
            exit 1
            ;;
        *)
            PROJECT_DIR="$(realpath "$1")"
            shift
            ;;
    esac
done

PROJECT_DIR="${PROJECT_DIR:-$(realpath "$PWD")}"
SYSTEMD_DIR="$HOME/.config/systemd/user"
PLASMOID_ID="showaiusage"

echo "📦 Show AI Usage — Installer"
echo "   Project: $PROJECT_DIR"
[[ "$DRY_RUN" == true ]] && echo "   Mode:    DRY RUN (no changes will be made)"
echo ""

# ── Detect install mode ────────────────────────────────────────
# Plugin package mode: has .plasmoid file in current directory
# Development mode: has package/ directory
PLUGIN_PACKAGE=""
if ls "$PROJECT_DIR"/*.plasmoid 1> /dev/null 2>&1; then
    PLUGIN_PACKAGE=$(ls "$PROJECT_DIR"/*.plasmoid | head -n 1)
    echo "   Mode:    Plugin package ($PLUGIN_PACKAGE)"
    INSTALL_MODE="package"
elif [ -d "$PROJECT_DIR/package" ]; then
    echo "   Mode:    Development (from source)"
    INSTALL_MODE="source"
else
    echo "   Mode:    Unknown — neither .plasmoid nor package/ found"
    INSTALL_MODE="unknown"
fi
echo ""

# ── 0. Pre-flight checks ───────────────────────────────────────
echo "[0/5] Checking dependencies ..."
FAILED=false

check_dep() {
    local name="$1" binary="$2" hint="$3"
    if command -v "$binary" &>/dev/null; then
        echo "      ✓  $name ($binary found)"
    else
        echo "      ✗  $name — $binary not found."
        echo "         $hint"
        FAILED=true
    fi
}

check_dep "uv" "uv" "Install from: https://docs.astral.sh/uv/"
check_dep "kpackagetool6" "kpackagetool6" "Part of kpackage — ensure plasma-workspace is installed."
check_dep "systemctl --user" "systemctl" "systemd --user services are required."

# Edge: try both names
if command -v msedge &>/dev/null; then
    echo "      ✓  Microsoft Edge (msedge)"
elif command -v microsoft-edge-stable &>/dev/null; then
    echo "      ✓  Microsoft Edge (microsoft-edge-stable)"
else
    echo "      ✗  Microsoft Edge — not found."
    echo "         Install from: https://www.microsoft.com/edge"
    FAILED=true
fi

# systemd --user availability
if systemctl --user show-environment &>/dev/null; then
    echo "      ✓  systemd --user available"
else
    echo "      ✗  systemd --user is not available."
    echo "         Ensure systemd --user services are enabled."
    FAILED=true
fi

echo ""
if [[ "$FAILED" == true ]]; then
    echo "✗  One or more dependencies are missing. Please install them and re-run."
    exit 1
fi

# ── 1. Verify project structure ────────────────────────────────
echo "[1/5] Verifying project structure ..."
if [ ! -f "$PROJECT_DIR/pyproject.toml" ]; then
    echo "✗  No pyproject.toml found at $PROJECT_DIR — is this the right directory?"
    exit 1
fi

if [ "$INSTALL_MODE" = "unknown" ]; then
    echo "✗  Neither package/ directory nor .plasmoid file found."
    echo "   If installing from a release package, ensure the .plasmoid file is present."
    exit 1
fi
echo "      ✓  Project structure valid"
echo ""

[[ "$DRY_RUN" == true ]] && echo "⚠  DRY RUN — stopping before making changes." && exit 0

# ── 2. Install Python dependencies ─────────────────────────────
echo "[2/5] Installing Python dependencies ..."
uv sync --project "$PROJECT_DIR"
echo "      ✓  Done"

# Check Playwright browsers, install if missing
echo "      Checking Playwright browsers..."
# First check if Playwright can use system Edge (preferred - no download needed)
if uv run --project "$PROJECT_DIR" python -c "from playwright.sync_api import sync_playwright; sync_playwright().start().chromium.launch(headless=True, channel='msedge').close()" 2>/dev/null; then
    echo "      ✓  System Edge browser available for Playwright"
# Fall back to Playwright's bundled Chromium
elif uv run --project "$PROJECT_DIR" python -c "from playwright.sync_api import sync_playwright; sync_playwright().start().chromium.launch(headless=True).close()" 2>/dev/null; then
    echo "      ✓  Playwright bundled Chromium available"
else
    echo "      → Installing Playwright browsers (chromium)..."
    # Ignore errors here - on Ubuntu 26.04+ Playwright may not have prebuilt binaries yet,
    # but system Edge will still work via the channel='msedge' parameter
    if uv run --project "$PROJECT_DIR" python -m playwright install chromium 2>/dev/null; then
        echo "      ✓  Playwright browsers installed"
    else
        echo "      ⚠  Playwright Chromium install failed (likely unsupported OS version)"
        echo "         System Edge will be used instead — this is normal on newer distributions."
    fi
fi
echo ""

# ── 3. Install / upgrade Plasmoid ─────────────────────────────
echo "[3/5] Installing Plasmoid (kpackagetool6) ..."
if [ "$INSTALL_MODE" = "package" ] && [ -n "$PLUGIN_PACKAGE" ]; then
    # Plugin package mode: install from .plasmoid file
    if kpackagetool6 --type Plasma/Applet --show "$PLASMOID_ID" &>/dev/null; then
        kpackagetool6 --type Plasma/Applet --upgrade "$PLUGIN_PACKAGE"
        echo "      ✓  Upgraded existing Plasmoid from package"
    else
        kpackagetool6 --type Plasma/Applet --install "$PLUGIN_PACKAGE"
        echo "      ✓  Installed new Plasmoid from package"
    fi
else
    # Development mode: install from package/ directory
    if kpackagetool6 --type Plasma/Applet --show "$PLASMOID_ID" &>/dev/null; then
        kpackagetool6 --type Plasma/Applet --upgrade "$PROJECT_DIR/package"
        echo "      ✓  Upgraded existing Plasmoid from source"
    else
        kpackagetool6 --type Plasma/Applet --install "$PROJECT_DIR/package"
        echo "      ✓  Installed new Plasmoid from source"
    fi
fi
echo ""

# ── 3b. Record runtime paths for the widget ────────────────────
# The installed plasmoid lives separately from this project; persist the
# project dir + uv path so the config page can launch the poller (login).
RUNTIME_CONF="$HOME/.config/show-ai-usage/runtime.conf"
mkdir -p "$(dirname "$RUNTIME_CONF")"
{
    echo "PROJECT_DIR=$PROJECT_DIR"
    echo "UV=$(command -v uv || echo uv)"
} > "$RUNTIME_CONF"
chmod 0600 "$RUNTIME_CONF"
echo "      ✓  Runtime paths recorded ($RUNTIME_CONF)"
echo ""

# ── 4. Install systemd user units (skip if --no-timer) ─────────
if [[ "$NO_TIMER" == true ]]; then
    echo "[4/5] Skipping systemd timer installation (--no-timer)"
    echo ""
else
    echo "[4/5] Installing systemd user units ..."
    mkdir -p "$SYSTEMD_DIR"

    # Remove old symlinks / files before installing
    rm -f "$SYSTEMD_DIR/show-ai-usage.service"
    rm -f "$SYSTEMD_DIR/show-ai-usage.timer"

    # Resolve uv path so systemd (which has a minimal PATH) can find it
    UV_PATH="$(command -v uv)"
    if [[ -z "$UV_PATH" ]]; then
        echo "✗  uv not found in PATH — cannot install systemd service."
        exit 1
    fi

    # Substitute placeholders and install as regular file
    sed -e "s|@@PROJECT_DIR@@|$PROJECT_DIR|g" \
        -e "s|@@UV_PATH@@|$UV_PATH|g" \
        "$PROJECT_DIR/systemd/show-ai-usage.service" \
        > "$SYSTEMD_DIR/show-ai-usage.service"

    cp "$PROJECT_DIR/systemd/show-ai-usage.timer" "$SYSTEMD_DIR/show-ai-usage.timer"

    systemctl --user daemon-reload
    echo "      ✓  Units installed"
    echo ""

    # ── 5. Enable and start timer ──────────────────────────────
    echo "[5/5] Enabling timer ..."
    systemctl --user enable --now show-ai-usage.timer
    echo "      ✓  Timer enabled and started"
fi
echo ""

# ── Post-install verification ──────────────────────────────────
echo "── Verification ──────────────────────────────"
if systemctl --user is-active show-ai-usage.timer &>/dev/null 2>&1; then
    echo "   ✓  Timer: active"
elif [[ "$NO_TIMER" == true ]]; then
    echo "   -  Timer: skipped (--no-timer)"
else
    echo "   ⚠  Timer: not active — check 'systemctl --user status show-ai-usage.timer'"
fi

if kpackagetool6 --type Plasma/Applet --show "$PLASMOID_ID" &>/dev/null; then
    echo "   ✓  Plasmoid: installed"
else
    echo "   ⚠  Plasmoid: not found"
fi

# One-shot dry run to verify fetch chain
if uv run --project "$PROJECT_DIR" python -m poller.main --oneshot --providers codex 2>&1 | grep -q "results"; then
    echo "   ✓  Fetch chain: working"
else
    echo "   -  Fetch chain: not tested (run --oneshot manually after logging in)"
fi
echo "──────────────────────────────────────────────"
echo ""

# ── Onboarding: per-provider credential setup ──────────────────
# Two fetch methods exist:
#   • browser : open the isolated browser and log in (cookies kept in
#               browser-data/, mode 0700)
#   • direct  : call the provider API with a token (token kept in
#               secrets.env, mode 0600)
run_onboarding() {
    local POLLER=(uv run --project "$PROJECT_DIR" python -m poller.main)

    echo "── 初始化引导 ──────────────────────────────"
    echo "  抓取方式："
    echo "    • 浏览器登录：打开隔离浏览器手动登录（登录态存 browser-data/，权限 0700）"
    echo "    • 直连 API  ：用 Token 直接调用接口，更快更稳（Token 存 secrets.env，权限 0600）"
    echo ""
    echo "  隐私数据存储位置："
    echo "    登录态: $HOME/.local/share/show-ai-usage/browser-data/"
    echo "    密钥  : $HOME/.config/show-ai-usage/secrets.env"
    echo "    配置  : $HOME/.config/show-ai-usage/config.toml"
    echo "    用量  : $HOME/.local/share/show-ai-usage/data.json"
    echo ""
    echo "  密钥只写入 secrets.env，绝不写入 config.toml 或插件配置。"
    echo "  （可随时跳过，之后在「插件设置 → Data Polling」中配置。）"
    echo ""

    local claude_method="browser" kimi_method="direct" minimax_method="direct"
    local ans

    # OpenAI Codex — browser only
    read -r -p "  为 OpenAI Codex 配置浏览器登录？[Y/n/s跳过] " ans
    case "${ans:-y}" in
        [Yy]*) "${POLLER[@]}" --login codex || echo "  ⚠ codex 登录未完成，可稍后重试" ;;
        *) echo "  - 跳过 codex" ;;
    esac
    echo ""

    # Claude — browser (default) or direct (auto-reads ~/.claude/.credentials.json)
    read -r -p "  Claude 抓取方式？[b]浏览器登录 [d]直连API [s]跳过 (默认 b) " ans
    case "${ans:-b}" in
        [Dd]*)
            claude_method="direct"
            echo "  Claude 直连默认读取 ~/.claude/.credentials.json。"
            read -r -p "  另行手动录入 Claude Token？[y/N] " ans
            [[ "$ans" =~ ^[Yy] ]] && "${POLLER[@]}" --set-token claude
            ;;
        [Ss]*) echo "  - 跳过 claude" ;;
        *) "${POLLER[@]}" --login claude || echo "  ⚠ claude 登录未完成" ;;
    esac
    echo ""

    # Kimi — direct (default) or browser
    read -r -p "  Kimi 抓取方式？[d]直连API [b]浏览器登录 [s]跳过 (默认 d) " ans
    case "${ans:-d}" in
        [Bb]*) kimi_method="browser"; "${POLLER[@]}" --login kimi || echo "  ⚠ kimi 登录未完成" ;;
        [Ss]*) echo "  - 跳过 kimi" ;;
        *) kimi_method="direct"; "${POLLER[@]}" --set-token kimi || echo "  ⚠ kimi Token 未录入" ;;
    esac
    echo ""

    # MiniMax — direct (default; API key or mmx CLI) or browser
    read -r -p "  MiniMax 抓取方式？[d]直连API [b]浏览器登录 [s]跳过 (默认 d) " ans
    case "${ans:-d}" in
        [Bb]*) minimax_method="browser"; "${POLLER[@]}" --login minimax || echo "  ⚠ minimax 登录未完成" ;;
        [Ss]*) echo "  - 跳过 minimax（如本机已装 mmx CLI，直连可免 Token）" ;;
        *)
            minimax_method="direct"
            echo "  MiniMax 直连可用 API Key；若本机已装 mmx CLI 也可免 Token。"
            read -r -p "  录入 MiniMax API Key？[Y/n] " ans
            [[ "${ans:-y}" =~ ^[Yy] ]] && { "${POLLER[@]}" --set-token minimax || echo "  ⚠ minimax Key 未录入"; }
            ;;
    esac
    echo ""

    # Persist chosen methods to config.toml (headless/CLI path). Widget users
    # can override these in the widget's settings afterwards.
    if [[ "$NO_TIMER" == false ]]; then
        python3 "$PROJECT_DIR/package/contents/scripts/sync_config.py" \
            --enable --interval 300 --providers codex,claude,kimi,minimax \
            --claude-method "$claude_method" --kimi-method "$kimi_method" \
            --minimax-method "$minimax_method" >/dev/null \
            && echo "  ✓ 抓取方式已写入 config.toml"
    fi
    echo "──────────────────────────────────────────────"
    echo ""
}

if [[ "$DRY_RUN" == false && "$NO_ONBOARD" == false && -t 0 ]]; then
    run_onboarding
else
    echo "ℹ  跳过初始化引导（非交互终端或 --no-onboard）。"
    echo "   稍后可手动：登录 'uv run python -m poller.main --login <provider>'，"
    echo "   或录入 Token 'uv run python -m poller.main --set-token <provider>'。"
    echo ""
fi

echo "✅  Installation complete!"
echo ""
echo "   → Add the widget to your panel: right-click panel → Add Widget → AI Usage Monitor"
echo "   → Configure polling & fetch method: right-click widget → Configure → Data Polling"
echo "   → Login to providers: uv run python -m poller.main --login <provider>"
echo "   → Set an API token (stored in secrets.env, 0600): uv run python -m poller.main --set-token <provider>"
echo "   → Run once: uv run python -m poller.main --oneshot"
echo "   → View data: uv run python -m poller.main --status"
echo "   → Edit config manually: $HOME/.config/show-ai-usage/config.toml"
