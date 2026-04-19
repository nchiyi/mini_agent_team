import pytest
from pathlib import Path


def test_tier1_remember_creates_entry(tmp_path):
    from src.core.memory.tier1 import Tier1Store
    store = Tier1Store(permanent_dir=str(tmp_path))
    store.remember(user_id=1, content="I am a software engineer")
    entries = store.list_entries(user_id=1)
    assert len(entries) == 1
    assert "I am a software engineer" in entries[0]["content"]
    assert "ts" in entries[0]


def test_tier1_multiple_entries(tmp_path):
    from src.core.memory.tier1 import Tier1Store
    store = Tier1Store(permanent_dir=str(tmp_path))
    store.remember(user_id=1, content="fact one")
    store.remember(user_id=1, content="fact two")
    entries = store.list_entries(user_id=1)
    assert len(entries) == 2
    contents = [e["content"] for e in entries]
    assert "fact one" in contents
    assert "fact two" in contents


def test_tier1_forget_removes_matching_entry(tmp_path):
    from src.core.memory.tier1 import Tier1Store
    store = Tier1Store(permanent_dir=str(tmp_path))
    store.remember(user_id=1, content="I like Python")
    store.remember(user_id=1, content="I dislike Java")
    store.forget(user_id=1, keyword="Java")
    entries = store.list_entries(user_id=1)
    assert len(entries) == 1
    assert "Python" in entries[0]["content"]


def test_tier1_user_isolation(tmp_path):
    from src.core.memory.tier1 import Tier1Store
    store = Tier1Store(permanent_dir=str(tmp_path))
    store.remember(user_id=1, content="user1 fact")
    store.remember(user_id=2, content="user2 fact")
    assert len(store.list_entries(user_id=1)) == 1
    assert len(store.list_entries(user_id=2)) == 1
    assert store.list_entries(user_id=1)[0]["content"] == "user1 fact"


def test_tier1_render_for_context(tmp_path):
    from src.core.memory.tier1 import Tier1Store
    store = Tier1Store(permanent_dir=str(tmp_path))
    store.remember(user_id=1, content="I prefer dark mode")
    rendered = store.render_for_context(user_id=1)
    assert "I prefer dark mode" in rendered
