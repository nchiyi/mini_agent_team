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

    async def close(self) -> None:
        if self._writer_task:
            await self._write_queue.put(None)
            await self._writer_task
        if self._db:
            await self._db.close()
