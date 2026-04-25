# tests/gateway/test_router_memory.py
import pytest
from src.gateway.router import Router


@pytest.mark.asyncio
async def test_remember_command():
    router = Router(known_runners={"claude"}, default_runner="claude")
    cmd = await router.parse("/remember I prefer Python over Ruby")
    assert cmd.is_remember is True
    assert cmd.prompt == "I prefer Python over Ruby"


@pytest.mark.asyncio
async def test_forget_command():
    router = Router(known_runners={"claude"}, default_runner="claude")
    cmd = await router.parse("/forget Ruby")
    assert cmd.is_forget is True
    assert cmd.prompt == "Ruby"


@pytest.mark.asyncio
async def test_recall_command():
    router = Router(known_runners={"claude"}, default_runner="claude")
    cmd = await router.parse("/recall architecture decision")
    assert cmd.is_recall is True
    assert cmd.prompt == "architecture decision"


@pytest.mark.asyncio
async def test_remember_without_content_is_unknown():
    """'/remember' with no content falls back to default runner as unknown slash."""
    router = Router(known_runners={"claude"}, default_runner="claude")
    cmd = await router.parse("/remember")
    # No content — treat as unknown slash, pass to default runner
    assert cmd.runner == "claude"
    assert cmd.is_remember is False
