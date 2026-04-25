import asyncio
import logging
from typing import AsyncGenerator

from src.agent_team import worktree as wt
from src.agent_team.models import SubTask, SubTaskResult
from src.agent_team.planner import plan as _plan
from src.roles import build_role_prompt_prefix

logger = logging.getLogger(__name__)


async def _stream_subprocess(
    binary: str,
    args: list[str],
    prompt: str,
    cwd: str,
    timeout: int,
    role: str = "",
    role_base_dir: str | None = None,
) -> AsyncGenerator[str, None]:
    dna = build_role_prompt_prefix(role, role_base_dir)
    full_prompt = dna + prompt if dna else prompt
    
    cmd = [binary] + args + [full_prompt]
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdin=asyncio.subprocess.DEVNULL,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
        cwd=cwd,
    )
    try:
        async with asyncio.timeout(timeout):
            while True:
                line = await proc.stdout.readline()
                if not line:
                    break
                yield line.decode("utf-8", errors="replace")
    except asyncio.TimeoutError:
        proc.kill()
        await proc.wait()
        yield f"[timed out after {timeout}s]\n"
    finally:
        if proc.returncode is None:
            proc.kill()
            await proc.wait()


async def _collect_subprocess_output(
    binary: str,
    args: list[str],
    prompt: str,
    cwd: str,
    timeout: int,
    role: str = "",
    role_base_dir: str | None = None,
) -> tuple[list[str], int]:
    """Run subprocess, collect all output lines, return (chunks, returncode)."""
    dna = build_role_prompt_prefix(role, role_base_dir)
    full_prompt = dna + prompt if dna else prompt

    cmd = [binary] + args + [full_prompt]
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdin=asyncio.subprocess.DEVNULL,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
        cwd=cwd,
    )
    chunks = []
    try:
        async with asyncio.timeout(timeout):
            while True:
                line = await proc.stdout.readline()
                if not line:
                    break
                chunks.append(line.decode("utf-8", errors="replace"))
        await proc.wait()
    except asyncio.TimeoutError:
        proc.kill()
        await proc.wait()
        chunks.append(f"[timed out after {timeout}s]\n")
    finally:
        if proc.returncode is None:
            proc.kill()
            await proc.wait()
    return chunks, proc.returncode if proc.returncode is not None else 0


async def run_p7(
    task_description: str,
    binary: str,
    args: list[str],
    timeout: int,
    cwd: str,
    role: str = "",
) -> AsyncGenerator[str, None]:
    yield f"[P7] Running as {role if role else 'default'}...\n"
    async for chunk in _stream_subprocess(
        binary, args, task_description, cwd, timeout, role=role, role_base_dir=cwd
    ):
        yield chunk


async def run_p10(
    task_description: str,
    binary: str,
    args: list[str],
    timeout: int,
    cwd: str,
    role: str = "expert-architect" # P10 defaults to architect
) -> AsyncGenerator[str, None]:
    p10_prompt = (
        "Produce a strategy document for the following. "
        "Do NOT write implementation code. Output: goals, trade-offs, recommended approach, risks.\n"
        f"Task: {task_description}"
    )
    yield f"[P10] Generating architecture document as {role}...\n"
    async for chunk in _stream_subprocess(
        binary, args, p10_prompt, cwd, timeout, role=role, role_base_dir=cwd
    ):
        yield chunk


