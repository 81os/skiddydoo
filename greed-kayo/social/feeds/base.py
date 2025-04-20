import asyncio
from typing import List, Optional, TypedDict

from discord import TextChannel, Thread
from xxhash import xxh32_hexdigest

from main import zyn


class BaseRecord(TypedDict):
    guild_id: int
    channel_id: int
    template: Optional[str]


class Feed:
    """
    Base class for all Social Feeds.
    """

    bot: zyn
    name: str
    posted: int = 0
    scheduled_deletion: List[int] = []
    task: Optional[asyncio.Task] = None

    def __init__(
        self,
        bot: zyn,
        *,
        name: str = "",
    ):
        self.bot = bot
        self.name = name
        self.task = asyncio.create_task(self.feed())

    def __repr__(self) -> str:
        state = "running" if self.task and not self.task.done() else "finished"
        return f"<{self.name}Feed state={state} posted={self.posted}>"

    def __str__(self) -> str:
        return self.name

    @property
    def redis(self):
        return self.bot.redis

    @property
    def key(self) -> str:
        return xxh32_hexdigest(f"feed:{self.name}")

    async def feed(self) -> None:
        """
        The feed task.
        """

        raise NotImplementedError

    async def stop(self) -> None:
        """
        Stop the feed task.
        """

        if self.task:
            self.task.cancel("Feed stopped.")
            self.task = None

    async def get_records(self) -> dict[str | int, List[BaseRecord]]:
        """
        Get records receiving the feed.

        This will group the feeds based on the name_id,
        Which means that if you have multiple feeds for the same
        name_id, it will only fetch that user once.
        """

        raise NotImplementedError

    def can_post(self, channel: TextChannel | Thread) -> bool:
        """
        Check if the channel can receive the feed.
        """

        return (
            channel.permissions_for(channel.guild.me).send_messages
            and channel.permissions_for(channel.guild.me).embed_links
            and channel.permissions_for(channel.guild.me).attach_files
        )
