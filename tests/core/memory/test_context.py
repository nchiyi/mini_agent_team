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
