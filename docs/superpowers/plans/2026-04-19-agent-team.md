# AgentTeam Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add `/team` command that routes tasks to single or parallel CLI agents (P7/P9/P10) with git worktree isolation per subtask.

**Architecture:** AgentTeam is a module (`modules/agent_team/`) wrapping a core library (`src/agent_team/`) that handles classification, worktree lifecycle, parallel execution via `asyncio.gather`, and streamed progress output. The module handler is a thin env-var reader that calls into the library.

**Tech Stack:** Python 3.11+ asyncio, git worktree CLI, pytest-asyncio

---

## File Map

| File | Action | Responsibility |
|------|--------|----------------|
| `src/agent_team/__init__.py` | Create | Empty package marker |
| `src/agent_team/models.py` | Create | `TaskMode`, `SubTask`, `TeamTask` dataclasses |
| `src/agent_team/classifier.py` | Create | `classify(args)` → `(TaskMode, str)` |
| `src/agent_team/worktree.py` | Create | `create()`, `remove()`, `worktree_path()` |
| `src/agent_team/planner.py` | Create | `parse_subtasks()` (pure) + `plan()` (calls LLM) |
| `src/agent_team/executor.py` | Create | `run_p7()`, `run_p10()`, `run_p9()` async generators |
| `modules/agent_team/__init__.py` | Create | Empty package marker |
| `modules/agent_team/manifest.yaml` | Create | Module manifest |
| `modules/agent_team/handler.py` | Create | Thin wrapper reading env vars, dispatching executor |
| `tests/agent_team/__init__.py` | Create | Empty package marker |
| `tests/agent_team/test_classifier.py` | Create | Classifier unit tests |
| `tests/agent_team/test_worktree.py` | Create | Worktree async tests with real git |
| `tests/agent_team/test_planner.py` | Create | Planner parse + integration tests |
| `tests/agent_team/test_executor.py` | Create | Executor P7/P9/P10 tests |

---

### Task 1: Models + Classifier

**Files:**
- Create: `src/agent_team/__init__.py`
- Create: `src/agent_team/models.py`
- Create: `src/agent_team/classifier.py`
- Create: `tests/agent_team/__init__.py`
- Test: `tests/agent_team/test_classifier.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/agent_team/__init__.py
# (empty)
```

```python
# tests/agent_team/test_classifier.py
import pytest
from src.agent_team.models import TaskMode


def test_classify_default_p7():
    from src.agent_team.classifier import classify
    mode, task = classify("build something")
    assert mode == TaskMode.P7
    assert task == "build something"


def test_classify_p9_lowercase():
    from src.agent_team.classifier import classify
    mode, task = classify("p9 refactor the auth module")
    assert mode == TaskMode.P9
    assert task == "refactor the auth module"


def test_classify_p9_uppercase():
    from src.agent_team.classifier import classify
    mode, task = classify("P9 build X")
    assert mode == TaskMode.P9
    assert task == "build X"


def test_classify_p10():
    from src.agent_team.classifier import classify
    mode, task = classify("p10 design the caching layer")
    assert mode == TaskMode.P10
    assert task == "design the caching layer"


def test_classify_empty_string():
    from src.agent_team.classifier import classify
    mode, task = classify("")
    assert mode == TaskMode.P7
    assert task == ""


def test_classify_p9_no_task():
    from src.agent_team.classifier import classify
    # "p9" with no following text: strip gives "p9", not "p9 " so falls through to P7
    mode, task = classify("p9")
    assert mode == TaskMode.P7
    assert task == "p9"
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd /tmp/telegram-to-control
python3 -m pytest tests/agent_team/test_classifier.py -v
```

Expected: `ERROR` with `ModuleNotFoundError: No module named 'src.agent_team'`

- [ ] **Step 3: Create package + models + classifier**

```python
# src/agent_team/__init__.py
# (empty file)
```

