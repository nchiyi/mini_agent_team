import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path


class AuditLog:
    def __init__(self, audit_dir: str, max_entries: int):
        self._dir = Path(audit_dir)
        self._dir.mkdir(parents=True, exist_ok=True)
        self._max_entries = max_entries
        self._lock = asyncio.Lock()

    async def write(self, *, user_id: int, channel: str, runner: str, prompt: str, cwd: str) -> None:
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        log_file = self._dir / f"{today}.jsonl"
        entry = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "user_id": user_id,
            "channel": channel,
            "runner": runner,
            "prompt": prompt[:200],
            "cwd": cwd,
        }
        async with self._lock:
            with open(log_file, "a", encoding="utf-8") as f:
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")
