# src/channels/discord_adapter.py
import asyncio
import logging
import re
from pathlib import Path
from typing import Callable, Awaitable
import discord
from src.channels.base import BaseAdapter, InboundMessage

_UPLOAD_DIR = Path("data/uploads")

logger = logging.getLogger(__name__)
MAX_LEN = 2000

_ALLOW_OPTS = frozenset(("off", "mentions", "all"))
_SAFE_EXT = re.compile(r'^\.[a-zA-Z0-9]{1,10}$')


async def _typing_loop(channel: discord.abc.Messageable) -> None:
    """Keep the typing indicator alive every 8 s (Discord expires it at 10 s)."""
    try:
        while True:
            await channel.trigger_typing()
            await asyncio.sleep(8)
    except asyncio.CancelledError:
        pass
    except Exception:
        pass


class DiscordAdapter(BaseAdapter):
    def __init__(
        self,
        token: str,
        allowed_user_ids: list[int],
        gateway_handler: Callable[[InboundMessage], Awaitable[None]],
        allowed_channel_ids: list[int] | None = None,
        allow_bot_messages: str = "off",
        allow_user_messages: str = "all",
        trusted_bot_ids: list[int] | None = None,
    ):
        intents = discord.Intents.default()
        intents.message_content = True
        self._client = discord.Client(intents=intents)
        self._token = token
        self._allowed = set(allowed_user_ids)
        self._allowed_channels: set[int] = set(allowed_channel_ids or [])
        self._allow_bot_messages = allow_bot_messages if allow_bot_messages in _ALLOW_OPTS else "off"
        self._allow_user_messages = allow_user_messages if allow_user_messages in _ALLOW_OPTS else "all"
        self._trusted_bots: set[int] = set(trusted_bot_ids or [])
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

            # ── channel filter ──────────────────────────────────────────────
            if self._allowed_channels and message.channel.id not in self._allowed_channels:
                return

            bot_id = self._client.user.id if self._client.user else 0
            is_bot_msg = message.author.bot
            is_mentioned = any(u.id == bot_id for u in message.mentions)

            # ── authorization ───────────────────────────────────────────────
            if is_bot_msg:
                if self._allow_bot_messages == "off":
                    return
                if self._trusted_bots and message.author.id not in self._trusted_bots:
                    logger.debug("bot %s not in trusted_bot_ids, ignoring", message.author.id)
                    return
                if self._allow_bot_messages == "mentions" and not is_mentioned:
                    return
            else:
                user_id = message.author.id
                if not self.is_authorized(user_id):
                    await message.channel.send("Unauthorized.")
                    return
                if self._allow_user_messages == "off":
                    return
                if self._allow_user_messages == "mentions" and not is_mentioned:
                    return

            user_id = message.author.id
            self._user_channel[user_id] = message.channel
            if user_id not in self._user_locks:
                self._user_locks[user_id] = asyncio.Lock()
            async with self._user_locks[user_id]:
                self._dispatch_channel[user_id] = message.channel
                typing_task = asyncio.create_task(_typing_loop(message.channel))
                try:
                    attachments: list[str] = []
                    if message.attachments:
                        _UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
                        upload_root = _UPLOAD_DIR.resolve()
                        for att in message.attachments:
                            raw_ext = Path(att.filename).suffix
                            ext = raw_ext if _SAFE_EXT.match(raw_ext) else ""
                            dest = _UPLOAD_DIR / f"{user_id}_{att.id}{ext}"
                            if not dest.resolve().is_relative_to(upload_root):
                                logger.warning("Attachment path escaped upload dir: %s", dest)
                                continue
                            await att.save(dest)
                            attachments.append(str(dest))
                    await gateway_handler(
                        InboundMessage(
                            user_id=user_id,
                            channel="discord",
                            text=message.content or "(no text)",
                            message_id=str(message.id),
                            attachments=attachments,
                        )
                    )
                finally:
                    typing_task.cancel()
                    self._dispatch_channel.pop(user_id, None)

    def is_authorized(self, user_id: int) -> bool:
        return not self._allowed or user_id in self._allowed

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
