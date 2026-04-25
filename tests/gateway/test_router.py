# tests/gateway/test_router.py
import pytest
from src.gateway.router import Router, ParsedCommand


@pytest.mark.asyncio
async def test_route_slash_prefix():
    router = Router(known_runners={"claude", "codex", "gemini"}, default_runner="claude")
    cmd = await router.parse("/claude write a hello world")
    assert cmd.runner == "claude"
    assert cmd.prompt == "write a hello world"


@pytest.mark.asyncio
async def test_route_default_runner_for_plain_text():
    router = Router(known_runners={"claude", "codex", "gemini"}, default_runner="claude")
    cmd = await router.parse("what is the weather today?")
    assert cmd.runner == "claude"
    assert cmd.prompt == "what is the weather today?"


@pytest.mark.asyncio
async def test_route_plain_text_can_attach_semantic_role(monkeypatch):
    from src.gateway.role_router import RoleRouter

    async def fake_route(self, text, threshold=None):
        return "code-auditor"

    monkeypatch.setattr(RoleRouter, "route", fake_route)
    router = Router(known_runners={"claude", "codex", "gemini"}, default_runner="claude")
    cmd = await router.parse("please audit this diff")
    assert cmd.role == "code-auditor"


@pytest.mark.asyncio
async def test_route_use_command_changes_runner():
    router = Router(known_runners={"claude", "codex", "gemini"}, default_runner="claude")
    cmd = await router.parse("/use codex")
    assert cmd.is_switch_runner is True
    assert cmd.runner == "codex"


@pytest.mark.asyncio
async def test_route_cancel_command():
    router = Router(known_runners={"claude", "codex", "gemini"}, default_runner="claude")
    cmd = await router.parse("/cancel")
    assert cmd.is_cancel is True


@pytest.mark.asyncio
async def test_route_status_command():
    router = Router(known_runners={"claude", "codex", "gemini"}, default_runner="claude")
    cmd = await router.parse("/status")
    assert cmd.is_status is True


@pytest.mark.asyncio
async def test_route_reset_command():
    router = Router(known_runners={"claude", "codex", "gemini"}, default_runner="claude")
    cmd = await router.parse("/reset")
    assert cmd.is_reset is True


@pytest.mark.asyncio
async def test_route_new_command():
    router = Router(known_runners={"claude", "codex", "gemini"}, default_runner="claude")
    cmd = await router.parse("/new")
    assert cmd.is_new is True


@pytest.mark.asyncio
async def test_route_unknown_slash_falls_back_to_default():
    router = Router(known_runners={"claude", "codex", "gemini"}, default_runner="claude")
    cmd = await router.parse("/unknown do something")
    assert cmd.runner == "claude"
    assert "/unknown do something" in cmd.prompt


@pytest.mark.asyncio
async def test_route_voice_on():
    router = Router(known_runners={"claude"}, default_runner="claude")
    cmd = await router.parse("/voice on")
    assert cmd.is_voice_on is True
    assert cmd.is_voice_off is False


@pytest.mark.asyncio
async def test_route_voice_off():
    router = Router(known_runners={"claude"}, default_runner="claude")
    cmd = await router.parse("/voice off")
    assert cmd.is_voice_off is True
    assert cmd.is_voice_on is False


@pytest.mark.asyncio
async def test_parse_is_awaitable():
    router = Router(known_runners={"claude"}, default_runner="claude")
    cmd = await router.parse("hello")
    assert cmd.runner == "claude"


def test_parsed_command_is_reasoning_defaults_false():
    from src.gateway.router import ParsedCommand
    cmd = ParsedCommand(runner="claude", prompt="hello")
    assert cmd.is_reasoning is False


def test_parsed_command_is_reasoning_can_be_set():
    from src.gateway.router import ParsedCommand
    cmd = ParsedCommand(runner="claude", prompt="hello", is_reasoning=True)
    assert cmd.is_reasoning is True
