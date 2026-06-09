#!/usr/bin/env bash
#
# uninstall.sh — Uninstall Show AI Usage (user-local, no root required)
#
# Usage:
#   ./scripts/uninstall.sh              # uninstall, keep data
#   ./scripts/uninstall.sh --purge      # uninstall and remove all data
#
set -euo pipefail

SYSTEMD_DIR="$HOME/.config/systemd/user"
PLASMOID_ID="showaiusage"
PURGE="${1:-}"

echo "🗑️  Show AI Usage — Uninstaller"
echo ""

PROJECT_DIR="$PWD"

# ── 1. Stop and disable systemd timer ──────────────────────────
echo "[1/4] Stopping systemd timer ..."
systemctl --user stop show-ai-usage.timer 2>/dev/null || true
systemctl --user disable show-ai-usage.timer 2>/dev/null || true
echo "      ✓  Timer stopped and disabled"
echo ""

# ── 2. Remove systemd unit files ───────────────────────────────
echo "[2/4] Removing systemd unit files ..."
rm -f "$SYSTEMD_DIR/show-ai-usage.service"
rm -f "$SYSTEMD_DIR/show-ai-usage.timer"
systemctl --user daemon-reload
echo "      ✓  Unit files removed"
echo ""

# ── 3. Uninstall Plasmoid ──────────────────────────────────────
echo "[3/4] Uninstalling Plasmoid ..."
if kpackagetool6 --type Plasma/Applet --show "$PLASMOID_ID" &>/dev/null; then
    kpackagetool6 --type Plasma/Applet --remove "$PLASMOID_ID"
    echo "      ✓  Plasmoid removed"
else
    echo "      -  Plasmoid not installed, skipping"
fi
echo ""

# ── 4. Clean up data files (optional) ──────────────────────────
if [ "$PURGE" = "--purge" ]; then
    echo "[4/4] Purging config and data files ..."
    rm -rf "$HOME/.config/show-ai-usage"
    rm -rf "$HOME/.local/share/show-ai-usage"
    echo "      ✓  Config and data removed"
    echo "      Note: browser-data/ in the project directory was kept."
    echo "      Remove manually: rm -rf \"$PROJECT_DIR/browser-data\""
else
    echo "[4/4] Keeping config and data files."
    echo "      To remove them manually:"
    echo "        rm -rf ~/.config/show-ai-usage"
    echo "        rm -rf ~/.local/share/show-ai-usage"
fi
echo ""

echo "✅  Uninstall complete."
