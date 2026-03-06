import os
import logging
from dotenv import load_dotenv

# Initialize logging as early as possible
logger = logging.getLogger("config")

# --- Default configurations ---
BOT_TOKEN = ""
ALLOWED_USER_IDS = []
DEFAULT_CWD = os.path.expanduser("~")
OLLAMA_BASE_URL = "http://localhost:11434/v1"
OLLAMA_CLOUD_API_KEY = ""
DEFAULT_MODEL = "llama3.1"
ALLOWED_MODELS = ""
MAX_MESSAGE_LENGTH = 4096
STREAM_UPDATE_INTERVAL = 200
DEBUG_LOG = False

def reload():
    """Reload configuration from environment and .env file."""
    global BOT_TOKEN, ALLOWED_USER_IDS, DEFAULT_CWD, OLLAMA_BASE_URL
    global OLLAMA_CLOUD_API_KEY, DEFAULT_MODEL, ALLOWED_MODELS
    global DEBUG_LOG

    # Re-load .env file
    load_dotenv(override=True)
    
    import re
    
    raw_token = os.getenv("TELEGRAM_BOT_TOKEN", "")
    # Remove any ANSI escape sequences or control characters (e.g., from copy-pasting terminal output)
    BOT_TOKEN = re.sub(r'[\x00-\x1f\x7f-\x9f]', '', raw_token).strip()

    
    allowed_str = os.getenv("ALLOWED_USER_IDS", "")
    ALLOWED_USER_IDS = [
        int(uid.strip())
        for uid in allowed_str.split(",")
        if uid.strip().isdigit()
    ]
    
    DEFAULT_CWD = os.getenv("DEFAULT_CWD", os.path.expanduser("~"))
    OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434/v1")
    OLLAMA_CLOUD_API_KEY = os.getenv("OLLAMA_CLOUD_API_KEY", "")
    DEFAULT_MODEL = os.getenv("DEFAULT_MODEL", "llama3.1")
    ALLOWED_MODELS = os.getenv("ALLOWED_MODELS", "")
    DEBUG_LOG = os.getenv("DEBUG_LOG", "false").lower() == "true"
    
    logger.info("Configuration reloaded from .env")

# Initial load
reload()
