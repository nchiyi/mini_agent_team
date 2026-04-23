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
