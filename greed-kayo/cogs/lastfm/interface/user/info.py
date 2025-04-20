from __future__ import annotations

from typing import List

from cashews import cache
from discord.ext.commands import CommandError
from pydantic import BaseModel, Field

from cogs.lastfm import http


class ImageItem(BaseModel):
    size: str
    text: str = Field(..., alias="#text")


class Registered(BaseModel):
    unixtime: int
    text: int = Field(..., alias="#text")


class User(BaseModel):
    name: str
    age: int
    subscriber: bool
    realname: str
    bootstrap: bool
    playcount: int
    artist_count: int
    playlists: int
    track_count: int
    album_count: int
    image: List[ImageItem]
    registered: Registered
    country: str
    gender: str
    url: str
    type: str

    def __str__(self) -> str:
        return self.name

    @property
    def scrobbles(self) -> int:
        return self.playcount

    @property
    def avatar(self) -> str:
        return self.image[-1].text.replace(".png", ".gif")

    @classmethod
    @cache(ttl="30m", prefix="lastfm:user")
    async def fetch(cls, username: str) -> User:
        response = await http.get(
            "/2.0/",
            params={
                "method": "user.getInfo",
                "user": username,
            },
        )
        if response.status != 200:
            raise CommandError(f"Last.fm user **{username}** not found")

        return cls.parse_obj((await response.json())["user"])
