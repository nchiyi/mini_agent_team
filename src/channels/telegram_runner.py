"""Per-bot Telegram launcher.

Each Telegram `Application` is bot-scoped: token, allowlist override, and
``bot_id`` stamping all come from ``bot_cfg``. ``main()`` launches one
task per ``cfg.bots`` entry whose ``channel == "telegram"``.
"""
from __future__ import annotations

import asyncio
import logging
import os
import re
from dataclasses import replace
from pathlib import Path
from telegram import Update
from telegram.ext import Application, MessageHandler, ContextTypes, filters

from src.channels.attachments import safe_ext, download_telegram_file
from src.channels.base import InboundMessage
from src.channels.telegram import TelegramAdapter
from src.core.bots import BotConfig
from src.core.config import _resolve_channel_auth
from src.gateway.app_context import AppContext
from src.gateway.bot_turns import BotTurnTracker
from src.gateway.dispatcher import dispatch
from src.gateway.policy import should_handle as _should_handle
from src.gateway.streaming import StreamingBridge

logger = logging.getLogger(__name__)

_SAFE_EXT = re.compile(r'^\.[a-zA-Z0-9]{1,10}$')


def _build_inbound_from_update(
    update, *, bot_id, registry, text: str | None = None,
    attachments: list[str] | None = None,
) -> InboundMessage:
    """Pure helper: construct an InboundMessage with B-2 group fields populated.

    Extracted so we can unit-test mention parsing / chat_id extraction
    without spinning up a real Telegram Application.
    """
    msg = update.message
    raw_text = msg.text or msg.caption or ""
    inbound_text = raw_text if text is None else text

    mentioned: list[str] = []
    seen: set[str] = set()
    for ent in (msg.entities or []):
        if getattr(ent, "type", None) != "mention":
            continue
        mention_text = raw_text[ent.offset:ent.offset + ent.length]
        resolved = registry.resolve(channel="telegram", username=mention_text)
        if resolved and resolved not in seen:
            mentioned.append(resolved)
            seen.add(resolved)

    reply_to = msg.reply_to_message
    reply_to_message_id = (
        str(reply_to.message_id) if reply_to is not None else None
    )
    reply_to_user_id = (
        reply_to.from_user.id
        if reply_to is not None and reply_to.from_user is not None
        else None
    )

    return InboundMessage(
        user_id=update.effective_user.id,
        channel="telegram",
        text=inbound_text or "(no text)",
        message_id=str(msg.message_id),
        bot_id=bot_id,
        chat_id=msg.chat.id,
        chat_type=msg.chat.type,
        mentioned_bot_ids=mentioned,
        attachments=attachments or [],
        from_bot=bool(msg.from_user and msg.from_user.is_bot),
        reply_to_message_id=reply_to_message_id,
        reply_to_user_id=reply_to_user_id,
    )


def _maybe_expand_at_all(
    inbound: "InboundMessage",
    bot_cfg: "BotConfig",
    registry,
) -> "InboundMessage":
    """If bot_cfg opts in, expand @all/@大家/@everyone to the registered bot ids;
    otherwise return the inbound unchanged. Pure function."""
    if not bot_cfg.respond_to_at_all:
        return inbound
    from dataclasses import replace
    from src.gateway.dispatcher import _expand_at_all
    expanded = _expand_at_all(inbound, registry)
    if expanded == list(inbound.mentioned_bot_ids):
        return inbound
    return replace(inbound, mentioned_bot_ids=expanded)


