import asyncio
import os
from typing import AsyncIterator

_DEV_BINARY = os.environ.get("DEV_AGENT_BINARY", "claude")
_DEV_ARGS_RAW = os.environ.get("DEV_AGENT_ARGS", "--dangerously-skip-permissions")
_DEV_TIMEOUT = int(os.environ.get("DEV_AGENT_TIMEOUT", "300"))


async def handle(command: str, args: str, user_id: int, channel: str) -> AsyncIterator[str]:
    if not args.strip():
        yield "Usage: /dev <task description>"
        return

    binary = os.environ.get("DEV_AGENT_BINARY", _DEV_BINARY)
    args_raw = os.environ.get("DEV_AGENT_ARGS", _DEV_ARGS_RAW)
    extra_args = [a for a in args_raw.split() if a]
    timeout = int(os.environ.get("DEV_AGENT_TIMEOUT", str(_DEV_TIMEOUT)))

    cmd = [binary] + extra_args + [args.strip()]
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
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
            yield f"\n[dev_agent timed out after {timeout}s]"
        finally:
            if proc.returncode is None:
                proc.kill()
                await proc.wait()
    except FileNotFoundError:
        yield f"'{binary}' not found. Set DEV_AGENT_BINARY env var."
    except Exception as e:
        yield f"dev_agent error: {e}"
