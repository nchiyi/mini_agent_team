#!/usr/bin/env bash
set -euo pipefail

REPO="https://github.com/nchiyi/mini_agent_team.git"
_SCRIPT_URL="https://raw.githubusercontent.com/nchiyi/mini_agent_team/main/install.sh"

# When run via curl | bash, stdin is a pipe so interactive prompts don't work.
# Re-download the full script and re-exec once; _MAT_REEXEC prevents looping.
if [ ! -t 0 ] && [ -z "${_MAT_REEXEC:-}" ]; then
    _TMPSCRIPT=$(mktemp /tmp/mat-install.XXXXXX)
    curl -fsSL "$_SCRIPT_URL" -o "$_TMPSCRIPT"
    chmod +x "$_TMPSCRIPT"
    export _MAT_REEXEC=1
    exec bash "$_TMPSCRIPT" "$@"
fi
DIR="mini_agent_team"

# Guard: detect if install.sh is being run from INSIDE the repo directory.
# Running `curl | bash install.sh` from within mini_agent_team causes a nested
# clone at mini_agent_team/mini_agent_team, breaking DEFAULT_CWD and paths.
if [ -f "main.py" ] && [ -f "setup.py" ] && git rev-parse --git-dir > /dev/null 2>&1; then
    echo "❌  Error: install.sh must be run from the PARENT directory, not from inside the repo."
    echo "    Run:"
    echo "      cd .."
    echo "      curl -fsSL https://raw.githubusercontent.com/nchiyi/mini_agent_team/main/install.sh | bash"
    exit 1
fi

echo ""
echo "╔══════════════════════════════════════╗"
echo "║     mini_agent_team  installer       ║"
echo "╚══════════════════════════════════════╝"
echo ""

# ── 1. clone ──────────────────────────────
if [ -d "$DIR" ]; then
    echo "📁  Directory '$DIR' already exists."
    # The directory may be: (a) a clean clone, (b) a clone with local edits,
    # (c) not a git repo at all (someone unpacked an archive). Handle all three
    # without crashing on `set -e`.
    if ! git -C "$DIR" rev-parse --git-dir >/dev/null 2>&1; then
        echo "❌  '$DIR' exists but is not a git repository."
        echo "    Either remove it (rm -rf $DIR) or move it out of the way,"
        echo "    then re-run this installer."
        exit 1
    fi
    if ! git -C "$DIR" diff --quiet || ! git -C "$DIR" diff --cached --quiet; then
        echo "⚠️   '$DIR' has uncommitted local changes; skipping git pull."
        echo "    Commit or stash them first if you want the latest upstream:"
        echo "      cd $DIR && git stash && git pull --ff-only && git stash pop"
    elif ! git -C "$DIR" pull --ff-only 2>/tmp/mat-pull.err; then
        echo "⚠️   git pull --ff-only failed:"
        sed 's/^/      /' /tmp/mat-pull.err
        echo "    Continuing with the existing checkout."
        rm -f /tmp/mat-pull.err
    else
        echo "✅  Repo updated to latest."
        rm -f /tmp/mat-pull.err
    fi
else
    echo "📥  Cloning repo..."
    git clone "$REPO" "$DIR"
fi
cd "$DIR"

# ── 2. Python check ───────────────────────
_py_ver_num() { "$1" -c 'import sys; print(sys.version_info.major * 100 + sys.version_info.minor)' 2>/dev/null || echo 0; }

PYTHON_BIN="python3"

# Prefer an explicitly versioned binary if the default is too old.
# Also probe common Homebrew and pyenv locations that may not be in PATH.
if [ "$(_py_ver_num python3)" -lt 311 ]; then
    for _candidate in \
        python3.13 python3.12 python3.11 \
        /opt/homebrew/bin/python3.13 /opt/homebrew/bin/python3.12 /opt/homebrew/bin/python3.11 \
        /usr/local/bin/python3.13 /usr/local/bin/python3.12 /usr/local/bin/python3.11 \
        "$HOME/.pyenv/shims/python3.13" "$HOME/.pyenv/shims/python3.12" "$HOME/.pyenv/shims/python3.11"; do
        if { command -v "$_candidate" &>/dev/null || [ -x "$_candidate" ]; } && \
           [ "$(_py_ver_num "$_candidate")" -ge 311 ]; then
            PYTHON_BIN="$_candidate"
            break
        fi
    done
fi

