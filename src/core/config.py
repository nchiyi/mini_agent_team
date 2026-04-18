# src/core/config.py
import os, tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional
from dotenv import load_dotenv


@dataclass
class GatewayConfig:
    default_runner: str
    session_idle_minutes: int
    max_message_length_telegram: int
    max_message_length_discord: int
    stream_edit_interval_seconds: float


@dataclass
class RunnerConfig:
    path: str
    args: list[str]
    timeout_seconds: int
    context_token_budget: int


@dataclass
class AuditConfig:
    path: str
    max_entries: int


@dataclass
class MemoryConfig:
    db_path: str
    hot_path: str
    cold_permanent_path: str
    cold_session_path: str
    tier3_context_turns: int
    distill_trigger_turns: int


@dataclass
class Config:
    gateway: GatewayConfig
    runners: dict[str, RunnerConfig]
    audit: AuditConfig
    memory: MemoryConfig
    telegram_token: str = ""
    discord_token: str = ""
    allowed_user_ids: list[int] = field(default_factory=list)
    default_cwd: str = ""


def load_config(
    config_path: str = "config/config.toml",
    env_path: Optional[str] = "secrets/.env",
) -> Config:
    p = Path(config_path)
    if not p.exists():
        raise FileNotFoundError(f"Config not found: {config_path}")

    with open(p, "rb") as f:
        raw = tomllib.load(f)

    if env_path and Path(env_path).exists():
        load_dotenv(env_path)

    gw = raw["gateway"]
    gateway = GatewayConfig(
        default_runner=gw["default_runner"],
        session_idle_minutes=gw["session_idle_minutes"],
        max_message_length_telegram=gw["max_message_length_telegram"],
        max_message_length_discord=gw["max_message_length_discord"],
        stream_edit_interval_seconds=gw["stream_edit_interval_seconds"],
    )

    runners = {
        name: RunnerConfig(
            path=rc["path"],
            args=rc.get("args", []),
            timeout_seconds=rc.get("timeout_seconds", 300),
            context_token_budget=rc.get("context_token_budget", 4000),
        )
        for name, rc in raw.get("runners", {}).items()
    }

    audit_raw = raw["audit"]
    audit = AuditConfig(path=audit_raw["path"], max_entries=audit_raw["max_entries"])

    mem = raw["memory"]
    memory = MemoryConfig(
        db_path=mem["db_path"],
        hot_path=mem["hot_path"],
        cold_permanent_path=mem["cold_permanent_path"],
        cold_session_path=mem["cold_session_path"],
        tier3_context_turns=mem["tier3_context_turns"],
        distill_trigger_turns=mem["distill_trigger_turns"],
    )

    allowed_raw = os.environ.get("ALLOWED_USER_IDS", "")
    allowed = [int(x.strip()) for x in allowed_raw.split(",") if x.strip().isdigit()]

    return Config(
        gateway=gateway,
        runners=runners,
        audit=audit,
        memory=memory,
        telegram_token=os.environ.get("TELEGRAM_BOT_TOKEN", ""),
        discord_token=os.environ.get("DISCORD_BOT_TOKEN", ""),
        allowed_user_ids=allowed,
        default_cwd=os.environ.get("DEFAULT_CWD", str(Path.home())),
    )
