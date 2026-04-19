import pytest

pytestmark = pytest.mark.asyncio


async def test_run_p7_streams_output(tmp_path):
    from src.agent_team.executor import run_p7
    chunks = [c async for c in run_p7(
        task_description="hello world",
        binary="echo",
        args=[],
        timeout=5,
        cwd=str(tmp_path),
    )]
    full = "".join(chunks)
    assert "[P7]" in full
    assert "hello world" in full


async def test_run_p7_first_chunk_has_prefix(tmp_path):
    from src.agent_team.executor import run_p7
    chunks = [c async for c in run_p7(
        task_description="test",
        binary="echo",
        args=[],
        timeout=5,
        cwd=str(tmp_path),
    )]
    assert chunks[0].startswith("[P7]")


async def test_run_p10_streams_output(tmp_path):
    from src.agent_team.executor import run_p10
    chunks = [c async for c in run_p10(
        task_description="design cache",
        binary="echo",
        args=[],
        timeout=5,
        cwd=str(tmp_path),
    )]
    full = "".join(chunks)
    assert "[P10]" in full


async def test_run_p10_first_chunk_has_prefix(tmp_path):
    from src.agent_team.executor import run_p10
    chunks = [c async for c in run_p10(
        task_description="test",
        binary="echo",
        args=[],
        timeout=5,
        cwd=str(tmp_path),
    )]
    assert chunks[0].startswith("[P10]")


async def test_run_p7_empty_task(tmp_path):
    from src.agent_team.executor import run_p7
    # echo with empty string still produces output (a newline)
    chunks = [c async for c in run_p7(
        task_description="",
        binary="echo",
        args=[],
        timeout=5,
        cwd=str(tmp_path),
    )]
    assert len(chunks) >= 1
