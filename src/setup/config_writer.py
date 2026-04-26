"""
Non-destructive config writer with diff preview and 3-way prompt.
"""
import difflib
import os
import sys
from datetime import datetime
from pathlib import Path

_G = "\033[32m"
_Y = "\033[33m"
_R = "\033[31m"
_B = "\033[1m"
_X = "\033[0m"


def _prompt_tty(msg: str, default: str = "") -> str:
    suffix = f" [{default}]" if default else ""
    prompt_text = f"{msg}{suffix}: "
    try:
        if not sys.stdin.isatty():
            with open("/dev/tty", "r+") as _tty:
                _tty.write(prompt_text)
                _tty.flush()
                val = _tty.readline().rstrip("\n").strip()
        else:
            val = input(prompt_text).strip()
    except (EOFError, KeyboardInterrupt):
        print("\nSetup cancelled.")
        sys.exit(0)
    return val or default


def _show_diff(existing: str, new_content: str, label: str) -> None:
    existing_lines = existing.splitlines(keepends=True)
    new_lines = new_content.splitlines(keepends=True)
    diff = list(
        difflib.unified_diff(
            existing_lines,
            new_lines,
            fromfile="existing",
            tofile="new",
        )
    )
    if not diff:
        return
    print(f"\n  Config diff ({label}):")
    max_lines = 40
    for i, line in enumerate(diff):
        if i >= max_lines:
            remaining = len(diff) - max_lines
            print(f"  {_Y}... ({remaining} more lines truncated){_X}")
            break
        line_stripped = line.rstrip("\n")
        if line_stripped.startswith("---") or line_stripped.startswith("+++"):
            print(f"  {_B}{line_stripped}{_X}")
        elif line_stripped.startswith("@@"):
            print(f"  {_Y}{line_stripped}{_X}")
        elif line_stripped.startswith("+"):
            print(f"  {_G}{line_stripped}{_X}")
        elif line_stripped.startswith("-"):
            print(f"  {_R}{line_stripped}{_X}")
        else:
            print(f"  {line_stripped}")
    print()


def _make_backup(path: Path) -> Path:
    """Create a timestamped backup of the file; returns backup path."""
    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    backup = path.parent / f"{path.name}.bak.{ts}"
    backup.write_bytes(path.read_bytes())
    return backup


def write_config_with_diff(path: str, new_content: str, label: str = "config.toml") -> None:
    """
    Non-destructive config write:
    1. If file doesn't exist: write directly.
    2. If file exists and content identical: skip.
    3. If file exists and different:
       a. Show diff (unified format, truncated to 40 lines if long).
       b. Auto-backup: path.bak.{timestamp}.
       c. Prompt: keep / overwrite / merge.
    """
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)

    # Case 1: new file
    if not p.exists():
        p.write_text(new_content)
        print(f"  {_G}✓ Created {label}{_X}")
        return

    existing = p.read_text()

    # Case 2: identical content
    if existing == new_content:
        print(f"  {_G}✓ {label} unchanged — skipped{_X}")
        return

    # Case 3: different content
    _show_diff(existing, new_content, label)
    backup = _make_backup(p)
    print(f"  {_Y}⚠ Backup saved: {backup.name}{_X}")

    while True:
        choice = _prompt_tty(
            f"  [{_G}k{_X}] keep existing  [{_G}o{_X}] overwrite  [{_G}m{_X}] merge (open in $EDITOR)",
            "k",
        ).lower()
        if choice == "k":
            print(f"  {_G}✓ Keeping existing {label}{_X}")
            return
        elif choice == "o":
            p.write_text(new_content)
            print(f"  {_G}✓ Overwrote {label}{_X}")
            return
        elif choice == "m":
            editor = os.environ.get("EDITOR", "nano")
            merge_target = backup
            print(f"  Opening {merge_target.name} in {editor}...")
            print(f"  Edit to your liking, save and close. The file will be copied to {p.name}.")
            os.system(f'{editor} "{merge_target}"')
            merged = merge_target.read_text()
            p.write_text(merged)
            print(f"  {_G}✓ Merged {label} saved{_X}")
            return
        else:
            print(f"  {_R}✗ Invalid choice: {choice!r} — enter k, o, or m{_X}")


def write_env_with_diff(path: str, new_content: str, label: str = ".env") -> None:
    """
    Same non-destructive logic as write_config_with_diff, plus enforces
    chmod 0o600 on the file after any write operation.
    """
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)

    # Case 1: new file
    if not p.exists():
        p.write_text(new_content)
        p.chmod(0o600)
        print(f"  {_G}✓ Created {label} (mode 600){_X}")
        return

    existing = p.read_text()

    # Case 2: identical content — still ensure 600
    if existing == new_content:
        p.chmod(0o600)
        print(f"  {_G}✓ {label} unchanged — skipped (mode 600 ensured){_X}")
        return

    # Case 3: different content
    _show_diff(existing, new_content, label)
    backup = _make_backup(p)
    backup.chmod(0o600)
    print(f"  {_Y}⚠ Backup saved: {backup.name} (mode 600){_X}")

    while True:
        choice = _prompt_tty(
            f"  [{_G}k{_X}] keep existing  [{_G}o{_X}] overwrite  [{_G}m{_X}] merge (open in $EDITOR)",
            "k",
        ).lower()
        if choice == "k":
            p.chmod(0o600)
            print(f"  {_G}✓ Keeping existing {label} (mode 600 ensured){_X}")
            return
        elif choice == "o":
            p.write_text(new_content)
            p.chmod(0o600)
            print(f"  {_G}✓ Overwrote {label} (mode 600){_X}")
            return
        elif choice == "m":
            editor = os.environ.get("EDITOR", "nano")
            merge_target = backup
            print(f"  Opening {merge_target.name} in {editor}...")
            print(f"  Edit to your liking, save and close. The file will be copied to {p.name}.")
            os.system(f'{editor} "{merge_target}"')
            merged = merge_target.read_text()
            p.write_text(merged)
            p.chmod(0o600)
            print(f"  {_G}✓ Merged {label} saved (mode 600){_X}")
            return
        else:
            print(f"  {_R}✗ Invalid choice: {choice!r} — enter k, o, or m{_X}")
