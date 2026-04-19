import asyncio
from pathlib import Path


async def create(base_repo: str, path: str, branch: str) -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    proc = await asyncio.create_subprocess_exec(
        "git", "worktree", "add", path, "-b", branch,
        cwd=base_repo,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    _, stderr = await proc.communicate()
    if proc.returncode != 0:
        raise RuntimeError(f"git worktree add failed: {stderr.decode().strip()}")


async def remove(path: str) -> None:
    if not Path(path).exists():
        return

    # Try to find the base repository by walking up from the worktree path
    worktree_path_obj = Path(path)
    current = worktree_path_obj.parent.parent  # Go up from worktrees/name to parent

    # Execute git worktree remove from the base repo directory
    proc = await asyncio.create_subprocess_exec(
        "git", "worktree", "remove", "--force", path,
        cwd=str(current),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    await proc.communicate()


def worktree_path(data_dir: str, task_id: str, index: int) -> str:
    return f"{data_dir}/worktrees/{task_id}-{index}"
