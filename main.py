# main.py
"""
Gateway Agent Platform — entry point.
Starts TelegramAdapter and connects it to the Gateway pipeline.
"""
import asyncio
import logging
from telegram import Update
from telegram.ext import Application, MessageHandler, ContextTypes, filters

from src.core.config import load_config
from src.runners.audit import AuditLog
from src.runners.cli_runner import CLIRunner
from src.channels.telegram import TelegramAdapter
from src.gateway.router import Router
from src.gateway.session import SessionManager
from src.gateway.streaming import StreamingBridge

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(name)s] %(levelname)s: %(message)s")
logger = logging.getLogger("main")


def build_app(cfg_path="config/config.toml", env_path="secrets/.env"):
    cfg = load_config(config_path=cfg_path, env_path=env_path)

    audit = AuditLog(audit_dir=cfg.audit.path, max_entries=cfg.audit.max_entries)

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

    router = Router(known_runners=set(runners.keys()), default_runner=cfg.gateway.default_runner)
    session_mgr = SessionManager(
        idle_minutes=cfg.gateway.session_idle_minutes,
        default_runner=cfg.gateway.default_runner,
        default_cwd=cfg.default_cwd,
    )

    tg_app = Application.builder().token(cfg.telegram_token).build()
    bot = tg_app.bot
    adapter = TelegramAdapter(bot=bot, allowed_user_ids=cfg.allowed_user_ids)
    bridge = StreamingBridge(adapter, edit_interval=cfg.gateway.stream_edit_interval_seconds)

    async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not update.message or not update.message.text:
            return
        user_id = update.effective_user.id
        if not adapter.is_authorized(user_id):
            await update.message.reply_text("Unauthorized.")
            return

        channel = "telegram"
        text = update.message.text.strip()
        session = session_mgr.get_or_create(user_id=user_id, channel=channel)
        cmd = router.parse(text)

        if cmd.is_cancel:
            await update.message.reply_text("No active task to cancel.")
            return
        if cmd.is_reset:
            await update.message.reply_text("Context cleared.")
            return
        if cmd.is_new:
            await update.message.reply_text("New session started.")
            return
        if cmd.is_status:
            await update.message.reply_text(
                f"Status\nRunners: {list(runners.keys())}\nDefault: {session.current_runner}\nCWD: {session.cwd}"
            )
            return
        if cmd.is_switch_runner:
            session.current_runner = cmd.runner
            await update.message.reply_text(f"Switched to {cmd.runner}")
            return

        target_runner = runners.get(session.current_runner)
        if not target_runner:
            await update.message.reply_text(f"Runner '{session.current_runner}' not found.")
            return

        await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")
        try:
            await bridge.stream(
                user_id=user_id,
                chunks=target_runner.run(
                    prompt=cmd.prompt,
                    user_id=user_id,
                    channel=channel,
                    cwd=session.cwd,
                ),
            )
        except TimeoutError:
            await update.message.reply_text("Runner timed out.")
        except Exception as e:
            logger.error("Runner error: %s", e)
            await update.message.reply_text(f"Error: {e}")

    tg_app.add_handler(MessageHandler(filters.TEXT, handle_message))
    return tg_app


if __name__ == "__main__":
    app = build_app()
    logger.info("Bot starting...")
    app.run_polling()
