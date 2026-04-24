import subprocess
from pathlib import Path

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


@pytest.fixture
def git_repo(tmp_path):
    subprocess.run(["git", "init", str(tmp_path)], check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "t@t.com"],
                   check=True, capture_output=True, cwd=str(tmp_path))
    subprocess.run(["git", "config", "user.name", "T"],
                   check=True, capture_output=True, cwd=str(tmp_path))
    (tmp_path / "README.md").write_text("test")
    subprocess.run(["git", "add", "."], check=True, capture_output=True, cwd=str(tmp_path))
    subprocess.run(["git", "commit", "-m", "init"],
                   check=True, capture_output=True, cwd=str(tmp_path))
    return tmp_path


async def test_run_p9_both_subtasks_execute(git_repo):
    from src.agent_team.executor import run_p9
    # python3 -c "print(JSON)" outputs the plan; echo is used as runner
    json_plan = '[{"agent":"echo","prompt":"task-a","dod":"done"},{"agent":"echo","prompt":"task-b","dod":"done"}]'
    chunks = [c async for c in run_p9(
        task_description="do two things",
        task_id="test-p9",
        planner_binary="python3",
        planner_args=["-c", f"print('{json_plan}')"],
        runner_binaries={"echo": "echo"},
        runner_args={"echo": []},
        timeout=10,
        cwd=str(git_repo),
        data_dir=str(git_repo),
    )]
    full = "".join(chunks)
    assert "[P9]" in full
    # Both subtasks should have produced output
    assert "subtask-0" in full
    assert "subtask-1" in full


async def test_run_p9_one_failure_continues(git_repo):
    from src.agent_team.executor import run_p9
    # First subtask uses "false" (exits 1), second uses "echo"
    json_plan = '[{"agent":"false","prompt":"x","dod":"done"},{"agent":"echo","prompt":"succeeds","dod":"done"}]'
    chunks = [c async for c in run_p9(
        task_description="mixed task",
        task_id="test-p9-fail",
        planner_binary="python3",
        planner_args=["-c", f"print('{json_plan}')"],
        runner_binaries={"false": "false", "echo": "echo"},
        runner_args={"false": [], "echo": []},
        timeout=10,
        cwd=str(git_repo),
        data_dir=str(git_repo),
    )]
    full = "".join(chunks)
    # Should report both: one failure, one success
    assert "✗" in full  # "false" subtask reported as failure
    assert "✓" in full  # echo subtask reported as success
    # The echo subtask should still have run
    assert "subtask-1" in full


async def test_run_p9_cleanup_successful_worktrees(git_repo):
    from src.agent_team.executor import run_p9
    json_plan = '[{"agent":"echo","prompt":"hello","dod":"done"},{"agent":"echo","prompt":"world","dod":"done"}]'
    _ = [c async for c in run_p9(
        task_description="one task",
        task_id="test-cleanup",
        planner_binary="python3",
        planner_args=["-c", f"print('{json_plan}')"],
        runner_binaries={"echo": "echo"},
        runner_args={"echo": []},
        timeout=10,
        cwd=str(git_repo),
        data_dir=str(git_repo),
    )]
    # Successful worktrees should be cleaned up
    wt = Path(git_repo) / "worktrees" / "test-cleanup-0"
    assert not wt.exists()


async def test_run_p9_summary_includes_returncode_and_dod(git_repo):
    from src.agent_team.executor import run_p9
    json_plan = '[{"agent":"echo","prompt":"hello","dod":"printed"},{"agent":"echo","prompt":"world","dod":"printed"}]'
    chunks = [c async for c in run_p9(
        task_description="two echos",
        task_id="test-result",
        planner_binary="python3",
        planner_args=["-c", f"print('{json_plan}')"],
        runner_binaries={"echo": "echo"},
        runner_args={"echo": []},
        timeout=10,
        cwd=str(git_repo),
        data_dir=str(git_repo),
    )]
    full = "".join(chunks)
    assert "rc=0" in full
    assert "dod=met" in full


async def test_run_p9_failed_subtask_shows_leftover(git_repo):
    from src.agent_team.executor import run_p9
    json_plan = '[{"agent":"false","prompt":"fail","dod":"done"},{"agent":"echo","prompt":"ok","dod":"done"}]'
    chunks = [c async for c in run_p9(
        task_description="mixed",
        task_id="test-leftover",
        planner_binary="python3",
        planner_args=["-c", f"print('{json_plan}')"],
        runner_binaries={"false": "false", "echo": "echo"},
        runner_args={"false": [], "echo": []},
        timeout=10,
        cwd=str(git_repo),
        data_dir=str(git_repo),
    )]
    full = "".join(chunks)
    assert "dod=unmet" in full
    assert "Leftover worktrees" in full
