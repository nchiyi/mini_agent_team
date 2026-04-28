# src/gateway/session.py
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.core.memory.tier3 import Tier3Store

logger = logging.getLogger(__name__)


@dataclass
class Session:
    user_id: int
    channel: str
    current_runner: str
    cwd: str
    bot_id: str = "default"
    chat_id: int | None = None
    active_role: str = ""
    pending_reasoning: str = ""
    last_active: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def touch(self) -> None:
        self.last_active = datetime.now(timezone.utc)


# Module-level dicts kept for backward compatibility (skills/modules that import directly).
# main.py uses SessionManager methods instead.
_ACTIVE_ROLES: dict[tuple[int, str], str] = {}
_VOICE_ENABLED: dict[tuple[int, str], bool] = {}


def get_active_role(user_id: int, channel: str) -> str:
    return _ACTIVE_ROLES.get((user_id, channel), "")


def set_active_role(user_id: int, channel: str, role: str) -> None:
    key = (user_id, channel)
    if role:
        _ACTIVE_ROLES[key] = role
    else:
        _ACTIVE_ROLES.pop(key, None)


def clear_active_role(user_id: int, channel: str) -> None:
    set_active_role(user_id, channel, "")


def is_voice_enabled(user_id: int, channel: str) -> bool:
    return _VOICE_ENABLED.get((user_id, channel), False)


def set_voice_enabled(user_id: int, channel: str, enabled: bool) -> None:
    _VOICE_ENABLED[(user_id, channel)] = enabled


class SessionManager:
    def __init__(self, idle_minutes: int, default_runner: str, default_cwd: str):
        self._idle_minutes = idle_minutes
        self._default_runner = default_runner
        self._default_cwd = default_cwd
        self._sessions: dict[tuple[int, str, str, int], Session] = {}
        self._active_roles: dict[tuple[int, str, str, int], str] = {}
        self._voice_enabled: dict[tuple[int, str, str, int], bool] = {}
        self._tier3: "Tier3Store | None" = None
        self._settings_loaded: set[tuple[int, str, str, int]] = set()

    def attach_tier3(self, tier3: "Tier3Store") -> None:
        """Attach a Tier3Store so settings are persisted to SQLite."""
        self._tier3 = tier3

    # ── role state ────────────────────────────────────────────────────────

    def get_active_role(
        self, user_id: int, channel: str, bot_id: str = "default",
        chat_id: int | None = None,
    ) -> str:
        if chat_id is None:
            chat_id = user_id
        return self._active_roles.get((user_id, channel, bot_id, chat_id), "")

    def set_active_role(
        self, user_id: int, channel: str, role: str, bot_id: str = "default",
        chat_id: int | None = None,
    ) -> None:
        if chat_id is None:
            chat_id = user_id
        key = (user_id, channel, bot_id, chat_id)
        if role:
            self._active_roles[key] = role
        else:
            self._active_roles.pop(key, None)
        session = self._sessions.get(key)
        if session:
            session.active_role = role
        if self._tier3 is not None:
            try:
                asyncio.get_event_loop().create_task(
                    self._tier3.set_active_role(user_id=user_id, channel=channel, role=role)
                )
            except RuntimeError:
                pass

    def clear_active_role(
        self, user_id: int, channel: str, bot_id: str = "default",
        chat_id: int | None = None,
    ) -> None:
        self.set_active_role(user_id, channel, "", bot_id, chat_id)

    # ── voice state ───────────────────────────────────────────────────────

    def is_voice_enabled(
        self, user_id: int, channel: str, bot_id: str = "default",
        chat_id: int | None = None,
    ) -> bool:
        if chat_id is None:
            chat_id = user_id
        return self._voice_enabled.get((user_id, channel, bot_id, chat_id), False)

    def set_voice_enabled(
        self, user_id: int, channel: str, enabled: bool, bot_id: str = "default",
        chat_id: int | None = None,
    ) -> None:
        if chat_id is None:
            chat_id = user_id
        self._voice_enabled[(user_id, channel, bot_id, chat_id)] = enabled
        if self._tier3 is not None:
            try:
                asyncio.get_event_loop().create_task(
                    self._tier3.set_voice_enabled(user_id=user_id, channel=channel, enabled=enabled)
                )
            except RuntimeError:
                pass

    # ── settings restore ──────────────────────────────────────────────────

    async def restore_settings_if_needed(
        self, user_id: int, channel: str, bot_id: str = "default",
        chat_id: int | None = None,
    ) -> None:
        """Load persisted settings from DB once per (user_id, channel, bot_id, chat_id) per process."""
        if chat_id is None:
            chat_id = user_id
        key = (user_id, channel, bot_id, chat_id)
        if key in self._settings_loaded or self._tier3 is None:
            return
        self._settings_loaded.add(key)
        try:
            role = await self._tier3.get_active_role(user_id=user_id, channel=channel)
            if role:
                self._active_roles[key] = role
                session = self._sessions.get(key)
                if session:
                    session.active_role = role
            voice = await self._tier3.get_voice_enabled(user_id=user_id, channel=channel)
            if voice:
                self._voice_enabled[key] = voice
        except Exception:
            logger.debug("Failed to restore settings for %s/%s", user_id, channel, exc_info=True)

    # ── session lifecycle ─────────────────────────────────────────────────

    def get_or_create(
        self,
        user_id: int,
        channel: str,
        bot_id: str = "default",
        chat_id: int | None = None,
        default_runner_override: str | None = None,
        default_role_override: str | None = None,
    ) -> Session:
        if chat_id is None:
            chat_id = user_id
        key = (user_id, channel, bot_id, chat_id)
        if key not in self._sessions:
            self._sessions[key] = Session(
                user_id=user_id,
                channel=channel,
                bot_id=bot_id,
                chat_id=chat_id,
                current_runner=default_runner_override or self._default_runner,
                cwd=self._default_cwd,
                active_role=(
                    default_role_override
                    if default_role_override is not None
                    else self.get_active_role(user_id, channel, bot_id, chat_id)
                ),
            )
        else:
            self._sessions[key].active_role = self.get_active_role(
                user_id, channel, bot_id, chat_id,
            )
        self._sessions[key].touch()
        return self._sessions[key]

    def release_idle(self) -> None:
        now = datetime.now(timezone.utc)
        cutoff = timedelta(minutes=self._idle_minutes)
        stale = [k for k, s in self._sessions.items() if now - s.last_active > cutoff]
        for k in stale:
            del self._sessions[k]
