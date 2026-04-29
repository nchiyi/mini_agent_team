"""B-2 follow-up: bot self-awareness — system prefix injects MAT context."""
import pytest


def test_mat_prefix_constant_defined():
    """The constant exists and mentions key MAT capabilities."""
    from src.gateway.dispatcher import _MAT_SYSTEM_PREFIX
    assert "/discuss" in _MAT_SYSTEM_PREFIX
    assert "/recall" in _MAT_SYSTEM_PREFIX
    assert "claude" in _MAT_SYSTEM_PREFIX
    assert "codex" in _MAT_SYSTEM_PREFIX
    assert "gemini" in _MAT_SYSTEM_PREFIX
    assert "MAT" in _MAT_SYSTEM_PREFIX


def test_apply_role_prompt_prepends_mat_prefix(tmp_path):
    """apply_role_prompt now prepends the MAT system prefix."""
    from src.gateway.dispatcher import apply_role_prompt, _MAT_SYSTEM_PREFIX
    out = apply_role_prompt("hello", "fullstack-dev", str(tmp_path))
    assert out.startswith(_MAT_SYSTEM_PREFIX), \
        "MAT prefix must be at the very top of the prompt sent to runner"
    assert "hello" in out


def test_apply_role_prompt_with_unknown_role_still_prefixes(tmp_path):
    """Even when the role file doesn't exist, MAT prefix still injected."""
    from src.gateway.dispatcher import apply_role_prompt, _MAT_SYSTEM_PREFIX
    out = apply_role_prompt("hello", "nonexistent-role", str(tmp_path))
    assert _MAT_SYSTEM_PREFIX in out
    assert "hello" in out


def test_apply_role_prompt_with_empty_role_still_prefixes(tmp_path):
    from src.gateway.dispatcher import apply_role_prompt, _MAT_SYSTEM_PREFIX
    out = apply_role_prompt("hello", "", str(tmp_path))
    assert _MAT_SYSTEM_PREFIX in out


def test_mat_prefix_explicitly_corrects_no_codex_misconception():
    """Bot must be told NOT to claim it has no access to other LLMs."""
    from src.gateway.dispatcher import _MAT_SYSTEM_PREFIX
    # Some phrasing that tells Claude not to say no:
    s = _MAT_SYSTEM_PREFIX.lower()
    assert "yes" in s or "do not" in s or "don't" in s or "tell them" in s, \
        "Prefix should explicitly counter the 'I cannot call other LLMs' default"
