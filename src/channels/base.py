# src/channels/base.py
from abc import ABC, abstractmethod
from dataclasses import dataclass, field


@dataclass
class InboundMessage:
    user_id: int
    channel: str        # "telegram" | "discord"
    text: str
    message_id: str
    attachments: list[str] = field(default_factory=list)  # local file paths


class BaseAdapter(ABC):
    @abstractmethod
    async def send(self, user_id: int, text: str) -> str:
        """Send a message. Returns message_id."""
        ...

    @abstractmethod
    async def edit(self, message_id: str, text: str) -> None:
        """Edit an existing message."""
        ...

    @abstractmethod
    async def react(self, message_id: str, emoji: str) -> None:
        """Add a reaction; no-op if unsupported."""
        ...

    def max_message_length(self) -> int:
        return 4096
