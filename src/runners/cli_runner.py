# src/runners/cli_runner.py
import asyncio
from typing import AsyncIterator
from src.runners.audit import AuditLog


class CLIRunner:
    def __init__(
        self,
        name: str,
        binary: str,
        args: list[str],
        timeout_seconds: int,
        context_token_budget: int,
        audit: AuditLog,
    ):
        self.name = name
        self.binary = binary
        self.args = args
        self.timeout_seconds = timeout_seconds
        self.context_token_budget = context_token_budget
        self._audit = audit

    async def run(
        self,
        prompt: str,
        user_id: int,
        channel: str,
        cwd: str,
    ) -> AsyncIterator[str]:
        await self._audit.write(
            user_id=user_id,
            channel=channel,
            runner=self.name,
            prompt=prompt,
            cwd=cwd,
        )

        cmd = [self.binary] + self.args + [prompt]
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
            cwd=cwd,
        )

        try:
            async with asyncio.timeout(self.timeout_seconds):
                assert proc.stdout is not None
                while True:
                    line = await proc.stdout.readline()
                    if not line:
                        break
                    yield line.decode("utf-8", errors="replace")
        except asyncio.TimeoutError:
            proc.kill()
            await proc.wait()
            raise TimeoutError(f"Runner '{self.name}' exceeded {self.timeout_seconds}s timeout")
        finally:
            if proc.returncode is None:
                proc.kill()
                await proc.wait()
