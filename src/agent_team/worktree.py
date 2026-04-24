import asyncio
import logging
from pathlib import Path

logger = logging.getLogger(__name__)


async def preflight(base_repo: str) -> None:
    """Raise RuntimeError if base_repo is not a valid git repository."""
    if not Path(base_repo).is_dir():
        raise RuntimeError(f"base_repo does not exist: {base_repo!r}")
    proc = await asyncio.create_subprocess_exec(
        "git", "rev-parse", "HEAD",
        cwd=base_repo,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    _, stderr = await proc.communicate()
    if proc.returncode != 0:
        raise RuntimeError(
            f"base_repo {base_repo!r} is not a git repository or has no commits: "
            f"{stderr.decode().strip()}"
        )

    # Log (but do not fail) if the working tree is dirty.
    dirty_proc = await asyncio.create_subprocess_exec(
        "git", "status", "--porcelain",
        cwd=base_repo,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, _ = await dirty_proc.communicate()
    if stdout.strip():
        logger.warning("base_repo %r has uncommitted changes; worktree may diverge", base_repo)


async def create(base_repo: str, path: str, branch: str) -> None:
    await preflight(base_repo)

    wt_path = Path(path)
    wt_path.parent.mkdir(parents=True, exist_ok=True)

    if wt_path.exists():
        logger.warning("Worktree path already exists, reusing: %s", path)
        return

    # Try to create with -b (new branch).
    # If the branch exists but is not checked out elsewhere, fall back to -B.
    # If the branch is checked out in another worktree, use a unique branch name.
    candidates = [("-b", branch), ("-B", branch), ("-b", f"{branch}-1")]
    for flag, br in candidates:
        proc = await asyncio.create_subprocess_exec(
            "git", "worktree", "add", path, flag, br,
            cwd=base_repo,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        _, stderr = await proc.communicate()
        if proc.returncode == 0:
            return
        err = stderr.decode().strip()
        if flag == "-b" and br == branch and (
            "already exists" in err or "fatal: A branch named" in err
        ):
            logger.warning("Branch %r already exists, retrying with -B", branch)
            continue
        if "-B" in flag and "already used by worktree" in err:
            logger.warning("Branch %r is active in another worktree, retrying with unique name", branch)
            continue
        raise RuntimeError(f"git worktree add failed: {err}")


async def remove(path: str, base_repo: str = "") -> None:
    if not Path(path).exists():
        return

    cwd = base_repo if base_repo else str(Path(path).parent.parent)

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


def list_leftover_worktrees(data_dir: str) -> list[str]:
    """Return paths under data_dir/worktrees/ that still exist on disk."""
    root = Path(data_dir) / "worktrees"
    if not root.exists():
        return []
    return [str(p) for p in sorted(root.iterdir()) if p.is_dir()]
