# src/channels/telegram.py
import logging
from telegram import Bot, Message
from telegram.error import TelegramError
from src.channels.base import BaseAdapter, InboundMessage

logger = logging.getLogger(__name__)
MAX_LEN = 4096


class TelegramAdapter(BaseAdapter):
    def __init__(self, bot: Bot, allowed_user_ids: list[int]):
        self._bot = bot
        self._allowed = set(allowed_user_ids)

    def is_authorized(self, user_id: int) -> bool:
        return bool(self._allowed) and user_id in self._allowed

    async def send(self, user_id: int, text: str) -> str:
        chunks = self._split(text)
        last_msg: Message | None = None
        for chunk in chunks:
            try:
                last_msg = await self._bot.send_message(chat_id=user_id, text=chunk)
            except TelegramError as e:
                logger.error("send failed: %s", e)
                raise
        return f"{user_id}:{last_msg.message_id}" if last_msg else ""

    async def edit(self, message_id: str, text: str) -> None:
        # message_id format: "chat_id:msg_id" — set by Gateway when creating stream message
        try:
            chat_id, mid = message_id.split(":", 1)
            safe = text[:MAX_LEN]
            await self._bot.edit_message_text(chat_id=int(chat_id), message_id=int(mid), text=safe)
        except TelegramError as e:
            logger.warning("edit failed (will re-send): %s", e)

    async def react(self, message_id: str, emoji: str) -> None:
        pass  # Telegram reaction API requires Bot API 7.0+; deferred

    def max_message_length(self) -> int:
        return MAX_LEN

    @staticmethod
    def _split(text: str) -> list[str]:
        chunks = []
        while len(text) > MAX_LEN:
            split_pos = text.rfind("\n", 0, MAX_LEN)
            if split_pos == -1:
                split_pos = MAX_LEN
            chunks.append(text[:split_pos])
            text = text[split_pos:].lstrip("\n")
        if text:
            chunks.append(text)
        return chunks
