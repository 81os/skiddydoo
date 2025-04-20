from __future__ import annotations

from typing import List, Literal, Optional

from discord.ext.commands import CommandError
from pydantic import BaseModel, Field

from cogs.lastfm import http


class Artist(BaseModel):
    url: str
    name: str
    mbid: Optional[str]


class ImageItem(BaseModel):
    size: str
    text: str = Field(..., alias="#text")


class FieldAttr(BaseModel):
    rank: int


class AlbumItem(BaseModel):
    artist: Artist
    image: List[ImageItem]
    mbid: Optional[str]
    url: str
    playcount: int
    field_attr: FieldAttr = Field(..., alias="@attr")
    name: str

    def __str__(self) -> str:
        return self.name


class FieldAttr1(BaseModel):
    user: str
    totalPages: int
    page: int
    perPage: int
    total: int


class TopAlbums(BaseModel):
    album: List[AlbumItem]
    field_attr: FieldAttr1 = Field(..., alias="@attr")

    @classmethod
    async def fetch(
        cls,
        username: str,
        limit: int = 50,
        page: int = 1,
        period: Literal[
            "overall",
            "7day",
            "1month",
            "3month",
            "6month",
            "12month",
        ] = "overall",
    ) -> List[AlbumItem]:
        response = await http.get(
            "/2.0/",
            params={
                "method": "user.getTopAlbums",
                "user": username,
                "limit": limit,
                "page": page,
                "period": period,
            },
        )
        if response.status == 404:
            raise CommandError(f"Last.fm user **{username}** not found")

        try:
            return cls.parse_obj((await response.json())["topalbums"]).album
        except (KeyError, AttributeError):
            return []
