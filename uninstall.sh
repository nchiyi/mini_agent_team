#!/usr/bin/env bash
set -euo pipefail

# Resolve project directory: prefer the directory this script lives in,
# fall back to $HOME/mini_agent_team, or accept a path as first argument.
_script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="${1:-}"
if [ -z "$PROJECT_DIR" ]; then
    if [ -f "$_script_dir/main.py" ]; then
        PROJECT_DIR="$_script_dir"
    elif [ -d "$HOME/mini_agent_team" ]; then
        PROJECT_DIR="$HOME/mini_agent_team"
    else
        echo "❌  Cannot locate project directory."
        echo "    Usage: bash uninstall.sh [/path/to/mini_agent_team]"
        exit 1
    fi
fi

echo ""
echo "╔══════════════════════════════════════╗"
echo "║    mini_agent_team  uninstaller      ║"
echo "╚══════════════════════════════════════╝"
echo ""
echo "Project directory: $PROJECT_DIR"
echo ""

# ── Confirm ───────────────────────────────
read -rp "⚠️   This will stop the bot and remove the project. Continue? [y/N]: " _CONFIRM
if [[ ! "$_CONFIRM" =~ ^[Yy]$ ]]; then
    echo "Aborted."
    exit 0
fi

# ── Stop systemd service ──────────────────
if systemctl --user is-active --quiet gateway-agent 2>/dev/null; then
    echo "🛑  Stopping systemd service..."
    systemctl --user stop gateway-agent
fi
if systemctl --user is-enabled --quiet gateway-agent 2>/dev/null; then
    systemctl --user disable gateway-agent
fi
_UNIT="$HOME/.config/systemd/user/gateway-agent.service"
if [ -f "$_UNIT" ]; then
    rm -f "$_UNIT"
    systemctl --user daemon-reload
    echo "✅  Systemd service removed"
fi

# ── Stop Docker container ─────────────────
if [ -f "$PROJECT_DIR/docker-compose.yml" ] && command -v docker &>/dev/null; then
    if docker compose -f "$PROJECT_DIR/docker-compose.yml" ps --quiet 2>/dev/null | grep -q .; then
        echo "🐳  Stopping Docker container..."
        docker compose -f "$PROJECT_DIR/docker-compose.yml" down
        echo "✅  Docker container stopped"
    fi
fi

# ── Ask about data ────────────────────────
echo ""
read -rp "🗂️   Keep conversation data/history? [Y/n]: " _KEEP_DATA
_KEEP_DATA="${_KEEP_DATA:-Y}"

# ── Remove project ────────────────────────
if [[ "$_KEEP_DATA" =~ ^[Nn]$ ]]; then
    echo "🗑️   Removing project and all data..."
    rm -rf "$PROJECT_DIR"
    echo "✅  $PROJECT_DIR removed"
else
    _BACKUP="$HOME/mat-data-backup-$(date +%Y%m%d%H%M%S)"
    if [ -d "$PROJECT_DIR/data" ]; then
        cp -r "$PROJECT_DIR/data" "$_BACKUP"
        echo "💾  Data backed up to: $_BACKUP"
    fi
    rm -rf "$PROJECT_DIR"
    echo "✅  $PROJECT_DIR removed (data saved to $_BACKUP)"
fi

echo ""
echo "╔══════════════════════════════════════╗"
echo "║    Uninstall complete.               ║"
echo "╚══════════════════════════════════════╝"
echo ""
