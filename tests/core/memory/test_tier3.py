# tests/core/memory/test_tier3.py
import asyncio, pytest

pytestmark = pytest.mark.asyncio


async def test_tier3_save_and_retrieve(tmp_path):
    from src.core.memory.tier3 import Tier3Store
    store = Tier3Store(db_path=str(tmp_path / "history.db"))
    await store.init()

    await store.save_turn(user_id=1, channel="telegram", role="user", content="hello")
    await store.save_turn(user_id=1, channel="telegram", role="assistant", content="hi there")

    turns = await store.get_recent(user_id=1, channel="telegram", n=10)
    assert len(turns) == 2
    assert turns[0]["role"] == "user"
    assert turns[0]["content"] == "hello"
    assert turns[1]["role"] == "assistant"

    await store.close()


async def test_tier3_channel_isolation(tmp_path):
    from src.core.memory.tier3 import Tier3Store
    store = Tier3Store(db_path=str(tmp_path / "history.db"))
    await store.init()

    await store.save_turn(user_id=1, channel="telegram", role="user", content="tg msg")
    await store.save_turn(user_id=1, channel="discord",  role="user", content="dc msg")

    tg_turns = await store.get_recent(user_id=1, channel="telegram", n=10)
    dc_turns = await store.get_recent(user_id=1, channel="discord",  n=10)
    assert len(tg_turns) == 1
    assert len(dc_turns) == 1
    assert tg_turns[0]["content"] == "tg msg"
    assert dc_turns[0]["content"] == "dc msg"

    await store.close()


async def test_tier3_get_recent_respects_limit(tmp_path):
    from src.core.memory.tier3 import Tier3Store
    store = Tier3Store(db_path=str(tmp_path / "history.db"))
    await store.init()

    for i in range(25):
        await store.save_turn(user_id=1, channel="telegram", role="user", content=f"msg {i}")

    turns = await store.get_recent(user_id=1, channel="telegram", n=10)
    assert len(turns) == 10
    # Should return the MOST RECENT 10, in chronological order
    assert turns[-1]["content"] == "msg 24"

    await store.close()


async def test_tier3_fts_search(tmp_path):
    from src.core.memory.tier3 import Tier3Store
    store = Tier3Store(db_path=str(tmp_path / "history.db"))
    await store.init()

    await store.save_turn(user_id=1, channel="telegram", role="user", content="gateway architecture design")
    await store.save_turn(user_id=1, channel="telegram", role="user", content="memory system sqlite")
    await store.save_turn(user_id=1, channel="telegram", role="user", content="discord adapter implementation")

    results = await store.search(user_id=1, channel="telegram", query="sqlite memory", limit=5)
    assert any("memory" in r["content"] or "sqlite" in r["content"] for r in results)

    await store.close()


async def test_tier3_count_turns(tmp_path):
    from src.core.memory.tier3 import Tier3Store
    store = Tier3Store(db_path=str(tmp_path / "history.db"))
    await store.init()

    assert await store.count_turns(user_id=1, channel="telegram") == 0
    await store.save_turn(user_id=1, channel="telegram", role="user", content="a")
    await store.save_turn(user_id=1, channel="telegram", role="assistant", content="b")
    assert await store.count_turns(user_id=1, channel="telegram") == 2
    assert await store.count_turns(user_id=1, channel="discord") == 0

    await store.close()


async def test_tier3_prune_before_id(tmp_path):
    from src.core.memory.tier3 import Tier3Store
    store = Tier3Store(db_path=str(tmp_path / "history.db"))
    await store.init()

    for i in range(5):
        await store.save_turn(user_id=1, channel="telegram", role="user", content=f"msg {i}")

    oldest = await store.get_oldest_turns(user_id=1, channel="telegram", n=3)
    assert len(oldest) == 3
    cutoff_id = oldest[-1]["id"]

    pruned = await store.prune_before_id(user_id=1, channel="telegram", before_id=cutoff_id)
    assert pruned == 3
    assert await store.count_turns(user_id=1, channel="telegram") == 2

    remaining = await store.get_recent(user_id=1, channel="telegram", n=10)
    assert all("msg 3" in r["content"] or "msg 4" in r["content"] for r in remaining)

    await store.close()


async def test_tier3_distill_timestamp(tmp_path):
    from src.core.memory.tier3 import Tier3Store
    from datetime import datetime, timezone
    store = Tier3Store(db_path=str(tmp_path / "history.db"))
    await store.init()

    assert await store.get_last_distill_ts(user_id=1, channel="telegram") is None

    now = datetime.now(timezone.utc)
    await store.set_last_distill_ts(user_id=1, channel="telegram", ts=now)
    retrieved = await store.get_last_distill_ts(user_id=1, channel="telegram")
    assert retrieved is not None
    assert abs((retrieved - now).total_seconds()) < 1

    later = datetime.now(timezone.utc)
    await store.set_last_distill_ts(user_id=1, channel="telegram", ts=later)
    updated = await store.get_last_distill_ts(user_id=1, channel="telegram")
    assert updated > retrieved

    await store.close()


async def test_tier3_log_and_get_usage(tmp_path):
    from src.core.memory.tier3 import Tier3Store
    store = Tier3Store(db_path=str(tmp_path / "history.db"))
    await store.init()

    await store.log_usage(user_id=1, channel="telegram", runner="claude",
                          prompt_tokens=100, completion_tokens=50)
    await store.log_usage(user_id=1, channel="telegram", runner="claude",
                          prompt_tokens=200, completion_tokens=80)
    await store.log_usage(user_id=1, channel="telegram", runner="codex",
                          prompt_tokens=150, completion_tokens=60)

    summary = await store.get_usage_summary(user_id=1)
    assert "claude" in summary
    assert "codex" in summary
    assert summary["claude"]["prompt"] == 300
    assert summary["claude"]["completion"] == 130
    assert summary["claude"]["total"] == 430
    assert summary["codex"]["total"] == 210

    empty = await store.get_usage_summary(user_id=999)
    assert empty == {}

    await store.close()


async def test_tier3_usage_user_isolation(tmp_path):
    from src.core.memory.tier3 import Tier3Store
    store = Tier3Store(db_path=str(tmp_path / "history.db"))
    await store.init()

    await store.log_usage(user_id=1, channel="telegram", runner="claude",
                          prompt_tokens=100, completion_tokens=50)
    await store.log_usage(user_id=2, channel="telegram", runner="claude",
                          prompt_tokens=999, completion_tokens=999)

    s1 = await store.get_usage_summary(user_id=1)
    s2 = await store.get_usage_summary(user_id=2)
    assert s1["claude"]["total"] == 150
    assert s2["claude"]["total"] == 1998

    await store.close()
