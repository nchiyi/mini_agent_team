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


async def test_worktree_path():
    from src.agent_team.worktree import worktree_path
    result = worktree_path("data", "abc123", 0)
    assert result == "data/worktrees/abc123-0"
    result2 = worktree_path("data", "abc123", 1)
    assert result2 == "data/worktrees/abc123-1"


async def test_preflight_valid_repo(git_repo):
    from src.agent_team.worktree import preflight
    await preflight(str(git_repo))  # must not raise


async def test_preflight_nonexistent_dir(tmp_path):
    from src.agent_team.worktree import preflight
    with pytest.raises(RuntimeError, match="does not exist"):
        await preflight(str(tmp_path / "no_such_dir"))


async def test_preflight_non_git_dir(tmp_path):
    from src.agent_team.worktree import preflight
    with pytest.raises(RuntimeError, match="not a git repository"):
        await preflight(str(tmp_path))


async def test_create_branch_collision(git_repo, tmp_path):
    from src.agent_team.worktree import create
    wt1 = str(tmp_path / "wt1")
    wt2 = str(tmp_path / "wt2")
    await create(base_repo=str(git_repo), path=wt1, branch="team/col-0")
    # Second create with same branch name — should succeed via -B fallback
    await create(base_repo=str(git_repo), path=wt2, branch="team/col-0")
    assert Path(wt1).exists()
    assert Path(wt2).exists()


async def test_create_path_collision_is_noop(git_repo, tmp_path):
    from src.agent_team.worktree import create
    wt = str(tmp_path / "existing_wt")
    await create(base_repo=str(git_repo), path=wt, branch="team/exist-0")
    # Second call to same path: must not raise, must leave existing wt intact
    await create(base_repo=str(git_repo), path=wt, branch="team/exist-1")
    assert Path(wt).exists()


async def test_list_leftover_worktrees(git_repo, tmp_path):
    from src.agent_team.worktree import create, list_leftover_worktrees
    wt = str(tmp_path / "worktrees" / "task-0")
    await create(base_repo=str(git_repo), path=wt, branch="team/list-0")
    leftovers = list_leftover_worktrees(str(tmp_path))
    assert any("task-0" in p for p in leftovers)


async def test_list_leftover_worktrees_empty(tmp_path):
    from src.agent_team.worktree import list_leftover_worktrees
    assert list_leftover_worktrees(str(tmp_path)) == []