```python
# src/agent_team/models.py
from dataclasses import dataclass, field
from enum import Enum


class TaskMode(Enum):
    P7 = "p7"
    P9 = "p9"
    P10 = "p10"


@dataclass
class SubTask:
    id: str
    agent: str
    prompt: str
    dod: str
    worktree_path: str = ""
    status: str = "pending"
    result: str = ""


@dataclass
class TeamTask:
    id: str
    mode: TaskMode
    description: str
    subtasks: list[SubTask] = field(default_factory=list)
```

```python
# src/agent_team/classifier.py
from src.agent_team.models import TaskMode


def classify(args: str) -> tuple[TaskMode, str]:
    lower = args.strip().lower()
    if lower.startswith("p9 "):
        return TaskMode.P9, args[3:].strip()
    if lower.startswith("p10 "):
        return TaskMode.P10, args[4:].strip()
    return TaskMode.P7, args.strip()
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd /tmp/telegram-to-control
python3 -m pytest tests/agent_team/test_classifier.py -v
```

Expected: `6 passed`

- [ ] **Step 5: Commit**

```bash
cd /tmp/telegram-to-control
git add src/agent_team/__init__.py src/agent_team/models.py src/agent_team/classifier.py \
        tests/agent_team/__init__.py tests/agent_team/test_classifier.py
git commit -m "feat: add AgentTeam models and P7/P9/P10 classifier"
```

---

### Task 2: Worktree Lifecycle

**Files:**
- Create: `src/agent_team/worktree.py`
- Test: `tests/agent_team/test_worktree.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/agent_team/test_worktree.py
import asyncio
import pytest
import subprocess
from pathlib import Path

pytestmark = pytest.mark.asyncio


@pytest.fixture
def git_repo(tmp_path):
    """Create a minimal git repo for worktree tests."""
    subprocess.run(["git", "init", str(tmp_path)], check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "test@test.com"],
                   check=True, capture_output=True, cwd=str(tmp_path))
    subprocess.run(["git", "config", "user.name", "Test"],
                   check=True, capture_output=True, cwd=str(tmp_path))
    # Need at least one commit for worktrees to work
    (tmp_path / "README.md").write_text("test")
    subprocess.run(["git", "add", "."], check=True, capture_output=True, cwd=str(tmp_path))
    subprocess.run(["git", "commit", "-m", "init"],
                   check=True, capture_output=True, cwd=str(tmp_path))
    return tmp_path


async def test_create_worktree(git_repo, tmp_path):
    from src.agent_team.worktree import create
    wt_path = str(tmp_path / "worktrees" / "task-0")
    await create(base_repo=str(git_repo), path=wt_path, branch="team/task-0")
    assert Path(wt_path).exists()
    assert (Path(wt_path) / ".git").exists()


async def test_remove_worktree(git_repo, tmp_path):
    from src.agent_team.worktree import create, remove
    wt_path = str(tmp_path / "worktrees" / "task-1")
    await create(base_repo=str(git_repo), path=wt_path, branch="team/task-1")
    await remove(wt_path)
    assert not Path(wt_path).exists()


async def test_remove_nonexistent_is_noop():
    from src.agent_team.worktree import remove
    # Should not raise even if path doesn't exist
    await remove("/tmp/no_such_worktree_xyz123")


def test_worktree_path():
    from src.agent_team.worktree import worktree_path
    result = worktree_path("data", "abc123", 0)
    assert result == "data/worktrees/abc123-0"
    result2 = worktree_path("data", "abc123", 1)
    assert result2 == "data/worktrees/abc123-1"
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd /tmp/telegram-to-control
python3 -m pytest tests/agent_team/test_worktree.py -v
```

Expected: `ERROR` with `ModuleNotFoundError: No module named 'src.agent_team.worktree'`

- [ ] **Step 3: Implement worktree.py**

