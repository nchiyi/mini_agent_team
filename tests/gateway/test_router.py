# tests/gateway/test_router.py
import pytest
from src.gateway.router import Router, ParsedCommand


def test_route_slash_prefix():
    router = Router(known_runners={"claude", "codex", "gemini"}, default_runner="claude")
    cmd = router.parse("/claude write a hello world")
    assert cmd.runner == "claude"
    assert cmd.prompt == "write a hello world"


def test_route_default_runner_for_plain_text():
    router = Router(known_runners={"claude", "codex", "gemini"}, default_runner="claude")
    cmd = router.parse("what is the weather today?")
    assert cmd.runner == "claude"
    assert cmd.prompt == "what is the weather today?"


def test_route_use_command_changes_runner():
    router = Router(known_runners={"claude", "codex", "gemini"}, default_runner="claude")
    cmd = router.parse("/use codex")
    assert cmd.is_switch_runner is True
    assert cmd.runner == "codex"


def test_route_cancel_command():
    router = Router(known_runners={"claude", "codex", "gemini"}, default_runner="claude")
    cmd = router.parse("/cancel")
    assert cmd.is_cancel is True


def test_route_status_command():
    router = Router(known_runners={"claude", "codex", "gemini"}, default_runner="claude")
    cmd = router.parse("/status")
    assert cmd.is_status is True


def test_route_reset_command():
    router = Router(known_runners={"claude", "codex", "gemini"}, default_runner="claude")
    cmd = router.parse("/reset")
    assert cmd.is_reset is True


def test_route_new_command():
    router = Router(known_runners={"claude", "codex", "gemini"}, default_runner="claude")
    cmd = router.parse("/new")
    assert cmd.is_new is True


def test_route_unknown_slash_falls_back_to_default():
    router = Router(known_runners={"claude", "codex", "gemini"}, default_runner="claude")
    cmd = router.parse("/unknown do something")
    assert cmd.runner == "claude"
    assert "/unknown do something" in cmd.prompt
