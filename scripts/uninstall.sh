#!/usr/bin/env bash
#
# uninstall.sh — Uninstall Show AI Usage (user-local, no root required)
#
# Usage:
#   ./scripts/uninstall.sh                  # uninstall, keep data
#   ./scripts/uninstall.sh --purge          # uninstall + remove config & data
#   ./scripts/uninstall.sh --purge-all      # uninstall + remove config, data, .venv
#
set -euo pipefail

SYSTEMD_DIR="$HOME/.config/systemd/user"
PLASMOID_ID="showaiusage"
MODE="${1:-}"

echo "🗑️  Show AI Usage — Uninstaller"
echo ""

# Determine project directory safely
PROJECT_DIR="$PWD"

# ── Safety check ─────────────────────────────────────────────
if [ ! -f "$PROJECT_DIR/pyproject.toml" ]; then
    echo "⚠  Warning: Project directory seems to have moved or been deleted."
    echo "   systemd unit files will still be removed, but project files"
    echo "   cannot be cleaned automatically."
fi

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
case "$MODE" in
    --purge-all)
        echo "[4/4] Purging all files ..."

        # List directories to be removed
        echo "   The following directories will be DELETED:"
        echo "     - $HOME/.config/show-ai-usage"
        echo "     - $HOME/.local/share/show-ai-usage"
        if [ -d "$PROJECT_DIR/browser-data" ]; then
            echo "     - $PROJECT_DIR/browser-data"
        fi
        if [ -d "$PROJECT_DIR/.venv" ]; then
            echo "     - $PROJECT_DIR/.venv"
        fi

        echo ""
        echo -n "   Continue? [y/N] "
        read -r CONFIRM
        if [[ "$CONFIRM" =~ ^[Yy]$ ]]; then
            rm -rf "$HOME/.config/show-ai-usage"
            rm -rf "$HOME/.local/share/show-ai-usage"

            if [ -d "$PROJECT_DIR/browser-data" ]; then
                rm -rf "$PROJECT_DIR/browser-data"
                echo "      ✓  browser-data removed"
            fi
            if [ -d "$PROJECT_DIR/.venv" ]; then
                rm -rf "$PROJECT_DIR/.venv"
                echo "      ✓  .venv removed"
            fi
            echo "      ✓  All files purged"
        else
            echo "      ✗  Purge cancelled by user"
        fi
        ;;
    --purge)
        echo "[4/4] Purging config and data files ..."
        echo "   Removing: $HOME/.config/show-ai-usage"
        echo "   Removing: $HOME/.local/share/show-ai-usage"
        rm -rf "$HOME/.config/show-ai-usage"
        rm -rf "$HOME/.local/share/show-ai-usage"
        echo "      ✓  Config and data removed"
        echo "      Note: browser-data/ in the project directory was kept."
        echo "      To remove manually: rm -rf \"$PROJECT_DIR/browser-data\""
        echo "      To also remove .venv: rm -rf \"$PROJECT_DIR/.venv\""
        ;;
    *)
        echo "[4/4] Keeping config and data files."
        echo "      To remove them manually:"
        echo "        rm -rf ~/.config/show-ai-usage"
        echo "        rm -rf ~/.local/share/show-ai-usage"
        echo ""
        echo "   To reinstall:"
        echo "     git clone <repo> && cd show-ai-usage && ./scripts/install.sh"
        ;;
esac
echo ""

echo "✅  Uninstall complete."
echo ""
echo "⚠️  Note: The widget may still appear on your panel (showing N/A)."
echo "   To remove it:"
echo "     1. Right-click the widget on your panel → Remove 'AI Usage Monitor'"
echo "     2. Or restart Plasma Shell: plasmashell --replace"