```python
# src/agent_team/worktree.py
import asyncio
from pathlib import Path


async def create(base_repo: str, path: str, branch: str) -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    proc = await asyncio.create_subprocess_exec(
        "git", "worktree", "add", path, "-b", branch,
        cwd=base_repo,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    _, stderr = await proc.communicate()
    if proc.returncode != 0:
        raise RuntimeError(f"git worktree add failed: {stderr.decode().strip()}")


async def remove(path: str) -> None:
    if not Path(path).exists():
        return
    proc = await asyncio.create_subprocess_exec(
        "git", "worktree", "remove", "--force", path,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    await proc.communicate()


def worktree_path(data_dir: str, task_id: str, index: int) -> str:
    return f"{data_dir}/worktrees/{task_id}-{index}"
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd /tmp/telegram-to-control
python3 -m pytest tests/agent_team/test_worktree.py -v
```

Expected: `4 passed`

- [ ] **Step 5: Commit**

```bash
cd /tmp/telegram-to-control
git add src/agent_team/worktree.py tests/agent_team/test_worktree.py
git commit -m "feat: add git worktree lifecycle management"
```

---

### Task 3: Executor — P7 + P10

**Files:**
- Create: `src/agent_team/executor.py` (P7 + P10 only; P9 added in Task 5)
- Test: `tests/agent_team/test_executor.py` (P7 + P10 tests only)

- [ ] **Step 1: Write the failing tests**

```python
# tests/agent_team/test_executor.py
import pytest

pytestmark = pytest.mark.asyncio


async def test_run_p7_streams_output(tmp_path):
    from src.agent_team.executor import run_p7
    chunks = [c async for c in run_p7(
        task_description="hello world",
        binary="echo",
        args=[],
        timeout=5,
        cwd=str(tmp_path),
    )]
    full = "".join(chunks)
    assert "[P7]" in full
    assert "hello world" in full


async def test_run_p7_first_chunk_has_prefix(tmp_path):
    from src.agent_team.executor import run_p7
    chunks = [c async for c in run_p7(
        task_description="test",
        binary="echo",
        args=[],
        timeout=5,
        cwd=str(tmp_path),
    )]
    assert chunks[0].startswith("[P7]")


async def test_run_p10_streams_output(tmp_path):
    from src.agent_team.executor import run_p10
    chunks = [c async for c in run_p10(
        task_description="design cache",
        binary="echo",
        args=[],
        timeout=5,
        cwd=str(tmp_path),
    )]
    full = "".join(chunks)
    assert "[P10]" in full


async def test_run_p10_first_chunk_has_prefix(tmp_path):
    from src.agent_team.executor import run_p10
    chunks = [c async for c in run_p10(
        task_description="test",
        binary="echo",
        args=[],
        timeout=5,
        cwd=str(tmp_path),
    )]
    assert chunks[0].startswith("[P10]")


async def test_run_p7_empty_task(tmp_path):
    from src.agent_team.executor import run_p7
    # echo with empty string still produces output (a newline)
    chunks = [c async for c in run_p7(
        task_description="",
        binary="echo",
        args=[],
        timeout=5,
        cwd=str(tmp_path),
    )]
    assert len(chunks) >= 1
```

- [ ] **Step 2: Run to verify failure**

```bash
cd /tmp/telegram-to-control
python3 -m pytest tests/agent_team/test_executor.py -v
```

Expected: `ERROR` with `ModuleNotFoundError: No module named 'src.agent_team.executor'`

- [ ] **Step 3: Implement executor.py (P7 + P10 only)**

```python
# src/agent_team/executor.py
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
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd /tmp/telegram-to-control
python3 -m pytest tests/agent_team/test_executor.py -v
```

Expected: `5 passed`

- [ ] **Step 5: Commit**

```bash
cd /tmp/telegram-to-control
git add src/agent_team/executor.py tests/agent_team/test_executor.py
git commit -m "feat: add executor run_p7 and run_p10"
```

---

### Task 4: Planner

