import asyncio
from typing import AsyncIterator


async def handle(command: str, args: str, user_id: int, channel: str) -> AsyncIterator[str]:
    if not args.strip():
        yield "Usage: /search <query>"
        return
    try:
        from duckduckgo_search import DDGS
        results = await asyncio.to_thread(
            lambda: list(DDGS().text(args.strip(), max_results=5))
        )
        if not results:
            yield "No results found."
            return
        lines = []
        for r in results:
            title = r.get("title", "")
            href = r.get("href", "")
            body = (r.get("body", "") or "")[:150]
            lines.append(f"{title}\n{href}\n{body}")
        yield "\n\n".join(lines)
    except ImportError:
        yield "duckduckgo-search not installed. Run: pip install duckduckgo-search"
    except Exception as e:
        yield f"Search error: {e}"
