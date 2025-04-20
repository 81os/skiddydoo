from __future__ import annotations

from typing import List, Optional

from pydantic import BaseModel, Field

from cogs.lastfm import http


class Streamable(BaseModel):
    text: str = Field(..., alias="#text")
    fulltrack: str


class Artist(BaseModel):
    name: str
    mbid: Optional[str]
    url: str


class ImageItem(BaseModel):
    text: str = Field(..., alias="#text")
    size: str


class TrackItem(BaseModel):
    name: str
    playcount: int
    mbid: Optional[str] = None
    match: float
    url: str
    streamable: Streamable
    duration: Optional[int] = None
    artist: Artist
    image: List[ImageItem]

    def __str__(self) -> str:
        return self.name


class FieldAttr(BaseModel):
    artist: str


class SimilarTracks(BaseModel):
    track: List[TrackItem]
    field_attr: FieldAttr = Field(..., alias="@attr")

    @classmethod
    async def fetch(
        cls,
        artist: str,
        track: str,
        limit: int = 50,
        page: int = 1,
    ) -> List[TrackItem]:
        response = await http.get(
            "/2.0/",
            params={
                "method": "track.getSimilar",
                "artist": artist,
                "track": track,
                "limit": limit,
                "page": page,
            },
        )
        if response.status != 200:
            return []

        return cls.parse_obj((await response.json())["similartracks"]).track
