#!/usr/bin/env bash
#
# install.sh — Install Show AI Usage (user-local, no root required)
#
# Usage:
#   ./scripts/install.sh                  # install from current directory
#   ./scripts/install.sh /path/to/project # install from specified path
#
set -euo pipefail

# ── Resolve project directory ──────────────────────────────────
PROJECT_DIR="$(realpath "${1:-$PWD}")"
SYSTEMD_DIR="$HOME/.config/systemd/user"
PLASMOID_ID="showaiusage"

echo "📦 Show AI Usage — Installer"
echo "   Project: $PROJECT_DIR"
echo ""

# ── 1. Verify project structure ────────────────────────────────
if [ ! -f "$PROJECT_DIR/pyproject.toml" ]; then
    echo "✗  No pyproject.toml found at $PROJECT_DIR — is this the right directory?"
    exit 1
fi

if [ ! -d "$PROJECT_DIR/package" ]; then
    echo "✗  No package/ directory — Plasmoid files missing."
    exit 1
fi

# ── 2. Install Python dependencies ─────────────────────────────
echo "[1/5] Installing Python dependencies ..."
uv sync --project "$PROJECT_DIR"
echo "      ✓  Done"
echo ""

# ── 3. Install / upgrade Plasmoid ─────────────────────────────
echo "[2/5] Installing Plasmoid (kpackagetool6) ..."
if kpackagetool6 --type Plasma/Applet --show "$PLASMOID_ID" &>/dev/null; then
    kpackagetool6 --type Plasma/Applet --upgrade "$PROJECT_DIR/package"
    echo "      ✓  Upgraded existing Plasmoid"
else
    kpackagetool6 --type Plasma/Applet --install "$PROJECT_DIR/package"
    echo "      ✓  Installed new Plasmoid"
fi
echo ""

# ── 4. Install systemd user units ──────────────────────────────
echo "[3/5] Installing systemd user units ..."
mkdir -p "$SYSTEMD_DIR"

sed "s|@@PROJECT_DIR@@|$PROJECT_DIR|g" \
    "$PROJECT_DIR/systemd/show-ai-usage.service" \
    > "$SYSTEMD_DIR/show-ai-usage.service"

cp "$PROJECT_DIR/systemd/show-ai-usage.timer" "$SYSTEMD_DIR/show-ai-usage.timer"

systemctl --user daemon-reload
echo "      ✓  Units installed"
echo ""

# ── 5. Enable and start timer ──────────────────────────────────
echo "[4/5] Enabling timer ..."
systemctl --user enable --now show-ai-usage.timer
echo "      ✓  Timer enabled and started"
echo ""

# ── 6. Verify ──────────────────────────────────────────────────
echo "[5/5] Verifying installation ..."
echo ""
echo "   Timer status:"
systemctl --user status show-ai-usage.timer --no-pager 2>&1 | head -5
echo ""
echo "   Plasmoid:"
kpackagetool6 --type Plasma/Applet --show "$PLASMOID_ID"
echo ""

echo "✅  Installation complete!"
echo ""
echo "   → Add the widget to your panel: right-click panel → Add Widget → AI Usage Monitor"
echo "   → Login to providers: uv run python poller/main.py --login <provider>"
echo "   → Run once: uv run python poller/main.py --oneshot"
echo "   → View data: uv run python poller/main.py --status"
echo "   → Edit config: $HOME/.config/show-ai-usage/config.toml"
