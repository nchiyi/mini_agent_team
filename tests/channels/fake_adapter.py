# tests/channels/fake_adapter.py
import asyncio
from src.channels.base import BaseAdapter


class FakeAdapter(BaseAdapter):
    def __init__(self):
        self.sent: list[str] = []
        self.edits: dict[str, str] = {}
        self._counter = 0

    async def send(self, user_id: int, text: str) -> str:
        self._counter += 1
        mid = str(self._counter)
        self.sent.append(text)
        return mid

    async def edit(self, message_id: str, text: str) -> None:
        self.edits[message_id] = text

    async def react(self, message_id: str, emoji: str) -> None:
        pass

    def max_message_length(self) -> int:
        return 4096
