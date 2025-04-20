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


class FieldAttr(BaseModel):
    rank: int


class TrackItem(BaseModel):
    name: str
    playcount: int
    listeners: int
    mbid: Optional[str]
    url: str
    streamable: str
    artist: Artist
    image: List[ImageItem]
    field_attr: FieldAttr = Field(..., alias="@attr")


class FieldAttr1(BaseModel):
    artist: str
    page: int
    perPage: int
    totalPages: int
    total: int


class TopTracks(BaseModel):
    track: List[TrackItem]
    field_attr: FieldAttr1 = Field(..., alias="@attr")

    @classmethod
    async def fetch(
        cls,
        artist: str,
        limit: int = 50,
        page: int = 1,
    ) -> List[TrackItem]:
        response = await http.get(
            "/2.0/",
            params={
                "method": "artist.getTopTracks",
                "artist": artist,
                "limit": limit,
                "page": page,
            },
        )

        try:
            return cls.parse_obj((await response.json())["toptracks"]).track
        except (ValidationError, KeyError):
            return []
