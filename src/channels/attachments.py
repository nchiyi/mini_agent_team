# src/channels/attachments.py
"""Helpers for downloading channel attachments to a local upload directory."""
import logging
import re
from pathlib import Path

logger = logging.getLogger(__name__)

_SAFE_EXT = re.compile(r'^\.[a-zA-Z0-9]{1,10}$')
_UPLOAD_DIR = Path("data/uploads")


def safe_ext(raw: str, fallback: str = "") -> str:
    """Return raw if it passes the safe-extension check, else fallback."""
    return raw if _SAFE_EXT.match(raw) else fallback


async def download_telegram_file(tg_file, filename: str,
                                  upload_dir: Path = _UPLOAD_DIR) -> str:
    """Download a Telegram file to upload_dir/filename. Raises ValueError if path escapes."""
    upload_dir.mkdir(parents=True, exist_ok=True)
    upload_root = upload_dir.resolve()
    dest = upload_dir / filename
    if not dest.resolve().is_relative_to(upload_root):
        raise ValueError(f"Attachment path escaped upload dir: {dest}")
    await tg_file.download_to_drive(str(dest))
    return str(dest)
