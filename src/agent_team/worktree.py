import asyncio
import logging
from pathlib import Path

logger = logging.getLogger(__name__)


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


async def remove(path: str, base_repo: str = "") -> None:
    if not Path(path).exists():
        return

    # Use provided base_repo or derive from path
    cwd = base_repo if base_repo else str(Path(path).parent.parent)

    # Execute git worktree remove from the base repo directory
    proc = await asyncio.create_subprocess_exec(
        "git", "worktree", "remove", "--force", path,
        cwd=cwd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    _, stderr = await proc.communicate()
    if proc.returncode != 0:
        logger.warning("git worktree remove failed (rc=%d): %s", proc.returncode, stderr.decode().strip())


def worktree_path(data_dir: str, task_id: str, index: int) -> str:
    return f"{data_dir}/worktrees/{task_id}-{index}"
