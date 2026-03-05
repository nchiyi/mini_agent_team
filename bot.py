#!/usr/bin/env python3
"""
telegram-to-control — Telegram AI Agent Platform
=================================================
A personal AI agent accessible via Telegram.
Uses Google GenAI SDK as AI brain with a modular skills system.
"""
import logging
import os

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
from core.auth import create_genai_client
from core.gemini import GeminiClient
from core.memory import Memory
from core.scheduler import Scheduler
from skills import discover_skills

# Logging
log_level = logging.DEBUG if config.DEBUG_LOG else logging.INFO
logging.basicConfig(
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    level=log_level,
)
logger = logging.getLogger("bot")

# If NOT in debug mode, suppress verbose third-party libraries
if not config.DEBUG_LOG:
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("telegram").setLevel(logging.WARNING)
    logging.getLogger("apscheduler").setLevel(logging.WARNING)

# Initialize core
memory = Memory()
genai_client = create_genai_client()
gemini = GeminiClient(client=genai_client, default_model=config.DEFAULT_MODEL)
scheduler = Scheduler()
engine = Engine(gemini=gemini, memory=memory, scheduler=scheduler)


def is_authorized(user_id: int) -> bool:
    """Check if user is in the whitelist."""
    if not config.ALLOWED_USER_IDS:
        return True
    return user_id in config.ALLOWED_USER_IDS

async def try_auto_bind(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    """
    If ALLOWED_USER_IDS is completely empty in config, the first person
    to interact with the bot gets automatically bound as the sole owner.
    """
    if config.ALLOWED_USER_IDS:
         return False

    user_id = update.effective_user.id
    username = update.effective_user.username or "Unknown"

    config.ALLOWED_USER_IDS = [user_id]

    import re
    try:
        with open(".env", "r", encoding="utf-8") as f:
            env_content = f.read()

        if "ALLOWED_USER_IDS=" in env_content:
            env_content = re.sub(r"ALLOWED_USER_IDS=.*", f"ALLOWED_USER_IDS={user_id}", env_content)
        else:
            env_content += f"\nALLOWED_USER_IDS={user_id}\n"

        with open(".env", "w", encoding="utf-8") as f:
            f.write(env_content)

        logger.info(f"Auto-bound to first user: {user_id} (@{username})")
        await update.message.reply_text(
            f"🎉 **專屬綁定成功！**\n\n"
            f"您是第一個與我對話的使用者 (ID: `{user_id}`)。\n"
            f"我已經將這個 Bot 鎖定為**您專屬**，其他人無法再使用。\n\n"
            f"已自動更新 `.env` 檔案。",
            parse_mode="Markdown"
        )
        return True
    except Exception as e:
        logger.error(f"Auto-bind failed: {e}")
        return False


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
            await update.message.reply_text(chunk)


# === Command Handlers ===

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await try_auto_bind(update, context)

    if not is_authorized(update.effective_user.id):
        await update.message.reply_text("🚫 此 Bot 已綁定為私人專屬，未授權的使用者。")
        return

    skills_info = engine.get_all_skills_info()
    skills_list = "\n".join(
        f"  {', '.join(s['commands'])} — {s['description']}"
        for s in skills_info
    )

    await update.message.reply_text(
        f"🤖 **Telegram AI Agent**\n\n"
        f"引擎: Google GenAI SDK ✅\n"
        f"模型: `{config.DEFAULT_MODEL}`\n"
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
        display_cwd = cwd.replace(os.path.expanduser("~"), "~")
        await update.message.reply_text(f"📂 目前工作目錄: `{display_cwd}`", parse_mode="Markdown")
        return

    new_cwd = " ".join(context.args)

    if not os.path.isdir(new_cwd):
        await update.message.reply_text(f"❌ 目錄不存在: {new_cwd}")
        return

    memory.set_setting(user_id, "cwd", new_cwd)
    await update.message.reply_text(f"✅ 工作目錄: `{new_cwd}`", parse_mode="Markdown")


async def cmd_skill(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Route /command to the appropriate skill."""
    if not is_authorized(update.effective_user.id):
        await update.message.reply_text("🚫 此 Bot 已綁定為私人專屬，未授權。")
        return

    command = update.message.text.split()[0]
    args = update.message.text.split()[1:] if len(update.message.text.split()) > 1 else []

    skill = engine.get_skill_for_command(command)
    if not skill:
        await update.message.reply_text(f"❌ 未知指令: {command}")
        return

    # Show typing status
    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")
    processing_msg = await update.message.reply_text(f"⏳ {skill.name} 執行中...")

    try:
        result = await skill.handle(command, args, update.effective_user.id)
        await processing_msg.delete()
        await split_send(update, result)
    except Exception as e:
        if processing_msg:
            await processing_msg.delete()
        await update.message.reply_text(f"❌ Skill 錯誤: {e}")


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle free-text messages — streaming response with live updates."""
    user_id = update.effective_user.id

    if not is_authorized(user_id):
        await update.message.reply_text("🚫 此 Bot 已綁定為私人專屬，未授權。")
        return

    text = update.message.text.strip()
    if not text:
        return

    cwd = memory.get_setting(user_id, "cwd", config.DEFAULT_CWD)
    display_cwd = cwd.replace(os.path.expanduser("~"), "~")

    # Show typing status
    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")

    # First try Function Calling routing (fast path)
    try:
        result = await engine.handle_text(text, user_id, cwd)
        await split_send(update, result)
    except Exception as e:
        logger.error(f"handle_message error: {e}")
        await update.message.reply_text(f"❌ 錯誤: {e}")


async def send_notification(user_id: int, message: str):
    """Callback for scheduler to send notifications."""
    try:
        await app_instance.bot.send_message(chat_id=user_id, text=message)
    except Exception as e:
        logger.error(f"Failed to send notification to {user_id}: {e}")


# === Main ===

app_instance = None


async def post_init(application: Application):
    """Actions to take after the application has initialized."""
    try:
        commands = [
            BotCommand("start", "開始並顯示幫助"),
            BotCommand("help", "顯示指令說明"),
            BotCommand("cwd", "設定/查看工作目錄")
        ]

        skills_info = engine.get_all_skills_info()
        for s in skills_info:
            for cmd in s['commands']:
                cmd_name = cmd.lstrip("/")
                desc = s['description']
                commands.append(BotCommand(cmd_name.lower(), desc[:100]))

        await application.bot.set_my_commands(commands)
        logger.info(f"✅ Registered {len(commands)} commands to Telegram menu")
    except Exception as e:
        logger.error(f"Failed to register commands: {e}")

    scheduler.start()
    logger.info("✅ Scheduler started in post_init hook")


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
    print(f"   引擎: Google GenAI SDK ✅")
    print(f"   模型: {config.DEFAULT_MODEL}")
    print(f"   Skills: {len(skills)} 個")
    print(f"   白名單: {config.ALLOWED_USER_IDS or '無（允許所有人）'}")

    # Build application with post_init hook
    app = Application.builder().token(config.BOT_TOKEN).post_init(post_init).build()
    app_instance = app

    # Set up scheduler notification callback
    scheduler.set_notify_callback(send_notification)

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