PY_VER=$("$PYTHON_BIN" -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")' 2>/dev/null || echo "not found")

# Linux distro detection via /etc/os-release (POSIX-standard since 2012, present
# on Ubuntu/Debian/Fedora/RHEL/Arch/Alpine/openSUSE/etc).
_linux_distro() {
    if [ -r /etc/os-release ]; then
        # shellcheck disable=SC1091
        . /etc/os-release 2>/dev/null
        echo "${ID:-unknown}"
    else
        echo "unknown"
    fi
}

if [ "$(_py_ver_num "$PYTHON_BIN")" -lt 311 ]; then
    if [ "$PY_VER" = "not found" ]; then
        echo "❌  Python not found. 3.11+ is required."
    else
        echo "❌  Python $PY_VER found, but 3.11+ is required."
    fi
    echo ""
    if [[ "$OSTYPE" == "linux-gnu"* ]]; then
        DISTRO="$(_linux_distro)"
        case "$DISTRO" in
            ubuntu|debian|linuxmint|pop|elementary)
                echo "💡  Detected Ubuntu/Debian-family ($DISTRO)."
                echo "    Will run: sudo add-apt-repository ppa:deadsnakes/ppa && sudo apt install python3.11 python3.11-venv"
                printf "🔧  Auto-install Python 3.11 now? [y/N]: " >/dev/tty
                read -r _DO_INSTALL </dev/tty
                if [[ "$_DO_INSTALL" =~ ^[Yy]$ ]]; then
                    if ! command -v add-apt-repository &>/dev/null; then
                        sudo apt update && sudo apt install -y software-properties-common
                    fi
                    sudo add-apt-repository -y ppa:deadsnakes/ppa
                    sudo apt update
                    sudo apt install -y python3.11 python3.11-venv
                    PYTHON_BIN="python3.11"
                else
                    echo "👉  Manual install: sudo apt install python3.11 python3.11-venv (after adding deadsnakes PPA)"
                    exit 1
                fi
                ;;
            fedora|rhel|centos|rocky|almalinux|amzn)
                echo "💡  Detected Fedora/RHEL-family ($DISTRO)."
                echo "    Will run: sudo dnf install -y python3.11"
                printf "🔧  Auto-install Python 3.11 now? [y/N]: " >/dev/tty
                read -r _DO_INSTALL </dev/tty
                if [[ "$_DO_INSTALL" =~ ^[Yy]$ ]]; then
                    sudo dnf install -y python3.11 || sudo yum install -y python3.11
                    PYTHON_BIN="python3.11"
                else
                    echo "👉  Manual install: sudo dnf install python3.11"
                    exit 1
                fi
                ;;
            arch|manjaro|endeavouros)
                echo "💡  Detected Arch-family ($DISTRO). Arch ships latest Python."
                echo "    Will run: sudo pacman -S --noconfirm python"
                printf "🔧  Auto-install Python now? [y/N]: " >/dev/tty
                read -r _DO_INSTALL </dev/tty
                if [[ "$_DO_INSTALL" =~ ^[Yy]$ ]]; then
                    sudo pacman -S --noconfirm python python-pip
                    PYTHON_BIN="python3"
                else
                    echo "👉  Manual install: sudo pacman -S python python-pip"
                    exit 1
                fi
                ;;
            alpine)
                echo "💡  Detected Alpine."
                echo "    Will run: sudo apk add python3 py3-pip py3-virtualenv"
                printf "🔧  Auto-install now? [y/N]: " >/dev/tty
                read -r _DO_INSTALL </dev/tty
                if [[ "$_DO_INSTALL" =~ ^[Yy]$ ]]; then
                    sudo apk add --no-cache python3 py3-pip py3-virtualenv
                    PYTHON_BIN="python3"
                else
                    echo "👉  Manual install: sudo apk add python3 py3-pip py3-virtualenv"
                    exit 1
                fi
                ;;
            opensuse-leap|opensuse-tumbleweed|sles|sled)
                echo "💡  Detected openSUSE/SLE ($DISTRO)."
                echo "    Will run: sudo zypper install -y python311"
                printf "🔧  Auto-install now? [y/N]: " >/dev/tty
                read -r _DO_INSTALL </dev/tty
                if [[ "$_DO_INSTALL" =~ ^[Yy]$ ]]; then
                    sudo zypper install -y python311 python311-pip
                    PYTHON_BIN="python3.11"
                else
                    echo "👉  Manual install: sudo zypper install python311"
                    exit 1
                fi
                ;;
            gentoo)
                echo "💡  Detected Gentoo. Manual emerge required:"
                echo "    sudo emerge -av dev-lang/python:3.11"
                exit 1
                ;;
            *)
                # Unknown / minor distro — try generic package managers as a hint.
                echo "⚠️   Unknown Linux distro: $DISTRO"
                if   command -v apt   &>/dev/null; then echo "👉  Try: sudo apt install python3.11 python3.11-venv"
                elif command -v dnf   &>/dev/null; then echo "👉  Try: sudo dnf install python3.11"
                elif command -v yum   &>/dev/null; then echo "👉  Try: sudo yum install python3.11"
                elif command -v pacman &>/dev/null; then echo "👉  Try: sudo pacman -S python"
                elif command -v apk   &>/dev/null; then echo "👉  Try: sudo apk add python3 py3-pip py3-virtualenv"
                elif command -v zypper &>/dev/null; then echo "👉  Try: sudo zypper install python311"
                else echo "👉  Install Python 3.11+ manually: https://www.python.org/downloads/"
                fi
                exit 1
                ;;
        esac
        # Re-probe after install
        PY_VER=$("$PYTHON_BIN" -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")' 2>/dev/null || echo "not found")
        if [ "$(_py_ver_num "$PYTHON_BIN")" -lt 311 ]; then
            echo "❌  Python install completed but $PYTHON_BIN is still below 3.11. Please re-run installer."
            exit 1
        fi
        echo "✅  Python $PY_VER installed"
    elif [[ "$OSTYPE" == "darwin"* ]]; then
        if command -v brew &>/dev/null; then
            echo "💡  Detected macOS with Homebrew."
            echo "    This will run: brew install python@3.11"
            printf "🔧  Auto-install Python 3.11 now? [y/N]: " >/dev/tty
            read -r _DO_INSTALL </dev/tty
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
            echo "💡  macOS — install Homebrew first (https://brew.sh) then rerun, or:"
            echo "    download from https://www.python.org/downloads/"
            exit 1
        fi
    else
        echo "💡  Unsupported OSTYPE: $OSTYPE — install Python 3.11+ manually."
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
# requirements.txt is a pip-compile lock file for Linux x86_64.
# On macOS some wheels (e.g. onnxruntime) are not available at the pinned
# version, so we fall back to requirements.in (unpinned) on that platform.
if [ "$(uname -s)" = "Darwin" ]; then
    echo "ℹ️   macOS detected — installing from requirements.in (platform-flexible)"
    pip install --quiet -r requirements.in
else
    pip install --quiet -r requirements.txt
fi
echo "✅  Dependencies installed"

# ── 5. ACP packages ───────────────────────────────────────────────
echo "ℹ️   ACP 套件設定已移至 wizard 精靈（Step 4.5）。"
echo "    精靈會根據你選擇的協作模式，僅安裝需要的套件。"

# ── 6. first-run check ────────────────────
# NOTE: install.sh is a legacy entry point. The canonical entry point is
# 'python -m src.setup.wizard' or 'python setup.py'. This script will be
# removed in a future release.
echo ""
echo "⚠️  DEPRECATION: install.sh will be removed in a future release."
echo "   Use: python setup.py  (or: python -m src.setup.wizard)"
echo ""

_is_configured() {
    [ -f "data/setup-state.json" ] && \
    ./venv/bin/python3 -c "
import json, sys
try:
    d = json.load(open('data/setup-state.json'))
    # v2 schema: mode == 'launch' means fully configured
    if d.get('version', 1) >= 2:
        sys.exit(0 if d.get('mode') == 'launch' else 1)
    # v1 schema: step 8 or 9 in completed_steps
    steps = d.get('completed_steps', [])
    sys.exit(0 if 8 in steps or 9 in steps else 1)
except Exception:
    sys.exit(1)
" 2>/dev/null
}

if _is_configured; then
    # Pick a service-manager label that matches the host so the menu doesn't
    # tell macOS users to "Restart service (systemd)" when the agent script
    # actually drives launchd.
    if [[ "$(uname -s)" == "Darwin" ]]; then
        _SVC_LABEL="launchd"
    else
        _SVC_LABEL="systemd"
    fi
    echo ""
    echo "╔══════════════════════════════════════╗"
    echo "║  mini_agent_team is already set up   ║"
    echo "╚══════════════════════════════════════╝"
    echo ""
    echo "  1. Start bot (foreground)"
    echo "  2. Restart service ($_SVC_LABEL)"
    echo "  3. Update tokens / settings  (./agent config)"
    echo "  4. Reconfigure from scratch  (re-run wizard)"
    echo "  5. Exit"
    echo ""
    printf "Choose [1]: " >/dev/tty
    read -r _MGMT </dev/tty
    _MGMT="${_MGMT:-1}"
    echo ""
    case "$_MGMT" in
        1)
            echo "🚀  Starting bot..."
            exec ./venv/bin/python3 main.py
            ;;
        2)
            ./agent restart
            ;;
        3)
            ./agent config </dev/tty
            ;;
        4)
            echo "🔄  Resetting wizard state..."
            ./venv/bin/python3 -m src.setup.wizard --reset </dev/tty
            ;;
        *)
            echo "👋  Bye."
            ;;
    esac
else
    # ── 5. wizard (first run) ──────────────
    echo ""
    echo "🧙  Launching setup wizard..."
    echo ""
    ./venv/bin/python3 -m src.setup.wizard </dev/tty
fi
