# tests/core/memory/test_context.py
import asyncio, pytest

pytestmark = pytest.mark.asyncio


async def test_context_empty_memory_returns_empty(tmp_path):
    from src.core.memory.tier3 import Tier3Store
    from src.core.memory.tier1 import Tier1Store
    from src.core.memory.context import ContextAssembler

    t3 = Tier3Store(db_path=str(tmp_path / "db/history.db"))
    await t3.init()
    t1 = Tier1Store(permanent_dir=str(tmp_path / "tier1"))
    assembler = ContextAssembler(tier1=t1, tier3=t3, max_tokens=4000)

    ctx = await assembler.build(user_id=1, channel="telegram", recent_turns=5)
    assert ctx == ""

    await t3.close()


async def test_context_includes_tier1_entries(tmp_path):
    from src.core.memory.tier3 import Tier3Store
    from src.core.memory.tier1 import Tier1Store
    from src.core.memory.context import ContextAssembler

    t3 = Tier3Store(db_path=str(tmp_path / "db/history.db"))
    await t3.init()
    t1 = Tier1Store(permanent_dir=str(tmp_path / "tier1"))
    t1.remember(user_id=1, channel="telegram", content="I prefer Python")
    assembler = ContextAssembler(tier1=t1, tier3=t3, max_tokens=4000)

    ctx = await assembler.build(user_id=1, channel="telegram", recent_turns=5)
    assert "I prefer Python" in ctx

    await t3.close()


async def test_context_includes_tier3_history(tmp_path):
    from src.core.memory.tier3 import Tier3Store
    from src.core.memory.tier1 import Tier1Store
    from src.core.memory.context import ContextAssembler

    t3 = Tier3Store(db_path=str(tmp_path / "db/history.db"))
    await t3.init()
    await t3.save_turn(user_id=1, channel="telegram", role="user", content="previous question")
    await t3.save_turn(user_id=1, channel="telegram", role="assistant", content="previous answer")
    t1 = Tier1Store(permanent_dir=str(tmp_path / "tier1"))
    assembler = ContextAssembler(tier1=t1, tier3=t3, max_tokens=4000)

    ctx = await assembler.build(user_id=1, channel="telegram", recent_turns=5)
    assert "previous question" in ctx
    assert "previous answer" in ctx

    await t3.close()


async def test_context_respects_token_budget(tmp_path):
    from src.core.memory.tier3 import Tier3Store
    from src.core.memory.tier1 import Tier1Store
    from src.core.memory.context import ContextAssembler, count_tokens

    t3 = Tier3Store(db_path=str(tmp_path / "db/history.db"))
    await t3.init()
    # Add many turns to exceed budget
    for i in range(50):
        await t3.save_turn(user_id=1, channel="telegram", role="user",
                           content=f"This is message number {i} with some extra content to use tokens.")
    t1 = Tier1Store(permanent_dir=str(tmp_path / "tier1"))
    assembler = ContextAssembler(tier1=t1, tier3=t3, max_tokens=500)

    ctx = await assembler.build(user_id=1, channel="telegram", recent_turns=50)
    assert count_tokens(ctx) <= 500

    await t3.close()


async def test_context_build_messages_returns_structured_roles(tmp_path):
    from src.core.memory.tier3 import Tier3Store
    from src.core.memory.tier1 import Tier1Store
    from src.core.memory.context import ContextAssembler

    t3 = Tier3Store(db_path=str(tmp_path / "db/history.db"))
    await t3.init()
    await t3.save_turn(user_id=1, channel="telegram", role="user", content="hello")
    await t3.save_turn(user_id=1, channel="telegram", role="assistant", content="hi")
    t1 = Tier1Store(permanent_dir=str(tmp_path / "tier1"))
    t1.remember(user_id=1, channel="telegram", content="I prefer concise replies")
    assembler = ContextAssembler(tier1=t1, tier3=t3, max_tokens=4000)

    messages = await assembler.build_messages(user_id=1, channel="telegram", recent_turns=5)
    assert messages[0]["role"] == "system"
    assert "I prefer concise replies" in messages[0]["content"]
    assert messages[1:] == [
        {"role": "user", "content": "hello"},
        {"role": "assistant", "content": "hi"},
    ]

    await t3.close()


async def test_tier1_truncation_drops_oldest_entries(tmp_path):
    """ContextAssembler must drop oldest Tier1 entries, never slice mid-sentence."""
    from src.core.memory.tier1 import Tier1Store
    from src.core.memory.tier3 import Tier3Store
    from src.core.memory.context import ContextAssembler

    t1 = Tier1Store(permanent_dir=str(tmp_path / "tier1"))
    t3 = Tier3Store(db_path=str(tmp_path / "db/history.db"))
    await t3.init()

    # Add many entries so they exceed a tiny budget
    for i in range(20):
        t1.remember(user_id=1, channel="telegram", content=f"Memory entry number {i:02d}")

    # Very small budget: only a few entries can fit
    assembler = ContextAssembler(tier1=t1, tier3=t3, max_tokens=4000, tier1_budget=30)
    ctx = await assembler.build(user_id=1, channel="telegram", recent_turns=0)

    # Result must start with the section header (not mid-string)
    assert ctx.startswith("## Permanent Memory")
    # Most-recent entries should be present; oldest should be dropped
    assert "entry number 19" in ctx
    assert "entry number 00" not in ctx

    await t3.close()


