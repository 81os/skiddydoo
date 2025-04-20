from __future__ import annotations

from typing import List, Optional

from discord.ext.commands import CommandError
from pydantic import BaseModel, Field

from cogs.lastfm import http


class ImageItem(BaseModel):
    size: str
    text: str = Field(..., alias="#text")

    def __str__(self) -> str:
        return self.text


# class FieldAttr(BaseModel):
#     rank: int


class Artist(BaseModel):
    url: str
    name: str
    mbid: Optional[str]

    def __str__(self) -> str:
        return self.name


class TrackItem(BaseModel):
    duration: int
    url: str
    name: str
    artist: Artist

    def __str__(self) -> str:
        return self.name


class Tracks(BaseModel):
    track: List[TrackItem]

    def __str__(self) -> str:
        return ", ".join(track.name for track in self.track)


class Album(BaseModel):
    artist: str
    mbid: Optional[str]
    name: str
    userplaycount: int
    image: List[ImageItem]
    tracks: Optional[Tracks]
    listeners: int
    playcount: int
    url: str

    def __str__(self) -> str:
        return self.name

    @property
    def plays(self) -> int:
        return self.userplaycount or 0

    @classmethod
    async def fetch(
        cls,
        album: str,
        artist: str,
        username: str = "",
    ) -> Album:
        response = await http.get(
            "/2.0/",
            params={
                "method": "album.getInfo",
                "username": username,
                "artist": artist,
                "album": album,
            },
        )

        try:
            return cls.parse_obj((await response.json())["album"])
        except KeyError as exc:
            raise CommandError(
                f"Last.fm album **{album}** by **{artist}** not found"
            ) from exc
