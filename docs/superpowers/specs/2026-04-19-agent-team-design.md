# AgentTeam (Phase 4) — Design Spec

**Date:** 2026-04-19
**Repo:** nchiyi/telegram-to-control
**Phase:** 4 of Gateway Agent Platform

---

## Goal

Add `/team` command that lets users delegate tasks to a coordinated team of CLI agents (claude, codex, gemini). P7 single-agent tasks run directly; P9 multi-agent tasks run in parallel git worktrees; P10 produces architecture documents without implementation.

---

## Architecture

AgentTeam is implemented as a module (`modules/agent_team/`) that delegates to a core library (`src/agent_team/`). The module handler is a thin wrapper; all logic lives in the core library.

```
modules/agent_team/
  manifest.yaml           ← commands: [/team], timeout: 600s
  handler.py              ← thin wrapper calling src/agent_team

src/agent_team/
  __init__.py
  models.py               ← TeamTask, SubTask, TaskMode dataclasses
  classifier.py           ← parse /team prefix → TaskMode (P7/P9/P10)
  planner.py              ← P9: split task into subtasks with DoD
  executor.py             ← run subtasks via CLIRunner, stream progress
  worktree.py             ← git worktree lifecycle (create/cleanup)

tests/agent_team/
  test_classifier.py
  test_worktree.py
  test_executor.py
```

---

## Routing: P7 / P9 / P10

Routing is explicit via prefix. No LLM classification — predictable and instant.

| Input | Mode | Behaviour |
|-------|------|-----------|
| `/team <task>` | P7 | Single agent (claude), no worktree |
| `/team p9 <task>` | P9 | Parallel agents in isolated worktrees |
| `/team p10 <task>` | P10 | Output architecture/strategy doc only |

Parsing is done in `classifier.py`:

```python
def classify(args: str) -> tuple[TaskMode, str]:
    """Return (mode, task_text) from raw args string."""
    lower = args.strip().lower()
    if lower.startswith("p9 "):
        return TaskMode.P9, args[3:].strip()
    if lower.startswith("p10 "):
        return TaskMode.P10, args[4:].strip()
    return TaskMode.P7, args.strip()
```

---

## Data Models

```python
from dataclasses import dataclass, field
from enum import Enum

class TaskMode(Enum):
    P7 = "p7"
    P9 = "p9"
    P10 = "p10"

@dataclass
class SubTask:
    id: str           # e.g. "task-abc123-0"
    agent: str        # "claude" | "codex" | "gemini"
    prompt: str
    dod: str          # Definition of Done
    worktree_path: str = ""
    status: str = "pending"   # pending | running | done | failed
    result: str = ""

@dataclass
class TeamTask:
    id: str
    mode: TaskMode
    description: str
    subtasks: list[SubTask] = field(default_factory=list)
```

---

## P7 Flow

1. Parse `/team <task>` → P7 mode
2. Yield `[P7] Running with claude...`
3. Call `CLIRunner("claude").run(task, user_id, channel, cwd)`, stream chunks
4. Yield final status

No worktree needed. Uses session's current `cwd`.

---

## P9 Flow

1. Parse `/team p9 <task>` → P9 mode
2. **Plan**: Use `planner.py` to call `CLIRunner("claude")` with a planning prompt that returns a JSON list of subtasks:
   ```
   You are a task planner. Break the following task into 2-4 independent subtasks.
   Each subtask must specify: agent (claude/codex/gemini), prompt, and definition_of_done.
   Output ONLY valid JSON: [{"agent": "...", "prompt": "...", "dod": "..."}]
   Task: <task_description>
   ```
3. Yield `[P9] Plan:\n  - [codex] <subtask 0>\n  - [gemini] <subtask 1>\nExecuting...`
4. **Execute in parallel**:
   - For each subtask: create git worktree at `data/worktrees/<task-id>-<i>/`
   - Run `CLIRunner(agent).run(prompt, ...)` concurrently via `asyncio.gather(..., return_exceptions=True)`
   - Stream per-subtask progress as `[subtask-N] <chunk>`
5. **After all complete**:
   - Report per-subtask results (done/failed)
   - If all succeeded: yield merge instructions to user (claude suggests merge command)
   - If any failed: report failures; successful worktrees preserved for inspection