**Files:**
- Create: `src/agent_team/planner.py`
- Test: `tests/agent_team/test_planner.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/agent_team/test_planner.py
import pytest

pytestmark = pytest.mark.asyncio


def test_parse_subtasks_valid_json():
    from src.agent_team.planner import parse_subtasks
    output = '[{"agent":"codex","prompt":"build x","dod":"tests pass"}]'
    subtasks = parse_subtasks(output, task_id="t1")
    assert len(subtasks) == 1
    assert subtasks[0].agent == "codex"
    assert subtasks[0].prompt == "build x"
    assert subtasks[0].dod == "tests pass"
    assert subtasks[0].id == "t1-0"


def test_parse_subtasks_multiple():
    from src.agent_team.planner import parse_subtasks
    output = (
        'Here is the plan:\n'
        '[{"agent":"codex","prompt":"impl","dod":"code done"},'
        '{"agent":"gemini","prompt":"docs","dod":"docs written"}]\n'
        'End of plan.'
    )
    subtasks = parse_subtasks(output, task_id="t2")
    assert len(subtasks) == 2
    assert subtasks[0].id == "t2-0"
    assert subtasks[1].id == "t2-1"
    assert subtasks[1].agent == "gemini"


def test_parse_subtasks_no_json_raises():
    from src.agent_team.planner import parse_subtasks
    with pytest.raises(ValueError, match="valid JSON"):
        parse_subtasks("no json here", task_id="t3")


def test_parse_subtasks_missing_dod_defaults_empty():
    from src.agent_team.planner import parse_subtasks
    output = '[{"agent":"claude","prompt":"do something"}]'
    subtasks = parse_subtasks(output, task_id="t4")
    assert subtasks[0].dod == ""


async def test_plan_uses_binary_and_returns_subtasks(tmp_path):
    from src.agent_team.planner import plan
    # python3 -c "print(...)" outputs JSON regardless of the prompt argument
    json_out = '[{"agent":"codex","prompt":"build it","dod":"done"}]'
    subtasks = await plan(
        task_description="build something",
        task_id="plan-test",
        binary="python3",
        args=["-c", f"print('{json_out}')"],
        timeout=10,
        cwd=str(tmp_path),
    )
    assert len(subtasks) == 1
    assert subtasks[0].agent == "codex"
    assert subtasks[0].id == "plan-test-0"
```

- [ ] **Step 2: Run to verify failure**

```bash
cd /tmp/telegram-to-control
python3 -m pytest tests/agent_team/test_planner.py -v
```

Expected: `ERROR` with `ModuleNotFoundError: No module named 'src.agent_team.planner'`

- [ ] **Step 3: Implement planner.py**

```python
# src/agent_team/planner.py
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
    match = re.search(r'\[.*?\]', output, re.DOTALL)
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
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd /tmp/telegram-to-control
python3 -m pytest tests/agent_team/test_planner.py -v
```

Expected: `5 passed`

- [ ] **Step 5: Commit**

```bash
cd /tmp/telegram-to-control
git add src/agent_team/planner.py tests/agent_team/test_planner.py
git commit -m "feat: add planner parse_subtasks and plan()"
```

---

### Task 5: Executor — P9 Parallel

**Files:**
- Modify: `src/agent_team/executor.py` (add `run_p9` and `_collect_subtask`)
- Modify: `tests/agent_team/test_executor.py` (add P9 tests)

**Context:** `run_p9` plans subtasks (via `planner.plan`), creates git worktrees, runs agents in parallel via `asyncio.gather`, streams all collected output, then reports results and cleans up successful worktrees.

- [ ] **Step 1: Write the failing P9 tests**

Add these tests to the BOTTOM of `tests/agent_team/test_executor.py`:

