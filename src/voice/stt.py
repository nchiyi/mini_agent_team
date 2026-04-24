# src/voice/stt.py
import logging
import os

logger = logging.getLogger(__name__)


async def transcribe(audio_path: str, provider: str = "groq") -> str | None:
    """Transcribe audio file to text. Returns None on failure."""
    if provider == "groq":
        return await _transcribe_groq(audio_path)
    if provider == "faster-whisper":
        return await _transcribe_faster_whisper(audio_path)
    logger.warning("Unknown STT provider: %s", provider)
    return None


async def _transcribe_groq(audio_path: str) -> str | None:
    api_key = os.environ.get("GROQ_API_KEY", "")
    if not api_key:
        logger.warning("GROQ_API_KEY not set — cannot transcribe voice")
        return None
    try:
        from groq import AsyncGroq  # type: ignore
    except ImportError:
        logger.warning("groq package not installed — pip install groq")
        return None
    try:
        client = AsyncGroq(api_key=api_key)
        with open(audio_path, "rb") as f:
            result = await client.audio.transcriptions.create(
                file=(audio_path, f),
                model="whisper-large-v3-turbo",
                response_format="text",
            )
        return result.strip() if isinstance(result, str) else str(result).strip()
    except Exception:
        logger.error("Groq STT failed", exc_info=True)
        return None


async def _transcribe_faster_whisper(audio_path: str) -> str | None:
    try:
        from faster_whisper import WhisperModel  # type: ignore
    except ImportError:
        logger.warning("faster-whisper not installed — pip install faster-whisper")
        return None
    try:
        import asyncio
        loop = asyncio.get_event_loop()
        def _run():
            model = WhisperModel("small", device="cpu", compute_type="int8")
            segments, _ = model.transcribe(audio_path)
            return " ".join(s.text for s in segments).strip()
        return await loop.run_in_executor(None, _run)
    except Exception:
        logger.error("faster-whisper STT failed", exc_info=True)
        return None
