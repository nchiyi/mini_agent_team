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
    """No bot_id kwarg → bot_id='default' → reads {uid}_{ch}_default.jsonl"""
    from src.core.memory.tier1 import Tier1Store
    store = Tier1Store(permanent_dir=str(tmp_path))
    store.remember(user_id=1, channel="telegram", content="legacy")
    items = store.list_entries(user_id=1, channel="telegram")
    assert any("legacy" in e["content"] for e in items)
    # File should be the new shape:
    assert (tmp_path / "1_telegram_default.jsonl").exists()


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
    assert (tmp_path / "1_telegram_default.jsonl").exists()


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
