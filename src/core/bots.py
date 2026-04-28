import os
import logging
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class BotConfig:
    id: str
    channel: str = "telegram"
    token_env: str = "TELEGRAM_BOT_TOKEN"
    default_runner: str = ""
    default_role: str = ""
    allowed_user_ids: list[int] | None = None
    allow_all_users: bool | None = None
    label: str = ""

    @property
    def token(self) -> str:
        return os.environ.get(self.token_env, "")


def load_bots(raw_toml: dict[str, Any], default_runner: str) -> list[BotConfig]:
    """Parse [bots.X] sections from config.toml; fall back to legacy single-token env."""
    bots_section = raw_toml.get("bots") if isinstance(raw_toml, dict) else None
    if isinstance(bots_section, dict) and bots_section:
        out: list[BotConfig] = []
        for bid, raw in bots_section.items():
            if not isinstance(raw, dict):
                continue
            cfg = BotConfig(
                id=str(bid),
                channel=raw.get("channel", "telegram"),
                token_env=raw.get("token_env", f"BOT_{bid.upper()}_TOKEN"),
                default_runner=raw.get("default_runner") or default_runner,
                default_role=raw.get("default_role", ""),
                allowed_user_ids=raw.get("allowed_user_ids"),
                allow_all_users=raw.get("allow_all_users"),
                label=raw.get("label", ""),
            )
            if not cfg.token:
                logger.warning(
                    "Bot %r dropped: env var %s is not set", bid, cfg.token_env
                )
                continue
            out.append(cfg)
        return out

    # Legacy fallback
    if os.environ.get("TELEGRAM_BOT_TOKEN"):
        return [BotConfig(
            id="default",
            channel="telegram",
            token_env="TELEGRAM_BOT_TOKEN",
            default_runner=default_runner,
        )]
    return []
