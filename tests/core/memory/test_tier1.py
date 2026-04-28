import pytest
from pathlib import Path


def test_tier1_remember_creates_entry(tmp_path):
    from src.core.memory.tier1 import Tier1Store
    store = Tier1Store(permanent_dir=str(tmp_path))
    store.remember(user_id=1, channel="telegram", content="I am a software engineer")
    entries = store.list_entries(user_id=1, channel="telegram")
    assert len(entries) == 1
    assert "I am a software engineer" in entries[0]["content"]
    assert "ts" in entries[0]


def test_tier1_multiple_entries(tmp_path):
    from src.core.memory.tier1 import Tier1Store
    store = Tier1Store(permanent_dir=str(tmp_path))
    store.remember(user_id=1, channel="telegram", content="fact one")
    store.remember(user_id=1, channel="telegram", content="fact two")
    entries = store.list_entries(user_id=1, channel="telegram")
    assert len(entries) == 2
    contents = [e["content"] for e in entries]
    assert "fact one" in contents
    assert "fact two" in contents


def test_tier1_forget_removes_matching_entry(tmp_path):
    from src.core.memory.tier1 import Tier1Store
    store = Tier1Store(permanent_dir=str(tmp_path))
    store.remember(user_id=1, channel="telegram", content="I like Python")
    store.remember(user_id=1, channel="telegram", content="I dislike Java")
    store.forget(user_id=1, channel="telegram", keyword="Java")
    entries = store.list_entries(user_id=1, channel="telegram")
    assert len(entries) == 1
    assert "Python" in entries[0]["content"]


def test_tier1_user_isolation(tmp_path):
    from src.core.memory.tier1 import Tier1Store
    store = Tier1Store(permanent_dir=str(tmp_path))
    store.remember(user_id=1, channel="telegram", content="user1 fact")
    store.remember(user_id=2, channel="telegram", content="user2 fact")
    assert len(store.list_entries(user_id=1, channel="telegram")) == 1
    assert len(store.list_entries(user_id=2, channel="telegram")) == 1
    assert store.list_entries(user_id=1, channel="telegram")[0]["content"] == "user1 fact"


def test_tier1_render_for_context(tmp_path):
    from src.core.memory.tier1 import Tier1Store
    store = Tier1Store(permanent_dir=str(tmp_path))
    store.remember(user_id=1, channel="telegram", content="I prefer dark mode")
    rendered = store.render_for_context(user_id=1, channel="telegram")
    assert "I prefer dark mode" in rendered


def test_tier1_isolated_per_bot(tmp_path):
    from src.core.memory.tier1 import Tier1Store
    store = Tier1Store(permanent_dir=str(tmp_path))
    store.remember(user_id=1, channel="telegram", bot_id="dev", content="dev memory")
    store.remember(user_id=1, channel="telegram", bot_id="search", content="search memory")
    dev = store.list_entries(user_id=1, channel="telegram", bot_id="dev")
    search = store.list_entries(user_id=1, channel="telegram", bot_id="search")
    assert any("dev memory" in e["content"] for e in dev)
    assert all("search memory" not in e["content"] for e in dev)
    assert any("search memory" in e["content"] for e in search)


def test_tier1_default_bot_when_kwarg_omitted(tmp_path):
    """No bot_id kwarg → bot_id='default', no chat_id → chat_id=user_id."""
    from src.core.memory.tier1 import Tier1Store
    store = Tier1Store(permanent_dir=str(tmp_path))
    store.remember(user_id=1, channel="telegram", content="legacy")
    items = store.list_entries(user_id=1, channel="telegram")
    assert any("legacy" in e["content"] for e in items)
    # File shape after B-2: {uid}_{ch}_{bid}_{uid}.jsonl
    assert (tmp_path / "1_telegram_default_1.jsonl").exists()


def test_tier1_legacy_jsonl_renamed_on_first_read(tmp_path):
    """Pre-existing {uid}_{ch}.jsonl from pre-multibot install gets renamed on access."""
    import json
    from src.core.memory.tier1 import Tier1Store
    legacy = tmp_path / "1_telegram.jsonl"
    legacy.write_text(json.dumps({"ts": "2026-01-01T00:00:00Z",
                                  "content": "pre-existing fact"}) + "\n")
    store = Tier1Store(permanent_dir=str(tmp_path))
    items = store.list_entries(user_id=1, channel="telegram")
    assert any("pre-existing fact" in e["content"] for e in items)
    assert not legacy.exists()
    # After B-2 the migrated file uses the new {uid}_{ch}_{bid}_{uid} shape.
    assert (tmp_path / "1_telegram_default_1.jsonl").exists()


def test_tier1_render_for_context_per_bot(tmp_path):
    from src.core.memory.tier1 import Tier1Store
    store = Tier1Store(permanent_dir=str(tmp_path))
    store.remember(user_id=1, channel="telegram", bot_id="dev", content="dev fact")
    store.remember(user_id=1, channel="telegram", bot_id="search", content="search fact")
    dev_render = store.render_for_context(user_id=1, channel="telegram", bot_id="dev")
    search_render = store.render_for_context(user_id=1, channel="telegram", bot_id="search")
    assert "dev fact" in dev_render
    assert "dev fact" not in search_render
    assert "search fact" in search_render


def test_tier1_isolated_per_chat_id(tmp_path):
    from src.core.memory.tier1 import Tier1Store
    store = Tier1Store(permanent_dir=str(tmp_path))
    store.remember(user_id=1, channel="telegram", bot_id="dev",
                   chat_id=-100, content="group A msg")
    store.remember(user_id=1, channel="telegram", bot_id="dev",
                   chat_id=-200, content="group B msg")
    a = store.list_entries(user_id=1, channel="telegram", bot_id="dev", chat_id=-100)
    b = store.list_entries(user_id=1, channel="telegram", bot_id="dev", chat_id=-200)
    assert any("group A msg" in e["content"] for e in a)
    assert all("group A msg" not in e["content"] for e in b)
    assert any("group B msg" in e["content"] for e in b)


def test_tier1_dm_chat_id_defaults_to_user_id(tmp_path):
    """No chat_id → defaults to user_id; legacy file rename still works."""
    from src.core.memory.tier1 import Tier1Store
    store = Tier1Store(permanent_dir=str(tmp_path))
    store.remember(user_id=1, channel="telegram", bot_id="dev", content="dm fact")
    items = store.list_entries(user_id=1, channel="telegram", bot_id="dev")
    assert any("dm fact" in e["content"] for e in items)
    # New file shape includes chat_id = user_id:
    assert (tmp_path / "1_telegram_dev_1.jsonl").exists()


def test_tier1_legacy_b1_file_renamed_on_first_read(tmp_path):
    """A B-1-shape file {uid}_{ch}_{bid}.jsonl gets renamed on access."""
    import json
    from src.core.memory.tier1 import Tier1Store
    legacy = tmp_path / "1_telegram_dev.jsonl"
    legacy.write_text(
        json.dumps({"ts": "2026-04-29T00:00:00Z", "content": "b1-era fact"}) + "\n"
    )
    store = Tier1Store(permanent_dir=str(tmp_path))
    items = store.list_entries(user_id=1, channel="telegram", bot_id="dev")
    assert any("b1-era fact" in e["content"] for e in items)
    assert not legacy.exists()
    assert (tmp_path / "1_telegram_dev_1.jsonl").exists()