6. **Cleanup**: remove worktrees of successful subtasks

The executor does NOT auto-merge — it reports results and lets the user decide.

---

## P10 Flow

1. Parse `/team p10 <task>` → P10 mode
2. Yield `[P10] Generating architecture document...`
3. Call `CLIRunner("claude").run(p10_prompt, ...)` with a prompt that wraps the task:
   ```
   You are a software architect. Produce a strategy document for the following.
   Do NOT write implementation code. Output: goals, trade-offs, recommended approach, risks.
   Task: <task_description>
   ```
4. Stream output directly — no worktrees needed

---

## Git Worktree Lifecycle

`worktree.py` wraps `git worktree add/remove`:

```python
async def create(base_repo: str, path: str, branch: str) -> None:
    """git worktree add <path> -b <branch>"""

async def remove(path: str) -> None:
    """git worktree remove --force <path>"""

def worktree_path(data_dir: str, task_id: str, index: int) -> str:
    return f"{data_dir}/worktrees/{task_id}-{index}"
```

- `base_repo`: the session's current `cwd` (must be a git repo)
- If `cwd` is not a git repo → yield error, skip worktree creation, fall back to temp dirs
- Branch name: `team/<task-id>-<index>`
- Cleanup runs in `finally` block of executor so it runs even on exception

---

## Progress Streaming

All progress yielded as string chunks from `handler.py`. Format:

- `[P7] Running with claude...`
- `[P9] Subtask 0 (codex): <line>`
- `[P9] Subtask 1 (gemini): <line>`
- `[P9] ✓ Subtask 0 done | ✗ Subtask 1 failed: <error>`
- `[P10] <architecture doc lines>`

Prefix `[P7]`/`[P9]`/`[P10]` on first chunk only; subsequent chunks are raw output.

---

## Fault Isolation

- `asyncio.gather(*tasks, return_exceptions=True)` — one failing subtask never stops others
- Each subtask's exception is caught, stored in `SubTask.status = "failed"`, reported at end
- Failed worktrees are NOT cleaned up (preserved for inspection)
- Handler-level `try/except` wraps the entire team execution — unexpected errors yield error message, never crash Gateway

---

## Configuration

No new top-level config section. Reads from environment at runtime (following `dev_agent` pattern):

```
TEAM_DEFAULT_AGENT=claude        # agent for P7 and P10 (default: claude)
TEAM_PLANNER_AGENT=claude        # agent for P9 planning step (default: claude)
TEAM_DATA_DIR=data               # root for worktrees/ (default: data)
TEAM_TIMEOUT=600                 # seconds per subtask (default: 600)
```

---

## Tests

**test_classifier.py** — pure unit tests, no subprocess:
- `classify("")` → P7, empty string
- `classify("build X")` → P7, "build X"
- `classify("p9 build X")` → P9, "build X"
- `classify("p10 design Y")` → P10, "design Y"
- Case insensitive: `classify("P9 build X")` → P9

**test_worktree.py** — requires a real git repo (tmpdir fixture):
- `create()` creates worktree directory and branch
- `remove()` removes worktree
- Idempotent: `remove()` on nonexistent path does not raise

**test_executor.py** — mock CLIRunner:
- P7: streams runner output with `[P7]` prefix on first chunk
- P9: two subtasks both succeed → both results reported, returns exceptions=[] 
- P9: one subtask fails → other still completes, failure reported in output
- P10: streams runner output with `[P10]` prefix

---

## Acceptance Criteria (from spec §8.4)

- [ ] `/team <task>` → P7, runs via single agent, streams output
- [ ] `/team p9 <task>` → creates worktrees, runs parallel agents
- [ ] One subtask failing → other subtask continues, failure reported
- [ ] Each subtask has DoD output reported
- [ ] Progress pushed to channel during execution
- [ ] Worktrees cleaned up after successful task
- [ ] `/team p10 <task>` → outputs strategy document, no code

---

## Out of Scope (Phase 4)

- Auto-merge of P9 results (user merges manually based on report)
- LLM-based automatic P7/P9/P10 classification (explicit prefix only)
- MCP tool integration within team tasks
- Cross-session task tracking
