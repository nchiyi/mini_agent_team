#!/usr/bin/env python3
import os
import subprocess
import sys
from pathlib import Path

# ── Python version guard ───────────────────────────────────────────────────
# This project requires Python 3.11+. If the current interpreter is older,
# re-exec with the venv interpreter (if available) so `python3 setup.py`
# works even when the system python3 is an older version.
if sys.version_info < (3, 11):
    _here = Path(__file__).parent
    _venv_py = _here / "venv" / "bin" / "python3"
    if _venv_py.exists():
        os.execv(str(_venv_py), [str(_venv_py)] + sys.argv)
    else:
        print(
            f"Error: Python 3.11+ is required (got {sys.version_info.major}.{sys.version_info.minor}).\n"
            "Run install.sh first to create the virtual environment, or activate it manually:\n"
            "  source venv/bin/activate && python3 setup.py",
            file=sys.stderr,
        )
        sys.exit(1)

# ── Normal startup ─────────────────────────────────────────────────────────
import argparse
import asyncio

sys.path.insert(0, str(Path(__file__).parent))

from src.setup.wizard import run_wizard


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Gateway Agent Platform — interactive setup wizard"
    )
    parser.add_argument(
        "--reset", action="store_true",
        help="Clear saved progress and restart from step 1"
    )
    parser.add_argument(
        "--cwd", default=".",
        help="Project root directory (default: current directory)"
    )
    args = parser.parse_args()
    asyncio.run(run_wizard(reset=args.reset, cwd=args.cwd))


if __name__ == "__main__":
    main()
