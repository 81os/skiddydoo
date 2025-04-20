from __future__ import annotations

from typing import TYPE_CHECKING, List, Optional, cast

from discord.ext.commands import CommandError
from pydantic import BaseModel, Field

from cogs.lastfm import http
from cogs.lastfm.interface.user import RecentTracks

if TYPE_CHECKING:
    from cogs.lastfm.lastfm import Context


class ImageItem(BaseModel):
    text: str = Field(..., alias="#text")
    size: str


class ArtistSearch(BaseModel):
    name: str
    listeners: int
    mbid: Optional[str]
    url: str
    streamable: str
    image: List[ImageItem]

    def __str__(self) -> str:
        return self.name

    @classmethod
    async def fetch(
        cls,
        artist: str,
        limit: int = 30,
        page: int = 1,
    ) -> ArtistSearch:
        response = await http.get(
            "/2.0/",
            params={
                "method": "artist.search",
                "artist": artist,
                "limit": limit,
                "page": page,
            },
        )

        try:
            return cls.parse_obj(
                response.json()["results"]["artistmatches"]["artist"][0]
            )
        except IndexError as exc:
            raise CommandError(f"Last.fm artist **{artist}** not found") from exc

    @classmethod
    async def convert(cls, ctx: Context, argument: str) -> str:
        result = await cls.fetch(argument, limit=1)
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
