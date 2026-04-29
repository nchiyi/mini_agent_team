import pytest
import sqlite3
from pathlib import Path


def _build_legacy_db(path: Path) -> None:
    """Build a pre-multibot tier3 database matching the current production schema."""
    con = sqlite3.connect(path)
    con.executescript("""
        CREATE TABLE turns (
            id      INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            channel TEXT    NOT NULL,
            role    TEXT    NOT NULL,
            content TEXT    NOT NULL,
            ts      TEXT    NOT NULL
        );
        CREATE INDEX idx_turns_user_channel_ts ON turns(user_id, channel, ts);
        CREATE TABLE settings (
            user_id INTEGER NOT NULL,
            channel TEXT    NOT NULL,
            key     TEXT    NOT NULL,
            value   TEXT    NOT NULL,
            PRIMARY KEY (user_id, channel, key)
        );
        CREATE TABLE usage_logs (
            id                INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id           INTEGER NOT NULL,
            channel           TEXT    NOT NULL,
            runner            TEXT    NOT NULL,
            prompt_tokens     INTEGER DEFAULT 0,
            completion_tokens INTEGER DEFAULT 0,
            total_tokens      INTEGER DEFAULT 0,
            ts                TEXT    NOT NULL
        );
        INSERT INTO turns (user_id, channel, role, content, ts)
        VALUES (1, 'telegram', 'user', 'pre-existing turn', '2026-04-28T00:00:00Z');
        INSERT INTO settings (user_id, channel, key, value)
        VALUES (1, 'telegram', 'active_role', 'fullstack-dev');
        INSERT INTO usage_logs (user_id, channel, runner, prompt_tokens, completion_tokens, total_tokens, ts)
        VALUES (1, 'telegram', 'claude', 100, 50, 150, '2026-04-28T00:00:00Z');
    """)
    con.commit()
    con.close()


@pytest.mark.asyncio
async def test_legacy_turns_visible_under_default_bot(tmp_path):
    db = tmp_path / "old.db"
    _build_legacy_db(db)
    from src.core.memory.tier3 import Tier3Store
    store = Tier3Store(str(db))
    await store.init()
    rows = await store.get_recent(user_id=1, channel="telegram", bot_id="default", n=10)
    assert any(r["content"] == "pre-existing turn" for r in rows)
    other = await store.get_recent(user_id=1, channel="telegram", bot_id="dev", n=10)
    assert other == []
    await store.close()


@pytest.mark.asyncio
async def test_legacy_settings_visible_under_default_bot(tmp_path):
    db = tmp_path / "old.db"
    _build_legacy_db(db)
    from src.core.memory.tier3 import Tier3Store
    store = Tier3Store(str(db))
    await store.init()
    val = await store.get_setting(user_id=1, channel="telegram", bot_id="default", key="active_role")
    assert val == "fullstack-dev"
    val2 = await store.get_setting(user_id=1, channel="telegram", bot_id="dev", key="active_role")
    assert val2 is None
    await store.close()


@pytest.mark.asyncio
async def test_settings_isolated_per_bot(tmp_path):
    db = tmp_path / "fresh.db"
    from src.core.memory.tier3 import Tier3Store
    store = Tier3Store(str(db))
    await store.init()
    await store.set_setting(user_id=1, channel="telegram", bot_id="dev",
                            key="active_role", value="fullstack-dev")
    await store.set_setting(user_id=1, channel="telegram", bot_id="search",
                            key="active_role", value="researcher")
    a = await store.get_setting(user_id=1, channel="telegram", bot_id="dev", key="active_role")
    b = await store.get_setting(user_id=1, channel="telegram", bot_id="search", key="active_role")
    assert a == "fullstack-dev"
    assert b == "researcher"
    await store.close()


@pytest.mark.asyncio
async def test_save_turn_and_get_recent_with_bot_id(tmp_path):
    db = tmp_path / "fresh.db"
    from src.core.memory.tier3 import Tier3Store
    store = Tier3Store(str(db))
    await store.init()
    await store.save_turn(user_id=1, channel="telegram", bot_id="dev",
                          role="user", content="hello dev")
    await store.save_turn(user_id=1, channel="telegram", bot_id="search",
                          role="user", content="hello search")
    dev = await store.get_recent(user_id=1, channel="telegram", bot_id="dev", n=10)
    search = await store.get_recent(user_id=1, channel="telegram", bot_id="search", n=10)
    assert any(r["content"] == "hello dev" for r in dev)
    assert all(r["content"] != "hello dev" for r in search)
    assert any(r["content"] == "hello search" for r in search)
    await store.close()


@pytest.mark.asyncio
async def test_legacy_usage_log_visible_under_default(tmp_path):
    db = tmp_path / "old.db"
    _build_legacy_db(db)
    from src.core.memory.tier3 import Tier3Store
    store = Tier3Store(str(db))
    await store.init()
    # The aggregator queries don't filter by bot_id (intentionally cross-bot).
    total = await store.get_token_usage_since(user_id=1, since_iso="2026-01-01T00:00:00Z")
    assert total == 150
    await store.close()
