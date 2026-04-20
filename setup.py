#!/usr/bin/env python3
import argparse
import asyncio
import sys
from pathlib import Path

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
