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
    agent: str  # This is the runner/binary name (e.g., claude, gemini)
    prompt: str
    role: str = ""  # The role slug from roster/
    dod: str = ""
    worktree_path: str = ""
    status: str = "pending"
    result: str = ""


@dataclass
class SubTaskResult:
    subtask_id: str
    status: str          # "done" | "failed" | "timeout"
    returncode: int
    stdout_snippet: str  # last 500 chars of output
    changed_files: list[str] = field(default_factory=list)
    worktree_path: str = ""
    dod_verdict: str = ""  # "met" | "unmet" | "unknown"


@dataclass
class TeamTask:
    id: str
    mode: TaskMode
    description: str
    subtasks: list[SubTask] = field(default_factory=list)
