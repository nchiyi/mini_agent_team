"""Multi-bot scheduling tests for the main() launcher.

Exercises ``_build_channel_tasks`` directly so we don't need a live
Telegram Application — covers the wiring B-1 added to ``main()`` without
the integration cost of e2e fixtures.
"""
import asyncio
from types import SimpleNamespace

import pytest

import main as main_module
from src.core.bots import BotConfig


def _make_ctx(*, bots, discord_token=""):
    cfg = SimpleNamespace(bots=bots, discord_token=discord_token)
    return SimpleNamespace(cfg=cfg)


def test_build_channel_tasks_one_per_telegram_bot(monkeypatch):
    invoked: list[str] = []

    async def fake_run_for_bot(ctx, bot_cfg):
        invoked.append(bot_cfg.id)

    monkeypatch.setattr(main_module, "run_telegram_for_bot", fake_run_for_bot)
    ctx = _make_ctx(bots=[
        BotConfig(id="dev", channel="telegram", default_runner="claude"),
        BotConfig(id="search", channel="telegram", default_runner="gemini"),
    ])
    coros = main_module._build_channel_tasks(ctx)
    assert len(coros) == 2

    async def _await_all():
        await asyncio.gather(*coros)
    asyncio.run(_await_all())
    assert sorted(invoked) == ["dev", "search"]


def test_build_channel_tasks_skips_unknown_channel_bot(monkeypatch):
    invoked: list[str] = []

    async def fake_run_for_bot(ctx, bot_cfg):
        invoked.append(bot_cfg.id)

    monkeypatch.setattr(main_module, "run_telegram_for_bot", fake_run_for_bot)
    ctx = _make_ctx(bots=[
        BotConfig(id="dev", channel="telegram", default_runner="claude"),
        BotConfig(id="future", channel="slack", default_runner="codex"),
    ])
    coros = main_module._build_channel_tasks(ctx)
    async def _await_all():
        await asyncio.gather(*coros)
    asyncio.run(_await_all())
    assert invoked == ["dev"]


def test_build_channel_tasks_includes_discord_when_bot_configured(monkeypatch):
    tg_invoked: list[str] = []
    dc_invoked: list[str] = []

    async def fake_run_telegram_for_bot(ctx, bot_cfg):
        tg_invoked.append(bot_cfg.id)

    async def fake_run_discord_for_bot(ctx, bot_cfg):
        dc_invoked.append(bot_cfg.id)

    monkeypatch.setattr(main_module, "run_telegram_for_bot", fake_run_telegram_for_bot)
    monkeypatch.setattr(main_module, "run_discord_for_bot", fake_run_discord_for_bot)
    ctx = _make_ctx(
        bots=[
            BotConfig(id="dev", channel="telegram", default_runner="claude"),
            BotConfig(id="dc1", channel="discord", default_runner="claude"),
        ],
    )
    coros = main_module._build_channel_tasks(ctx)
    assert len(coros) == 2
    async def _await_all():
        await asyncio.gather(*coros)
    asyncio.run(_await_all())
    assert tg_invoked == ["dev"]
    assert dc_invoked == ["dc1"]


def test_build_channel_tasks_empty_when_no_bots_no_discord(monkeypatch):
    monkeypatch.setattr(main_module, "run_telegram_for_bot",
                        lambda ctx, bot_cfg: asyncio.sleep(0))
    ctx = _make_ctx(bots=[])
    coros = main_module._build_channel_tasks(ctx)
    assert coros == []


def test_build_channel_tasks_one_per_discord_bot(monkeypatch):
    """Discord bots in cfg.bots each get their own coroutine."""
    from unittest.mock import MagicMock

    monkeypatch.setenv("BOT_A_TOKEN", "x")
    monkeypatch.setenv("BOT_B_TOKEN", "y")
    ctx = MagicMock()
    ctx.cfg.bots = [
        BotConfig(id="a", channel="discord", token_env="BOT_A_TOKEN"),
        BotConfig(id="b", channel="discord", token_env="BOT_B_TOKEN"),
    ]
    ctx.cfg.discord_token = ""  # no legacy single-bot path
    coros = main_module._build_channel_tasks(ctx)
    assert len(coros) == 2
    for c in coros:
        c.close()  # cleanup unawaited coroutines


def test_build_channel_tasks_mixed_telegram_and_discord(monkeypatch):
    from unittest.mock import MagicMock

    monkeypatch.setenv("T1", "x")
    monkeypatch.setenv("T2", "y")
    monkeypatch.setenv("D1", "x")
    monkeypatch.setenv("D2", "y")
    ctx = MagicMock()
    ctx.cfg.bots = [
        BotConfig(id="t1", channel="telegram", token_env="T1"),
        BotConfig(id="t2", channel="telegram", token_env="T2"),
        BotConfig(id="d1", channel="discord", token_env="D1"),
        BotConfig(id="d2", channel="discord", token_env="D2"),
    ]
    ctx.cfg.discord_token = ""
    coros = main_module._build_channel_tasks(ctx)
    assert len(coros) == 4
    for c in coros:
        c.close()
