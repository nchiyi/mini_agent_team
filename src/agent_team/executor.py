import asyncio
from typing import AsyncGenerator

from src.agent_team import worktree as wt
from src.agent_team.models import SubTask
from src.agent_team.planner import plan as _plan


async def _stream_subprocess(
    binary: str,
    args: list[str],
    prompt: str,
    cwd: str,
    timeout: int,
) -> AsyncGenerator[str, None]:
    cmd = [binary] + args + [prompt]
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
) -> tuple[list[str], int]:
    """Run subprocess, collect all output lines, return (chunks, returncode)."""
    cmd = [binary] + args + [prompt]
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
    except asyncio.TimeoutError:
        proc.kill()
        await proc.wait()
        chunks.append(f"[timed out after {timeout}s]\n")
    finally:
        if proc.returncode is None:
            proc.kill()
            await proc.wait()
    return chunks, proc.returncode or 0


async def run_p7(
    task_description: str,
    binary: str,
    args: list[str],
    timeout: int,
    cwd: str,
) -> AsyncGenerator[str, None]:
    yield "[P7] Running...\n"
    async for chunk in _stream_subprocess(binary, args, task_description, cwd, timeout):
        yield chunk


async def run_p10(
    task_description: str,
    binary: str,
    args: list[str],
    timeout: int,
    cwd: str,
) -> AsyncGenerator[str, None]:
    p10_prompt = (
        "You are a software architect. Produce a strategy document for the following. "
        "Do NOT write implementation code. Output: goals, trade-offs, recommended approach, risks.\n"
        f"Task: {task_description}"
    )
    yield "[P10] Generating architecture document...\n"
    async for chunk in _stream_subprocess(binary, args, p10_prompt, cwd, timeout):
        yield chunk


async def _collect_subtask(
    subtask: "SubTask",
    runner_binaries: dict[str, str],
    runner_args: dict[str, list[str]],
    timeout: int,
    cwd: str,
    data_dir: str,
    index: int,
) -> tuple["SubTask", list[str]]:
    binary = runner_binaries.get(subtask.agent, subtask.agent)
    args = runner_args.get(subtask.agent, [])
    task_id = subtask.id.rsplit("-", 1)[0]
    subtask.worktree_path = wt.worktree_path(data_dir, task_id, index)

    chunks = []
    try:
        await wt.create(base_repo=cwd, path=subtask.worktree_path, branch=f"team/{subtask.id}")
        subtask.status = "running"
        raw_chunks, returncode = await _collect_subprocess_output(
            binary, args, subtask.prompt, subtask.worktree_path, timeout
        )
        chunks = [f"[subtask-{index}] {c}" for c in raw_chunks]
        if returncode != 0:
            subtask.status = "failed"
            subtask.result = f"exited with code {returncode}"
        else:
            subtask.status = "done"
    except Exception as e:
        subtask.status = "failed"
        subtask.result = str(e)
        chunks.append(f"[subtask-{index}] ERROR: {e}\n")

    return subtask, chunks


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
) -> AsyncGenerator[str, None]:
    yield "[P9] Planning subtasks...\n"
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

    plan_lines = "\n".join(f"  [{i}|{st.agent}] {st.prompt[:60]}" for i, st in enumerate(subtasks))
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
            _, chunks = result
            for chunk in chunks:
                yield chunk

    yield "[P9] Summary:\n"
    for result in results:
        if isinstance(result, Exception):
            yield f"[P9]   ✗ error: {result}\n"
        else:
            subtask, _ = result
            if subtask.status == "done":
                yield f"[P9]   ✓ subtask {subtask.id} done\n"
                try:
                    await wt.remove(subtask.worktree_path, base_repo=cwd)
                except Exception:
                    pass
            else:
                yield f"[P9]   ✗ subtask {subtask.id} failed: {subtask.result}\n"
                yield f"[P9]   Worktree preserved at: {subtask.worktree_path}\n"
