import asyncio
import json
import re

from src.agent_team.models import SubTask
from src.roles import available_role_slugs


def _planner_prompt_prefix(cwd: str) -> str:
    roles = available_role_slugs(cwd)
    role_lines = "\n".join(f"- {slug}" for slug in roles) if roles else "- department-head"
    return (
        "You are a Senior Department Head. Break the following task into 2-4 specialized subtasks. "
        "For each subtask, assign the best 'role' (slug from available roster), a 'runner' "
        "(claude, gemini, or codex), a specific 'prompt', and a 'dod' (definition of done). "
        "\nAvailable Roles:\n"
        f"{role_lines}\n"
        "\nOutput ONLY a valid JSON array: "
        '[{"role": "slug", "runner": "...", "prompt": "...", "dod": "..."}]\n'
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
                    role = item.get("role", "")
                    runner = item.get("runner", item.get("agent", ""))
                    prompt = item.get("prompt", "")
                    if not runner or not prompt:
                        raise ValueError(
                            f"Subtask {i} missing required field 'runner/agent' or 'prompt'. Item: {item}"
                        )
                    subtasks.append(SubTask(
                        id=f"{task_id}-{i}",
                        agent=runner,
                        role=role,
                        prompt=prompt,
                        dod=item.get("dod", ""),
                    ))
                return subtasks
        except (json.JSONDecodeError, KeyError, TypeError, AttributeError):
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

    prompt = _planner_prompt_prefix(cwd) + task_description
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
        output_snippet = "".join(chunks)[:300]
        # Claude-code often outputs lots of ansi, try to find JSON anyway
        try:
            return parse_subtasks("".join(chunks), task_id)
        except Exception:
            raise RuntimeError(
                f"Planner subprocess exited with code {proc.returncode}. "
                f"Output: {output_snippet}"
            )

    return parse_subtasks("".join(chunks), task_id)
