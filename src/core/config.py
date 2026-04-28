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
    daily_token_budget: int = 0    # 0 = no limit
    weekly_token_budget: int = 0   # 0 = no limit
    warn_threshold: float = 0.8    # warn when usage reaches this fraction
    hard_stop_at_limit: bool = False  # true=refuse dispatch; false=allow with warning


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
class AgentTeamConfig:
    max_depth: int = 2
    fallback_role: str = "fullstack-dev"


@dataclass
class DispatchConfig:
    max_pipeline_rounds: int = 4
    max_discussion_rounds: int = 3
    max_debate_voters: int = 5
    enforce_token_budget: bool = True


@dataclass
class VoiceConfig:
    stt_provider: str = "groq"
    tts_provider: str = "edge-tts"
    tts_voice: str = "zh-TW-HsiaoChenNeural"


@dataclass
class TelegramConfig:
    """Per-channel auth overrides for Telegram.

    Fields left as None fall back to the global allowed_user_ids / allow_all_users.
    """
    allowed_user_ids: list[int] | None = None   # None → use global
    allow_all_users: bool | None = None          # None → use global


@dataclass
class DiscordConfig:
    allowed_channel_ids: list[int] = field(default_factory=list)
    allow_bot_messages: str = "off"
    allow_user_messages: str = "all"
    trusted_bot_ids: list[int] = field(default_factory=list)
    allowed_user_ids: list[int] | None = None   # None → use global
    allow_all_users: bool | None = None          # None → use global


@dataclass
class Config:
    gateway: GatewayConfig
    runners: dict[str, RunnerConfig]
    audit: AuditConfig
    memory: MemoryConfig
    voice: VoiceConfig = field(default_factory=VoiceConfig)
    telegram: TelegramConfig = field(default_factory=TelegramConfig)
    discord: DiscordConfig = field(default_factory=DiscordConfig)
    agent_team: AgentTeamConfig = field(default_factory=AgentTeamConfig)
    dispatch: DispatchConfig = field(default_factory=DispatchConfig)
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
        daily_token_budget=rl_raw.get("daily_token_budget", 0),
        weekly_token_budget=rl_raw.get("weekly_token_budget", 0),
        warn_threshold=rl_raw.get("warn_threshold", 0.8),
        hard_stop_at_limit=rl_raw.get("hard_stop_at_limit", False),
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

    tg_raw = raw.get("telegram", {})
    tg_allowed_raw = tg_raw.get("allowed_user_ids")
    tg_allow_all_raw = tg_raw.get("allow_all_users")
    telegram_cfg = TelegramConfig(
        allowed_user_ids=[int(x) for x in tg_allowed_raw] if tg_allowed_raw is not None else None,
        allow_all_users=bool(tg_allow_all_raw) if tg_allow_all_raw is not None else None,
    )

    disc_raw = raw.get("discord", {})
    dc_allowed_raw = disc_raw.get("allowed_user_ids")
    dc_allow_all_raw = disc_raw.get("allow_all_users")
    discord_cfg = DiscordConfig(
        allowed_channel_ids=[int(x) for x in disc_raw.get("allowed_channel_ids", [])],
        allow_bot_messages=disc_raw.get("allow_bot_messages", "off"),
        allow_user_messages=disc_raw.get("allow_user_messages", "all"),
        trusted_bot_ids=[int(x) for x in disc_raw.get("trusted_bot_ids", [])],
        allowed_user_ids=[int(x) for x in dc_allowed_raw] if dc_allowed_raw is not None else None,
        allow_all_users=bool(dc_allow_all_raw) if dc_allow_all_raw is not None else None,
    )

    at_raw = raw.get("agent_team", {})
    agent_team = AgentTeamConfig(
        max_depth=at_raw.get("max_depth", 2),
        fallback_role=at_raw.get("fallback_role", "fullstack-dev"),
    )

    dp_raw = raw.get("dispatch", {})
    dispatch = DispatchConfig(
        max_pipeline_rounds=dp_raw.get("max_pipeline_rounds", 4),
        max_discussion_rounds=dp_raw.get("max_discussion_rounds", 3),
        max_debate_voters=dp_raw.get("max_debate_voters", 5),
        enforce_token_budget=dp_raw.get("enforce_token_budget", True),
    )

    allow_all_raw = raw.get("gateway", {}).get("allow_all_users", False)
    allow_all_users = bool(allow_all_raw) or os.environ.get("ALLOW_ALL_USERS", "").lower() == "true"
    if allow_all_users:
        logger.warning(
            "allow_all_users is enabled — bot accepts messages from ANY user. "
            "Set ALLOWED_USER_IDS or disable allow_all_users to restrict access."
        )

    cfg = Config(
        gateway=gateway,
        runners=runners,
        audit=audit,
        memory=memory,
        voice=voice,
        telegram=telegram_cfg,
        discord=discord_cfg,
        agent_team=agent_team,
        dispatch=dispatch,
        telegram_token=os.environ.get("TELEGRAM_BOT_TOKEN", ""),
        discord_token=os.environ.get("DISCORD_BOT_TOKEN", ""),
        allowed_user_ids=allowed,
        allow_all_users=allow_all_users,
        default_cwd=os.environ.get("DEFAULT_CWD", str(Path.home())),
        skills_dir=skills_dir,
        modules_dir=skills_dir,
    )

    # ── startup auth log ────────────────────────────────────────────────────
    _log_channel_auth(cfg, "telegram", cfg.telegram.allowed_user_ids, cfg.telegram.allow_all_users)
    _log_channel_auth(cfg, "discord", cfg.discord.allowed_user_ids, cfg.discord.allow_all_users)

    return cfg


def _resolve_channel_auth(
    cfg: "Config",
    channel_allowed: list[int] | None,
    channel_allow_all: bool | None,
) -> tuple[list[int], bool]:
    """Apply fallback chain: per-channel → global → deny.

    Returns (effective_allowed_user_ids, effective_allow_all_users).
    """
    if channel_allowed is not None or channel_allow_all is not None:
        # At least one per-channel field is explicitly set — use them,
        # defaulting the unset sibling to its safe default.
        return (
            channel_allowed if channel_allowed is not None else [],
            channel_allow_all if channel_allow_all is not None else False,
        )
    # Fall back to global settings.
    return cfg.allowed_user_ids, cfg.allow_all_users


def _log_channel_auth(
    cfg: "Config",
    channel: str,
    channel_allowed: list[int] | None,
    channel_allow_all: bool | None,
) -> None:
    effective_ids, effective_all = _resolve_channel_auth(cfg, channel_allowed, channel_allow_all)
    source = "channel-override" if (channel_allowed is not None or channel_allow_all is not None) else "global"
    if effective_all:
        logger.info("%s auth: open [source=%s]", channel, source)
    elif effective_ids:
        logger.info("%s auth: strict (%d users) [source=%s]", channel, len(effective_ids), source)
    else:
        logger.info("%s auth: deny-all [source=%s]", channel, source)