async def _changed_files(worktree_path: str) -> list[str]:
    """Return files changed relative to HEAD in a worktree."""
    try:
        proc = await asyncio.create_subprocess_exec(
            "git", "diff", "--name-only", "HEAD",
            cwd=worktree_path,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, _ = await proc.communicate()
        if proc.returncode == 0:
            return [f for f in stdout.decode().splitlines() if f]
    except Exception:
        pass
    return []


async def _collect_subtask(
    subtask: "SubTask",
    runner_binaries: dict[str, str],
    runner_args: dict[str, list[str]],
    timeout: int,
    cwd: str,
    data_dir: str,
    index: int,
) -> tuple["SubTask", "SubTaskResult", list[str]]:
    binary = runner_binaries.get(subtask.agent, subtask.agent)
    args = runner_args.get(subtask.agent, [])
    task_id = subtask.id.rsplit("-", 1)[0]
    subtask.worktree_path = wt.worktree_path(data_dir, task_id, index)

    chunks: list[str] = []
    returncode = -1
    changed: list[str] = []
    timed_out = False

    try:
        await wt.create(base_repo=cwd, path=subtask.worktree_path, branch=f"team/{subtask.id}")
        subtask.status = "running"
        raw_chunks, returncode = await _collect_subprocess_output(
            binary,
            args,
            subtask.prompt,
            subtask.worktree_path,
            timeout,
            role=subtask.role,
            role_base_dir=cwd,
        )
        timed_out = any("[timed out" in c for c in raw_chunks)
        chunks = [f"[subtask-{index}|{subtask.role}] {c}" for c in raw_chunks]
        if timed_out:
            subtask.status = "timeout"
            subtask.result = f"timed out after {timeout}s"
        elif returncode != 0:
            subtask.status = "failed"
            subtask.result = f"exited with code {returncode}"
        else:
            subtask.status = "done"
            changed = await _changed_files(subtask.worktree_path)
    except Exception as e:
        subtask.status = "failed"
        subtask.result = str(e)
        chunks.append(f"[subtask-{index}] ERROR: {e}\n")

    stdout_snippet = "".join(chunks)[-500:] if chunks else ""
    dod_verdict = "unknown"
    if subtask.status == "done":
        dod_verdict = "met"
    elif subtask.status in ("failed", "timeout"):
        dod_verdict = "unmet"

    sr = SubTaskResult(
        subtask_id=subtask.id,
        status=subtask.status,
        returncode=returncode,
        stdout_snippet=stdout_snippet,
        changed_files=changed,
        worktree_path=subtask.worktree_path,
        dod_verdict=dod_verdict,
    )
    return subtask, sr, chunks


async def run_p9(
    task_description: str,
    task_id: str,
    planner_binary: str,
    planner_args: list[str],
    runner_binaries: dict[str, str],
    runner_args: dict[str, list[str]],
    timeout: int,
    cwd: str,
    data_dir: str,
    depth: int = 0,
    max_depth: int = 2,
    fallback_role: str = "fullstack-dev",
) -> AsyncGenerator[str, None]:
    if depth >= max_depth:
        logger.warning("run_p9 depth=%d >= max_depth=%d, falling back to single runner", depth, max_depth)
        yield f"[P9] depth limit reached (depth={depth}), running as single task\n"
        async for chunk in run_p7(task_description, planner_binary, planner_args, timeout, cwd, role=fallback_role):
            yield chunk
        return

    yield "[P9] Planning subtasks as department-head...\n"
    try:
        subtasks = await _plan(
            task_description=task_description,
            task_id=task_id,
            binary=planner_binary,
            args=planner_args,
            timeout=min(120, timeout),
            cwd=cwd,
        )
    except Exception as e:
        yield f"[P9] Planning failed: {e}\n"
        return

    for st in subtasks:
        st.depth = depth + 1
        st.parent_id = task_id

    plan_lines = "\n".join(f"  [{i}|{st.agent}|{st.role}] {st.prompt[:60]}" for i, st in enumerate(subtasks))
    yield f"[P9] Plan:\n{plan_lines}\n[P9] Executing {len(subtasks)} subtasks in parallel...\n"

    results = await asyncio.gather(
        *[
            _collect_subtask(st, runner_binaries, runner_args, timeout, cwd, data_dir, i)
            for i, st in enumerate(subtasks)
        ],
        return_exceptions=True,
    )

    for result in results:
        if isinstance(result, Exception):
            yield f"[P9] Subtask error: {result}\n"
        else:
            _, _sr, chunks = result
            for chunk in chunks:
                yield chunk

    yield "[P9] Summary:\n"
    leftover_paths: list[str] = []
    for result in results:
        if isinstance(result, Exception):
            yield f"[P9]   ✗ error: {result}\n"
        else:
            subtask, sr, _ = result
            if subtask.status == "done":
                files_str = ", ".join(sr.changed_files) if sr.changed_files else "(none)"
                yield f"[P9]   ✓ {subtask.id} ({subtask.role}) rc={sr.returncode} dod={sr.dod_verdict} changed={files_str}\n"
                try:
                    await wt.remove(subtask.worktree_path, base_repo=cwd)
                except Exception:
                    leftover_paths.append(subtask.worktree_path)
            else:
                yield (
                    f"[P9]   ✗ {subtask.id} ({subtask.role}) {subtask.status} "
                    f"rc={sr.returncode} dod={sr.dod_verdict}: {subtask.result}\n"
                )
                leftover_paths.append(subtask.worktree_path)
    if leftover_paths:
        yield "[P9] Leftover worktrees (manual cleanup required):\n"
        for p in leftover_paths:
            yield f"[P9]   {p}\n"
