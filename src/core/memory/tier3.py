# src/core/memory/tier3.py
import asyncio
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
import aiosqlite

logger = logging.getLogger(__name__)


class Tier3Store:
    """SQLite conversation history with WAL mode and FTS5 search.

    All conversation/setting tables carry ``bot_id`` and ``chat_id`` columns
    so the same user can chat with multiple bots across multiple chat scopes
    (DMs and groups) without their histories bleeding together. ``bot_id``
    defaults to ``"default"`` and ``chat_id`` defaults to ``user_id`` (DM
    convention). Pre-multibot databases are migrated in place on
    :meth:`init`; B-1-era databases (have ``bot_id`` but not ``chat_id``)
    are migrated by adding the column with backfill ``chat_id := user_id``.
    """

    _CREATE_TURNS = """
    CREATE TABLE IF NOT EXISTS turns (
        id      INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        channel TEXT    NOT NULL,
        bot_id  TEXT    NOT NULL DEFAULT 'default',
        chat_id INTEGER NOT NULL DEFAULT 0,
        role    TEXT    NOT NULL,
        content TEXT    NOT NULL,
        ts      TEXT    NOT NULL
    )
    """
    _CREATE_IDX = """
    CREATE INDEX IF NOT EXISTS idx_turns_user_channel_bot_chat_ts
    ON turns(user_id, channel, bot_id, chat_id, ts)
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
        bot_id  TEXT    NOT NULL DEFAULT 'default',
        chat_id INTEGER NOT NULL DEFAULT 0,
        key     TEXT    NOT NULL,
        value   TEXT    NOT NULL,
        PRIMARY KEY (user_id, channel, bot_id, chat_id, key)
    )
    """
    _CREATE_USAGE_LOGS = """
    CREATE TABLE IF NOT EXISTS usage_logs (
        id                INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id           INTEGER NOT NULL,
        channel           TEXT    NOT NULL,
        bot_id            TEXT    NOT NULL DEFAULT 'default',
        chat_id           INTEGER NOT NULL DEFAULT 0,
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

    async def _column_exists(self, table: str, column: str) -> bool:
        async with self._db.execute(f"PRAGMA table_info({table})") as cur:
            cols = [r[1] async for r in cur]
        return column in cols

    async def _migrate_add_bot_id(self) -> None:
        """In-place migration: add bot_id to turns/usage_logs (cheap), rebuild
        settings table (PK change requires full table rewrite in SQLite).

        Note: index creation is deferred until after _maybe_add_chat_id runs
        (the chat_id-aware index references chat_id which doesn't exist yet)."""
        # turns: ALTER ADD COLUMN — primary key unchanged (just `id`).
        if not await self._column_exists("turns", "bot_id"):
            await self._db.execute(
                "ALTER TABLE turns ADD COLUMN bot_id TEXT NOT NULL DEFAULT 'default'"
            )
            await self._db.execute("DROP INDEX IF EXISTS idx_turns_user_channel_ts")
        # usage_logs: ALTER ADD COLUMN — primary key unchanged.
        if not await self._column_exists("usage_logs", "bot_id"):
            await self._db.execute(
                "ALTER TABLE usage_logs ADD COLUMN bot_id TEXT NOT NULL DEFAULT 'default'"
            )
        # settings: rebuild table because PK changes.
        if not await self._column_exists("settings", "bot_id"):
            await self._db.executescript("""
                CREATE TABLE settings_new (
                    user_id INTEGER NOT NULL,
                    channel TEXT    NOT NULL,
                    bot_id  TEXT    NOT NULL DEFAULT 'default',
                    key     TEXT    NOT NULL,
                    value   TEXT    NOT NULL,
                    PRIMARY KEY (user_id, channel, bot_id, key)
                );
                INSERT INTO settings_new (user_id, channel, bot_id, key, value)
                SELECT user_id, channel, 'default', key, value FROM settings;
                DROP TABLE settings;
                ALTER TABLE settings_new RENAME TO settings;
            """)
        await self._db.commit()

    async def _maybe_add_chat_id(self) -> None:
        """In-place migration: add chat_id to turns/usage_logs (cheap), rebuild
        settings table because chat_id joins the PRIMARY KEY."""
        # turns
        if not await self._column_exists("turns", "chat_id"):
            await self._db.execute(
                "ALTER TABLE turns ADD COLUMN chat_id INTEGER NOT NULL DEFAULT 0"
            )
            # Backfill: legacy DM rows had no chat_id; we treat user_id as chat_id.
            await self._db.execute(
                "UPDATE turns SET chat_id = user_id WHERE chat_id = 0"
            )
            await self._db.execute(
                "DROP INDEX IF EXISTS idx_turns_user_channel_bot_ts"
            )
            await self._db.execute(self._CREATE_IDX)
        # usage_logs
        if not await self._column_exists("usage_logs", "chat_id"):
            await self._db.execute(
                "ALTER TABLE usage_logs ADD COLUMN chat_id INTEGER NOT NULL DEFAULT 0"
            )
            await self._db.execute(
                "UPDATE usage_logs SET chat_id = user_id WHERE chat_id = 0"
            )
        # settings: rebuild because PK changes.
        if not await self._column_exists("settings", "chat_id"):
            await self._db.executescript("""
                CREATE TABLE settings_new (
                    user_id INTEGER NOT NULL,
                    channel TEXT    NOT NULL,
                    bot_id  TEXT    NOT NULL DEFAULT 'default',
                    chat_id INTEGER NOT NULL DEFAULT 0,
                    key     TEXT    NOT NULL,
                    value   TEXT    NOT NULL,
                    PRIMARY KEY (user_id, channel, bot_id, chat_id, key)
                );
                INSERT INTO settings_new (user_id, channel, bot_id, chat_id, key, value)
                SELECT user_id, channel, bot_id, user_id, key, value FROM settings;
                DROP TABLE settings;
                ALTER TABLE settings_new RENAME TO settings;
            """)
        await self._db.commit()

    async def init(self) -> None:
        self._db = await aiosqlite.connect(str(self._path))
        await self._db.execute("PRAGMA journal_mode=WAL")
        # Create base tables first (CREATE IF NOT EXISTS — safe for legacy DBs
        # because their existing schema satisfies the IF NOT EXISTS check).
        await self._db.execute(self._CREATE_TURNS)
        await self._db.execute(self._CREATE_FTS)
        await self._db.execute(self._CREATE_TRIGGER_AI)
        await self._db.execute(self._CREATE_TRIGGER_AD)
        await self._db.execute(self._CREATE_SETTINGS)
        await self._db.execute(self._CREATE_USAGE_LOGS)
        await self._db.commit()
        # Migrate older shapes BEFORE creating chat_id-aware indexes. Order
        # matters: bot_id must exist before chat_id migration runs.
        await self._migrate_add_bot_id()
        await self._maybe_add_chat_id()
        await self._db.execute(self._CREATE_IDX)
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
            user_id, channel, bot_id, chat_id, role, content, ts, done_event = item
            try:
                await self._db.execute(
                    "INSERT INTO turns(user_id, channel, bot_id, chat_id, role, content, ts) "
                    "VALUES (?,?,?,?,?,?,?)",
                    (user_id, channel, bot_id, chat_id, role, content, ts),
                )
                await self._db.commit()
            except Exception:
                logger.error("DB write failed", exc_info=True)
            finally:
                done_event.set()
                self._write_queue.task_done()

    async def save_turn(
        self, *, user_id: int, channel: str, role: str, content: str,
        bot_id: str = "default", chat_id: int | None = None,
    ) -> None:
        if chat_id is None:
            chat_id = user_id
        ts = datetime.now(timezone.utc).isoformat()
        done_event = asyncio.Event()
        await self._write_queue.put(
            (user_id, channel, bot_id, chat_id, role, content, ts, done_event)
        )
        await done_event.wait()

    async def get_recent(
        self, *, user_id: int, channel: str, n: int,
        bot_id: str = "default", chat_id: int | None = None,
    ) -> list[dict[str, Any]]:
        if chat_id is None:
            chat_id = user_id
        async with self._db.execute(
            """SELECT role, content, ts FROM turns
               WHERE user_id=? AND channel=? AND bot_id=? AND chat_id=?
               ORDER BY id DESC LIMIT ?""",
            (user_id, channel, bot_id, chat_id, n),
        ) as cur:
            rows = await cur.fetchall()
        return [{"role": r["role"], "content": r["content"], "ts": r["ts"]} for r in reversed(rows)]

    async def search(
        self, *, user_id: int, channel: str, query: str, limit: int = 5,
        bot_id: str = "default", chat_id: int | None = None,
    ) -> list[dict[str, Any]]:
        if chat_id is None:
            chat_id = user_id
        async with self._db.execute(
            """SELECT t.role, t.content, t.ts
               FROM turns_fts f
               JOIN turns t ON t.id = f.rowid
               WHERE turns_fts MATCH ? AND t.user_id = ? AND t.channel = ?
                 AND t.bot_id = ? AND t.chat_id = ?
               ORDER BY rank LIMIT ?""",
            (query, user_id, channel, bot_id, chat_id, limit),
        ) as cur:
            rows = await cur.fetchall()
        return [{"role": r["role"], "content": r["content"], "ts": r["ts"]} for r in rows]

    async def count_turns(
        self, *, user_id: int, channel: str,
        bot_id: str = "default", chat_id: int | None = None,
    ) -> int:
        if chat_id is None:
            chat_id = user_id
        async with self._db.execute(
            "SELECT COUNT(*) FROM turns WHERE user_id=? AND channel=? AND bot_id=? AND chat_id=?",
            (user_id, channel, bot_id, chat_id),
        ) as cur:
            row = await cur.fetchone()
        return row[0] if row else 0

    async def get_oldest_turns(
        self, *, user_id: int, channel: str, n: int,
        bot_id: str = "default", chat_id: int | None = None,
    ) -> list[dict[str, Any]]:
        if chat_id is None:
            chat_id = user_id
        async with self._db.execute(
            """SELECT id, role, content, ts FROM turns
               WHERE user_id=? AND channel=? AND bot_id=? AND chat_id=?
               ORDER BY id ASC LIMIT ?""",
            (user_id, channel, bot_id, chat_id, n),
        ) as cur:
            rows = await cur.fetchall()
        return [{"id": r["id"], "role": r["role"], "content": r["content"], "ts": r["ts"]} for r in rows]

    async def prune_before_id(
        self, *, user_id: int, channel: str, before_id: int,
        bot_id: str = "default", chat_id: int | None = None,
    ) -> int:
        if chat_id is None:
            chat_id = user_id
        async with self._db.execute(
            "SELECT COUNT(*) FROM turns WHERE user_id=? AND channel=? AND bot_id=? AND chat_id=? AND id<=?",
            (user_id, channel, bot_id, chat_id, before_id),
        ) as cur:
            row = await cur.fetchone()
        count = row[0] if row else 0
        await self._db.execute(
            "DELETE FROM turns WHERE user_id=? AND channel=? AND bot_id=? AND chat_id=? AND id<=?",
            (user_id, channel, bot_id, chat_id, before_id),
        )
        await self._db.commit()
        return count

    async def get_setting(
        self, *, user_id: int, channel: str, key: str,
        bot_id: str = "default", chat_id: int | None = None,
    ) -> str | None:
        if chat_id is None:
            chat_id = user_id
        async with self._db.execute(
            "SELECT value FROM settings WHERE user_id=? AND channel=? AND bot_id=? AND chat_id=? AND key=?",
            (user_id, channel, bot_id, chat_id, key),
        ) as cur:
            row = await cur.fetchone()
        return row["value"] if row else None

    async def set_setting(
        self, *, user_id: int, channel: str, key: str, value: str,
        bot_id: str = "default", chat_id: int | None = None,
    ) -> None:
        if chat_id is None:
            chat_id = user_id
        await self._db.execute(
            """INSERT INTO settings(user_id, channel, bot_id, chat_id, key, value)
               VALUES (?,?,?,?,?,?)
               ON CONFLICT(user_id, channel, bot_id, chat_id, key) DO UPDATE SET value=excluded.value""",
            (user_id, channel, bot_id, chat_id, key, value),
        )
        await self._db.commit()

    async def get_active_role(
        self, *, user_id: int, channel: str,
        bot_id: str = "default", chat_id: int | None = None,
    ) -> str:
        return (await self.get_setting(
            user_id=user_id, channel=channel, bot_id=bot_id, chat_id=chat_id,
            key="active_role",
        )) or ""

    async def set_active_role(
        self, *, user_id: int, channel: str, role: str,
        bot_id: str = "default", chat_id: int | None = None,
    ) -> None:
        await self.set_setting(
            user_id=user_id, channel=channel, bot_id=bot_id, chat_id=chat_id,
            key="active_role", value=role,
        )

    async def get_voice_enabled(
        self, *, user_id: int, channel: str,
        bot_id: str = "default", chat_id: int | None = None,
    ) -> bool:
        val = await self.get_setting(
            user_id=user_id, channel=channel, bot_id=bot_id, chat_id=chat_id,
            key="voice_enabled",
        )
        return val == "true"

    async def set_voice_enabled(
        self, *, user_id: int, channel: str, enabled: bool,
        bot_id: str = "default", chat_id: int | None = None,
    ) -> None:
        await self.set_setting(
            user_id=user_id, channel=channel, bot_id=bot_id, chat_id=chat_id,
            key="voice_enabled", value="true" if enabled else "false",
        )

    async def get_last_distill_ts(
        self, *, user_id: int, channel: str,
        bot_id: str = "default", chat_id: int | None = None,
    ) -> datetime | None:
        if chat_id is None:
            chat_id = user_id
        async with self._db.execute(
            "SELECT value FROM settings WHERE user_id=? AND channel=? AND bot_id=? AND chat_id=? AND key='last_distill_ts'",
            (user_id, channel, bot_id, chat_id),
        ) as cur:
            row = await cur.fetchone()
        if row is None:
            return None
        return datetime.fromisoformat(row["value"])

    async def set_last_distill_ts(
        self, *, user_id: int, channel: str, ts: datetime,
        bot_id: str = "default", chat_id: int | None = None,
    ) -> None:
        if chat_id is None:
            chat_id = user_id
        await self._db.execute(
            """INSERT INTO settings(user_id, channel, bot_id, chat_id, key, value)
               VALUES (?,?,?,?,'last_distill_ts',?)
               ON CONFLICT(user_id, channel, bot_id, chat_id, key) DO UPDATE SET value=excluded.value""",
            (user_id, channel, bot_id, chat_id, ts.isoformat()),
        )
        await self._db.commit()

    async def log_usage(
        self, *, user_id: int, channel: str, runner: str,
        prompt_tokens: int, completion_tokens: int,
        bot_id: str = "default", chat_id: int | None = None,
    ) -> None:
        if chat_id is None:
            chat_id = user_id
        ts = datetime.now(timezone.utc).isoformat()
        total = prompt_tokens + completion_tokens
        await self._db.execute(
            """INSERT INTO usage_logs(user_id, channel, bot_id, chat_id, runner, prompt_tokens,
               completion_tokens, total_tokens, ts) VALUES (?,?,?,?,?,?,?,?,?)""",
            (user_id, channel, bot_id, chat_id, runner, prompt_tokens, completion_tokens, total, ts),
        )
        await self._db.commit()

    async def get_token_usage_since(self, *, user_id: int, since_iso: str) -> int:
        """Return total tokens used by user since since_iso (ISO 8601 string).

        Aggregates across ALL bots intentionally — usage budgets are per-user."""
        async with self._db.execute(
            "SELECT COALESCE(SUM(total_tokens), 0) AS t FROM usage_logs WHERE user_id=? AND ts >= ?",
            (user_id, since_iso),
        ) as cur:
            row = await cur.fetchone()
        return int(row["t"]) if row else 0

    async def get_dispatch_count_since(self, *, user_id: int, since_iso: str) -> int:
        """Return number of dispatch entries (rows) for user since since_iso.

        Aggregates across ALL bots intentionally."""
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
