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


class AlbumSearch(BaseModel):
    name: str
    artist: str
    url: str
    image: List[ImageItem]
    streamable: str
    mbid: Optional[str]

    def __str__(self) -> str:
        return self.name

    @classmethod
    async def fetch(
        cls,
        album: str,
        limit: int = 30,
        page: int = 1,
    ) -> AlbumSearch:
        response = await http.get(
            "/2.0/",
            params={
                "method": "album.search",
                "album": album,
                "limit": limit,
                "page": page,
            },
        )

        try:
            return cls.parse_obj(
                (await response.json())["results"]["albummatches"]["album"][0]
            )
        except IndexError as exc:
            raise CommandError(f"Last.fm album **{album}** not found") from exc

    @classmethod
    async def convert(cls, ctx: Context, argument: str) -> AlbumSearch:
        return await cls.fetch(argument, limit=1)

    @classmethod
    async def fallback(
        cls,
        ctx: Context,
        username: Optional[str] = None,
    ) -> AlbumSearch:
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
            raise CommandError("You must provide a track name")

        track = recent_tracks[0]
        if not track.album:
            raise CommandError("You must provide a track name")

        return await cls.fetch(f"{track.album} - {track.artist}")
