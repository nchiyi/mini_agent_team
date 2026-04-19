import json
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class WizardState:
    completed_steps: list[int] = field(default_factory=list)
    channel: str = ""
    telegram_token: str = ""
    discord_token: str = ""
    allowed_user_ids: list[int] = field(default_factory=list)
    selected_clis: list[str] = field(default_factory=list)
    search_mode: str = "fts5"
    update_notifications: bool = True
    deploy_mode: str = "foreground"


_FIELDS = set(WizardState.__dataclass_fields__)


def load_state(path: str) -> WizardState:
    p = Path(path)
    if not p.exists():
        return WizardState()
    with open(p) as f:
        data = json.load(f)
    return WizardState(**{k: v for k, v in data.items() if k in _FIELDS})


def save_state(state: WizardState, path: str) -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as f:
        json.dump({
            "completed_steps": state.completed_steps,
            "channel": state.channel,
            "telegram_token": state.telegram_token,
            "discord_token": state.discord_token,
            "allowed_user_ids": state.allowed_user_ids,
            "selected_clis": state.selected_clis,
            "search_mode": state.search_mode,
            "update_notifications": state.update_notifications,
            "deploy_mode": state.deploy_mode,
        }, f, indent=2)


def reset_state(path: str) -> None:
    Path(path).unlink(missing_ok=True)


def is_step_done(state: WizardState, step: int) -> bool:
    return step in state.completed_steps


def mark_step_done(state: WizardState, step: int) -> None:
    if step not in state.completed_steps:
        state.completed_steps.append(step)
