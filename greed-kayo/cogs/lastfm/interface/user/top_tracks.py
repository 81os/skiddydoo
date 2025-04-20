from __future__ import annotations

from typing import List, Literal, Optional

from discord.ext.commands import CommandError
from pydantic import BaseModel, Field

from cogs.lastfm import http


class Streamable(BaseModel):
    fulltrack: str
    text: str = Field(..., alias="#text")


class ImageItem(BaseModel):
    size: str
    text: str = Field(..., alias="#text")


class Artist(BaseModel):
    url: str
    name: str
    mbid: Optional[str]


class FieldAttr(BaseModel):
    rank: int


class TrackItem(BaseModel):
    streamable: Streamable
    mbid: Optional[str]
    name: str
    image: List[ImageItem]
    artist: Artist
    url: str
    duration: int
    field_attr: FieldAttr = Field(..., alias="@attr")
    playcount: int

    def __str__(self) -> str:
        return self.name


class FieldAttr1(BaseModel):
    user: str
    totalPages: int
    page: int
    perPage: int
    total: int


class TopTracks(BaseModel):
    track: List[TrackItem]
    field_attr: FieldAttr1 = Field(..., alias="@attr")

    @classmethod
    async def fetch(
        cls,
        username: str,
        limit: int = 100,
        page: int = 1,
        period: Literal[
            "overall", "7day", "1month", "3month", "6month", "12month"
        ] = "overall",
    ) -> List[TrackItem]:
        response = await http.get(
            "/2.0/",
            params={
                "method": "user.getTopTracks",
                "user": username,
                "limit": limit,
                "page": page,
                "period": period,
            },
        )
        if response.status == 404:
            raise CommandError(f"Last.fm user **{username}** not found")

        try:
            return TopTracks.parse_obj((await response.json())["toptracks"]).track
        except (KeyError, AttributeError):
            return []
