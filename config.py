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

# Ollama (OpenAI Compatible)
OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434/v1")
OLLAMA_CLOUD_API_KEY = os.getenv("OLLAMA_CLOUD_API_KEY", "")
DEFAULT_MODEL = os.getenv("DEFAULT_MODEL", "llama3.1")

# Limits
MAX_MESSAGE_LENGTH = 4096  # Telegram max
STREAM_UPDATE_INTERVAL = 200  # chars between streaming edits

# Logging
DEBUG_LOG = os.getenv("DEBUG_LOG", "false").lower() == "true"
