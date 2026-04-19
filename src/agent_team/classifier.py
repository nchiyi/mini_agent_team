# src/agent_team/classifier.py
from src.agent_team.models import TaskMode


def classify(args: str) -> tuple[TaskMode, str]:
    lower = args.strip().lower()
    if lower.startswith("p9 "):
        return TaskMode.P9, args[3:].strip()
    if lower.startswith("p10 "):
        return TaskMode.P10, args[4:].strip()
    if lower.startswith("p7 "):
        return TaskMode.P7, args[3:].strip()
    return TaskMode.P7, args.strip()
