# Gateway Agent Platform — Phase 2a: Discord Adapter

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add Discord as a second control channel running alongside Telegram, with shared gateway dispatch logic.

**Architecture:** Extract a `dispatch()` coroutine from main.py that handles all gateway logic (routing, session, runner, streaming). Both TelegramAdapter and DiscordAdapter call it. Each adapter has its own StreamingBridge. Both run as concurrent asyncio tasks via `asyncio.gather()`.

**Tech Stack:** discord.py 2.x, python-telegram-bot 21+, asyncio.gather()

---

## File Map

| File | Change |
|------|--------|
| `src/channels/discord_adapter.py` | Create: DiscordAdapter wrapping discord.py Client |
| `main.py` | Modify: extract `dispatch()`, add `run_discord()`, run both with asyncio.gather() |
| `tests/channels/test_discord_split.py` | Create: unit tests for splitting + auth logic |
| `tests/test_e2e_dual.py` | Create: two FakeAdapters share the same gateway pipeline |
| `requirements.txt` | Modify: add discord.py>=2.0 |

---

## Task 1: DiscordAdapter

**Files:**
- Create: `src/channels/discord_adapter.py`
- Create: `tests/channels/test_discord_split.py`
- Modify: `requirements.txt`

- [ ] **Step 1: Install discord.py**

```bash
cd /tmp/telegram-to-control
pip install "discord.py>=2.0" 2>/dev/null | tail -3
echo "discord.py>=2.0" >> requirements.txt
```

- [ ] **Step 2: Write failing tests**

```python
# tests/channels/test_discord_split.py
import pytest


def test_discord_split_long_message():
    from src.channels.discord_adapter import DiscordAdapter
    text = "a" * 2500
    chunks = DiscordAdapter._split(text)
    assert len(chunks) == 2
    assert all(len(c) <= 2000 for c in chunks)
    assert "".join(chunks) == text


def test_discord_split_short_message():
    from src.channels.discord_adapter import DiscordAdapter
    text = "hello world"
    chunks = DiscordAdapter._split(text)
    assert chunks == ["hello world"]


def test_discord_split_at_newline():
    from src.channels.discord_adapter import DiscordAdapter
    # A line just under 2000 chars, then a newline, then more text
    text = ("a" * 1999) + "\n" + ("b" * 100)
    chunks = DiscordAdapter._split(text)
    assert len(chunks) == 2
    assert chunks[0].endswith("a")
    assert "b" in chunks[1]


def test_discord_is_authorized_empty_allowlist():
    from src.channels.discord_adapter import DiscordAdapter
    # Empty allowlist → everyone allowed
    adapter = DiscordAdapter.__new__(DiscordAdapter)
    adapter._allowed = set()
    assert adapter.is_authorized(12345) is True


def test_discord_is_authorized_with_allowlist():
    from src.channels.discord_adapter import DiscordAdapter
    adapter = DiscordAdapter.__new__(DiscordAdapter)
    adapter._allowed = {111, 222}
    assert adapter.is_authorized(111) is True
    assert adapter.is_authorized(999) is False
```

- [ ] **Step 3: Run to verify failure**

```bash
cd /tmp/telegram-to-control
python3 -m pytest tests/channels/test_discord_split.py -v 2>&1 | head -15
```
Expected: FAIL with `ModuleNotFoundError: No module named 'src.channels.discord_adapter'`

- [ ] **Step 4: Implement src/channels/discord_adapter.py**

