from __future__ import annotations

from typing import List, Optional

from discord.ext.commands import CommandError
from pydantic import BaseModel, Field

from cogs.lastfm import http
from cogs.lastfm.interface.spotify.track import SpotifyTrack


class Artist(BaseModel):
    name: str
    mbid: Optional[str]
    url: str

    def __str__(self) -> str:
        return self.name


class ImageItem(BaseModel):
    text: str = Field(..., alias="#text")
    size: str

    def __str__(self) -> str:
        return self.text


# class FieldAttr(BaseModel):
#     position: str


class Album(BaseModel):
    artist: str
    title: str
    mbid: Optional[str]
    url: str
    image: List[ImageItem]
    # field_attr: FieldAttr = Field(..., alias="@attr")

    def __str__(self) -> str:
        return self.title


class Wiki(BaseModel):
    published: str
    summary: str
    content: str

    def __str__(self) -> str:
        return self.summary


class Track(BaseModel):
    name: str
    mbid: Optional[str]
    url: str
    duration: int
    listeners: int
    playcount: int
    artist: Artist
    album: Optional[Album]
    userplaycount: Optional[int] = 0
    userloved: Optional[bool] = False
    wiki: Optional[Wiki]
    image: Optional[str]
    spotify: Optional[SpotifyTrack]

    def __str__(self) -> str:
        return self.name

    @property
    def plays(self) -> int:
        return self.userplaycount or 0

    # @property
    # def image(self) -> Optional[str]:
    #     if not self.album:
    #         return

    #     return self.album.image[-1].text

    @classmethod
    async def fetch(
        cls,
        track: str,
        artist: str,
        username: str = "",
        image_url: Optional[str] = None,
    ) -> Track:
        response = await http.get(
            "/2.0/",
            params={
                "method": "track.getInfo",
                "username": username,
                "artist": artist,
                "track": track,
            },
        )

        try:
            return cls(**(await response.json())["track"], image=image_url)
        except KeyError as exc:
            raise CommandError(f"Last.fm track **{track}** not found") from exc
