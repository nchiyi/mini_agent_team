# src/voice/tts.py
import logging
import tempfile
import os

logger = logging.getLogger(__name__)


async def synthesise(text: str, voice: str = "zh-TW-HsiaoChenNeural") -> str | None:
    """Convert text to speech. Returns path to .mp3 file, or None on failure."""
    try:
        import edge_tts  # type: ignore
    except ImportError:
        logger.warning("edge-tts not installed — pip install edge-tts")
        return None
    try:
        fd, out_path = tempfile.mkstemp(suffix=".mp3")
        os.close(fd)
        communicate = edge_tts.Communicate(text, voice)
        await communicate.save(out_path)
        return out_path
    except Exception:
        logger.error("edge-tts TTS failed", exc_info=True)
        return None
