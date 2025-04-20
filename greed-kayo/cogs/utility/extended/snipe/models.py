from datetime import datetime
from io import BytesIO
from typing import List, Optional

from discord import File, Message, Reaction, User
from discord.http import HTTPClient
from discord.utils import utcnow
from pydantic import BaseModel
from typing_extensions import Self
from xxhash import xxh64_hexdigest

from tools.client.redis import Redis


class MessageAttachment(BaseModel):
    url: str
    size: int
    filename: str
    content_type: Optional[str]

    def __str__(self) -> str:
        return self.url

    def is_image(self) -> bool:
        return self.content_type.startswith("image/") if self.content_type else False

    async def to_file(self, http: HTTPClient) -> File:
        buffer = await http.get_from_cdn(self.url)
        return File(BytesIO(buffer), filename=self.filename)


class MessageSnipe(BaseModel):
    guild_id: int
    channel_id: int
    message_id: int
    user_id: int
    user_name: str
    user_avatar: str
    created_at: datetime
    deleted_at: datetime
    content: str
    attachments: List[MessageAttachment] = []
    stickers: List[str] = []

    @property
    def filtered(self) -> bool:
        """Check if a bot filtered the message."""
        return (self.deleted_at - self.created_at).total_seconds() < 0.520

    @staticmethod
    def key(channel_id: int) -> str:
        return xxh64_hexdigest(f"snipe:{channel_id}")

    @classmethod
    async def push(cls, redis: Redis, message: Message) -> Optional[Self]:
        if (
            not message.guild
            or message.author.bot
            and not message.attachments
            or message.content.strip() == ".pick"
        ):
            return None

        if not message.content and not message.attachments and not message.stickers:
            return None

        data = cls(
            guild_id=message.guild.id,
            channel_id=message.channel.id,
            message_id=message.id,
            user_id=message.author.id,
            user_name=message.author.name,
            user_avatar=message.author.display_avatar.url,
            created_at=message.created_at,
            deleted_at=utcnow(),
            content=message.content,
            attachments=[
                MessageAttachment(
                    url=attachment.proxy_url,
                    size=attachment.size,
                    filename=attachment.filename,
                    content_type=attachment.content_type,
                )
                for attachment in message.attachments
            ],
            stickers=[str(sticker.url) for sticker in message.stickers],
        )

        key = cls.key(message.channel.id)
        cache_size = await redis.rpush(key, data.json())
        if cache_size > 100:
            await redis.ltrim(key, -49, -1)

        await redis.expire(key, 64800)
        return data

    @classmethod
    async def get(cls, redis: Redis, channel_id: int, index: int = 1) -> Optional[Self]:
        key = cls.key(channel_id)
        if not await redis.llen(key):
            return None

        index = -index
        snipes = await redis.lrange(key, index, index)
        if not snipes:
            return None

        return cls.parse_raw(snipes[0])


class ReactionSnipe(BaseModel):
    guild_id: int
    channel_id: int
    message_id: int
    user_id: int
    user_name: str
    removed_at: datetime
    emoji: str

    @property
    def message_url(self) -> str:
        return f"https://discord.com/channels/{self.guild_id}/{self.channel_id}/{self.message_id}"

    @staticmethod
    def key(channel_id: int) -> str:
        return xxh64_hexdigest(f"rsnipe:{channel_id}")

    @classmethod
    async def push(cls, redis: Redis, reaction: Reaction, user: User) -> Optional[Self]:
        if not reaction.message.guild:
            return None

        data = cls(
            guild_id=reaction.message.guild.id,
            channel_id=reaction.message.channel.id,
            message_id=reaction.message.id,
            user_id=user.id,
            user_name=user.name,
            removed_at=utcnow(),
            emoji=str(reaction.emoji),
        )

        key = cls.key(reaction.message.channel.id)
        cache_size = await redis.rpush(key, data.json())
        if cache_size > 100:
            await redis.ltrim(key, -49, -1)

        await redis.expire(key, 14400)
        return data

    @classmethod
    async def get(cls, redis: Redis, channel_id: int, index: int = 1) -> Optional[Self]:
        key = cls.key(channel_id)
        if not await redis.llen(key):
            return None

        index = -index
        snipes = await redis.lrange(key, index, index)
        if not snipes:
            return None

        return cls.parse_raw(snipes[0])
