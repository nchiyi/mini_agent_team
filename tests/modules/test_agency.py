import pytest


pytestmark = pytest.mark.asyncio


async def _collect(gen):
    return [chunk async for chunk in gen]


async def test_agency_list_uses_roster(monkeypatch):
    from modules.agency.handler import handle

    monkeypatch.setattr(
        "modules.agency.handler.load_roles",
        lambda: {
            "code-auditor": {
                "name": "Code Auditor",
                "summary": "Review code changes",
            }
        },
    )

    output = await _collect(handle("/agency", "list", 1, "telegram"))
    assert "Code Auditor" in output[0]
    assert "code-auditor" in output[0]


async def test_agency_use_sets_active_role(monkeypatch):
    from modules.agency.handler import handle
    from src.gateway.session import get_active_role, clear_active_role

    monkeypatch.setattr(
        "modules.agency.handler.load_roles",
        lambda: {
            "code-auditor": {
                "name": "Code Auditor",
                "summary": "Review code changes",
            }
        },
    )

    clear_active_role(1, "telegram")
    output = await _collect(handle("/agency", "use code-auditor", 1, "telegram"))
    assert "角色已啟動" in output[0]
    assert get_active_role(1, "telegram") == "code-auditor"


async def test_agency_clear_resets_active_role(monkeypatch):
    from modules.agency.handler import handle
    from src.gateway.session import set_active_role, get_active_role

    monkeypatch.setattr("modules.agency.handler.load_roles", lambda: {})

    set_active_role(1, "telegram", "code-auditor")
    output = await _collect(handle("/agency", "clear", 1, "telegram"))
    assert "已清除" in output[0]
    assert get_active_role(1, "telegram") == ""
