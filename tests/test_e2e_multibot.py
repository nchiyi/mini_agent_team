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


def test_build_channel_tasks_skips_non_telegram_bot(monkeypatch):
    invoked: list[str] = []

    async def fake_run_for_bot(ctx, bot_cfg):
        invoked.append(bot_cfg.id)

    monkeypatch.setattr(main_module, "run_telegram_for_bot", fake_run_for_bot)
    ctx = _make_ctx(bots=[
        BotConfig(id="dev", channel="telegram", default_runner="claude"),
        BotConfig(id="future", channel="discord", default_runner="codex"),
    ])
    coros = main_module._build_channel_tasks(ctx)
    async def _await_all():
        await asyncio.gather(*coros)
    asyncio.run(_await_all())
    assert invoked == ["dev"]


def test_build_channel_tasks_includes_discord_when_token_set(monkeypatch):
    tg_invoked: list[str] = []
    dc_invoked: list[bool] = []

    async def fake_run_for_bot(ctx, bot_cfg):
        tg_invoked.append(bot_cfg.id)

    async def fake_run_discord(ctx):
        dc_invoked.append(True)

    monkeypatch.setattr(main_module, "run_telegram_for_bot", fake_run_for_bot)
    monkeypatch.setattr(main_module, "run_discord", fake_run_discord)
    ctx = _make_ctx(
        bots=[BotConfig(id="dev", channel="telegram", default_runner="claude")],
        discord_token="DC_TOKEN_123",
    )
    coros = main_module._build_channel_tasks(ctx)
    assert len(coros) == 2
    async def _await_all():
        await asyncio.gather(*coros)
    asyncio.run(_await_all())
    assert tg_invoked == ["dev"]
    assert dc_invoked == [True]


def test_build_channel_tasks_empty_when_no_bots_no_discord(monkeypatch):
    monkeypatch.setattr(main_module, "run_telegram_for_bot",
                        lambda ctx, bot_cfg: asyncio.sleep(0))
    monkeypatch.setattr(main_module, "run_discord",
                        lambda ctx: asyncio.sleep(0))
    ctx = _make_ctx(bots=[])
    coros = main_module._build_channel_tasks(ctx)
    assert coros == []
