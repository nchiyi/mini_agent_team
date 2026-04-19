import asyncio
import pytest
import subprocess
from pathlib import Path

pytestmark = pytest.mark.asyncio


@pytest.fixture
def git_repo(tmp_path):
    """Create a minimal git repo for worktree tests."""
    subprocess.run(["git", "init", str(tmp_path)], check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "test@test.com"],
                   check=True, capture_output=True, cwd=str(tmp_path))
    subprocess.run(["git", "config", "user.name", "Test"],
                   check=True, capture_output=True, cwd=str(tmp_path))
    # Need at least one commit for worktrees to work
    (tmp_path / "README.md").write_text("test")
    subprocess.run(["git", "add", "."], check=True, capture_output=True, cwd=str(tmp_path))
    subprocess.run(["git", "commit", "-m", "init"],
                   check=True, capture_output=True, cwd=str(tmp_path))
    return tmp_path


async def test_create_worktree(git_repo, tmp_path):
    from src.agent_team.worktree import create
    wt_path = str(tmp_path / "worktrees" / "task-0")
    await create(base_repo=str(git_repo), path=wt_path, branch="team/task-0")
    assert Path(wt_path).exists()
    assert (Path(wt_path) / ".git").exists()


async def test_remove_worktree(git_repo, tmp_path):
    from src.agent_team.worktree import create, remove
    wt_path = str(tmp_path / "worktrees" / "task-1")
    await create(base_repo=str(git_repo), path=wt_path, branch="team/task-1")
    await remove(wt_path)
    assert not Path(wt_path).exists()


async def test_remove_nonexistent_is_noop():
    from src.agent_team.worktree import remove
    # Should not raise even if path doesn't exist
    await remove("/tmp/no_such_worktree_xyz123")


def test_worktree_path():
    from src.agent_team.worktree import worktree_path
    result = worktree_path("data", "abc123", 0)
    assert result == "data/worktrees/abc123-0"
    result2 = worktree_path("data", "abc123", 1)
    assert result2 == "data/worktrees/abc123-1"
