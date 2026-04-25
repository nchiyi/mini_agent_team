# src/core/config.py
import logging
import os
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional
from dotenv import load_dotenv

logger = logging.getLogger(__name__)

_DEFAULT_RUNNER_ARGS: dict[str, list[str]] = {
    "claude": [],
    "codex": [],
    "gemini": [],
    "kiro": [],
}

_DANGEROUS_SKIP_PERMISSIONS = "--dangerously-skip-permissions"
_DANGEROUS_RUNNER_ARGS: frozenset[str] = frozenset({
    "--dangerously-skip-permissions",
    "--full-auto",
    "--skip-git-repo-check",
    "yolo",       # --approval-mode yolo (codex style)
    "--yolo",     # gemini ACP style
})

_LEGACY_RUNNER_ARGS: dict[str, list[list[str]]] = {
    "codex": [
        ["--approval-policy", "auto"],
        ["exec", "--skip-git-repo-check"],
    ],
    "gemini": [[]],
}


@dataclass
class RateLimitConfig:
    enabled: bool = True
    per_user_per_minute: int = 10
    burst: int = 3
    max_concurrent_dispatches: int = 5


@dataclass
class GatewayConfig:
    default_runner: str
    session_idle_minutes: int
    max_message_length_telegram: int
    max_message_length_discord: int
    stream_edit_interval_seconds: float
    rate_limit: RateLimitConfig = field(default_factory=RateLimitConfig)


@dataclass
class RunnerConfig:
    path: str = ""
    args: list[str] = field(default_factory=list)
    timeout_seconds: int = 300
    context_token_budget: int = 4000
    type: str = "acp"   # "acp" | "cli"


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
class VoiceConfig:
    stt_provider: str = "groq"
    tts_provider: str = "edge-tts"
    tts_voice: str = "zh-TW-HsiaoChenNeural"


@dataclass
class DiscordConfig:
    allowed_channel_ids: list[int] = field(default_factory=list)
    allow_bot_messages: str = "off"
    allow_user_messages: str = "all"
    trusted_bot_ids: list[int] = field(default_factory=list)


@dataclass
class Config:
    gateway: GatewayConfig
    runners: dict[str, RunnerConfig]
    audit: AuditConfig
    memory: MemoryConfig
    voice: VoiceConfig = field(default_factory=VoiceConfig)
    discord: DiscordConfig = field(default_factory=DiscordConfig)
    telegram_token: str = ""
    discord_token: str = ""
    allowed_user_ids: list[int] = field(default_factory=list)
    allow_all_users: bool = False
    default_cwd: str = ""
    skills_dir: str = "skills"
    modules_dir: str = "skills"  # backward-compat alias


def _normalise_runner_args(name: str, raw_args: list[str] | None) -> list[str]:
    args = list(raw_args or [])
    default_args = _DEFAULT_RUNNER_ARGS.get(name)
    if default_args is None:
        return args
    if not raw_args:
        return list(default_args)
    if args in _LEGACY_RUNNER_ARGS.get(name, []):
        return list(default_args)
    return args


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
    rl_raw = gw.get("rate_limit", {})
    rate_limit_cfg = RateLimitConfig(
        enabled=rl_raw.get("enabled", True),
        per_user_per_minute=rl_raw.get("per_user_per_minute", 10),
        burst=rl_raw.get("burst", 3),
        max_concurrent_dispatches=rl_raw.get("max_concurrent_dispatches", 5),
    )
    gateway = GatewayConfig(
        default_runner=gw["default_runner"],
        session_idle_minutes=gw["session_idle_minutes"],
        max_message_length_telegram=gw["max_message_length_telegram"],
        max_message_length_discord=gw["max_message_length_discord"],
        stream_edit_interval_seconds=gw["stream_edit_interval_seconds"],
        rate_limit=rate_limit_cfg,
    )

    runners = {
        name: RunnerConfig(
            path=rc.get("path", ""),
            args=_normalise_runner_args(name, rc.get("args")),
            timeout_seconds=rc.get("timeout_seconds", 300),
            context_token_budget=rc.get("context_token_budget", 4000),
            type=rc.get("type", "acp"),
        )
        for name, rc in raw.get("runners", {}).items()
    }
    for name, rc in runners.items():
        dangerous = [a for a in rc.args if a in _DANGEROUS_RUNNER_ARGS]
        if dangerous:
            logger.warning(
                "Runner '%s' uses privileged args %s — "
                "chat-sourced prompts will have elevated permissions.",
                name, dangerous,
            )

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

    skills_dir = raw.get("skills", {}).get("dir", None) or raw.get("modules", {}).get("dir", "skills")

    voice_raw = raw.get("voice", {})
    voice = VoiceConfig(
        stt_provider=voice_raw.get("stt_provider", "groq"),
        tts_provider=voice_raw.get("tts_provider", "edge-tts"),
        tts_voice=voice_raw.get("tts_voice", "zh-TW-HsiaoChenNeural"),
    )

    disc_raw = raw.get("discord", {})
    discord_cfg = DiscordConfig(
        allowed_channel_ids=[int(x) for x in disc_raw.get("allowed_channel_ids", [])],
        allow_bot_messages=disc_raw.get("allow_bot_messages", "off"),
        allow_user_messages=disc_raw.get("allow_user_messages", "all"),
        trusted_bot_ids=[int(x) for x in disc_raw.get("trusted_bot_ids", [])],
    )

    allow_all_raw = raw.get("gateway", {}).get("allow_all_users", False)
    allow_all_users = bool(allow_all_raw) or os.environ.get("ALLOW_ALL_USERS", "").lower() == "true"
    if allow_all_users:
        logger.warning(
            "allow_all_users is enabled — bot accepts messages from ANY user. "
            "Set ALLOWED_USER_IDS or disable allow_all_users to restrict access."
        )

    return Config(
        gateway=gateway,
        runners=runners,
        audit=audit,
        memory=memory,
        voice=voice,
        discord=discord_cfg,
        telegram_token=os.environ.get("TELEGRAM_BOT_TOKEN", ""),
        discord_token=os.environ.get("DISCORD_BOT_TOKEN", ""),
        allowed_user_ids=allowed,
        allow_all_users=allow_all_users,
        default_cwd=os.environ.get("DEFAULT_CWD", str(Path.home())),
        skills_dir=skills_dir,
        modules_dir=skills_dir,
    )
