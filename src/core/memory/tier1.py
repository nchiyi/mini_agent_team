import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


class Tier1Store:
    """Permanent per-user-per-channel memory stored as a JSONL file.

    Each line: {"ts": "...", "content": "..."}.
    A human-readable .md copy is kept in sync alongside the JSONL.
    """

    def __init__(self, permanent_dir: str):
        self._dir = Path(permanent_dir)
        self._dir.mkdir(parents=True, exist_ok=True)

    def _jsonl_path(self, user_id: int, channel: str) -> Path:
        return self._dir / f"{user_id}_{channel}.jsonl"

    def _md_path(self, user_id: int, channel: str) -> Path:
        return self._dir / f"{user_id}_{channel}.md"

    def remember(self, *, user_id: int, channel: str, content: str) -> None:
        entry = {"ts": datetime.now(timezone.utc).isoformat(), "content": content.strip()}
        with open(self._jsonl_path(user_id, channel), "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        self._sync_md(user_id, channel)

    def forget(self, *, user_id: int, channel: str, keyword: str) -> int:
        """Remove entries containing keyword (case-insensitive). Returns count removed."""
        path = self._jsonl_path(user_id, channel)
        if not path.exists():
            return 0
        entries = self.list_entries(user_id, channel)
        kept = [e for e in entries if keyword.lower() not in e["content"].lower()]
        removed = len(entries) - len(kept)
        with open(path, "w", encoding="utf-8") as f:
            for e in kept:
                f.write(json.dumps(e, ensure_ascii=False) + "\n")
        self._sync_md(user_id, channel)
        return removed

    def list_entries(self, user_id: int, channel: str) -> list[dict[str, Any]]:
        path = self._jsonl_path(user_id, channel)
        if not path.exists():
            return []
        entries = []
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line:
                entries.append(json.loads(line))
        return entries

    def render_for_context(self, user_id: int, channel: str) -> str:
        """Return all entries as a plain-text block for use in prompts."""
        entries = self.list_entries(user_id, channel)
        if not entries:
            return ""
        lines = ["## Permanent Memory"] + [f"- {e['content']}" for e in entries]
        return "\n".join(lines)

    def _sync_md(self, user_id: int, channel: str) -> None:
        entries = self.list_entries(user_id, channel)
        md_lines = [f"# Permanent Memory — user {user_id} / {channel}", ""]
        for e in entries:
            md_lines.append(f"- [{e['ts']}] {e['content']}")
        self._md_path(user_id, channel).write_text("\n".join(md_lines) + "\n", encoding="utf-8")
