# main.py
"""
Gateway Agent Platform — entry point.
Responsible for: config load, adapter startup/shutdown, session cleanup loop.
Dispatch logic lives in src/gateway/dispatcher.py.
"""
import asyncio
import logging
import os
import re
from pathlib import Path
from telegram import Update
from telegram.ext import Application, MessageHandler, ContextTypes, filters

from src.core.config import load_config, Config, _resolve_channel_auth
from src.runners.audit import AuditLog
from src.runners.cli_runner import CLIRunner
from src.runners.acp_runner import ACPRunner
from src.channels.telegram import TelegramAdapter
from src.channels.discord_adapter import DiscordAdapter
from src.channels.base import InboundMessage, BaseAdapter
from src.channels.attachments import safe_ext, download_telegram_file
from src.gateway.app_context import AppContext
from src.gateway.dispatcher import dispatch, apply_role_prompt, maybe_distill
from src.gateway.router import Router
from src.gateway.session import SessionManager
from src.gateway.streaming import StreamingBridge
from src.core.memory.tier1 import Tier1Store
from src.core.memory.tier3 import Tier3Store
from src.core.memory.context import ContextAssembler
from src.skills.loader import SkillRegistry as ModuleRegistry, load_skills as load_modules
from src.gateway.nlu import FastPathDetector
from src.gateway.rate_limit import RateLimiter
from src.roles import load_roles as _load_roles

_SAFE_EXT = re.compile(r'^\.[a-zA-Z0-9]{1,10}$')

# Backward-compat aliases — tests that import these names from main still work
_DEFAULT_ROLE = "department-head"
_apply_role_prompt = apply_role_prompt

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
)
logger = logging.getLogger("main")

# Backward-compat re-export so tests importing `from main import dispatch` keep working
__all__ = ["dispatch"]


async def _session_cleanup_loop(session_mgr, interval_seconds: int = 300) -> None:
    """Periodically evict sessions that have been idle past the configured timeout."""
    while True:
        await asyncio.sleep(interval_seconds)
        session_mgr.release_idle()


def _build_shared(cfg: Config, audit: AuditLog) -> AppContext:
    runners: dict = {}
    for name, rc in cfg.runners.items():
        if rc.type == "acp":
            runners[name] = ACPRunner(
                name=name,
                command=rc.path,
                args=rc.args,
                timeout_seconds=rc.timeout_seconds,
                context_token_budget=rc.context_token_budget,
                session_ttl_minutes=cfg.gateway.session_idle_minutes,
            )
        elif rc.type == "cli":
            runners[name] = CLIRunner(
                name=name,
                binary=rc.path,
                args=rc.args,
                timeout_seconds=rc.timeout_seconds,
                context_token_budget=rc.context_token_budget,
                audit=audit,
            )
        else:
            raise ValueError(f"Runner '{name}': unknown type '{rc.type}' (expected 'acp' or 'cli'")
    module_registry = load_modules(cfg.skills_dir)
    router = Router(
        known_runners=set(runners.keys()),
        default_runner=cfg.gateway.default_runner,
        module_registry=module_registry,
    )
    session_mgr = SessionManager(
        idle_minutes=cfg.gateway.session_idle_minutes,
        default_runner=cfg.gateway.default_runner,
        default_cwd=cfg.default_cwd,
    )
    tier1 = Tier1Store(permanent_dir=cfg.memory.cold_permanent_path)
    tier3 = Tier3Store(db_path=cfg.memory.db_path)
    session_mgr.attach_tier3(tier3)
    default_runner_cfg = cfg.runners.get(cfg.gateway.default_runner)
    max_tokens = default_runner_cfg.context_token_budget if default_runner_cfg else 4000
    assembler = ContextAssembler(tier1=tier1, tier3=tier3, max_tokens=max_tokens)
    nlu_detector = FastPathDetector(set(runners.keys()))
    rl_cfg = cfg.gateway.rate_limit
    rate_limiter = RateLimiter(
        per_user_per_minute=rl_cfg.per_user_per_minute,
        burst=rl_cfg.burst,
        max_concurrent=rl_cfg.max_concurrent_dispatches,
        enabled=rl_cfg.enabled,
    )
    return AppContext(
        cfg=cfg,
        runners=runners,
        module_registry=module_registry,
        router=router,
        session_mgr=session_mgr,
        tier1=tier1,
        tier3=tier3,
        assembler=assembler,
        nlu_detector=nlu_detector,
        rate_limiter=rate_limiter,
    )


