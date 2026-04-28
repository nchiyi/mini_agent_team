import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


class Tier1Store:
    """Permanent per-(user, channel, bot) memory stored as a JSONL file.

    Each line: {"ts": "...", "content": "..."}.
    A human-readable .md copy is kept in sync alongside the JSONL.
    Files are named ``{user_id}_{channel}_{bot_id}.jsonl`` so multiple bots
    serving the same user keep distinct stores. ``bot_id`` defaults to
    ``"default"``; pre-multibot files matching ``{user_id}_{channel}.jsonl``
    are transparently renamed to ``{user_id}_{channel}_default.jsonl`` on
    first access.
    """

    def __init__(self, permanent_dir: str):
        self._dir = Path(permanent_dir)
        self._dir.mkdir(parents=True, exist_ok=True)

    def _migrate_legacy(self, user_id: int, channel: str) -> None:
        """Rename pre-multibot {uid}_{ch}.jsonl → {uid}_{ch}_default.jsonl (idempotent)."""
        for ext in ("jsonl", "md"):
            legacy = self._dir / f"{user_id}_{channel}.{ext}"
            new = self._dir / f"{user_id}_{channel}_default.{ext}"
            if legacy.exists() and not new.exists():
                legacy.rename(new)

    def _jsonl_path(self, user_id: int, channel: str, bot_id: str = "default") -> Path:
        if bot_id == "default":
            self._migrate_legacy(user_id, channel)
        return self._dir / f"{user_id}_{channel}_{bot_id}.jsonl"

    def _md_path(self, user_id: int, channel: str, bot_id: str = "default") -> Path:
        if bot_id == "default":
            self._migrate_legacy(user_id, channel)
        return self._dir / f"{user_id}_{channel}_{bot_id}.md"

    def remember(self, *, user_id: int, channel: str, content: str, bot_id: str = "default") -> None:
        entry = {"ts": datetime.now(timezone.utc).isoformat(), "content": content.strip()}
        with open(self._jsonl_path(user_id, channel, bot_id), "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        self._sync_md(user_id, channel, bot_id)

    def forget(self, *, user_id: int, channel: str, keyword: str, bot_id: str = "default") -> int:
        """Remove entries containing keyword (case-insensitive). Returns count removed."""
        path = self._jsonl_path(user_id, channel, bot_id)
        if not path.exists():
            return 0
        entries = self.list_entries(user_id, channel, bot_id)
        kept = [e for e in entries if keyword.lower() not in e["content"].lower()]
        removed = len(entries) - len(kept)
        with open(path, "w", encoding="utf-8") as f:
            for e in kept:
                f.write(json.dumps(e, ensure_ascii=False) + "\n")
        self._sync_md(user_id, channel, bot_id)
        return removed

    def list_entries(self, user_id: int, channel: str, bot_id: str = "default") -> list[dict[str, Any]]:
        path = self._jsonl_path(user_id, channel, bot_id)
        if not path.exists():
            return []
        entries = []
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line:
                entries.append(json.loads(line))
        return entries

    def render_for_context(self, user_id: int, channel: str, bot_id: str = "default") -> str:
        """Return all entries as a plain-text block for use in prompts."""
        entries = self.list_entries(user_id, channel, bot_id)
        if not entries:
            return ""
        lines = ["## Permanent Memory"] + [f"- {e['content']}" for e in entries]
        return "\n".join(lines)

    def _sync_md(self, user_id: int, channel: str, bot_id: str = "default") -> None:
        entries = self.list_entries(user_id, channel, bot_id)
        md_lines = [f"# Permanent Memory — user {user_id} / {channel} / {bot_id}", ""]
        for e in entries:
            md_lines.append(f"- [{e['ts']}] {e['content']}")
        self._md_path(user_id, channel, bot_id).write_text("\n".join(md_lines) + "\n", encoding="utf-8")