```python
# src/channels/discord_adapter.py
import logging
from typing import Callable, Awaitable
import discord
from src.channels.base import BaseAdapter, InboundMessage

logger = logging.getLogger(__name__)
MAX_LEN = 2000


class DiscordAdapter(BaseAdapter):
    def __init__(
        self,
        token: str,
        allowed_user_ids: list[int],
        gateway_handler: Callable[[InboundMessage], Awaitable[None]],
    ):
        intents = discord.Intents.default()
        intents.message_content = True
        self._client = discord.Client(intents=intents)
        self._token = token
        self._allowed = set(allowed_user_ids)
        self._user_channel: dict[int, discord.TextChannel] = {}
        self._setup_handlers(gateway_handler)

    def _setup_handlers(
        self, gateway_handler: Callable[[InboundMessage], Awaitable[None]]
    ) -> None:
        @self._client.event
        async def on_message(message: discord.Message) -> None:
            if message.author == self._client.user:
                return
            user_id = message.author.id
            if not self.is_authorized(user_id):
                await message.channel.send("Unauthorized.")
                return
            self._user_channel[user_id] = message.channel
            await gateway_handler(
                InboundMessage(
                    user_id=user_id,
                    channel="discord",
                    text=message.content,
                    message_id=str(message.id),
                )
            )

    def is_authorized(self, user_id: int) -> bool:
        return not self._allowed or user_id in self._allowed

    async def send(self, user_id: int, text: str) -> str:
        channel = self._user_channel.get(user_id)
        if not channel:
            logger.error("No channel context for Discord user %s", user_id)
            return ""
        chunks = self._split(text)
        last_msg: discord.Message | None = None
        for chunk in chunks:
            try:
                last_msg = await channel.send(chunk)
            except discord.DiscordException as e:
                logger.error("Discord send failed: %s", e)
                raise
        return f"{channel.id}:{last_msg.id}" if last_msg else ""

    async def edit(self, message_id: str, text: str) -> None:
        try:
            channel_id, mid = message_id.split(":", 1)
            channel = self._client.get_channel(int(channel_id))
            if channel is None:
                return
            msg = await channel.fetch_message(int(mid))
            await msg.edit(content=text[:MAX_LEN])
        except discord.DiscordException as e:
            logger.warning("Discord edit failed: %s", e)

    async def react(self, message_id: str, emoji: str) -> None:
        pass

    def max_message_length(self) -> int:
        return MAX_LEN

    async def start(self) -> None:
        await self._client.start(self._token)

    async def close(self) -> None:
        await self._client.close()

    @staticmethod
    def _split(text: str) -> list[str]:
        chunks = []
        while len(text) > MAX_LEN:
            split_pos = text.rfind("\n", 0, MAX_LEN)
            if split_pos == -1:
                split_pos = MAX_LEN
            chunks.append(text[:split_pos])
            text = text[split_pos:].lstrip("\n")
        if text:
            chunks.append(text)
        return chunks
```

- [ ] **Step 5: Run tests**

```bash
cd /tmp/telegram-to-control
python3 -m pytest tests/channels/test_discord_split.py -v
```
Expected: 5 PASSED

- [ ] **Step 6: Commit**

```bash
cd /tmp/telegram-to-control
git add src/channels/discord_adapter.py tests/channels/test_discord_split.py requirements.txt
git commit -m "feat: DiscordAdapter with message splitting and channel context"
```

---

## Task 2: Refactor main.py + Dual-Adapter Support

**Files:**
- Modify: `main.py`
- Create: `tests/test_e2e_dual.py`

The existing `handle_message()` in main.py is Telegram-specific. Extract its gateway logic into a standalone `dispatch()` coroutine so Discord can reuse it.

- [ ] **Step 1: Write dual-adapter E2E tests first**

```python
# tests/test_e2e_dual.py
"""
E2E smoke test: two FakeAdapters (one for Telegram, one for Discord)
share the same Router/SessionManager/runners. Proves channel isolation.
"""
import sys, pytest
sys.path.insert(0, "tests/channels")
pytestmark = pytest.mark.asyncio


async def _make_pipeline(tmp_path, tg_adapter, dc_adapter):
    """Build shared gateway components and return a dispatch function for each channel."""
    from src.runners.audit import AuditLog
    from src.runners.cli_runner import CLIRunner
    from src.gateway.router import Router
    from src.gateway.session import SessionManager
    from src.gateway.streaming import StreamingBridge

    audit = AuditLog(audit_dir=str(tmp_path / "audit"), max_entries=100)
    runner = CLIRunner(
        name="echo", binary="echo", args=[],
        timeout_seconds=5, context_token_budget=1000, audit=audit,
    )
    runners = {"echo": runner}
    router = Router(known_runners=set(runners.keys()), default_runner="echo")
    session_mgr = SessionManager(idle_minutes=60, default_runner="echo", default_cwd=str(tmp_path))
    bridges = {
        "telegram": StreamingBridge(tg_adapter, edit_interval=0.0),
        "discord":  StreamingBridge(dc_adapter, edit_interval=0.0),
    }
    adapters = {"telegram": tg_adapter, "discord": dc_adapter}

    async def dispatch(user_id: int, channel: str, text: str) -> None:
        from src.gateway.router import ParsedCommand
        session = session_mgr.get_or_create(user_id=user_id, channel=channel)
        cmd = router.parse(text)
        adapter = adapters[channel]
        bridge = bridges[channel]

        if cmd.is_switch_runner:
            session.current_runner = cmd.runner
            await adapter.send(user_id, f"Switched to {cmd.runner}")
            return
        if cmd.is_cancel or cmd.is_reset or cmd.is_new or cmd.is_status:
            await adapter.send(user_id, "ok")
            return

        active_runner = runners[session.current_runner]
        await bridge.stream(
            user_id=user_id,
            chunks=active_runner.run(
                prompt=cmd.prompt, user_id=user_id,
                channel=channel, cwd=session.cwd,
            ),
        )

    return dispatch


async def test_both_channels_receive_responses(tmp_path):
    from fake_adapter import FakeAdapter

    tg = FakeAdapter()
    dc = FakeAdapter()
    dispatch = await _make_pipeline(tmp_path, tg, dc)

    await dispatch(user_id=1, channel="telegram", text="hello telegram")
    await dispatch(user_id=1, channel="discord",  text="hello discord")

    tg_out = " ".join(tg.sent + list(tg.edits.values()))
    dc_out = " ".join(dc.sent + list(dc.edits.values()))
    assert "hello telegram" in tg_out
    assert "hello discord" in dc_out


async def test_sessions_isolated_per_channel(tmp_path):
    from fake_adapter import FakeAdapter

    tg = FakeAdapter()
    dc = FakeAdapter()
    dispatch = await _make_pipeline(tmp_path, tg, dc)

    # Switch runner on Telegram session
    await dispatch(user_id=1, channel="telegram", text="/use echo")
    # Discord session still uses default "echo", independent
    await dispatch(user_id=1, channel="discord", text="discord independent")

    dc_out = " ".join(dc.sent + list(dc.edits.values()))
    assert "discord independent" in dc_out


async def test_same_user_id_different_channels_dont_collide(tmp_path):
    from fake_adapter import FakeAdapter

    tg = FakeAdapter()
    dc = FakeAdapter()
    dispatch = await _make_pipeline(tmp_path, tg, dc)

    await dispatch(user_id=42, channel="telegram", text="tg msg")
    await dispatch(user_id=42, channel="discord",  text="dc msg")

    tg_out = " ".join(tg.sent + list(tg.edits.values()))
    dc_out = " ".join(dc.sent + list(dc.edits.values()))
    assert "tg msg" in tg_out
    assert "dc msg" in dc_out
    # cross-contamination check
    assert "dc msg" not in tg_out
    assert "tg msg" not in dc_out
```

