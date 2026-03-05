#!/usr/bin/env python3
"""
telegram-to-control — Telegram Bot for Remote AI Agent Control
==============================================================
Use Telegram to invoke Gemini CLI or Claude Code CLI on your computer.
"""
import logging
import html

from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

import config
from agents import AGENTS

# Logging
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

# Per-user session state
user_sessions: dict[int, dict] = {}


def get_session(user_id: int) -> dict:
    """Get or create a session for the user."""
    if user_id not in user_sessions:
        user_sessions[user_id] = {
            "agent": config.DEFAULT_AGENT,
            "cwd": config.DEFAULT_CWD,
        }
    return user_sessions[user_id]


def is_authorized(user_id: int) -> bool:
    """Check if user is in the whitelist."""
    if not config.ALLOWED_USER_IDS:
        return True  # No whitelist = allow all (dev mode)
    return user_id in config.ALLOWED_USER_IDS


async def split_send(update: Update, text: str):
    """Send a message, splitting if it exceeds Telegram's limit."""
    if not text:
        text = "(空回應)"

    chunks = []
    while len(text) > config.MAX_MESSAGE_LENGTH:
        # Try to split at newline
        split_pos = text.rfind("\n", 0, config.MAX_MESSAGE_LENGTH)
        if split_pos == -1:
            split_pos = config.MAX_MESSAGE_LENGTH
        chunks.append(text[:split_pos])
        text = text[split_pos:].lstrip("\n")
    chunks.append(text)

    for chunk in chunks:
        await update.message.reply_text(chunk)


# === Command Handlers ===

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /start command."""
    if not is_authorized(update.effective_user.id):
        await update.message.reply_text("🚫 未授權的使用者。")
        return

    session = get_session(update.effective_user.id)
    await update.message.reply_text(
        "🤖 *Telegram\\-to\\-Control*\n\n"
        "直接發送訊息，我會轉送給 AI Agent 執行。\n\n"
        "📋 *指令：*\n"
        "`/agent gemini|claude` — 切換 Agent\n"
        "`/cwd <路徑>` — 切換工作目錄\n"
        "`/status` — 查看目前設定\n"
        "`/agents` — 查看可用的 Agent\n\n"
        f"🔧 目前 Agent: `{session['agent']}`\n"
        f"📂 工作目錄: `{session['cwd']}`",
        parse_mode="MarkdownV2",
    )


async def cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /status command."""
    if not is_authorized(update.effective_user.id):
        return

    session = get_session(update.effective_user.id)
    agent_name = session["agent"]
    agent_cls = AGENTS.get(agent_name)

    if agent_cls:
        agent = agent_cls()
        available = "✅ 已安裝" if agent.is_available() else "❌ 未安裝"
    else:
        available = "❓ 未知"

    await update.message.reply_text(
        f"🔧 Agent: {agent_name} ({available})\n"
        f"📂 工作目錄: {session['cwd']}"
    )


async def cmd_agent(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /agent command to switch agent."""
    if not is_authorized(update.effective_user.id):
        return

    if not context.args:
        await update.message.reply_text(
            f"用法: `/agent gemini|claude`\n目前: `{get_session(update.effective_user.id)['agent']}`",
            parse_mode="Markdown",
        )
        return

    agent_name = context.args[0].lower()
    if agent_name not in AGENTS:
        available = ", ".join(AGENTS.keys())
        await update.message.reply_text(f"❌ 不支援的 Agent。可用: {available}")
        return

    session = get_session(update.effective_user.id)
    session["agent"] = agent_name

    agent = AGENTS[agent_name]()
    status = "✅" if agent.is_available() else "⚠️ 未安裝"

    await update.message.reply_text(f"✅ 已切換至 {agent.name} {status}")


async def cmd_agents(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /agents command to list available agents."""
    if not is_authorized(update.effective_user.id):
        return

    lines = ["📋 *可用的 Agent:*\n"]
    for key, cls in AGENTS.items():
        agent = cls()
        status = "✅" if agent.is_available() else "❌"
        lines.append(f"  {status} `{key}` — {agent.name}")

    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")


async def cmd_cwd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /cwd command to change working directory."""
    if not is_authorized(update.effective_user.id):
        return

    if not context.args:
        session = get_session(update.effective_user.id)
        await update.message.reply_text(f"📂 目前工作目錄: `{session['cwd']}`", parse_mode="Markdown")
        return

    import os
    new_cwd = " ".join(context.args)

    if not os.path.isdir(new_cwd):
        await update.message.reply_text(f"❌ 目錄不存在: {new_cwd}")
        return

    session = get_session(update.effective_user.id)
    session["cwd"] = new_cwd
    await update.message.reply_text(f"✅ 工作目錄已切換至: `{new_cwd}`", parse_mode="Markdown")


# === Message Handler (main logic) ===

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle incoming text messages — send to the active agent."""
    user_id = update.effective_user.id

    if not is_authorized(user_id):
        await update.message.reply_text("🚫 未授權。")
        return

    prompt = update.message.text.strip()
    if not prompt:
        return

    session = get_session(user_id)
    agent_name = session["agent"]
    cwd = session["cwd"]

    agent_cls = AGENTS.get(agent_name)
    if not agent_cls:
        await update.message.reply_text(f"❌ Agent 未設定: {agent_name}")
        return

    agent = agent_cls()

    # Send "processing" indicator
    processing_msg = await update.message.reply_text(
        f"⏳ {agent.name} 處理中...\n📂 {cwd}"
    )

    try:
        result = await agent.execute(prompt, cwd)
        await processing_msg.delete()
        await split_send(update, f"💬 *{html.escape(agent.name)}:*\n\n{result}")
    except Exception as e:
        await processing_msg.delete()
        await update.message.reply_text(f"❌ 執行錯誤: {e}")


# === Main ===

def main():
    """Start the bot."""
    if not config.BOT_TOKEN:
        print("❌ 請在 .env 中設定 TELEGRAM_BOT_TOKEN")
        print("   cp .env.example .env && 編輯 .env")
        return

    print("🤖 telegram-to-control 啟動中...")
    print(f"   Agent: {config.DEFAULT_AGENT}")
    print(f"   CWD: {config.DEFAULT_CWD}")
    print(f"   白名單: {config.ALLOWED_USER_IDS or '無（允許所有人）'}")

    app = Application.builder().token(config.BOT_TOKEN).build()

    # Register handlers
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("status", cmd_status))
    app.add_handler(CommandHandler("agent", cmd_agent))
    app.add_handler(CommandHandler("agents", cmd_agents))
    app.add_handler(CommandHandler("cwd", cmd_cwd))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    print("✅ Bot 已啟動，等待訊息...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
