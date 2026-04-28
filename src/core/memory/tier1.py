import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


class Tier1Store:
    """Permanent per-(user, channel, bot, chat) memory stored as a JSONL file.

    Each line: {"ts": "...", "content": "..."}.
    A human-readable .md copy is kept in sync alongside the JSONL.
    Files are named ``{user_id}_{channel}_{bot_id}_{chat_id}.jsonl`` so the
    same user can chat with multiple bots across multiple chat scopes (DMs and
    groups) without their stores bleeding together. ``bot_id`` defaults to
    ``"default"`` and ``chat_id`` defaults to ``user_id`` (DM convention).
    Legacy file shapes are transparently renamed on first access:
      - pre-multibot: ``{uid}_{ch}.jsonl`` → ``{uid}_{ch}_default_{uid}.jsonl``
      - post-B-1:     ``{uid}_{ch}_{bid}.jsonl`` → ``{uid}_{ch}_{bid}_{uid}.jsonl``
    """

    def __init__(self, permanent_dir: str):
        self._dir = Path(permanent_dir)
        self._dir.mkdir(parents=True, exist_ok=True)

    def _migrate_legacy(self, user_id: int, channel: str, bot_id: str = "default") -> None:
        """Rename legacy shapes to the new {uid}_{ch}_{bid}_{uid} form (DM convention).

        Order matters: try B-1 shape first; only fall through to pre-multibot
        when bot_id == 'default' (pre-multibot files had no bot_id segment)."""
        for ext in ("jsonl", "md"):
            new = self._dir / f"{user_id}_{channel}_{bot_id}_{user_id}.{ext}"
            if new.exists():
                continue
            # B-1 shape: {uid}_{ch}_{bid}.{ext}
            b1_legacy = self._dir / f"{user_id}_{channel}_{bot_id}.{ext}"
            if b1_legacy.exists():
                b1_legacy.rename(new)
                continue
            # Pre-multibot shape: {uid}_{ch}.{ext} (only valid for default bot)
            if bot_id == "default":
                old = self._dir / f"{user_id}_{channel}.{ext}"
                if old.exists():
                    old.rename(new)

    def _jsonl_path(
        self, user_id: int, channel: str, bot_id: str = "default",
        chat_id: int | None = None,
    ) -> Path:
        if chat_id is None:
            chat_id = user_id
        if chat_id == user_id:
            # Only DM-shape paths can be migrated from legacy on-disk shapes.
            self._migrate_legacy(user_id, channel, bot_id)
        return self._dir / f"{user_id}_{channel}_{bot_id}_{chat_id}.jsonl"

    def _md_path(
        self, user_id: int, channel: str, bot_id: str = "default",
        chat_id: int | None = None,
    ) -> Path:
        if chat_id is None:
            chat_id = user_id
        if chat_id == user_id:
            self._migrate_legacy(user_id, channel, bot_id)
        return self._dir / f"{user_id}_{channel}_{bot_id}_{chat_id}.md"

    def remember(
        self, *, user_id: int, channel: str, content: str,
        bot_id: str = "default", chat_id: int | None = None,
    ) -> None:
        entry = {"ts": datetime.now(timezone.utc).isoformat(), "content": content.strip()}
        with open(self._jsonl_path(user_id, channel, bot_id, chat_id), "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        self._sync_md(user_id, channel, bot_id, chat_id)

    def forget(
        self, *, user_id: int, channel: str, keyword: str,
        bot_id: str = "default", chat_id: int | None = None,
    ) -> int:
        """Remove entries containing keyword (case-insensitive). Returns count removed."""
        path = self._jsonl_path(user_id, channel, bot_id, chat_id)
        if not path.exists():
            return 0
        entries = self.list_entries(user_id, channel, bot_id, chat_id)
        kept = [e for e in entries if keyword.lower() not in e["content"].lower()]
        removed = len(entries) - len(kept)
        with open(path, "w", encoding="utf-8") as f:
            for e in kept:
                f.write(json.dumps(e, ensure_ascii=False) + "\n")
        self._sync_md(user_id, channel, bot_id, chat_id)
        return removed

    def list_entries(
        self, user_id: int, channel: str, bot_id: str = "default",
        chat_id: int | None = None,
    ) -> list[dict[str, Any]]:
        path = self._jsonl_path(user_id, channel, bot_id, chat_id)
        if not path.exists():
            return []
        entries = []
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line:
                entries.append(json.loads(line))
        return entries

    def render_for_context(
        self, user_id: int, channel: str, bot_id: str = "default",
        chat_id: int | None = None,
    ) -> str:
        """Return all entries as a plain-text block for use in prompts."""
        entries = self.list_entries(user_id, channel, bot_id, chat_id)
        if not entries:
            return ""
        lines = ["## Permanent Memory"] + [f"- {e['content']}" for e in entries]
        return "\n".join(lines)

    def _sync_md(
        self, user_id: int, channel: str, bot_id: str = "default",
        chat_id: int | None = None,
    ) -> None:
        entries = self.list_entries(user_id, channel, bot_id, chat_id)
        if chat_id is None:
            chat_id = user_id
        md_lines = [
            f"# Permanent Memory — user {user_id} / {channel} / {bot_id} / chat {chat_id}",
            "",
        ]
        for e in entries:
            md_lines.append(f"- [{e['ts']}] {e['content']}")
        self._md_path(user_id, channel, bot_id, chat_id).write_text(
            "\n".join(md_lines) + "\n", encoding="utf-8",
        )
