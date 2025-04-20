from __future__ import annotations

from typing import TYPE_CHECKING, List, Optional, cast

from discord.ext.commands import CommandError
from pydantic import BaseModel, Field

from cogs.lastfm import http
from cogs.lastfm.interface.user.recent_tracks import RecentTracks

if TYPE_CHECKING:
    from cogs.lastfm.lastfm import Context


class ImageItem(BaseModel):
    text: str = Field(..., alias="#text")
    size: str


class Stats(BaseModel):
    listeners: int
    playcount: int
    userplaycount: Optional[int] = 0


class ArtistItem(BaseModel):
    name: str
    url: str
    image: List[ImageItem]


class Similar(BaseModel):
    artist: List[ArtistItem]

    def __str__(self) -> str:
        return ", ".join(artist.name for artist in self.artist)


class TagItem(BaseModel):
    name: str
    url: str


class Tags(BaseModel):
    tag: List[TagItem]

    def __str__(self) -> str:
        return ", ".join(tag.name for tag in self.tag)


class Link(BaseModel):
    text: str = Field(..., alias="#text")
    rel: str
    href: str

    def __str__(self) -> str:
        return self.href


class Links(BaseModel):
    link: Link

    def __str__(self) -> str:
        return self.link.href


class Bio(BaseModel):
    links: Links
    published: str
    summary: str
    content: str

    def __str__(self) -> str:
        return self.summary


class Artist(BaseModel):
    name: str
    mbid: Optional[str]
    url: str
    image: List[ImageItem]
    streamable: str
    ontour: bool
    stats: Stats
    similar: Similar
    tags: Tags
    bio: Bio

    def __str__(self) -> str:
        return self.name

    @property
    def plays(self) -> int:
        return self.stats.userplaycount or 0

    @classmethod
    async def fetch(
        cls,
        artist: str,
        username: str = "",
    ) -> Artist:
        response = await http.get(
            "/2.0/",
            params={
                "method": "artist.getInfo",
                "username": username,
                "artist": artist,
                "extended": 1,
            },
        )

        try:
            return cls.parse_obj((await response.json())["artist"])
        except KeyError as exc:
            raise CommandError(f"Last.fm artist **{artist}** not found") from exc

    @classmethod
    async def convert(cls, ctx: Context, argument: str) -> str:
        result = await cls.fetch(argument)
        return result.name

    @classmethod
    async def fallback(
        cls,
        ctx: Context,
        username: Optional[str] = None,
    ) -> str:
        username = username or cast(
            Optional[str],
            await ctx.bot.db.fetchval(
                """
                SELECT username
                FROM lastfm.config
                WHERE user_id = $1
                """,
                ctx.author.id,
            ),
        )
        if not username:
            raise CommandError(
                "You haven't set your Last.fm account yet",
                f"Use [`{ctx.clean_prefix}lastfm set <username>`](https://last.fm/join) to connect it",
            )

        recent_tracks = await RecentTracks.fetch(username)
        if not recent_tracks:
            raise CommandError("You must provide an artist name")

        return recent_tracks[0].artist.name
