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
