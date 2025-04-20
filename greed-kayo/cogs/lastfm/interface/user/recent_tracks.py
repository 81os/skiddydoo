from __future__ import annotations

from typing import TYPE_CHECKING, List, Optional, cast
from aiohttp import ClientSession

from discord import Color
from discord.ext.commands import CommandError
from pydantic import BaseModel, Field
from xxhash import xxh64_hexdigest

from cogs.lastfm import http
from tools import dominant_color
from tools.client.redis import Redis

if TYPE_CHECKING:
    from cogs.lastfm.interface.track.info import Track


class Artist(BaseModel):
    mbid: Optional[str]
    text: str = Field(..., alias="#text")

    def __str__(self) -> str:
        return self.text

    @property
    def name(self) -> str:
        return self.text

    @property
    def url(self) -> str:
        return f"https://www.last.fm/music/{self.text.replace(' ', '+')}"


class ImageItem(BaseModel):
    size: str
    text: str = Field(..., alias="#text")

    def __str__(self) -> str:
        return self.text


class Album(BaseModel):
    mbid: Optional[str]
    text: str = Field(..., alias="#text")

    def __str__(self) -> str:
        return self.text


class FieldAttr(BaseModel):
    nowplaying: bool


class Date(BaseModel):
    uts: int
    text: str = Field(..., alias="#text")


class TrackItem(BaseModel):
    artist: Artist
    streamable: str
    image: List[ImageItem]
    mbid: Optional[str]
    album: Album
    name: str
    field_attr: Optional[FieldAttr] = Field(None, alias="@attr")
    url: str
    date: Optional[Date] = None
    data: Optional[Track | TrackItem] = None

    def __str__(self) -> str:
        return self.name

    @property
    def key(self) -> str:
        return xxh64_hexdigest(self.url)

    async def color(self, redis: Redis) -> Color:
        image_url = self.image[-1].text
        if not image_url:
            return Color.dark_embed()

        key = xxh64_hexdigest(f"color:{image_url}")
        cached = cast(
            Optional[int],
            await redis.get(key),
        )
        if cached:
            return Color(cached)

        async with ClientSession() as session:
            async with session.get(image_url) as response:
                if response.status != 200:
                    return Color.dark_embed()

                image = await response.read()

        color = await dominant_color(image)
        await redis.set(key, color.value, ex=60 * 60 * 24 * 7)
        return color


class FieldAttr1(BaseModel):
    user: str
    totalPages: int
    page: int
    perPage: int
    total: int


class RecentTracks(BaseModel):
    track: List[TrackItem]
    field_attr: FieldAttr1 = Field(..., alias="@attr")

    @classmethod
    async def fetch(
        cls,
        username: str,
        limit: int = 50,
        page: int = 1,
    ) -> List[TrackItem]:
        response = await http.get(
            "/2.0/",
            params={
                "method": "user.getRecentTracks",
                "user": username,
                "limit": limit,
                "page": page,
            },
        )
        if response.status == 403:
            raise CommandError(
                f"Last.fm user **{username}** has their recent tracks hidden"
            )
        elif response.status != 200:
            raise CommandError(f"Last.fm user **{username}** not found")

        return cls.parse_obj((await response.json())["recenttracks"]).track