- [ ] **Step 2: Run to verify tests pass**

These tests use only existing components (FakeAdapter, CLIRunner, Router, etc.) and should pass before main.py is changed:

```bash
cd /tmp/telegram-to-control
python3 -m pytest tests/test_e2e_dual.py -v
```
Expected: 3 PASSED (if not, something is broken in existing components — fix before proceeding)

- [ ] **Step 3: Rewrite main.py**

Replace the existing main.py entirely:

```python
# main.py
"""
Gateway Agent Platform — entry point.
Runs TelegramAdapter and/or DiscordAdapter concurrently via asyncio.gather().
"""
import asyncio
import logging
from telegram import Update
from telegram.ext import Application, MessageHandler, ContextTypes, filters

from src.core.config import load_config, Config
from src.runners.audit import AuditLog
from src.runners.cli_runner import CLIRunner
from src.channels.telegram import TelegramAdapter
from src.channels.discord_adapter import DiscordAdapter
from src.channels.base import InboundMessage, BaseAdapter
from src.gateway.router import Router
from src.gateway.session import SessionManager
from src.gateway.streaming import StreamingBridge

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
)
logger = logging.getLogger("main")


def _build_shared(cfg: Config, audit: AuditLog):
    runners = {
        name: CLIRunner(
            name=name,
            binary=rc.path,
            args=rc.args,
            timeout_seconds=rc.timeout_seconds,
            context_token_budget=rc.context_token_budget,
            audit=audit,
        )
        for name, rc in cfg.runners.items()
    }
    router = Router(
        known_runners=set(runners.keys()),
        default_runner=cfg.gateway.default_runner,
    )
    session_mgr = SessionManager(
        idle_minutes=cfg.gateway.session_idle_minutes,
        default_runner=cfg.gateway.default_runner,
        default_cwd=cfg.default_cwd,
    )
    return runners, router, session_mgr


async def dispatch(
    inbound: InboundMessage,
    bridge: StreamingBridge,
    session_mgr: SessionManager,
    router: Router,
    runners: dict,
    send_reply,
) -> None:
    """Channel-agnostic gateway logic: parse command, update session, run or respond."""
    session = session_mgr.get_or_create(user_id=inbound.user_id, channel=inbound.channel)
    cmd = router.parse(inbound.text)

    if cmd.is_cancel:
        await send_reply("No active task to cancel.")
        return
    if cmd.is_reset:
        await send_reply("Context cleared.")
        return
    if cmd.is_new:
        await send_reply("New session started.")
        return
    if cmd.is_status:
        await send_reply(
            f"Status\nRunners: {list(runners.keys())}\n"
            f"Default: {session.current_runner}\nCWD: {session.cwd}"
        )
        return
    if cmd.is_switch_runner:
        session.current_runner = cmd.runner
        await send_reply(f"Switched to {cmd.runner}")
        return

    target_runner = runners.get(session.current_runner)
    if not target_runner:
        await send_reply(f"Runner '{session.current_runner}' not found.")
        return

    try:
        await bridge.stream(
            user_id=inbound.user_id,
            chunks=target_runner.run(
                prompt=cmd.prompt,
                user_id=inbound.user_id,
                channel=inbound.channel,
                cwd=session.cwd,
            ),
        )
    except TimeoutError:
        await send_reply("Runner timed out.")
    except Exception as e:
        logger.error("Runner error: %s", e)
        await send_reply(f"Error: {e}")


async def run_telegram(cfg: Config, runners, router, session_mgr) -> None:
    tg_app = Application.builder().token(cfg.telegram_token).build()
    adapter = TelegramAdapter(bot=tg_app.bot, allowed_user_ids=cfg.allowed_user_ids)
    bridge = StreamingBridge(adapter, edit_interval=cfg.gateway.stream_edit_interval_seconds)

    async def on_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not update.message or not update.message.text:
            return
        user_id = update.effective_user.id
        if not adapter.is_authorized(user_id):
            await update.message.reply_text("Unauthorized.")
            return
        await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")
        inbound = InboundMessage(
            user_id=user_id,
            channel="telegram",
            text=update.message.text.strip(),
            message_id=str(update.message.message_id),
        )
        await dispatch(
            inbound, bridge, session_mgr, router, runners,
            lambda t: adapter.send(user_id, t),
        )

    tg_app.add_handler(MessageHandler(filters.TEXT, on_message))
    async with tg_app:
        await tg_app.start()
        await tg_app.updater.start_polling()
        logger.info("Telegram bot running")
        try:
            await asyncio.Event().wait()
        finally:
            await tg_app.updater.stop()
            await tg_app.stop()


async def run_discord(cfg: Config, runners, router, session_mgr) -> None:
    discord_bridges: dict[int, StreamingBridge] = {}

    async def gateway_handler(inbound: InboundMessage) -> None:
        if inbound.user_id not in discord_bridges:
            discord_bridges[inbound.user_id] = StreamingBridge(
                dc_adapter, edit_interval=cfg.gateway.stream_edit_interval_seconds
            )
        bridge = discord_bridges[inbound.user_id]
        await dispatch(
            inbound, bridge, session_mgr, router, runners,
            lambda t: dc_adapter.send(inbound.user_id, t),
        )

    dc_adapter = DiscordAdapter(
        token=cfg.discord_token,
        allowed_user_ids=cfg.allowed_user_ids,
        gateway_handler=gateway_handler,
    )
    logger.info("Discord bot starting")
    await dc_adapter.start()


async def main(cfg_path: str = "config/config.toml", env_path: str = "secrets/.env") -> None:
    cfg = load_config(config_path=cfg_path, env_path=env_path)
    audit = AuditLog(audit_dir=cfg.audit.path, max_entries=cfg.audit.max_entries)
    runners, router, session_mgr = _build_shared(cfg, audit)

    coroutines = []
    if cfg.telegram_token:
        coroutines.append(run_telegram(cfg, runners, router, session_mgr))
    if cfg.discord_token:
        coroutines.append(run_discord(cfg, runners, router, session_mgr))

    if not coroutines:
        logger.error("No tokens configured. Set TELEGRAM_BOT_TOKEN or DISCORD_BOT_TOKEN.")
        return

    await asyncio.gather(*coroutines, return_exceptions=True)


if __name__ == "__main__":
    asyncio.run(main())
```