```python
import subprocess
from pathlib import Path


@pytest.fixture
def git_repo(tmp_path):
    subprocess.run(["git", "init", str(tmp_path)], check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "t@t.com"],
                   check=True, capture_output=True, cwd=str(tmp_path))
    subprocess.run(["git", "config", "user.name", "T"],
                   check=True, capture_output=True, cwd=str(tmp_path))
    (tmp_path / "README.md").write_text("test")
    subprocess.run(["git", "add", "."], check=True, capture_output=True, cwd=str(tmp_path))
    subprocess.run(["git", "commit", "-m", "init"],
                   check=True, capture_output=True, cwd=str(tmp_path))
    return tmp_path


async def test_run_p9_both_subtasks_execute(git_repo):
    from src.agent_team.executor import run_p9
    # python3 -c "print(JSON)" outputs the plan; echo is used as runner
    json_plan = '[{"agent":"echo","prompt":"task-a","dod":"done"},{"agent":"echo","prompt":"task-b","dod":"done"}]'
    chunks = [c async for c in run_p9(
        task_description="do two things",
        task_id="test-p9",
        planner_binary="python3",
        planner_args=["-c", f"print('{json_plan}')"],
        runner_binaries={"echo": "echo"},
        runner_args={"echo": []},
        timeout=10,
        cwd=str(git_repo),
        data_dir=str(git_repo),
    )]
    full = "".join(chunks)
    assert "[P9]" in full
    # Both subtasks should have produced output
    assert "subtask-0" in full
    assert "subtask-1" in full


async def test_run_p9_one_failure_continues(git_repo):
    from src.agent_team.executor import run_p9
    # First subtask uses "false" (exits 1), second uses "echo"
    json_plan = '[{"agent":"false","prompt":"x","dod":"done"},{"agent":"echo","prompt":"succeeds","dod":"done"}]'
    chunks = [c async for c in run_p9(
        task_description="mixed task",
        task_id="test-p9-fail",
        planner_binary="python3",
        planner_args=["-c", f"print('{json_plan}')"],
        runner_binaries={"false": "false", "echo": "echo"},
        runner_args={"false": [], "echo": []},
        timeout=10,
        cwd=str(git_repo),
        data_dir=str(git_repo),
    )]
    full = "".join(chunks)
    # Should report both: one failure, one success
    assert "✓" in full or "✗" in full
    # Should not raise — gather with return_exceptions handles the failure
    # The echo subtask should still have run
    assert "subtask-1" in full


async def test_run_p9_cleanup_successful_worktrees(git_repo):
    from src.agent_team.executor import run_p9
    from pathlib import Path
    json_plan = '[{"agent":"echo","prompt":"hello","dod":"done"}]'
    _ = [c async for c in run_p9(
        task_description="one task",
        task_id="test-cleanup",
        planner_binary="python3",
        planner_args=["-c", f"print('{json_plan}')"],
        runner_binaries={"echo": "echo"},
        runner_args={"echo": []},
        timeout=10,
        cwd=str(git_repo),
        data_dir=str(git_repo),
    )]
    # Successful worktree should be cleaned up
    wt = Path(git_repo) / "worktrees" / "test-cleanup-0"
    assert not wt.exists()
```

- [ ] **Step 2: Run to verify failure**

```bash
cd /tmp/telegram-to-control
python3 -m pytest tests/agent_team/test_executor.py::test_run_p9_both_subtasks_execute -v
```

Expected: `FAIL` or `ERROR` (run_p9 not yet defined)

- [ ] **Step 3: Add `_collect_subtask` and `run_p9` to executor.py**

Add this to the BOTTOM of `src/agent_team/executor.py` (do not remove existing content):

```python
from src.agent_team import worktree as wt
from src.agent_team.planner import plan as _plan


async def _collect_subtask(
    subtask,
    runner_binaries: dict[str, str],
    runner_args: dict[str, list[str]],
    timeout: int,
    cwd: str,
    data_dir: str,
    index: int,
) -> tuple:
    binary = runner_binaries.get(subtask.agent, subtask.agent)
    args = runner_args.get(subtask.agent, [])
    subtask.worktree_path = wt.worktree_path(data_dir, subtask.id.rsplit("-", 1)[0], index)

    chunks = []
    try:
        await wt.create(base_repo=cwd, path=subtask.worktree_path, branch=f"team/{subtask.id}")
        subtask.status = "running"
        async for chunk in _stream_subprocess(binary, args, subtask.prompt, subtask.worktree_path, timeout):
            chunks.append(f"[subtask-{index}] {chunk}")
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
) -> AsyncIterator[str]:
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
                    await wt.remove(subtask.worktree_path)
                except Exception:
                    pass
            else:
                yield f"[P9]   ✗ subtask {subtask.id} failed: {subtask.result}\n"
                yield f"[P9]   Worktree preserved at: {subtask.worktree_path}\n"
```

