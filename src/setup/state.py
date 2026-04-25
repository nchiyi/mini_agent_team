import json
from dataclasses import dataclass, field
from pathlib import Path

# ---------------------------------------------------------------------------
# Schema version
# ---------------------------------------------------------------------------
_SCHEMA_VERSION = 2

# ---------------------------------------------------------------------------
# v1 ↔ v2 step-ID mappings  (defined here so WizardState can reference them)
# ---------------------------------------------------------------------------
_V1_STEP_TO_MICRO: dict[int, str] = {
    1: "channel_select.done",
    2: "token_validation.done",
    3: "allowlist.done",
    4: "cli_select.done",
    5: "search_mode.done",
    6: "optional_packages.done",
    7: "update_notifications.done",
    8: "deploy_mode.done",
    9: "launch.done",
}
_MICRO_TO_V1_STEP: dict[str, int] = {v: k for k, v in _V1_STEP_TO_MICRO.items()}


class WizardState:
    """
    Setup wizard state — v2 schema.

    Primary storage uses micro-step IDs (strings) in `completed`.
    The legacy `completed_steps` (list[int]) is exposed as a dynamic
    property so that existing tests and callers continue to work unchanged.
    """

    # Declare slots for IDE / type-checker support
    __slots__ = (
        "version", "mode", "current_step", "completed", "failed",
        "channels", "telegram_token", "discord_token",
        "allowed_user_ids", "selected_clis", "search_mode",
        "update_notifications", "deploy_mode", "optional_packages", "data",
        "acp_mode", "installed_acp",
    )

    def __init__(
        self,
        version: int = _SCHEMA_VERSION,
        mode: str = "fresh",
        current_step: str = "",
        completed: list | None = None,
        failed: list | None = None,
        channels: list | None = None,
        telegram_token: str = "",
        discord_token: str = "",
        allowed_user_ids: list | None = None,
        selected_clis: list | None = None,
        search_mode: str = "fts5",
        update_notifications: bool = True,
        deploy_mode: str = "foreground",
        optional_packages: list | None = None,
        data: dict | None = None,
        acp_mode: str = "",
        installed_acp: list | None = None,
        # ── backward-compat: v1 integer step list ──────────────────────────
        completed_steps: list | None = None,
    ) -> None:
        self.version = version
        self.mode = mode
        self.current_step = current_step
        self.completed: list[str] = list(completed) if completed is not None else []
        self.failed: list[str] = list(failed) if failed is not None else []
        self.channels: list[str] = list(channels) if channels is not None else []
        self.telegram_token = telegram_token
        self.discord_token = discord_token
        self.allowed_user_ids: list[int] = list(allowed_user_ids) if allowed_user_ids is not None else []
        self.selected_clis: list[str] = list(selected_clis) if selected_clis is not None else []
        self.search_mode = search_mode
        self.update_notifications = update_notifications
        self.deploy_mode = deploy_mode
        self.optional_packages: list[str] = list(optional_packages) if optional_packages is not None else []
        self.data: dict = dict(data) if data is not None else {}
        self.acp_mode = acp_mode
        self.installed_acp: list[str] = list(installed_acp) if installed_acp is not None else []

        # Translate v1 integer steps into micro-step IDs on construction
        if completed_steps is not None:
            for step in completed_steps:
                micro = _V1_STEP_TO_MICRO.get(step)
                if micro and micro not in self.completed:
                    self.completed.append(micro)

    # ── backward-compat property ────────────────────────────────────────────
    @property
    def completed_steps(self) -> list[int]:
        """Dynamic view: returns v1 integer steps that map to completed micro-IDs."""
        result = []
        for micro in self.completed:
            step_num = _MICRO_TO_V1_STEP.get(micro)
            if step_num is not None:
                result.append(step_num)
        return sorted(result)

    def __repr__(self) -> str:  # for debugging
        return (
            f"WizardState(version={self.version!r}, mode={self.mode!r}, "
            f"current_step={self.current_step!r}, completed={self.completed!r})"
        )


# _FIELDS lists the kwargs accepted by WizardState.__init__ that are also
# persisted in / loaded from JSON.  completed_steps is included so v1 JSON
# files (which have that key) are handled transparently by load_state().
_FIELDS = {
    "version", "mode", "current_step", "completed", "failed",
    "channels", "telegram_token", "discord_token",
    "allowed_user_ids", "selected_clis", "search_mode",
    "update_notifications", "deploy_mode", "optional_packages", "data",
    "acp_mode", "installed_acp",
    "completed_steps",   # v1 key — WizardState.__init__ converts it
}

# ---------------------------------------------------------------------------
# v1 → v2 migration
# ---------------------------------------------------------------------------

