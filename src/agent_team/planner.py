import asyncio
import json
import re

from src.agent_team.models import SubTask

_PLANNER_PROMPT_PREFIX = (
    "You are a task planner. Break the following task into 2-4 independent subtasks. "
    "Each subtask must specify the agent (claude, codex, or gemini), the prompt to send, "
    "and a definition_of_done. "
    'Output ONLY valid JSON with no other text: [{"agent": "...", "prompt": "...", "dod": "..."}]\n'
    "Task: "
)


def parse_subtasks(output: str, task_id: str) -> list[SubTask]:
    for match in re.finditer(r'\[', output):
        start = match.start()
        try:
            raw, _end = json.JSONDecoder().raw_decode(output, start)
            if isinstance(raw, list):
                subtasks = []
                for i, item in enumerate(raw):
                    agent = item.get("agent", "")
                    prompt = item.get("prompt", "")
                    if not agent or not prompt:
                        raise ValueError(
                            f"Subtask {i} missing required field 'agent' or 'prompt'. Item: {item}"
                        )
                    subtasks.append(SubTask(
                        id=f"{task_id}-{i}",
                        agent=agent,
                        prompt=prompt,
                        dod=item.get("dod", ""),
                    ))
                return subtasks
        except (json.JSONDecodeError, KeyError):
            continue
    raise ValueError(f"Planner output contains no valid JSON array. Output: {output[:300]}")


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

    prompt = _PLANNER_PROMPT_PREFIX + task_description
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

    if proc.returncode != 0:
        raise RuntimeError(
            f"Planner subprocess exited with code {proc.returncode}. "
            f"Output: {''.join(chunks)[:300]}"
        )

    return parse_subtasks("".join(chunks), task_id)
