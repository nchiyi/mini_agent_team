import asyncio
import json
import re

from src.agent_team.models import SubTask

_PLANNER_PROMPT = (
    "You are a task planner. Break the following task into 2-4 independent subtasks. "
    "Each subtask must specify the agent (claude, codex, or gemini), the prompt to send, "
    "and a definition_of_done. "
    "Output ONLY valid JSON with no other text: "
    '[{{"agent": "...", "prompt": "...", "dod": "..."}}]\n'
    "Task: {task}"
)


def parse_subtasks(output: str, task_id: str) -> list[SubTask]:
    match = re.search(r'\[.*\]', output, re.DOTALL)
    if not match:
        raise ValueError(f"Planner output contains no valid JSON array. Output: {output[:300]}")
    raw = json.loads(match.group())
    return [
        SubTask(
            id=f"{task_id}-{i}",
            agent=item["agent"],
            prompt=item["prompt"],
            dod=item.get("dod", ""),
        )
        for i, item in enumerate(raw)
    ]


async def plan(
    task_description: str,
    task_id: str,
    binary: str = "claude",
    args: list[str] | None = None,
    timeout: int = 120,
    cwd: str = ".",
) -> list[SubTask]:
    if args is None:
        args = ["--dangerously-skip-permissions"]

    prompt = _PLANNER_PROMPT.format(task=task_description)
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
        raise RuntimeError("Planner subprocess timed out")
    finally:
        if proc.returncode is None:
            proc.kill()
            await proc.wait()

    return parse_subtasks("".join(chunks), task_id)
