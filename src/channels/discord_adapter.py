# src/channels/discord_adapter.py
import asyncio
import logging
from typing import Callable, Awaitable
import discord
from src.channels.base import BaseAdapter, InboundMessage

logger = logging.getLogger(__name__)
MAX_LEN = 2000


class DiscordAdapter(BaseAdapter):
    def __init__(
        self,
        token: str,
        allowed_user_ids: list[int],
        gateway_handler: Callable[[InboundMessage], Awaitable[None]],
    ):
        intents = discord.Intents.default()
        intents.message_content = True
        self._client = discord.Client(intents=intents)
        self._token = token
        self._allowed = set(allowed_user_ids)
        self._user_channel: dict[int, discord.TextChannel] = {}
        self._dispatch_channel: dict[int, discord.TextChannel] = {}
        self._user_locks: dict[int, asyncio.Lock] = {}
        self._setup_handlers(gateway_handler)

    def _setup_handlers(
        self, gateway_handler: Callable[[InboundMessage], Awaitable[None]]
    ) -> None:
        @self._client.event
        async def on_message(message: discord.Message) -> None:
            if message.author == self._client.user:
                return
            user_id = message.author.id
            if not self.is_authorized(user_id):
                await message.channel.send("Unauthorized.")
                return
            self._user_channel[user_id] = message.channel
            if user_id not in self._user_locks:
                self._user_locks[user_id] = asyncio.Lock()
            async with self._user_locks[user_id]:
                self._dispatch_channel[user_id] = message.channel
                try:
                    await gateway_handler(
                        InboundMessage(
                            user_id=user_id,
                            channel="discord",
                            text=message.content,
                            message_id=str(message.id),
                        )
                    )
                finally:
                    self._dispatch_channel.pop(user_id, None)

    def is_authorized(self, user_id: int) -> bool:
        return bool(self._allowed) and user_id in self._allowed

    async def send(self, user_id: int, text: str) -> str:
        channel = self._dispatch_channel.get(user_id) or self._user_channel.get(user_id)
        if not channel:
            logger.error("No channel context for Discord user %s", user_id)
            return ""
        chunks = self._split(text)
        last_msg: discord.Message | None = None
        for chunk in chunks:
            try:
                last_msg = await channel.send(chunk)
            except discord.DiscordException as e:
                logger.error("Discord send failed: %s", e)
                raise
        return f"{channel.id}:{last_msg.id}" if last_msg else ""

    async def edit(self, message_id: str, text: str) -> None:
        try:
            channel_id, mid = message_id.split(":", 1)
            channel = self._client.get_channel(int(channel_id))
            if channel is None:
                return
            msg = await channel.fetch_message(int(mid))
            await msg.edit(content=text[:MAX_LEN])
        except discord.DiscordException as e:
            logger.warning("Discord edit failed: %s", e)

    async def react(self, message_id: str, emoji: str) -> None:
        pass

    def max_message_length(self) -> int:
        return MAX_LEN

    async def start(self) -> None:
        await self._client.start(self._token)

    async def close(self) -> None:
        await self._client.close()

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
