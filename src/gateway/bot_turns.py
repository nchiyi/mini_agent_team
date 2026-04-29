"""Per-chat counter that caps consecutive bot-to-bot turns.

Without this, two MAT bots in the same group with
``allow_bot_messages = "all"`` could ping-pong forever. Mirroring
OpenAB's pattern: ``cap=10`` consecutive bot turns, reset to zero on
any human message. ``cap_reached`` returns True once the counter
reaches the cap; the dispatcher then drops further bot-sourced inbounds
until a human input resets the counter.

Thread-safe: a single ``threading.Lock`` guards the dict. Updates are
hot (every group message), reads are hot too — keep the critical
section tiny.
"""
from __future__ import annotations

import threading
from collections import OrderedDict
from dataclasses import dataclass, field


@dataclass
class BotTurnTracker:
    cap: int = 10
    max_seen_message_ids: int = 4096
    _counts: dict[tuple[str, int], int] = field(default_factory=dict)
    _seen_message_ids: OrderedDict[tuple[str, int | None, str], None] = field(
        default_factory=OrderedDict,
    )
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def claim_message(
        self, *, channel: str, chat_id: int | None, message_id: str | None,
    ) -> bool:
        """Return True only for the first bot that sees a non-empty message_id.

        Empty IDs are not deduplicated so callers keep the legacy per-bot
        policy path when a channel cannot provide a stable message id.
        """
        if not message_id:
            return True

        key = (channel, chat_id, message_id)
        with self._lock:
            if key in self._seen_message_ids:
                return False
            self._seen_message_ids[key] = None
            self._seen_message_ids.move_to_end(key)
            while len(self._seen_message_ids) > self.max_seen_message_ids:
                self._seen_message_ids.popitem(last=False)
            return True

    def note_bot_turn(self, *, channel: str, chat_id: int) -> None:
        """Record one bot-sourced turn in (channel, chat_id)."""
        with self._lock:
            key = (channel, chat_id)
            self._counts[key] = self._counts.get(key, 0) + 1

    def reset_on_human(self, *, channel: str, chat_id: int) -> None:
        """Zero the counter — call on any human-sourced inbound."""
        with self._lock:
            self._counts.pop((channel, chat_id), None)

    def consecutive(self, *, channel: str, chat_id: int) -> int:
        with self._lock:
            return self._counts.get((channel, chat_id), 0)

    def cap_reached(self, *, channel: str, chat_id: int) -> bool:
        return self.consecutive(channel=channel, chat_id=chat_id) >= self.cap
