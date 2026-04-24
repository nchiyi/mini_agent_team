# tests/modules/test_roster.py
"""Tests for the roster role library (issue #18)."""
from pathlib import Path
import pytest

ROSTER_DIR = Path(__file__).resolve().parents[2] / "roster"
REQUIRED_ROLES = {"department-head", "code-auditor", "expert-architect"}


def _load_all_roles():
    from src.roles import load_roles
    return load_roles(str(Path(__file__).resolve().parents[2]))


def test_roster_directory_exists():
    assert ROSTER_DIR.exists(), "roster/ directory must exist at repo root"


def test_required_roles_present():
    roles = _load_all_roles()
    for slug in REQUIRED_ROLES:
        assert slug in roles, f"Required role '{slug}' not found in roster"


def test_all_roles_have_required_fields():
    roles = _load_all_roles()
    for slug, meta in roles.items():
        assert meta.get("slug"), f"Role '{slug}' missing 'slug'"
        assert meta.get("name"), f"Role '{slug}' missing 'name'"
        assert meta.get("summary"), f"Role '{slug}' missing 'summary'"


def test_department_head_preferred_runner():
    roles = _load_all_roles()
    dh = roles.get("department-head", {})
    assert dh.get("preferred_runner") == "claude"


def test_fullstack_dev_role_exists():
    roles = _load_all_roles()
    assert "fullstack-dev" in roles
    assert roles["fullstack-dev"].get("preferred_runner") == "codex"


async def _collect(gen):
    return [chunk async for chunk in gen]


@pytest.mark.asyncio
async def test_agency_info_returns_role_details(monkeypatch):
    from skills.agency.handler import handle
    monkeypatch.setattr(
        "skills.agency.handler.load_roles",
        lambda: {
            "expert-architect": {
                "name": "架構專家",
                "summary": "系統架構設計",
                "identity": "你是一位架構師",
                "rules": ["模組化", "解耦"],
                "preferred_runner": "claude",
            }
        },
    )
    output = await _collect(handle("/agency", "info expert-architect", 1, "telegram"))
    assert "架構專家" in output[0]
    assert "claude" in output[0]


@pytest.mark.asyncio
async def test_agency_unknown_role_returns_error(monkeypatch):
    from skills.agency.handler import handle
    monkeypatch.setattr("skills.agency.handler.load_roles", lambda: {})
    output = await _collect(handle("/agency", "use no-such-role", 1, "telegram"))
    assert "找不到" in output[0]


@pytest.mark.asyncio
async def test_agency_use_none_clears_role(monkeypatch):
    from skills.agency.handler import handle
    from src.gateway.session import set_active_role, get_active_role
    monkeypatch.setattr("skills.agency.handler.load_roles", lambda: {})
    set_active_role(2, "discord", "code-auditor")
    output = await _collect(handle("/agency", "use none", 2, "discord"))
    assert "清除" in output[0]
    assert get_active_role(2, "discord") == ""
