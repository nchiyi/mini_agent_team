"""B-2 Task 7: chat_id column migration on Tier3 over a post-B-1 database."""
import pytest
import sqlite3
from pathlib import Path


def _build_post_b1_db(path: Path) -> None:
    """Build a tier3 DB matching the post-B-1 schema (has bot_id but not chat_id)."""
    con = sqlite3.connect(path)
    con.executescript("""
        CREATE TABLE turns (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            channel TEXT NOT NULL,
            bot_id TEXT NOT NULL DEFAULT 'default',
            role TEXT NOT NULL,
            content TEXT NOT NULL,
            ts TEXT NOT NULL
        );
        CREATE TABLE settings (
            user_id INTEGER NOT NULL,
            channel TEXT NOT NULL,
            bot_id TEXT NOT NULL DEFAULT 'default',
            key TEXT NOT NULL,
            value TEXT NOT NULL,
            PRIMARY KEY (user_id, channel, bot_id, key)
        );
        CREATE TABLE usage_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            channel TEXT NOT NULL,
            bot_id TEXT NOT NULL DEFAULT 'default',
            runner TEXT NOT NULL,
            prompt_tokens INTEGER DEFAULT 0,
            completion_tokens INTEGER DEFAULT 0,
            total_tokens INTEGER DEFAULT 0,
            ts TEXT NOT NULL
        );
        INSERT INTO turns (user_id, channel, bot_id, role, content, ts)
        VALUES (42, 'telegram', 'default', 'user', 'pre-existing DM', '2026-04-29T00:00:00Z');
        INSERT INTO settings (user_id, channel, bot_id, key, value)
        VALUES (42, 'telegram', 'default', 'active_role', 'fullstack-dev');
    """)
    con.commit()
    con.close()


@pytest.mark.asyncio
async def test_legacy_dm_turn_visible_under_user_id_chat(tmp_path):
    """ALTER backfills chat_id = user_id for existing rows; legacy DM history
    surfaces when caller queries with chat_id=user_id."""
    db = tmp_path / "post-b1.db"
    _build_post_b1_db(db)
    from src.core.memory.tier3 import Tier3Store
    store = Tier3Store(str(db))
    await store.init()
    rows = await store.get_recent(
        user_id=42, channel="telegram", bot_id="default", chat_id=42, n=10,
    )
    assert any(r["content"] == "pre-existing DM" for r in rows)
    other = await store.get_recent(
        user_id=42, channel="telegram", bot_id="default", chat_id=-100, n=10,
    )
    assert other == []
    await store.close()


@pytest.mark.asyncio
async def test_legacy_settings_survive_chat_id_pk_rebuild(tmp_path):
    db = tmp_path / "post-b1.db"
    _build_post_b1_db(db)
    from src.core.memory.tier3 import Tier3Store
    store = Tier3Store(str(db))
    await store.init()
    val = await store.get_setting(
        user_id=42, channel="telegram", bot_id="default", chat_id=42, key="active_role",
    )
    assert val == "fullstack-dev"
    val2 = await store.get_setting(
        user_id=42, channel="telegram", bot_id="default", chat_id=-100, key="active_role",
    )
    assert val2 is None
    await store.close()


@pytest.mark.asyncio
async def test_chat_id_isolation_on_fresh_db(tmp_path):
    db = tmp_path / "fresh.db"
    from src.core.memory.tier3 import Tier3Store
    store = Tier3Store(str(db))
    await store.init()
    await store.save_turn(
        user_id=1, channel="telegram", bot_id="dev", chat_id=-100,
        role="user", content="group fact",
    )
    await store.save_turn(
        user_id=1, channel="telegram", bot_id="dev", chat_id=1,
        role="user", content="dm fact",
    )
    group_rows = await store.get_recent(
        user_id=1, channel="telegram", bot_id="dev", chat_id=-100, n=10,
    )
    dm_rows = await store.get_recent(
        user_id=1, channel="telegram", bot_id="dev", chat_id=1, n=10,
    )
    assert any(r["content"] == "group fact" for r in group_rows)
    assert all(r["content"] != "group fact" for r in dm_rows)
    assert any(r["content"] == "dm fact" for r in dm_rows)
    await store.close()


@pytest.mark.asyncio
async def test_orphan_settings_new_table_recovered(tmp_path):
    """Simulate a crash mid-migration: settings_new exists but settings
    has not been renamed yet. Next init should recover gracefully."""
    db = tmp_path / "crashed.db"
    # Manually set up a state that mimics post-crash inconsistency
    import sqlite3
    con = sqlite3.connect(db)
    con.executescript("""
        CREATE TABLE turns (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL, channel TEXT NOT NULL,
            bot_id TEXT NOT NULL DEFAULT 'default',
            chat_id INTEGER NOT NULL DEFAULT 0,
            role TEXT NOT NULL, content TEXT NOT NULL, ts TEXT NOT NULL);
        CREATE TABLE settings (
            user_id INTEGER NOT NULL, channel TEXT NOT NULL,
            bot_id TEXT NOT NULL DEFAULT 'default',
            chat_id INTEGER NOT NULL DEFAULT 0,
            key TEXT NOT NULL, value TEXT NOT NULL,
            PRIMARY KEY (user_id, channel, bot_id, chat_id, key));
        -- orphan from a prior crashed migration
        CREATE TABLE settings_new (
            user_id INTEGER NOT NULL, channel TEXT NOT NULL,
            bot_id TEXT NOT NULL DEFAULT 'default',
            chat_id INTEGER NOT NULL DEFAULT 0,
            key TEXT NOT NULL, value TEXT NOT NULL,
            PRIMARY KEY (user_id, channel, bot_id, chat_id, key));
        CREATE TABLE usage_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL, channel TEXT NOT NULL,
            bot_id TEXT NOT NULL DEFAULT 'default',
            chat_id INTEGER NOT NULL DEFAULT 0,
            runner TEXT NOT NULL,
            prompt_tokens INTEGER DEFAULT 0,
            completion_tokens INTEGER DEFAULT 0,
            total_tokens INTEGER DEFAULT 0,
            ts TEXT NOT NULL);
        INSERT INTO settings VALUES (1, 'telegram', 'default', 1, 'active_role', 'real');
    """)
    con.commit()
    con.close()

    from src.core.memory.tier3 import Tier3Store
    store = Tier3Store(str(db))
    await store.init()  # must not raise
    val = await store.get_setting(
        user_id=1, channel="telegram", bot_id="default", chat_id=1, key="active_role",
    )
    assert val == "real"
    await store.close()
