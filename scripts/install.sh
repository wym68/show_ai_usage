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
PROJECT_DIR=""

while [[ $# -gt 0 ]]; do
    case "$1" in
        --no-timer) NO_TIMER=true; shift ;;
        --dry-run)  DRY_RUN=true;  shift ;;
        --prefix)
            if [[ -z "${2:-}" ]]; then echo "✗ --prefix requires a path argument"; exit 1; fi
            PROJECT_DIR="$(realpath "$2")"
            shift 2
            ;;
        -*)
            echo "✗ Unknown option: $1"
            echo "Usage: $0 [--no-timer] [--dry-run] [--prefix <path>] [<project-dir>]"
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

if [ ! -d "$PROJECT_DIR/package" ]; then
    echo "✗  No package/ directory — Plasmoid files missing."
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
if kpackagetool6 --type Plasma/Applet --show "$PLASMOID_ID" &>/dev/null; then
    kpackagetool6 --type Plasma/Applet --upgrade "$PROJECT_DIR/package"
    echo "      ✓  Upgraded existing Plasmoid"
else
    kpackagetool6 --type Plasma/Applet --install "$PROJECT_DIR/package"
    echo "      ✓  Installed new Plasmoid"
fi
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

echo "✅  Installation complete!"
echo ""
echo "   → Add the widget to your panel: right-click panel → Add Widget → AI Usage Monitor"
echo "   → Login to providers: uv run python -m poller.main --login <provider>"
echo "   → Run once: uv run python -m poller.main --oneshot"
echo "   → View data: uv run python -m poller.main --status"
echo "   → Edit config: $HOME/.config/show-ai-usage/config.toml"