def _migrate_v1_to_v2(data: dict) -> dict:
    """Upgrade a v1 state dict (completed_steps: list[int]) to v2 schema."""
    v1_steps: list[int] = data.get("completed_steps", [])
    completed: list[str] = []
    for step_num in sorted(v1_steps):
        micro = _V1_STEP_TO_MICRO.get(step_num)
        if micro:
            completed.append(micro)

    # Determine current_step: first step that is NOT done
    all_v1_steps_in_order = [1, 2, 3, 4, 5, 6, 7, 8, 9]
    current_step = ""
    for s in all_v1_steps_in_order:
        if s not in v1_steps:
            current_step = f"step{s}.pending"
            break

    # Determine mode
    if 8 in v1_steps or 9 in v1_steps:
        mode = "launch"
        current_step = "launch.done"
    elif v1_steps:
        mode = "resume"
    else:
        mode = "fresh"

    migrated = {
        "version": 2,
        "mode": mode,
        "current_step": current_step,
        "completed": completed,
        "failed": [],
        "data": {},
        # carry over configuration data
        "channels": data.get("channels", []),
        "telegram_token": data.get("telegram_token", ""),
        "discord_token": data.get("discord_token", ""),
        "allowed_user_ids": data.get("allowed_user_ids", []),
        "selected_clis": data.get("selected_clis", []),
        "search_mode": data.get("search_mode", "fts5"),
        "update_notifications": data.get("update_notifications", True),
        "deploy_mode": data.get("deploy_mode", "foreground"),
        "optional_packages": data.get("optional_packages", []),
    }
    return migrated


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def load_state(path: str) -> WizardState:
    p = Path(path)
    if not p.exists():
        return WizardState()
    try:
        with open(p) as f:
            data = json.load(f)

        # Version gate: migrate v1 → v2 transparently
        if data.get("version", 1) < 2:
            data = _migrate_v1_to_v2(data)

        return WizardState(**{k: v for k, v in data.items() if k in _FIELDS})
    except (json.JSONDecodeError, ValueError, OSError):
        return WizardState()


def save_state(state: WizardState, path: str) -> None:
    try:
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w") as f:
            json.dump({
                "version": state.version,
                "mode": state.mode,
                "current_step": state.current_step,
                "completed": state.completed,
                "failed": state.failed,
                "data": state.data,
                "channels": state.channels,
                "telegram_token": state.telegram_token,
                "discord_token": state.discord_token,
                "allowed_user_ids": state.allowed_user_ids,
                "selected_clis": state.selected_clis,
                "search_mode": state.search_mode,
                "update_notifications": state.update_notifications,
                "deploy_mode": state.deploy_mode,
                "optional_packages": state.optional_packages,
                "acp_mode": state.acp_mode,
                "installed_acp": state.installed_acp,
            }, f, indent=2)
    except OSError as e:
        raise RuntimeError(f"Cannot save wizard state to {path}: {e}") from e


def reset_state(path: str) -> None:
    Path(path).unlink(missing_ok=True)


# ---------------------------------------------------------------------------
# Micro-step helpers (v2 API)
# ---------------------------------------------------------------------------

def is_micro_step_done(state: WizardState, step_id: str) -> bool:
    """Return True if *step_id* (e.g. 'channel_select.done') is completed."""
    return step_id in state.completed


def mark_micro_step_done(state: WizardState, step_id: str) -> None:
    """Record *step_id* as completed (idempotent)."""
    if step_id not in state.completed:
        state.completed.append(step_id)


def set_current_step(state: WizardState, step_id: str) -> None:
    """Update the in-progress cursor."""
    state.current_step = step_id


# ---------------------------------------------------------------------------
# Legacy integer-step helpers  (kept so existing wizard step functions still
# compile and pass their original unit tests without modification)
# ---------------------------------------------------------------------------

# Mapping used by the shim: legacy int → micro-step ID written to completed[].
_LEGACY_INT_TO_MICRO: dict[int, str] = _V1_STEP_TO_MICRO


def is_step_done(state: WizardState, step: int) -> bool:
    """Backward-compat shim: check whether legacy integer step is done."""
    micro = _LEGACY_INT_TO_MICRO.get(step)
    if micro is None:
        return False
    return micro in state.completed


def mark_step_done(state: WizardState, step: int) -> None:
    """Backward-compat shim: mark legacy integer step as done."""
    micro = _LEGACY_INT_TO_MICRO.get(step)
    if micro and micro not in state.completed:
        state.completed.append(micro)
        # Keep current_step updated when advancing sequentially
        # (only move forward, never backwards)
        next_step = step + 1
        next_micro = _LEGACY_INT_TO_MICRO.get(next_step, f"step{next_step}.pending")
        if state.current_step == "" or state.current_step == f"step{step}.pending":
            state.current_step = next_micro


# ---------------------------------------------------------------------------
# Mode detection helper (used by wizard entry point)
# ---------------------------------------------------------------------------

def detect_mode(path: str, reset: bool = False) -> str:
    """
    Determine wizard mode WITHOUT loading full state.

    Returns one of: 'fresh', 'resume', 'reset', 'launch'
    """
    if reset:
        return "reset"
    p = Path(path)
    if not p.exists():
        return "fresh"
    try:
        with open(p) as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError):
        return "fresh"

    version = data.get("version", 1)
    if version >= 2:
        stored_mode = data.get("mode", "fresh")
        # If a previous run stored 'launch', honour it
        if stored_mode == "launch":
            return "launch"
        current_step = data.get("current_step", "")
        completed = data.get("completed", [])
        if completed or current_step:
            return "resume"
        return "fresh"

    # v1 path
    v1_steps = data.get("completed_steps", [])
    if 8 in v1_steps or 9 in v1_steps:
        return "launch"
    if v1_steps:
        return "resume"
    return "fresh"