async def run_telegram_for_bot(ctx: AppContext, bot_cfg: BotConfig) -> None:
    """Launch one Telegram polling loop bound to a single bot.

    Each ``InboundMessage`` constructed here is stamped with
    ``bot_id=bot_cfg.id`` so dispatcher / memory routes per-bot.
    """
    cfg = ctx.cfg
    tg_app = Application.builder().token(bot_cfg.token).build()

    me = await tg_app.bot.get_me()
    bot_cfg = replace(
        bot_cfg,
        bot_username=me.username or "",
        bot_id_telegram=me.id or 0,
    )
    ctx.bot_registry.register(
        channel="telegram",
        username=bot_cfg.bot_username,
        bot_id=bot_cfg.id,
    )
    logger.info("Registered bot @%s as %s", bot_cfg.bot_username, bot_cfg.id)

    # 3-level precedence: bot-level override → channel-level override → global.
    allowed = (
        bot_cfg.allowed_user_ids
        if bot_cfg.allowed_user_ids is not None
        else cfg.telegram.allowed_user_ids
    )
    allow_all = (
        bot_cfg.allow_all_users
        if bot_cfg.allow_all_users is not None
        else cfg.telegram.allow_all_users
    )
    tg_ids, tg_all = _resolve_channel_auth(cfg, allowed, allow_all)
    adapter = TelegramAdapter(
        bot=tg_app.bot, allowed_user_ids=tg_ids, allow_all_users=tg_all,
    )
    bridge = StreamingBridge(
        adapter, edit_interval=cfg.gateway.stream_edit_interval_seconds,
    )
    upload_dir = Path("data/uploads")

    async def _handle_inbound(
        update: Update, context: ContextTypes.DEFAULT_TYPE, *,
        text: str, attachments: list[str],
    ) -> None:
        user_id = update.effective_user.id
        if not adapter.is_authorized(user_id):
            await update.message.reply_text("Unauthorized.")
            return

        await context.bot.send_chat_action(
            chat_id=update.effective_chat.id, action="typing",
        )
        inbound = _build_inbound_from_update(
            update,
            bot_id=bot_cfg.id,
            registry=ctx.bot_registry,
            text=text or "(no text)",
            attachments=attachments,
        )

        inbound = _maybe_expand_at_all(inbound, bot_cfg, ctx.bot_registry)

        if not _should_handle(inbound, bot_cfg, ctx.bot_turns):
            return

        # Turn-cap bookkeeping
        if inbound.chat_type != "private" and inbound.chat_id is not None:
            if inbound.from_bot:
                ctx.bot_turns.note_bot_turn(
                    channel=inbound.channel, chat_id=inbound.chat_id,
                )
            else:
                ctx.bot_turns.reset_on_human(
                    channel=inbound.channel, chat_id=inbound.chat_id,
                )

        voice_reply = ctx.session_mgr.is_voice_enabled(
            user_id, "telegram", bot_id=bot_cfg.id,
        )

        async def send_text_and_voice(t: str) -> str:
            msg_id = await adapter.send(user_id, t)
            if voice_reply and t.strip():
                from src.voice.tts import synthesise
                audio_path = await synthesise(t, voice=cfg.voice.tts_voice)
                if audio_path:
                    try:
                        await context.bot.send_voice(
                            chat_id=user_id, voice=open(audio_path, "rb"),
                        )
                    except Exception:
                        logger.warning(
                            "Failed to send voice reply", exc_info=True,
                        )
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
            path = await download_telegram_file(
                tg_file,
                f"{msg.from_user.id}_{largest.file_unique_id}{ext}",
                upload_dir,
            )
            attachments.append(path)

        if msg.document:
            doc = msg.document
            tg_file = await context.bot.get_file(doc.file_id)
            raw_ext = Path(doc.file_name or "file").suffix
            ext = safe_ext(raw_ext)
            path = await download_telegram_file(
                tg_file,
                f"{msg.from_user.id}_{doc.file_unique_id}{ext}",
                upload_dir,
            )
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

    tg_app.add_handler(
        MessageHandler(
            filters.TEXT | filters.PHOTO | filters.Document.ALL, on_message,
        ),
    )
    tg_app.add_handler(MessageHandler(filters.VOICE, on_voice))
    async with tg_app:
        await tg_app.start()
        await tg_app.updater.start_polling(drop_pending_updates=True)
        logger.info("Telegram bot running [%s]", bot_cfg.id)
        try:
            await asyncio.Event().wait()
        finally:
            await tg_app.updater.stop()
            await tg_app.stop()
