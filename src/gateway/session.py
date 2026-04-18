# src/gateway/session.py
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta


@dataclass
class Session:
    user_id: int
    channel: str
    current_runner: str
    cwd: str
    last_active: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def touch(self) -> None:
        self.last_active = datetime.now(timezone.utc)


class SessionManager:
    def __init__(self, idle_minutes: int, default_runner: str, default_cwd: str):
        self._idle_minutes = idle_minutes
        self._default_runner = default_runner
        self._default_cwd = default_cwd
        self._sessions: dict[tuple[int, str], Session] = {}

    def get_or_create(self, user_id: int, channel: str) -> Session:
        key = (user_id, channel)
        if key not in self._sessions:
            self._sessions[key] = Session(
                user_id=user_id,
                channel=channel,
                current_runner=self._default_runner,
                cwd=self._default_cwd,
            )
        self._sessions[key].touch()
        return self._sessions[key]

    def release_idle(self) -> None:
        now = datetime.now(timezone.utc)
        cutoff = timedelta(minutes=self._idle_minutes)
        stale = [k for k, s in self._sessions.items() if now - s.last_active > cutoff]
        for k in stale:
            del self._sessions[k]
