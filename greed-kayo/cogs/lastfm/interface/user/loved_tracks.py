from __future__ import annotations

from typing import List, Optional

from discord.ext.commands import CommandError
from pydantic import BaseModel, Field

from cogs.lastfm import http


class Artist(BaseModel):
    url: str
    name: str
    mbid: Optional[str]


class Date(BaseModel):
    uts: int
    text: str = Field(..., alias="#text")


class ImageItem(BaseModel):
    size: str
    text: str = Field(..., alias="#text")


class Streamable(BaseModel):
    fulltrack: str
    text: str = Field(..., alias="#text")


class TrackItem(BaseModel):
    artist: Artist
    date: Date
    mbid: Optional[str]
    url: str
    name: str
    image: List[ImageItem]
    streamable: Streamable

    def __str__(self) -> str:
        return self.name


class FieldAttr(BaseModel):
    user: str
    totalPages: int
    page: int
    perPage: int
    total: int


class LovedTracks(BaseModel):
    track: List[TrackItem]
    field_attr: FieldAttr = Field(..., alias="@attr")

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
                "method": "user.getLovedTracks",
                "user": username,
                "limit": limit,
                "page": page,
            },
        )
        if response.status == 404:
            raise CommandError(f"Last.fm user **{username}** not found")

        try:
            return cls.parse_obj((await response.json())["lovedtracks"]).track
        except (KeyError, AttributeError):
            return []
