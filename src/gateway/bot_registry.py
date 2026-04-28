"""Process-wide registry mapping channel @usernames to MAT bot ids.

Populated at startup: each ``run_*_for_bot`` calls ``getMe()`` (or the
channel-specific equivalent) once, then registers
``(channel, lowered-username) → bot_id``. Looked up at message dispatch
time to translate user-typed @mentions into bot ids.

Thread-safe: register / resolve / all all guard the dicts with a single
``threading.Lock``. Updates are infrequent (startup-only), reads are hot.
"""
from __future__ import annotations

import threading
from dataclasses import dataclass, field


@dataclass
class BotRegistry:
    _by_channel_username: dict[tuple[str, str], str] = field(default_factory=dict)
    _by_channel_bot_ids: dict[str, set[str]] = field(default_factory=dict)
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def register(self, *, channel: str, username: str, bot_id: str) -> None:
        """Register ``@username`` (case-insensitive, leading @ stripped) → bot_id."""
        key = (channel, username.lstrip("@").lower())
        with self._lock:
            self._by_channel_username[key] = bot_id
            self._by_channel_bot_ids.setdefault(channel, set()).add(bot_id)

    def resolve(self, *, channel: str, username: str) -> str | None:
        """Return ``bot_id`` for the given (channel, @username) or None."""
        key = (channel, username.lstrip("@").lower())
        with self._lock:
            return self._by_channel_username.get(key)

    def all(self, *, channel: str) -> list[str]:
        """Return all registered bot_ids for the given channel, sorted for determinism."""
        with self._lock:
            return sorted(self._by_channel_bot_ids.get(channel, set()))
