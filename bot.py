#!/usr/bin/env python3
"""
telegram-to-control — Telegram AI Agent Platform
=================================================
A personal AI agent accessible via Telegram.
Uses Gemini CLI as AI brain with a modular skills system.
"""
import logging

from telegram import Update, BotCommand
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

import config
from core import Engine
from core.gemini import GeminiCLI
from core.memory import Memory
from core.scheduler import Scheduler
from skills import discover_skills

# Logging
logging.basicConfig(
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger("bot")

# Initialize core
memory = Memory()
gemini = GeminiCLI(timeout=config.AGENT_TIMEOUT)
scheduler = Scheduler()
engine = Engine(gemini=gemini, memory=memory, scheduler=scheduler)


def is_authorized(user_id: int) -> bool:
    """Check if user is in the whitelist."""
    if not config.ALLOWED_USER_IDS:
        return True
    return user_id in config.ALLOWED_USER_IDS


async def split_send(update: Update, text: str):
    """Send a message, auto-splitting at Telegram's 4096 char limit."""
    if not text:
        text = "(空回應)"

    chunks = []
    while len(text) > config.MAX_MESSAGE_LENGTH:
        split_pos = text.rfind("\n", 0, config.MAX_MESSAGE_LENGTH)
        if split_pos == -1:
            split_pos = config.MAX_MESSAGE_LENGTH
        chunks.append(text[:split_pos])
        text = text[split_pos:].lstrip("\n")
    chunks.append(text)

    for chunk in chunks:
        try:
            await update.message.reply_text(chunk, parse_mode="Markdown")
        except Exception:
            # Fallback without markdown if formatting fails
            await update.message.reply_text(chunk)


# === Command Handlers ===

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_authorized(update.effective_user.id):
        await update.message.reply_text("🚫 未授權的使用者。")
        return

    skills_info = engine.get_all_skills_info()
    skills_list = "\n".join(
        f"  {', '.join(s['commands'])} — {s['description']}"
        for s in skills_info
    )

    gemini_status = "✅" if gemini.is_available() else "❌ 未安裝"

    await update.message.reply_text(
        f"🤖 **Telegram AI Agent**\n\n"
        f"Gemini CLI: {gemini_status}\n"
        f"Skills 已載入: {len(skills_info)}\n\n"
        f"📋 **可用指令:**\n{skills_list}\n\n"
        f"  /cwd <路徑> — 切換工作目錄\n"
        f"  /help — 顯示此訊息\n\n"
        f"💬 直接發送文字訊息即可與 Gemini 對話。",
        parse_mode="Markdown",
    )


async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await cmd_start(update, context)


async def cmd_cwd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_authorized(update.effective_user.id):
        return

    user_id = update.effective_user.id

    if not context.args:
        cwd = memory.get_setting(user_id, "cwd", config.DEFAULT_CWD)
        await update.message.reply_text(f"📂 目前工作目錄: `{cwd}`", parse_mode="Markdown")
        return

    import os
    new_cwd = " ".join(context.args)

    if not os.path.isdir(new_cwd):
        await update.message.reply_text(f"❌ 目錄不存在: {new_cwd}")
        return

    memory.set_setting(user_id, "cwd", new_cwd)
    await update.message.reply_text(f"✅ 工作目錄: `{new_cwd}`", parse_mode="Markdown")


async def cmd_skill(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Route /command to the appropriate skill."""
    if not is_authorized(update.effective_user.id):
        await update.message.reply_text("🚫 未授權。")
        return

    command = update.message.text.split()[0]
    args = update.message.text.split()[1:] if len(update.message.text.split()) > 1 else []

    skill = engine.get_skill_for_command(command)
    if not skill:
        await update.message.reply_text(f"❌ 未知指令: {command}")
        return

    processing_msg = await update.message.reply_text(f"⏳ {skill.name} 處理中...")

    try:
        result = await skill.handle(command, args, update.effective_user.id)
        await processing_msg.delete()
        await split_send(update, result)
    except Exception as e:
        await processing_msg.delete()
        await update.message.reply_text(f"❌ Skill 錯誤: {e}")


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle free-text messages — send to Gemini CLI."""
    user_id = update.effective_user.id

    if not is_authorized(user_id):
        await update.message.reply_text("🚫 未授權。")
        return

    text = update.message.text.strip()
    if not text:
        return

    cwd = memory.get_setting(user_id, "cwd", config.DEFAULT_CWD)

    processing_msg = await update.message.reply_text(
        f"⏳ Gemini 處理中...\n📂 {cwd}"
    )

    try:
        result = await engine.handle_text(text, user_id, cwd)
        await processing_msg.delete()
        await split_send(update, result)
    except Exception as e:
        await processing_msg.delete()
        await update.message.reply_text(f"❌ 錯誤: {e}")


async def send_notification(user_id: int, message: str):
    """Callback for scheduler to send notifications."""
    try:
        await app_instance.bot.send_message(chat_id=user_id, text=message)
    except Exception as e:
        logger.error(f"Failed to send notification to {user_id}: {e}")


# === Main ===

app_instance = None


def main():
    global app_instance

    if not config.BOT_TOKEN:
        print("❌ 請在 .env 中設定 TELEGRAM_BOT_TOKEN")
        print("   cp .env.example .env && 編輯 .env")
        return

    # Discover and register skills
    skills = discover_skills()
    for skill in skills:
        engine.register_skill(skill)

    print(f"🤖 Telegram AI Agent 啟動中...")
    print(f"   Gemini CLI: {'✅' if gemini.is_available() else '❌ 未安裝'}")
    print(f"   Skills: {len(skills)} 個")
    print(f"   白名單: {config.ALLOWED_USER_IDS or '無（允許所有人）'}")

    app = Application.builder().token(config.BOT_TOKEN).build()
    app_instance = app

    # Set up scheduler notification callback
    scheduler.set_notify_callback(send_notification)
    scheduler.start()

    # Register built-in commands
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("help", cmd_help))
    app.add_handler(CommandHandler("cwd", cmd_cwd))

    # Register all skill commands
    for skill_name, skill in engine.skills.items():
        for cmd in skill.commands:
            cmd_name = cmd.lstrip("/")
            app.add_handler(CommandHandler(cmd_name, cmd_skill))

    # Free-text handler (must be last)
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    print("✅ Bot 已啟動，等待訊息...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
