from __future__ import annotations

import re
from typing import List, Optional

from aiohttp import ClientSession
from discord.ext.commands import CommandError
from pydantic import BaseModel
from yarl import URL

from config import PIPED_API
from tools.client import Context

from .video import Video

CHANNEL_URL = re.compile(
    r"(?:https?://)?(?:www\.)?youtube\.com/channel/([a-zA-Z0-9_-]{24})/?"
)


class Channel(BaseModel):
    id: str
    name: str
    description: Optional[str] = None
    subscribers: Optional[int] = 0
    is_verified: Optional[bool] = False
    avatar_url: Optional[str] = None
    banner_url: Optional[str] = None
    videos: List[Video] = []

    def __str__(self) -> str:
        return self.name

    @property
    def url(self) -> str:
        return f"https://www.youtube.com/channel/{self.id}/"

    @property
    def image_url(self) -> Optional[str]:
        return self.avatar_url

    @classmethod
    async def search(
        cls,
        session: ClientSession,
        name: str,
    ) -> Optional[Channel]:
        async with session.get(
            URL.build(
                scheme="https",
                host=PIPED_API,
                path="/search",
            ),
            params={
                "q": name,
                "filter": "all",
            },
        ) as response:
            if not response.ok:
                return None

            data = await response.json()
            channels = list(
                filter(lambda item: item["type"] == "channel", data["items"])
            )
            if not channels:
                return None

            channel = channels[0]
            return cls(
                id=channel["url"].split("/")[-1],
                name=channel["name"],
                description=channel["description"],
                subscribers=channel["subscribers"],
                is_verified=channel["verified"],
                avatar_url=channel["thumbnail"],
            )

    @classmethod
    async def from_id(
        cls,
        session: ClientSession,
        id: str,
    ) -> Optional[Channel]:
        """
        The full channel with videos.
        """

        async with session.get(
            URL.build(
                scheme="https",
                host=PIPED_API,
                path=f"/channel/{id}",
            ),
        ) as response:
            if not response.ok:
                return None

            data = await response.json()
            return cls(
                **data,
                avatar_url=data["avatarUrl"],
                banner_url=data["bannerUrl"],
                is_verified=data["verified"],
                subscribers=data["subscriberCount"],
                videos=[Video.parse(video) for video in data["relatedStreams"]],
            )

    @classmethod
    async def convert(cls, ctx: Context, argument: str) -> Channel:
        async with ctx.typing():
            match = re.match(CHANNEL_URL, argument)
            if match:
                channel = await cls.from_id(ctx.bot.session, match[1])
            else:
                channel = await cls.search(ctx.bot.session, argument)

        if not channel:
            raise CommandError("No **YouTube channel** found with that query!")

        return channel
