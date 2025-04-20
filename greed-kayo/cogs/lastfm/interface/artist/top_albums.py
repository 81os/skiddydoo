from __future__ import annotations

from typing import List, Optional

from pydantic import BaseModel, Field, ValidationError

from cogs.lastfm import http


class Artist(BaseModel):
    name: str
    mbid: Optional[str]
    url: str


class ImageItem(BaseModel):
    text: str = Field(..., alias="#text")
    size: str


class AlbumItem(BaseModel):
    name: str
    playcount: int
    mbid: Optional[str] = None
    url: str
    artist: Artist
    image: List[ImageItem]


class FieldAttr(BaseModel):
    artist: str
    page: int
    perPage: int
    totalPages: int
    total: int


class TopAlbums(BaseModel):
    album: List[AlbumItem]
    field_attr: FieldAttr = Field(..., alias="@attr")

    @classmethod
    async def fetch(
        cls,
        limit: int = 50,
        page: int = 1,
    ) -> List[AlbumItem]:
        response = await http.get(
            "/2.0/",
            params={
                "method": "artist.getTopAlbums",
                "limit": limit,
                "page": page,
            },
        )

        try:
            return cls.parse_obj((await response.json())["topalbums"]).album
        except (ValidationError, KeyError):
            return []
