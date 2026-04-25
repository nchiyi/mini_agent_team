# src/runners/acp_runner.py
import asyncio
import logging
import time
from typing import AsyncIterator

from src.runners.base import BaseRunner
from src.runners.acp_protocol import ACPConnection

logger = logging.getLogger(__name__)


class ACPRunner(BaseRunner):
    """
    Replaces CLIRunner for claude, codex, gemini.

    Starts a persistent ACP agent subprocess on first use, then routes all
    messages through long-lived sessions — no subprocess cold-start per message.

    Supported commands:
      claude  → claude-agent-acp
      codex   → codex-acp
      gemini  → gemini --acp --yolo
    """

    def __init__(
        self,
        name: str,
        command: str,
        args: list[str],
        timeout_seconds: int,
        context_token_budget: int,
        session_ttl_minutes: int = 60,
    ) -> None:
        self.name = name
        self.context_token_budget = context_token_budget
        self._command = command
        self._args = args
        self.timeout_seconds = timeout_seconds
        self._session_ttl = session_ttl_minutes * 60

        self._conn: ACPConnection | None = None
        self._init_lock = asyncio.Lock()
        self._session_lock = asyncio.Lock()
        self._initialized = False
        # user_id → (session_id, last_used_monotonic)
        self._sessions: dict[int, tuple[str, float]] = {}

    async def _ensure_initialized(self, cwd: str) -> None:
        async with self._init_lock:
            if self._initialized:
                return
            proc = await asyncio.create_subprocess_exec(
                self._command,
                *self._args,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.DEVNULL,
                cwd=cwd,
            )
            self._conn = ACPConnection(proc, cwd=cwd)
            self._conn.start()
            await self._conn.initialize()
            self._initialized = True
            logger.info("ACPRunner '%s' initialized (pid=%s)", self.name, proc.pid)

    async def _get_or_create_session(self, user_id: int, cwd: str) -> str:
        async with self._session_lock:
            now = time.monotonic()
            if user_id in self._sessions:
                session_id, last_used = self._sessions[user_id]
                if now - last_used < self._session_ttl:
                    self._sessions[user_id] = (session_id, now)
                    return session_id
                logger.info("ACPRunner '%s' session TTL expired for user %s", self.name, user_id)

            session_id = await self._conn.new_session(cwd=cwd)
            self._sessions[user_id] = (session_id, now)
            logger.info("ACPRunner '%s' new session for user %s: %s", self.name, user_id, session_id)
            return session_id

    async def run(
        self,
        prompt: str,
        user_id: int,
        channel: str,
        cwd: str,
        attachments: list[str] | None = None,
    ) -> AsyncIterator[str]:
        await self._ensure_initialized(cwd)
        session_id = await self._get_or_create_session(user_id, cwd)

        if attachments:
            # Prepend attachment paths as context — ACP handles file reading natively
            paths = "\n".join(f"[attached: {p}]" for p in attachments)
            prompt = f"{paths}\n\n{prompt}"

        try:
            async with asyncio.timeout(self.timeout_seconds):
                async for chunk in self._conn.prompt(session_id=session_id, text=prompt):
                    yield chunk
        except asyncio.TimeoutError:
            raise TimeoutError(
                f"ACPRunner '{self.name}' exceeded {self.timeout_seconds}s timeout"
            )
        except Exception as e:
            logger.error("ACPRunner '%s' error: %s", self.name, e, exc_info=True)
            self._sessions.pop(user_id, None)
            if (self._conn is not None
                    and self._conn._reader_task is not None
                    and self._conn._reader_task.done()):
                logger.warning("ACPRunner '%s': subprocess crashed, resetting for re-init", self.name)
                async with self._init_lock:
                    self._initialized = False
                    self._conn = None
                    self._sessions.clear()
            raise

    async def close(self) -> None:
        if self._conn is not None:
            await self._conn.close()
            self._conn = None
            self._initialized = False
