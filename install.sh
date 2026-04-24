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
_py_ver_num() { "$1" -c 'import sys; print(sys.version_info.major * 100 + sys.version_info.minor)' 2>/dev/null || echo 0; }

PYTHON_BIN="python3"

# Prefer an explicitly versioned binary if the default is too old
if [ "$(_py_ver_num python3)" -lt 311 ]; then
    for _candidate in python3.13 python3.12 python3.11; do
        if command -v "$_candidate" &>/dev/null && [ "$(_py_ver_num "$_candidate")" -ge 311 ]; then
            PYTHON_BIN="$_candidate"
            break
        fi
    done
fi

PY_VER=$("$PYTHON_BIN" -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")' 2>/dev/null || echo "not found")

if [ "$(_py_ver_num "$PYTHON_BIN")" -lt 311 ]; then
    echo "❌  Python $PY_VER found, but 3.11+ is required."
    echo ""
    if [[ "$OSTYPE" == "linux-gnu"* ]] && command -v apt &>/dev/null; then
        echo "💡  Detected Ubuntu/Debian."
        echo "    This will run: sudo add-apt-repository ppa:deadsnakes/ppa && sudo apt install python3.11 python3.11-venv"
        read -rp "🔧  Auto-install Python 3.11 now? [y/N]: " _DO_INSTALL
        if [[ "$_DO_INSTALL" =~ ^[Yy]$ ]]; then
            sudo add-apt-repository -y ppa:deadsnakes/ppa
            sudo apt install -y python3.11 python3.11-venv
            PYTHON_BIN="python3.11"
            PY_VER=$("$PYTHON_BIN" -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')
            echo "✅  Python $PY_VER installed"
        else
            echo "👉  Manual install:"
            echo "    sudo add-apt-repository ppa:deadsnakes/ppa"
            echo "    sudo apt install python3.11 python3.11-venv"
            exit 1
        fi
    elif [[ "$OSTYPE" == "darwin"* ]]; then
        if command -v brew &>/dev/null; then
            echo "💡  Detected macOS with Homebrew."
            echo "    This will run: brew install python@3.11"
            read -rp "🔧  Auto-install Python 3.11 now? [y/N]: " _DO_INSTALL
            if [[ "$_DO_INSTALL" =~ ^[Yy]$ ]]; then
                brew install python@3.11
                PYTHON_BIN="$(brew --prefix python@3.11)/bin/python3.11"
                PY_VER=$("$PYTHON_BIN" -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')
                echo "✅  Python $PY_VER installed"
            else
                echo "👉  Manual install: brew install python@3.11"
                exit 1
            fi
        else
            echo "💡  macOS — run one of:"
            echo "    brew install python@3.11"
            echo "    or download from: https://www.python.org/downloads/"
            exit 1
        fi
    else
        echo "💡  Please install Python 3.11+: https://www.python.org/downloads/"
        exit 1
    fi
else
    echo "✅  Python $PY_VER"
fi

# ── 3. venv ───────────────────────────────
if [ ! -d "venv" ]; then
    echo "🐍  Creating virtual environment..."
    "$PYTHON_BIN" -m venv venv
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
"$PYTHON_BIN" -m src.setup.wizard

echo ""
echo "🚀  Setup complete. To start the bot:"
echo "    cd $DIR && source venv/bin/activate && python3 main.py"
echo ""
echo "    Or with systemd (if configured by wizard):"
echo "    systemctl --user start gateway-agent"
echo ""
