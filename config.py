"""
telegram-to-control — Configuration
"""
import os
from dotenv import load_dotenv

load_dotenv()

# Telegram
BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
ALLOWED_USER_IDS = [
    int(uid.strip())
    for uid in os.getenv("ALLOWED_USER_IDS", "").split(",")
    if uid.strip().isdigit()
]

# Defaults
DEFAULT_CWD = os.getenv("DEFAULT_CWD", os.path.expanduser("~"))

# Limits
MAX_MESSAGE_LENGTH = 4096  # Telegram max
AGENT_TIMEOUT = 300  # 5 minutes for Gemini CLI

# Logging
DEBUG_LOG = os.getenv("DEBUG_LOG", "false").lower() == "true"
