import os
from typing import AsyncIterator

_OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://localhost:11434")
_VISION_MODEL = os.environ.get("VISION_MODEL", "llava")
_ALLOWED_IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp"}


async def handle(command: str, args: str, user_id: int, channel: str) -> AsyncIterator[str]:
    if not args.strip():
        yield "Usage: /describe <image_url_or_local_path>"
        return
    try:
        import httpx
        import base64
        from pathlib import Path

        target = args.strip()
        p = Path(target)
        if p.suffix.lower() not in _ALLOWED_IMAGE_SUFFIXES:
            # treat as URL regardless of whether a non-image path exists locally
            images = [target]
        elif p.exists():
            img_b64 = base64.b64encode(p.read_bytes()).decode()
            images = [img_b64]
        else:
            images = [target]

        payload = {
            "model": _VISION_MODEL,
            "prompt": "Describe this image in detail.",
            "images": images,
            "stream": False,
        }
        async with httpx.AsyncClient(timeout=60) as client:
            resp = await client.post(f"{_OLLAMA_URL}/api/generate", json=payload)
            resp.raise_for_status()
            data = resp.json()
            yield data.get("response", "No response from vision model.")
    except ImportError:
        yield "httpx not installed. Run: pip install httpx"
    except Exception as e:
        yield f"Vision error: {e}"
