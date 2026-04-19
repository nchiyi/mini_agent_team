import asyncio
from typing import AsyncIterator


async def _stream_subprocess(
    binary: str,
    args: list[str],
    prompt: str,
    cwd: str,
    timeout: int,
) -> AsyncIterator[str]:
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


async def run_p7(
    task_description: str,
    binary: str,
    args: list[str],
    timeout: int,
    cwd: str,
) -> AsyncIterator[str]:
    first = True
    async for chunk in _stream_subprocess(binary, args, task_description, cwd, timeout):
        if first:
            yield f"[P7] Running...\n"
            first = False
        yield chunk


async def run_p10(
    task_description: str,
    binary: str,
    args: list[str],
    timeout: int,
    cwd: str,
) -> AsyncIterator[str]:
    p10_prompt = (
        "You are a software architect. Produce a strategy document for the following. "
        "Do NOT write implementation code. Output: goals, trade-offs, recommended approach, risks.\n"
        f"Task: {task_description}"
    )
    first = True
    async for chunk in _stream_subprocess(binary, args, p10_prompt, cwd, timeout):
        if first:
            yield "[P10] Generating architecture document...\n"
            first = False
        yield chunk