async def test_tier1_truncation_no_slicing(tmp_path):
    """Verify no raw character-ratio slicing: every line in result is a complete entry."""
    from src.core.memory.tier1 import Tier1Store
    from src.core.memory.tier3 import Tier3Store
    from src.core.memory.context import ContextAssembler

    t1 = Tier1Store(permanent_dir=str(tmp_path / "tier1"))
    t3 = Tier3Store(db_path=str(tmp_path / "db/history.db"))
    await t3.init()

    t1.remember(user_id=1, channel="telegram", content="Full sentence one.")
    t1.remember(user_id=1, channel="telegram", content="Full sentence two.")

    assembler = ContextAssembler(tier1=t1, tier3=t3, max_tokens=4000, tier1_budget=200)
    ctx = await assembler.build(user_id=1, channel="telegram", recent_turns=0)

    lines = [l for l in ctx.splitlines() if l.startswith("- ")]
    for line in lines:
        assert line.endswith(".")  # each line is a complete entry

    await t3.close()


async def test_context_isolated_by_bot_id(tmp_path):
    from src.core.memory.tier3 import Tier3Store
    from src.core.memory.tier1 import Tier1Store
    from src.core.memory.context import ContextAssembler

    t3 = Tier3Store(db_path=str(tmp_path / "db/history.db"))
    await t3.init()
    t1 = Tier1Store(permanent_dir=str(tmp_path / "tier1"))

    # Write to two different bots for the same (user, channel).
    t1.remember(user_id=1, channel="telegram", bot_id="dev", content="dev fact")
    t1.remember(user_id=1, channel="telegram", bot_id="search", content="search fact")
    await t3.save_turn(user_id=1, channel="telegram", bot_id="dev",
                       role="user", content="dev question")
    await t3.save_turn(user_id=1, channel="telegram", bot_id="search",
                       role="user", content="search question")

    assembler = ContextAssembler(tier1=t1, tier3=t3, max_tokens=4000)
    dev_ctx = await assembler.build(user_id=1, channel="telegram",
                                    bot_id="dev", recent_turns=10)
    search_ctx = await assembler.build(user_id=1, channel="telegram",
                                       bot_id="search", recent_turns=10)
    assert "dev fact" in dev_ctx
    assert "dev question" in dev_ctx
    assert "search fact" not in dev_ctx
    assert "search question" not in dev_ctx
    assert "search fact" in search_ctx
    assert "search question" in search_ctx
    assert "dev fact" not in search_ctx

    await t3.close()


async def test_build_messages_isolated_by_bot_id(tmp_path):
    from src.core.memory.tier3 import Tier3Store
    from src.core.memory.tier1 import Tier1Store
    from src.core.memory.context import ContextAssembler

    t3 = Tier3Store(db_path=str(tmp_path / "db/history.db"))
    await t3.init()
    t1 = Tier1Store(permanent_dir=str(tmp_path / "tier1"))
    await t3.save_turn(user_id=1, channel="telegram", bot_id="dev",
                       role="user", content="from dev")
    await t3.save_turn(user_id=1, channel="telegram", bot_id="search",
                       role="user", content="from search")

    assembler = ContextAssembler(tier1=t1, tier3=t3, max_tokens=4000)
    dev_msgs = await assembler.build_messages(user_id=1, channel="telegram",
                                              bot_id="dev", recent_turns=10)
    search_msgs = await assembler.build_messages(user_id=1, channel="telegram",
                                                 bot_id="search", recent_turns=10)
    dev_contents = [m["content"] for m in dev_msgs]
    search_contents = [m["content"] for m in search_msgs]
    assert any("from dev" in c for c in dev_contents)
    assert all("from search" not in c for c in dev_contents)
    assert any("from search" in c for c in search_contents)
    assert all("from dev" not in c for c in search_contents)

    await t3.close()


async def test_context_isolated_by_chat_id(tmp_path):
    from src.core.memory.tier3 import Tier3Store
    from src.core.memory.tier1 import Tier1Store
    from src.core.memory.context import ContextAssembler

    t3 = Tier3Store(db_path=str(tmp_path / "db/history.db"))
    await t3.init()
    t1 = Tier1Store(permanent_dir=str(tmp_path / "tier1"))
    t1.remember(user_id=1, channel="telegram", bot_id="dev",
                chat_id=-100, content="group fact")
    t1.remember(user_id=1, channel="telegram", bot_id="dev",
                chat_id=1, content="dm fact")
    await t3.save_turn(user_id=1, channel="telegram", bot_id="dev",
                       chat_id=-100, role="user", content="group msg")
    await t3.save_turn(user_id=1, channel="telegram", bot_id="dev",
                       chat_id=1, role="user", content="dm msg")

    assembler = ContextAssembler(tier1=t1, tier3=t3, max_tokens=4000)
    group_ctx = await assembler.build(user_id=1, channel="telegram",
                                      bot_id="dev", chat_id=-100, recent_turns=10)
    dm_ctx = await assembler.build(user_id=1, channel="telegram",
                                   bot_id="dev", chat_id=1, recent_turns=10)
    assert "group fact" in group_ctx and "group msg" in group_ctx
    assert "dm fact" not in group_ctx and "dm msg" not in group_ctx
    assert "dm fact" in dm_ctx and "dm msg" in dm_ctx
    assert "group fact" not in dm_ctx and "group msg" not in dm_ctx

    await t3.close()
