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
    bot_id: str = "default"
    chat_id: int | None = None
    chat_type: str = "private"
    mentioned_bot_ids: list[str] = field(default_factory=list)
    from_bot: bool = False
    reply_to_message_id: str | None = None
    reply_to_user_id: int | None = None


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