async def run_telegram(ctx: AppContext) -> None:
    cfg = ctx.cfg
    tg_app = Application.builder().token(cfg.telegram_token).build()
    tg_ids, tg_all = _resolve_channel_auth(
        cfg, cfg.telegram.allowed_user_ids, cfg.telegram.allow_all_users
    )
    adapter = TelegramAdapter(bot=tg_app.bot, allowed_user_ids=tg_ids,
                              allow_all_users=tg_all)
    bridge = StreamingBridge(adapter, edit_interval=cfg.gateway.stream_edit_interval_seconds)
    upload_dir = Path("data/uploads")

    async def _handle_inbound(update: Update, context: ContextTypes.DEFAULT_TYPE, *,
                               text: str, attachments: list[str]) -> None:
        user_id = update.effective_user.id
        if not adapter.is_authorized(user_id):
            await update.message.reply_text("Unauthorized.")
            return

        await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")
        inbound = InboundMessage(
            user_id=user_id,
            channel="telegram",
            text=text or "(no text)",
            message_id=str(update.message.message_id),
            attachments=attachments,
        )

        voice_reply = ctx.session_mgr.is_voice_enabled(user_id, "telegram")

        async def send_text_and_voice(t: str) -> str:
            msg_id = await adapter.send(user_id, t)
            if voice_reply and t.strip():
                from src.voice.tts import synthesise
                audio_path = await synthesise(t, voice=cfg.voice.tts_voice)
                if audio_path:
                    try:
                        await context.bot.send_voice(chat_id=user_id, voice=open(audio_path, "rb"))
                    except Exception:
                        logger.warning("Failed to send voice reply", exc_info=True)
                    finally:
                        os.unlink(audio_path)
            return msg_id

        await dispatch(
            inbound, bridge, ctx.session_mgr, ctx.router, ctx.runners,
            ctx.tier1, ctx.tier3, ctx.assembler,
            send_text_and_voice,
            recent_turns=cfg.memory.tier3_context_turns,
            module_registry=ctx.module_registry,
            cfg=cfg,
            nlu_detector=ctx.nlu_detector,
            rate_limiter=ctx.rate_limiter,
        )

    async def on_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not update.message:
            return
        msg = update.message
        text = (msg.text or msg.caption or "").strip()
        attachments: list[str] = []

        if msg.photo:
            largest = max(msg.photo, key=lambda p: p.file_size or 0)
            tg_file = await context.bot.get_file(largest.file_id)
            raw_ext = Path(tg_file.file_path or "photo.jpg").suffix
            ext = safe_ext(raw_ext, ".jpg")
            path = await download_telegram_file(tg_file, f"{msg.from_user.id}_{largest.file_unique_id}{ext}", upload_dir)
            attachments.append(path)

        if msg.document:
            doc = msg.document
            tg_file = await context.bot.get_file(doc.file_id)
            raw_ext = Path(doc.file_name or "file").suffix
            ext = safe_ext(raw_ext)
            path = await download_telegram_file(tg_file, f"{msg.from_user.id}_{doc.file_unique_id}{ext}", upload_dir)
            attachments.append(path)

        if not text and not attachments:
            return
        await _handle_inbound(update, context, text=text, attachments=attachments)

    async def on_voice(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not update.message or not update.message.voice:
            return
        user_id = update.effective_user.id
        if not adapter.is_authorized(user_id):
            await update.message.reply_text("Unauthorized.")
            return
        voice = update.message.voice
        tg_file = await context.bot.get_file(voice.file_id)
        upload_dir.mkdir(parents=True, exist_ok=True)
        dest = upload_dir / f"{user_id}_{voice.file_unique_id}.ogg"
        await tg_file.download_to_drive(str(dest))
        from src.voice.stt import transcribe
        text = await transcribe(str(dest), provider=cfg.voice.stt_provider)
        if not text:
            await update.message.reply_text("(Could not transcribe voice message.)")
            return
        await update.message.reply_text(f"[Transcribed]: {text}")
        await _handle_inbound(update, context, text=text, attachments=[])

    tg_app.add_handler(MessageHandler(filters.TEXT | filters.PHOTO | filters.Document.ALL, on_message))
    tg_app.add_handler(MessageHandler(filters.VOICE, on_voice))
    async with tg_app:
        await tg_app.start()
        await tg_app.updater.start_polling(drop_pending_updates=True)
        logger.info("Telegram bot running")
        try:
            await asyncio.Event().wait()
        finally:
            await tg_app.updater.stop()
            await tg_app.stop()


async def run_discord(ctx: AppContext) -> None:
    cfg = ctx.cfg
    discord_bridges: dict[int, StreamingBridge] = {}

    async def gateway_handler(inbound: InboundMessage) -> None:
        if inbound.user_id not in discord_bridges:
            discord_bridges[inbound.user_id] = StreamingBridge(
                dc_adapter, edit_interval=cfg.gateway.stream_edit_interval_seconds
            )
        bridge = discord_bridges[inbound.user_id]
        await dispatch(
            inbound, bridge, ctx.session_mgr, ctx.router, ctx.runners,
            ctx.tier1, ctx.tier3, ctx.assembler,
            lambda t: dc_adapter.send(inbound.user_id, t),
            recent_turns=cfg.memory.tier3_context_turns,
            module_registry=ctx.module_registry,
            cfg=cfg,
            nlu_detector=ctx.nlu_detector,
            rate_limiter=ctx.rate_limiter,
        )

    dc_ids, dc_all = _resolve_channel_auth(
        cfg, cfg.discord.allowed_user_ids, cfg.discord.allow_all_users
    )
    dc_adapter = DiscordAdapter(
        token=cfg.discord_token,
        allowed_user_ids=dc_ids,
        gateway_handler=gateway_handler,
        allowed_channel_ids=cfg.discord.allowed_channel_ids,
        allow_bot_messages=cfg.discord.allow_bot_messages,
        allow_user_messages=cfg.discord.allow_user_messages,
        trusted_bot_ids=cfg.discord.trusted_bot_ids,
        allow_all_users=dc_all,
    )
    logger.info("Discord bot starting")
    await dc_adapter.start()


async def main(cfg_path: str = "config/config.toml", env_path: str = "secrets/.env") -> None:
    cfg = load_config(config_path=cfg_path, env_path=env_path)
    audit = AuditLog(audit_dir=cfg.audit.path, max_entries=cfg.audit.max_entries)
    ctx = _build_shared(cfg, audit)
    await ctx.tier3.init()

    asyncio.create_task(_session_cleanup_loop(ctx.session_mgr, interval_seconds=300))
    ctx.router._role_router.warm_up()

    for _slug in _load_roles(cfg.default_cwd):
        apply_role_prompt("", _slug, cfg.default_cwd)

    if not cfg.allowed_user_ids and not cfg.allow_all_users:
        logger.warning(
            "ALLOWED_USER_IDS is not set and allow_all_users is false — "
            "ALL user requests will be denied. "
            "Set ALLOWED_USER_IDS in secrets/.env to permit access."
        )

    coroutines = []
    if cfg.telegram_token:
        coroutines.append(run_telegram(ctx))
    if cfg.discord_token:
        coroutines.append(run_discord(ctx))

    if not coroutines:
        logger.error("No tokens configured. Set TELEGRAM_BOT_TOKEN or DISCORD_BOT_TOKEN.")
        return

    try:
        results = await asyncio.gather(*coroutines, return_exceptions=True)
        for result in results:
            if isinstance(result, Exception):
                from telegram.error import Conflict as TelegramConflict
                if isinstance(result, TelegramConflict):
                    logger.error(
                        "Telegram Conflict: another instance is already running. "
                        "Stop all other instances and restart. (%s)", result
                    )
                else:
                    logger.error("Channel exited with error: %s", result, exc_info=result)
    finally:
        await ctx.tier3.close()
        for runner in ctx.runners.values():
            if hasattr(runner, "close"):
                await runner.close()


if __name__ == "__main__":
    asyncio.run(main())