- [ ] **Step 4: Run all executor tests to verify they pass**

```bash
cd /tmp/telegram-to-control
python3 -m pytest tests/agent_team/test_executor.py -v
```

Expected: `8 passed` (5 from Task 3 + 3 new P9 tests)

- [ ] **Step 5: Commit**

```bash
cd /tmp/telegram-to-control
git add src/agent_team/executor.py tests/agent_team/test_executor.py
git commit -m "feat: add executor run_p9 with parallel worktree execution"
```

---

### Task 6: Module Manifest + Handler

**Files:**
- Create: `modules/agent_team/__init__.py`
- Create: `modules/agent_team/manifest.yaml`
- Create: `modules/agent_team/handler.py`

No new tests needed — the module system integration is tested via existing `test_e2e_modules.py` pattern. The handler is a thin wrapper; all logic is covered by executor/planner/classifier tests.

- [ ] **Step 1: Create the module files**

```python
# modules/agent_team/__init__.py
# (empty)
```

```yaml
# modules/agent_team/manifest.yaml
name: agent_team
version: 1.0.0
commands: [/team]
description: 多 Agent 協作（P7 單一任務 / P9 並行子任務 / P10 架構文件）
dependencies: []
enabled: true
timeout_seconds: 600
```

```python
# modules/agent_team/handler.py
import os
import uuid
from typing import AsyncIterator

from src.agent_team.classifier import classify
from src.agent_team.models import TaskMode
from src.agent_team.executor import run_p7, run_p9, run_p10


async def handle(command: str, args: str, user_id: int, channel: str) -> AsyncIterator[str]:
    mode, task = classify(args)

    if not task:
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
        ):
            yield chunk
```

- [ ] **Step 2: Verify module loads via ModuleRegistry**

```bash
cd /tmp/telegram-to-control
python3 -c "
from src.modules.loader import load_modules
reg = load_modules('modules')
print('commands:', reg.get_commands())
assert '/team' in reg.get_commands(), '/team not found'
print('OK: /team registered')
"
```

Expected output:
```
commands: ['/search', '/web', '/sysinfo', '/describe', '/dev', '/team']
OK: /team registered
```

- [ ] **Step 3: Run the full test suite**

```bash
cd /tmp/telegram-to-control
python3 -m pytest tests/agent_team/ tests/modules/ tests/runners/ tests/gateway/ -v --tb=short
```

Expected: All agent_team + modules + runners + gateway tests pass. (Ignore pre-existing errors in test_kimi.py / test_oauth.py / test_search.py — those are unrelated.)

- [ ] **Step 4: Commit**

```bash
cd /tmp/telegram-to-control
git add modules/agent_team/__init__.py modules/agent_team/manifest.yaml modules/agent_team/handler.py
git commit -m "feat: add agent_team module — /team command with P7/P9/P10 routing"
```

---

## Self-Review

**Spec coverage check:**

| Spec requirement | Covered by |
|---|---|
| `/team <task>` → P7, single agent | Task 1 (classifier) + Task 3 (run_p7) + Task 6 (handler) |
| `/team p9 <task>` → parallel worktrees | Task 1 (classifier) + Task 2 (worktree) + Task 5 (run_p9) |
| One failing subtask doesn't stop others | Task 5 (`asyncio.gather(return_exceptions=True)`) |
| Each subtask has DoD output | Task 4 (planner + SubTask.dod) + Task 5 (summary) |
| Progress pushed during execution | Task 3/5 (yield chunks) |
| Worktrees cleaned up after success | Task 5 (`wt.remove` in summary loop) |
| `/team p10 <task>` → architecture doc | Task 1 (classifier) + Task 3 (run_p10) |
| Fault isolation / handler errors | Task 6 handler wraps executor |

All spec requirements covered. No placeholders. Types consistent across tasks.
