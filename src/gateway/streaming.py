# src/gateway/streaming.py
import asyncio
from typing import AsyncIterator
from src.channels.base import BaseAdapter


class StreamingBridge:
    def __init__(self, adapter: BaseAdapter, edit_interval: float = 1.5):
        self._adapter = adapter
        self._interval = edit_interval

    async def stream(
        self,
        user_id: int,
        chunks: AsyncIterator[str],
    ) -> None:
        """Accumulate chunks and throttle-edit the message."""
        accumulated = ""
        message_id: str | None = None
        last_edit = 0.0

        async for chunk in chunks:
            accumulated += chunk
            now = asyncio.get_event_loop().time()

            if message_id is None:
                message_id = await self._adapter.send(user_id, accumulated)
                last_edit = now
            elif now - last_edit >= self._interval:
                safe = accumulated[: self._adapter.max_message_length()]
                await self._adapter.edit(message_id, safe)
                last_edit = now

        if message_id is not None and accumulated:
            max_len = self._adapter.max_message_length()
            await self._adapter.edit(message_id, accumulated[:max_len])
            overflow = accumulated[max_len:]
            if overflow:
                await self._adapter.send(user_id, overflow)
        elif not message_id and accumulated:
            await self._adapter.send(user_id, accumulated)
