import os
import uuid
from typing import AsyncIterator

from src.agent_team.classifier import classify
from src.agent_team.models import TaskMode
from src.agent_team.executor import run_p7, run_p9, run_p10


async def handle(command: str, args: str, user_id: int, channel: str) -> AsyncIterator[str]:
    mode, task = classify(args)

    bare_args = args.strip().lower()
    if not task or bare_args in {"p7", "p9", "p10"}:
        yield "Usage: /team <task> | /team p9 <parallel task> | /team p10 <architecture task>"
        return

    binary = os.environ.get("TEAM_BINARY", "claude")
    binary_args = [a for a in os.environ.get("TEAM_ARGS", "--dangerously-skip-permissions").split() if a]
    timeout = int(os.environ.get("TEAM_TIMEOUT", "600"))
    cwd = os.environ.get("TEAM_CWD", ".")
    data_dir = os.environ.get("TEAM_DATA_DIR", "data")

    if mode == TaskMode.P7:
        async for chunk in run_p7(task, binary, binary_args, timeout, cwd):
            yield chunk

    elif mode == TaskMode.P10:
        async for chunk in run_p10(task, binary, binary_args, timeout, cwd):
            yield chunk

    elif mode == TaskMode.P9:
        task_id = uuid.uuid4().hex[:8]
        runner_binaries = {
            "claude": os.environ.get("TEAM_CLAUDE_BINARY", "claude"),
            "codex": os.environ.get("TEAM_CODEX_BINARY", "codex"),
            "gemini": os.environ.get("TEAM_GEMINI_BINARY", "gemini"),
        }
        runner_args = {
            "claude": [a for a in os.environ.get("TEAM_CLAUDE_ARGS", "--dangerously-skip-permissions").split() if a],
            "codex": [a for a in os.environ.get("TEAM_CODEX_ARGS", "--approval-policy auto").split() if a],
            "gemini": [],
        }
        max_depth = int(os.environ.get("TEAM_MAX_DEPTH", "2"))
        fallback_role = os.environ.get("TEAM_FALLBACK_ROLE", "fullstack-dev")
        async for chunk in run_p9(
            task_description=task,
            task_id=task_id,
            planner_binary=binary,
            planner_args=binary_args,
            runner_binaries=runner_binaries,
            runner_args=runner_args,
            timeout=timeout,
            cwd=cwd,
            data_dir=data_dir,
            max_depth=max_depth,
            fallback_role=fallback_role,
        ):
            yield chunk
