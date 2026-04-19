# main.py
"""
Gateway Agent Platform — entry point.
Runs TelegramAdapter and/or DiscordAdapter concurrently via asyncio.gather().
Includes Tier 1 permanent memory, Tier 3 SQLite history, and context assembly.
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
from src.core.memory.tier1 import Tier1Store
from src.core.memory.tier3 import Tier3Store
from src.core.memory.context import ContextAssembler

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
)
logger = logging.getLogger("main")

_recent_turns = 20  # overridden by config at startup


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
    tier1 = Tier1Store(permanent_dir=cfg.memory.cold_permanent_path)
    tier3 = Tier3Store(db_path=cfg.memory.db_path)
    default_runner_cfg = cfg.runners.get(cfg.gateway.default_runner)
    max_tokens = default_runner_cfg.context_token_budget if default_runner_cfg else 4000
    assembler = ContextAssembler(tier1=tier1, tier3=tier3, max_tokens=max_tokens)
    return runners, router, session_mgr, tier1, tier3, assembler


async def dispatch(
    inbound: InboundMessage,
    bridge: StreamingBridge,
    session_mgr: SessionManager,
    router: Router,
    runners: dict,
    tier1: Tier1Store,
    tier3: Tier3Store,
    assembler: ContextAssembler,
    send_reply,
) -> None:
    """Channel-agnostic gateway logic."""
    session = session_mgr.get_or_create(user_id=inbound.user_id, channel=inbound.channel)
    cmd = router.parse(inbound.text)

    if cmd.is_remember:
        tier1.remember(user_id=inbound.user_id, content=cmd.prompt)
        await send_reply(f"Remembered: {cmd.prompt}")
        return
    if cmd.is_forget:
        removed = tier1.forget(user_id=inbound.user_id, keyword=cmd.prompt)
        await send_reply(f"Removed {removed} entries matching '{cmd.prompt}'")
        return
    if cmd.is_recall:
        results = await tier3.search(user_id=inbound.user_id, query=cmd.prompt, limit=5)
        if results:
            await send_reply("\n".join(r["content"] for r in results))
        else:
            await send_reply("Nothing found.")
        return
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

    await tier3.save_turn(
        user_id=inbound.user_id, channel=inbound.channel,
        role="user", content=inbound.text,
    )
    context = await assembler.build(
        user_id=inbound.user_id, channel=inbound.channel,
        recent_turns=_recent_turns,
    )
    full_prompt = (context + "\n\n" + cmd.prompt) if context else cmd.prompt

    try:
        response_chunks: list[str] = []

        async def collecting_gen():
            async for chunk in target_runner.run(
                prompt=full_prompt,
                user_id=inbound.user_id,
                channel=inbound.channel,
                cwd=session.cwd,
            ):
                response_chunks.append(chunk)
                yield chunk

        await bridge.stream(user_id=inbound.user_id, chunks=collecting_gen())
        response = "".join(response_chunks).strip()
        if response:
            await tier3.save_turn(
                user_id=inbound.user_id, channel=inbound.channel,
                role="assistant", content=response,
            )
    except TimeoutError:
        await send_reply("Runner timed out.")
    except Exception as e:
        logger.error("Runner error: %s", e)
        await send_reply(f"Error: {e}")


async def run_telegram(cfg: Config, runners, router, session_mgr, tier1, tier3, assembler) -> None:
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
            tier1, tier3, assembler,
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


async def run_discord(cfg: Config, runners, router, session_mgr, tier1, tier3, assembler) -> None:
    discord_bridges: dict[int, StreamingBridge] = {}

    async def gateway_handler(inbound: InboundMessage) -> None:
        if inbound.user_id not in discord_bridges:
            discord_bridges[inbound.user_id] = StreamingBridge(
                dc_adapter, edit_interval=cfg.gateway.stream_edit_interval_seconds
            )
        bridge = discord_bridges[inbound.user_id]
        await dispatch(
            inbound, bridge, session_mgr, router, runners,
            tier1, tier3, assembler,
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
    global _recent_turns
    cfg = load_config(config_path=cfg_path, env_path=env_path)
    _recent_turns = cfg.memory.tier3_context_turns
    audit = AuditLog(audit_dir=cfg.audit.path, max_entries=cfg.audit.max_entries)
    runners, router, session_mgr, tier1, tier3, assembler = _build_shared(cfg, audit)
    await tier3.init()

    coroutines = []
    if cfg.telegram_token:
        coroutines.append(run_telegram(cfg, runners, router, session_mgr, tier1, tier3, assembler))
    if cfg.discord_token:
        coroutines.append(run_discord(cfg, runners, router, session_mgr, tier1, tier3, assembler))

    if not coroutines:
        logger.error("No tokens configured. Set TELEGRAM_BOT_TOKEN or DISCORD_BOT_TOKEN.")
        return

    try:
        await asyncio.gather(*coroutines, return_exceptions=True)
    finally:
        await tier3.close()


if __name__ == "__main__":
    asyncio.run(main())
