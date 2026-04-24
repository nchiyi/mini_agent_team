# src/runners/cli_runner.py
import asyncio
from pathlib import Path
from typing import AsyncIterator
from src.runners.audit import AuditLog

_IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".gif", ".webp"}


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
        attachments: list[str] | None = None,
    ) -> AsyncIterator[str]:
        effective_prompt = prompt
        extra_args: list[str] = []

        if attachments:
            supports_image_flag = "claude" in self.binary or "claude" in self.name
            for path in attachments:
                ext = Path(path).suffix.lower()
                if supports_image_flag and ext in _IMAGE_EXTS:
                    extra_args += ["--image", path]
                else:
                    effective_prompt = f"[attached file: {path}]\n\n" + effective_prompt

        await self._audit.write(
            user_id=user_id,
            channel=channel,
            runner=self.name,
            prompt=effective_prompt,
            cwd=cwd,
        )

        cmd = [self.binary] + extra_args + self.args + [effective_prompt]
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