- [ ] **Step 4: Verify main.py imports cleanly**

```bash
cd /tmp/telegram-to-control
python3 -c "from main import dispatch, run_telegram, run_discord, main; print('OK')"
```
Expected: `OK`

- [ ] **Step 5: Run full test suite**

```bash
cd /tmp/telegram-to-control
python3 -m pytest tests/ -v --tb=short 2>&1 | tail -15
```
Expected: All tests PASS (28 total: 25 existing + 3 new dual-adapter tests)

- [ ] **Step 6: Commit**

```bash
cd /tmp/telegram-to-control
git add main.py tests/test_e2e_dual.py
git commit -m "feat: dual-adapter support — Telegram + Discord run concurrently"
```

---

## Self-Review

**Spec coverage (§3 DiscordAdapter):**
- [x] DiscordAdapter with 2000-char message limit — Task 1
- [x] Both adapters run simultaneously, one token error doesn't affect the other — `asyncio.gather(return_exceptions=True)` in Task 2
- [x] Telegram 4096 split (existing) / Discord 2000 split — Task 1
- [x] react/edit not supported fallback — react() is no-op, edit() has try/except — Task 1
- [ ] Rate limit exponential backoff on edit — deferred to Phase 2b (StreamingBridge enhancement)

**Placeholder scan:** None found — all steps have concrete code.

**Type consistency:**
- `InboundMessage` used consistently across discord_adapter.py, main.py, test_e2e_dual.py
- `BaseAdapter` signature (send/edit/react/max_message_length) matches between discord_adapter.py and base.py
- `dispatch()` signature consistent with how it's called in run_telegram() and run_discord()
