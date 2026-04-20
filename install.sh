#!/usr/bin/env bash
set -euo pipefail

REPO="https://github.com/nchiyi/mini_agent_team.git"
DIR="mini_agent_team"

echo ""
echo "╔══════════════════════════════════════╗"
echo "║     mini_agent_team  installer       ║"
echo "╚══════════════════════════════════════╝"
echo ""

# ── 1. clone ──────────────────────────────
if [ -d "$DIR" ]; then
    echo "📁  Directory '$DIR' already exists, pulling latest..."
    git -C "$DIR" pull --ff-only
else
    echo "📥  Cloning repo..."
    git clone "$REPO" "$DIR"
fi
cd "$DIR"

# ── 2. Python check ───────────────────────
if ! command -v python3 &>/dev/null; then
    echo "❌  python3 not found. Please install Python 3.11+."
    exit 1
fi

PY_VER=$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')
PY_MAJOR=$(python3 -c 'import sys; print(sys.version_info.major)')
PY_MINOR=$(python3 -c 'import sys; print(sys.version_info.minor)')
if [ "$PY_MAJOR" -lt 3 ] || { [ "$PY_MAJOR" -eq 3 ] && [ "$PY_MINOR" -lt 11 ]; }; then
    echo "❌  Python $PY_VER found, but 3.11+ is required."
    exit 1
fi
echo "✅  Python $PY_VER"

# ── 3. venv ───────────────────────────────
if [ ! -d "venv" ]; then
    echo "🐍  Creating virtual environment..."
    python3 -m venv venv
fi
source venv/bin/activate
echo "✅  Virtual environment active"

# ── 4. dependencies ───────────────────────
echo "📦  Installing dependencies..."
pip install --quiet --upgrade pip
pip install --quiet -r requirements.txt
echo "✅  Dependencies installed"

# ── 5. wizard ─────────────────────────────
echo ""
echo "🧙  Launching setup wizard..."
echo ""
python3 -m src.setup.wizard

echo ""
echo "🚀  Setup complete. To start the bot:"
echo "    cd $DIR && source venv/bin/activate && python3 main.py"
echo ""
echo "    Or with systemd (if configured by wizard):"
echo "    systemctl --user start gateway-agent"
echo ""
