# src/core/memory/tier3.py
import asyncio
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
import aiosqlite

logger = logging.getLogger(__name__)


class Tier3Store:
    """SQLite conversation history with WAL mode and FTS5 search."""

    _CREATE_TURNS = """
    CREATE TABLE IF NOT EXISTS turns (
        id      INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        channel TEXT    NOT NULL,
        role    TEXT    NOT NULL,
        content TEXT    NOT NULL,
        ts      TEXT    NOT NULL
    )
    """
    _CREATE_IDX = """
    CREATE INDEX IF NOT EXISTS idx_turns_user_channel_ts
    ON turns(user_id, channel, ts)
    """
    _CREATE_FTS = """
    CREATE VIRTUAL TABLE IF NOT EXISTS turns_fts USING fts5(
        content,
        content=turns,
        content_rowid=id,
        tokenize='unicode61'
    )
    """
    _CREATE_TRIGGER_AI = """
    CREATE TRIGGER IF NOT EXISTS turns_ai AFTER INSERT ON turns BEGIN
        INSERT INTO turns_fts(rowid, content) VALUES (new.id, new.content);
    END
    """
    _CREATE_TRIGGER_AD = """
    CREATE TRIGGER IF NOT EXISTS turns_ad AFTER DELETE ON turns BEGIN
        INSERT INTO turns_fts(turns_fts, rowid, content)
        VALUES ('delete', old.id, old.content);
    END
    """
    _CREATE_SETTINGS = """
    CREATE TABLE IF NOT EXISTS settings (
        user_id INTEGER NOT NULL,
        channel TEXT    NOT NULL,
        key     TEXT    NOT NULL,
        value   TEXT    NOT NULL,
        PRIMARY KEY (user_id, channel, key)
    )
    """
    _CREATE_USAGE_LOGS = """
    CREATE TABLE IF NOT EXISTS usage_logs (
        id                INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id           INTEGER NOT NULL,
        channel           TEXT    NOT NULL,
        runner            TEXT    NOT NULL,
        prompt_tokens     INTEGER DEFAULT 0,
        completion_tokens INTEGER DEFAULT 0,
        total_tokens      INTEGER DEFAULT 0,
        ts                TEXT    NOT NULL
    )
    """
    _CREATE_USAGE_IDX = """
    CREATE INDEX IF NOT EXISTS idx_usage_user_runner
    ON usage_logs(user_id, runner)
    """
    _CREATE_USAGE_TS_IDX = """
    CREATE INDEX IF NOT EXISTS idx_usage_user_ts
    ON usage_logs(user_id, ts)
    """

    def __init__(self, db_path: str):
        self._path = Path(db_path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._db: aiosqlite.Connection | None = None
        self._write_queue: asyncio.Queue = asyncio.Queue()
        self._writer_task: asyncio.Task | None = None

    async def init(self) -> None:
        self._db = await aiosqlite.connect(str(self._path))
        await self._db.execute("PRAGMA journal_mode=WAL")
        await self._db.execute(self._CREATE_TURNS)
        await self._db.execute(self._CREATE_IDX)
        await self._db.execute(self._CREATE_FTS)
        await self._db.execute(self._CREATE_TRIGGER_AI)
        await self._db.execute(self._CREATE_TRIGGER_AD)
        await self._db.execute(self._CREATE_SETTINGS)
        await self._db.execute(self._CREATE_USAGE_LOGS)
        await self._db.execute(self._CREATE_USAGE_IDX)
        await self._db.execute(self._CREATE_USAGE_TS_IDX)
        await self._db.commit()
        self._db.row_factory = aiosqlite.Row
        self._writer_task = asyncio.create_task(self._writer_loop())

    async def _writer_loop(self) -> None:
        while True:
            item = await self._write_queue.get()
            if item is None:
                break
            user_id, channel, role, content, ts, done_event = item
            try:
                await self._db.execute(
                    "INSERT INTO turns(user_id, channel, role, content, ts) VALUES (?,?,?,?,?)",
                    (user_id, channel, role, content, ts),
                )
                await self._db.commit()
            except Exception:
                logger.error("DB write failed", exc_info=True)
            finally:
                done_event.set()
                self._write_queue.task_done()

    async def save_turn(
        self, *, user_id: int, channel: str, role: str, content: str
    ) -> None:
        ts = datetime.now(timezone.utc).isoformat()
        done_event = asyncio.Event()
        await self._write_queue.put((user_id, channel, role, content, ts, done_event))
        await done_event.wait()

    async def get_recent(
        self, *, user_id: int, channel: str, n: int
    ) -> list[dict[str, Any]]:
        async with self._db.execute(
            """SELECT role, content, ts FROM turns
               WHERE user_id=? AND channel=?
               ORDER BY id DESC LIMIT ?""",
            (user_id, channel, n),
        ) as cur:
            rows = await cur.fetchall()
        return [{"role": r["role"], "content": r["content"], "ts": r["ts"]} for r in reversed(rows)]

    async def search(
        self, *, user_id: int, channel: str, query: str, limit: int = 5
    ) -> list[dict[str, Any]]:
        async with self._db.execute(
            """SELECT t.role, t.content, t.ts
               FROM turns_fts f
               JOIN turns t ON t.id = f.rowid
               WHERE turns_fts MATCH ? AND t.user_id = ? AND t.channel = ?
               ORDER BY rank LIMIT ?""",
            (query, user_id, channel, limit),
        ) as cur:
            rows = await cur.fetchall()
        return [{"role": r["role"], "content": r["content"], "ts": r["ts"]} for r in rows]

    async def count_turns(self, *, user_id: int, channel: str) -> int:
        async with self._db.execute(
            "SELECT COUNT(*) FROM turns WHERE user_id=? AND channel=?",
            (user_id, channel),
        ) as cur:
            row = await cur.fetchone()
        return row[0] if row else 0

    async def get_oldest_turns(
        self, *, user_id: int, channel: str, n: int
    ) -> list[dict[str, Any]]:
        async with self._db.execute(
            """SELECT id, role, content, ts FROM turns
               WHERE user_id=? AND channel=?
               ORDER BY id ASC LIMIT ?""",
            (user_id, channel, n),
        ) as cur:
            rows = await cur.fetchall()
        return [{"id": r["id"], "role": r["role"], "content": r["content"], "ts": r["ts"]} for r in rows]

    async def prune_before_id(self, *, user_id: int, channel: str, before_id: int) -> int:
        async with self._db.execute(
            "SELECT COUNT(*) FROM turns WHERE user_id=? AND channel=? AND id<=?",
            (user_id, channel, before_id),
        ) as cur:
            row = await cur.fetchone()
        count = row[0] if row else 0
        await self._db.execute(
            "DELETE FROM turns WHERE user_id=? AND channel=? AND id<=?",
            (user_id, channel, before_id),
        )
        await self._db.commit()
        return count

    async def get_setting(self, *, user_id: int, channel: str, key: str) -> str | None:
        async with self._db.execute(
            "SELECT value FROM settings WHERE user_id=? AND channel=? AND key=?",
            (user_id, channel, key),
        ) as cur:
            row = await cur.fetchone()
        return row["value"] if row else None

    async def set_setting(self, *, user_id: int, channel: str, key: str, value: str) -> None:
        await self._db.execute(
            """INSERT INTO settings(user_id, channel, key, value) VALUES (?,?,?,?)
               ON CONFLICT(user_id, channel, key) DO UPDATE SET value=excluded.value""",
            (user_id, channel, key, value),
        )
        await self._db.commit()

    async def get_active_role(self, *, user_id: int, channel: str) -> str:
        return (await self.get_setting(user_id=user_id, channel=channel, key="active_role")) or ""

    async def set_active_role(self, *, user_id: int, channel: str, role: str) -> None:
        await self.set_setting(user_id=user_id, channel=channel, key="active_role", value=role)

    async def get_voice_enabled(self, *, user_id: int, channel: str) -> bool:
        val = await self.get_setting(user_id=user_id, channel=channel, key="voice_enabled")
        return val == "true"

    async def set_voice_enabled(self, *, user_id: int, channel: str, enabled: bool) -> None:
        await self.set_setting(
            user_id=user_id, channel=channel,
            key="voice_enabled", value="true" if enabled else "false",
        )

    async def get_last_distill_ts(self, *, user_id: int, channel: str) -> datetime | None:
        async with self._db.execute(
            "SELECT value FROM settings WHERE user_id=? AND channel=? AND key='last_distill_ts'",
            (user_id, channel),
        ) as cur:
            row = await cur.fetchone()
        if row is None:
            return None
        return datetime.fromisoformat(row["value"])

    async def set_last_distill_ts(self, *, user_id: int, channel: str, ts: datetime) -> None:
        await self._db.execute(
            """INSERT INTO settings(user_id, channel, key, value) VALUES (?,?,'last_distill_ts',?)
               ON CONFLICT(user_id, channel, key) DO UPDATE SET value=excluded.value""",
            (user_id, channel, ts.isoformat()),
        )
        await self._db.commit()

    async def log_usage(
        self, *, user_id: int, channel: str, runner: str,
        prompt_tokens: int, completion_tokens: int,
    ) -> None:
        ts = datetime.now(timezone.utc).isoformat()
        total = prompt_tokens + completion_tokens
        await self._db.execute(
            """INSERT INTO usage_logs(user_id, channel, runner, prompt_tokens,
               completion_tokens, total_tokens, ts) VALUES (?,?,?,?,?,?,?)""",
            (user_id, channel, runner, prompt_tokens, completion_tokens, total, ts),
        )
        await self._db.commit()

    async def get_token_usage_since(self, *, user_id: int, since_iso: str) -> int:
        """Return total tokens used by user since since_iso (ISO 8601 string)."""
        async with self._db.execute(
            "SELECT COALESCE(SUM(total_tokens), 0) AS t FROM usage_logs WHERE user_id=? AND ts >= ?",
            (user_id, since_iso),
        ) as cur:
            row = await cur.fetchone()
        return int(row["t"]) if row else 0

    async def get_dispatch_count_since(self, *, user_id: int, since_iso: str) -> int:
        """Return number of dispatch entries (rows) for user since since_iso."""
        async with self._db.execute(
            "SELECT COUNT(*) AS n FROM usage_logs WHERE user_id=? AND ts >= ?",
            (user_id, since_iso),
        ) as cur:
            row = await cur.fetchone()
        return int(row["n"]) if row else 0

    async def get_usage_summary(self, *, user_id: int) -> dict[str, dict[str, int]]:
        async with self._db.execute(
            """SELECT runner,
                      SUM(prompt_tokens)     AS p,
                      SUM(completion_tokens) AS c,
                      SUM(total_tokens)      AS t
               FROM usage_logs WHERE user_id=?
               GROUP BY runner ORDER BY t DESC""",
            (user_id,),
        ) as cur:
            rows = await cur.fetchall()
        return {
            r["runner"]: {"prompt": r["p"], "completion": r["c"], "total": r["t"]}
            for r in rows
        }

    async def close(self) -> None:
        if self._writer_task:
            await self._write_queue.put(None)
            await self._writer_task
        if self._db:
            await self._db.close()
