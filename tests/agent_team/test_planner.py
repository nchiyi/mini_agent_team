import pytest

pytestmark = pytest.mark.asyncio


async def test_parse_subtasks_valid_json():
    from src.agent_team.planner import parse_subtasks
    output = '[{"agent":"codex","prompt":"build x","dod":"tests pass"}]'
    subtasks = parse_subtasks(output, task_id="t1")
    assert len(subtasks) == 1
    assert subtasks[0].agent == "codex"
    assert subtasks[0].prompt == "build x"
    assert subtasks[0].dod == "tests pass"
    assert subtasks[0].id == "t1-0"


async def test_parse_subtasks_multiple():
    from src.agent_team.planner import parse_subtasks
    output = (
        'Here is the plan:\n'
        '[{"agent":"codex","prompt":"impl","dod":"code done"},'
        '{"agent":"gemini","prompt":"docs","dod":"docs written"}]\n'
        'End of plan.'
    )
    subtasks = parse_subtasks(output, task_id="t2")
    assert len(subtasks) == 2
    assert subtasks[0].id == "t2-0"
    assert subtasks[1].id == "t2-1"
    assert subtasks[1].agent == "gemini"


async def test_parse_subtasks_no_json_raises():
    from src.agent_team.planner import parse_subtasks
    with pytest.raises(ValueError, match="valid JSON"):
        parse_subtasks("no json here", task_id="t3")


async def test_parse_subtasks_missing_dod_defaults_empty():
    from src.agent_team.planner import parse_subtasks
    output = '[{"agent":"claude","prompt":"do something"}]'
    subtasks = parse_subtasks(output, task_id="t4")
    assert subtasks[0].dod == ""


async def test_plan_uses_binary_and_returns_subtasks(tmp_path):
    from src.agent_team.planner import plan
    # python3 -c "print(...)" outputs JSON regardless of the prompt argument
    json_out = '[{"agent":"codex","prompt":"build it","dod":"done"}]'
    subtasks = await plan(
        task_description="build something",
        task_id="plan-test",
        binary="python3",
        args=["-c", f"print('{json_out}')"],
        timeout=10,
        cwd=str(tmp_path),
    )
    assert len(subtasks) == 1
    assert subtasks[0].agent == "codex"
    assert subtasks[0].id == "plan-test-0"


async def test_parse_subtasks_invalid_json_raises():
    from src.agent_team.planner import parse_subtasks
    # Has brackets but invalid JSON content
    with pytest.raises(ValueError, match="valid JSON"):
        parse_subtasks("[not valid json]", task_id="t5")


async def test_parse_subtasks_missing_agent_raises():
    from src.agent_team.planner import parse_subtasks
    with pytest.raises(ValueError, match="missing required"):
        parse_subtasks('[{"prompt":"x","dod":"y"}]', task_id="t6")


async def test_plan_subprocess_failure_raises(tmp_path):
    from src.agent_team.planner import plan
    with pytest.raises(RuntimeError, match="exited with code"):
        await plan(
            task_description="x",
            task_id="fail-test",
            binary="python3",
            args=["-c", "import sys; sys.exit(1)"],
            timeout=5,
            cwd=str(tmp_path),
        )
