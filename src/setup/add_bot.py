"""Standalone tool to add one bot to an existing mat install.

Usage::

    python3 -m src.setup.add_bot [--channel telegram|discord]

Reads existing config/config.toml + secrets/.env, prompts the user for a
new bot via bot_prompts.collect_bot, then appends:

- a new [bots.<id>] block to config.toml
- a new BOT_<ID>_TOKEN line to secrets/.env

Will refuse if the requested id already exists in either file.
"""
from __future__ import annotations

import argparse
import asyncio
import re
import sys
from pathlib import Path

from src.setup.bot_prompts import collect_bot
from src.setup.deploy import _render_bots_sections


class DuplicateBotIdError(Exception):
    pass


_BOT_ID_RE = re.compile(r"^\[bots\.([a-zA-Z][a-zA-Z0-9_]*)\]", re.MULTILINE)


def _existing_bot_ids(config_text: str) -> set[str]:
    return set(_BOT_ID_RE.findall(config_text))


async def add_bot_to_config(
    *, config_path: str, env_path: str, channel: str,
    default_runner: str = "claude",
) -> dict:
    cfg_path = Path(config_path)
    env_path_p = Path(env_path)
    config_text = cfg_path.read_text() if cfg_path.exists() else ""
    env_text = env_path_p.read_text() if env_path_p.exists() else ""

    existing = _existing_bot_ids(config_text)

    bot = await collect_bot(channel=channel, default_runner=default_runner)
    if bot["id"] in existing:
        raise DuplicateBotIdError(
            f"Bot id {bot['id']!r} already exists in {cfg_path}"
        )

    rendered_block = _render_bots_sections([
        {k: v for k, v in bot.items() if not k.startswith("_")}
    ])
    new_config = config_text.rstrip() + "\n\n" + rendered_block + "\n"
    cfg_path.parent.mkdir(parents=True, exist_ok=True)
    cfg_path.write_text(new_config)

    token_line = f'{bot["token_env"]}="{bot["_token_value"]}"\n'
    if env_text and not env_text.endswith("\n"):
        env_text += "\n"
    env_path_p.parent.mkdir(parents=True, exist_ok=True)
    env_path_p.write_text(env_text + token_line)
    env_path_p.chmod(0o600)

    return bot


async def _main() -> int:
    parser = argparse.ArgumentParser(prog="src.setup.add_bot")
    parser.add_argument("--channel", choices=["telegram", "discord"], required=False)
    parser.add_argument("--config", default="config/config.toml")
    parser.add_argument("--env", default="secrets/.env")
    parser.add_argument("--default-runner", default="claude")
    args = parser.parse_args()

    channel = args.channel
    if not channel:
        channel = input("Channel (telegram/discord): ").strip().lower()
        if channel not in ("telegram", "discord"):
            print(f"Unknown channel: {channel!r}", file=sys.stderr)
            return 2

    try:
        bot = await add_bot_to_config(
            config_path=args.config, env_path=args.env, channel=channel,
            default_runner=args.default_runner,
        )
    except DuplicateBotIdError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1

    print(f"\n✓ Added {channel} bot {bot['id']!r} to {args.config}")
    print(f"  Token saved to {args.env} as {bot['token_env']}")
    print("  Restart mat (or send SIGHUP if your deploy mode supports it) "
          "for the new bot to come online.")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(_main()))
