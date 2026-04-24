# tests/gateway/test_dept_head_default.py
"""
Tests for issue #17: Department Head default role and file resolution.
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


def test_default_role_is_department_head():
    import main
    assert main._DEFAULT_ROLE == "department-head"


@pytest.mark.asyncio
async def test_dispatch_applies_dept_head_when_no_role_set():
    """When no role is active, department-head DNA should be prepended."""
    import main
    from src.gateway.session import clear_active_role

    clear_active_role(1, "telegram")

    built_prompts = []

    original_apply = main._apply_role_prompt

    def capturing_apply(prompt, role_slug, base_dir):
        built_prompts.append((prompt, role_slug))
        return prompt  # skip actual file I/O for roles

    replies = []
    runner_mock = AsyncMock()

    async def fake_run(*a, **kw):
        yield "ok"

    runner_mock.run = fake_run
    runner_mock.context_token_budget = 4000

    inbound = MagicMock()
    inbound.user_id = 1
    inbound.channel = "telegram"
    inbound.text = "summarise the project"

    session_mgr = MagicMock()
    session = MagicMock()
    session.active_role = ""
    session.current_runner = "claude"
    session.cwd = "/tmp"
    session_mgr.get_or_create.return_value = session
    session_mgr.get_active_role.return_value = ""

    router = MagicMock()
    cmd = MagicMock()
    cmd.is_remember = cmd.is_forget = cmd.is_recall = False
    cmd.is_cancel = cmd.is_status = cmd.is_reset = cmd.is_new = False
    cmd.is_switch_runner = cmd.is_skill = False
    cmd.is_pipeline = cmd.is_discussion = cmd.is_debate = False
    cmd.is_voice_on = cmd.is_voice_off = False
    cmd.is_usage = False
    cmd.role = ""
    cmd.runner = "claude"
    cmd.prompt = "summarise the project"
    router.parse.return_value = cmd

    assembler = AsyncMock()
    assembler.build.return_value = ""

    tier3 = AsyncMock()
    tier1 = MagicMock()
    bridge = AsyncMock()

    with patch.object(main, "_apply_role_prompt", side_effect=capturing_apply), \
         patch.object(main, "resolve_file_refs", new=AsyncMock(return_value="summarise the project")):
        await main.dispatch(
            inbound=inbound,
            bridge=bridge,
            session_mgr=session_mgr,
            router=router,
            runners={"claude": runner_mock},
            tier1=tier1,
            tier3=tier3,
            assembler=assembler,
            send_reply=AsyncMock(),
            recent_turns=5,
        )

    assert len(built_prompts) == 1
    _, role_used = built_prompts[0]
    assert role_used == "department-head"
