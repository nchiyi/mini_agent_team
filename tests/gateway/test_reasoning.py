# tests/gateway/test_reasoning.py
import pytest


# ── NLU tests ────────────────────────────────────────────────────────────────

def _detector(runners=None):
    from src.gateway.nlu import FastPathDetector
    return FastPathDetector(runners or {"claude", "codex", "gemini"})


def test_nlu_zh_keyword_triggers_reasoning():
    cmd = _detector().detect("請深入分析台灣的半導體產業")
    assert cmd is not None
    assert cmd.is_reasoning is True
    assert "半導體產業" in cmd.prompt


def test_nlu_en_keyword_triggers_reasoning():
    cmd = _detector().detect("think carefully about the trolley problem")
    assert cmd is not None
    assert cmd.is_reasoning is True
    assert "trolley problem" in cmd.prompt


def test_nlu_step_by_step_triggers_reasoning():
    cmd = _detector().detect("step by step how does TCP handshake work")
    assert cmd is not None
    assert cmd.is_reasoning is True


def test_nlu_reasoning_keyword_case_insensitive():
    cmd = _detector().detect("Think Carefully about quantum computing")
    assert cmd is not None
    assert cmd.is_reasoning is True


def test_nlu_reasoning_strips_keyword_from_prompt():
    cmd = _detector().detect("請一步一步推導費馬最後定理")
    assert cmd is not None
    # keyword stripped; only the actual question remains
    assert "一步一步" not in cmd.prompt
    assert "費馬最後定理" in cmd.prompt


def test_nlu_keyword_only_returns_none():
    # Message is nothing but the keyword — no actual question
    cmd = _detector().detect("深入分析")
    assert cmd is None


def test_nlu_slash_command_not_intercepted():
    # /discuss must not be matched for reasoning
    cmd = _detector().detect("/discuss claude,codex step by step solve this")
    assert cmd is None


def test_nlu_reasoning_with_explicit_runner():
    cmd = _detector().detect("請 Claude 深入分析 RSA encryption")
    assert cmd is not None
    assert cmd.is_reasoning is True
    assert cmd.runner == "claude"


def test_nlu_reasoning_no_explicit_runner_uses_empty():
    cmd = _detector().detect("深入分析 black holes")
    assert cmd is not None
    assert cmd.is_reasoning is True
    assert cmd.runner == ""  # dispatcher uses session.current_runner
