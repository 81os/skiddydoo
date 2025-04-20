from asyncio import gather
from base64 import b64decode
from contextlib import suppress
from io import BytesIO
from logging import getLogger
from math import ceil
from typing import (
    Annotated,
    AsyncGenerator,
    List,
    Literal,
    Optional,
    Tuple,
    Union,
    cast,
)
from urllib.parse import quote_plus

from asyncspotify import Client as SpotifyClient
from asyncspotify import ClientCredentialsFlow as SpotifyClientCredentialsFlow
from cashews import cache
from colorama import Fore
from discord import Color, Embed, File, HTTPException, Member, Message
from discord.ext.commands import (
    BucketType,
    Cog,
    CommandError,
    Cooldown,
    CooldownMapping,
    MaxConcurrency,
    MaxConcurrencyReached,
    Range,
    command,
    group,
    has_permissions,
    cooldown,
    max_concurrency,
    parameter,
)
from discord.utils import format_dt
from pydantic import BaseModel, Field
from typing_extensions import Self
from yarl import URL

import cogs.lastfm.interface as lastfm
import cogs.lastfm.interface as interface
from cogs.lastfm.interface.spotify.track import SpotifyTrack
from config import AUTHORIZATION
from main import zyn
from tools import capture_time
from tools.client import Context as _Context
from tools.conversion import StrictMember, Timeframe
from tools.formatter import codeblock, plural, shorten
from tools.paginator import Paginator
from tools.parser import Script

log = getLogger("zyn/lastfm")
INDEX_CONCURRENCY = MaxConcurrency(1, per=BucketType.user, wait=False)
WHOKNOWS_COOLDOWN = CooldownMapping(Cooldown(1, 3), BucketType.member)


class Context(_Context):
    lastfm: lastfm.Config


class Variables:
    class Lastfm(BaseModel):
        url: str
        name: str
        avatar: str
        scrobbles: int
        artist_crown: str
        artists: int
        albums: int
        tracks: int

        def __str__(self) -> str:
            return self.name

        @property
        def plays(self) -> int:
            return self.scrobbles

    class Artist(BaseModel):
        url: str
        name: str
        image: str = Field("null")
        scrobbles: int = Field(default=0)

        def __str__(self) -> str:
            return self.name

        @property
        def plays(self) -> int:
            return self.scrobbles

        @property
        def lower(self) -> str:
            return self.name.lower()

        @property
        def upper(self) -> str:
            return self.name.upper()

        @classmethod
        async def from_track(
            cls,
            username: str,
            track: interface.user.recent_tracks.TrackItem,
        ) -> Self:
            artist = await lastfm.Artist.fetch(
                track.artist.text,
                username=username,
            )
            return cls(
                url=artist.url,
                name=artist.name,
                image=artist.image[-1].text,
                scrobbles=artist.stats.userplaycount or 0,
            )

    class Album(BaseModel):
        url: str
        name: str
        cover: str = Field("null")

        def __str__(self) -> str:
            return self.name

        @property
        def lower(self) -> str:
            return self.name.lower()

        @property
        def upper(self) -> str:
            return self.name.upper()

        @property
        def image(self) -> str:
            return self.cover or ""

    class Track(BaseModel):
        url: str
        name: str
        image: str = Field("null")
        scrobbles: int
        spotify: Optional[SpotifyTrack] = None

        def __str__(self) -> str:
            return self.name

        @property
        def plays(self) -> int:
            return self.scrobbles

        @property
        def lower(self) -> str:
            return self.name.lower()

        @property
        def upper(self) -> str:
            return self.name.upper()

        @classmethod
        async def from_track(
            cls,
            username: str,
            _track: interface.user.recent_tracks.TrackItem,
            spotify_client: SpotifyClient,
        ) -> tuple[interface.Track, Self]:
            track = await lastfm.Track.fetch(
                _track.name,
                _track.artist.name,
                username=username,
            )
            track_spotify = await SpotifyTrack.search(
                spotify_client,
                f"{track.name} - {track.artist.name}",
            )

            return track, cls(
                url=track.url,
                name=track.name,
                image=_track.image[-1].text or "null",
                scrobbles=track.userplaycount or 0,
                spotify=track_spotify,
            )

    @classmethod
    @cache(
        ttl="1m",
        key="{user.name}:{_track.key}",
    )
    async def construct(
        cls,
        ctx: Context,
        user: interface.User,
        _track: interface.user.recent_tracks.TrackItem,
        spotify_client: SpotifyClient,
    ) -> List[BaseModel]:
        artist, track = await gather(
            cls.Artist.from_track(user.name, _track),
            cls.Track.from_track(user.name, _track, spotify_client),
        )
        if track[0].album:
            album = cls.Album(
                url=track[0].album.url,
                name=track[0].album.title,
                cover=track[0].album.image[-1].text or "null",
            )
        elif _track.album.text:
            album = cls.Album(
                url=URL.build(
                    scheme="https",
                    host="www.last.fm",
                    path=f"/music/{quote_plus(artist.name)}/{quote_plus(_track.album.text)}",
                ).human_repr(),
                name=_track.album.text,
                cover=track[1].image or "null",
            )
        else:
            album = cls.Album(
                url=URL.build(
                    scheme="https",
                    host="www.last.fm",
                    path=f"/music/{quote_plus(artist.name)}/_/{quote_plus(_track.name)}",
                ).human_repr(),
                name=_track.name,
                cover=track[1].image or "null",
            )

        crown = cast(
            bool,
            await ctx.db.fetchval(
                """
                SELECT EXISTS(
                    SELECT 1
                    FROM lastfm.crowns
                    WHERE guild_id = $1
                    AND user_id = $2
                    AND artist = $3
                )
                """,
                ctx.guild.id,
                ctx.author.id,
                artist.name,
            ),
        )
        return [
            artist,
            album,
            track[1],
            cls.Lastfm(
                url=user.url,
                name=user.name,
                avatar=user.image[-1].text or "null",
                scrobbles=user.scrobbles,
                artists=user.artist_count,
                albums=user.album_count,
                tracks=user.track_count,
                artist_crown="👑" if crown else "",
            ),
        ]


class Lastfm(Cog):
    spotify_client: SpotifyClient

    def __init__(self, bot: zyn):
        self.bot = bot
        self.spotify_client = SpotifyClient(
            SpotifyClientCredentialsFlow(
                client_id=AUTHORIZATION.SPOTIFY.CLIENT_ID,
                client_secret=AUTHORIZATION.SPOTIFY.CLIENT_SECRET,
            ),
        )

    async def cog_load(self) -> None:
        await self.spotify_client.refresh()

    async def cog_unload(self) -> None:
        await self.spotify_client.close()

    async def cog_before_invoke(self, ctx: Context) -> None:
        if ctx.command in (
            self.lastfm,
            self.lastfm_set,
            self.nowplaying,
            self.spotify,
        ):
            return

        config = await lastfm.user.Config.fetch(self.bot, ctx.author.id)
        if not config:
            raise CommandError(
                "You haven't set your Last.fm account yet",
                f"Use [`{ctx.clean_prefix}lastfm set <username>`](https://last.fm/join) to connect it",
            )

        ctx.lastfm = config
        return await super().cog_before_invoke(ctx)

    async def cog_command_error(
        self,
        ctx: Context,
        exc: CommandError,
    ) -> Optional[Message]:
        if isinstance(exc, MaxConcurrencyReached) and ctx.command in (
            self.lastfm_set,
            self.lastfm_index,
        ):
            return await ctx.warn(
                "Your **Last.fm library** is currently being refreshed",
                "Please wait a couple of seconds before trying again",
            )

    async def cog_after_invoke(self, ctx: Context) -> None:
        """
        Automatically refresh the author's library.
        This task will only invoke 24 hours after their last index.
        """

        if (
            not hasattr(ctx, "lastfm")
            or hasattr(ctx, "lastfm")
            and not ctx.lastfm.should_index
        ):
            return

        elif ctx.command == self.lastfm_index:
            return

        try:
            await INDEX_CONCURRENCY.acquire(ctx)
        except MaxConcurrencyReached:
            return

        with capture_time(
            f"Daily index for {Fore.LIGHTMAGENTA_EX}{ctx.author}{Fore.RESET} / {Fore.LIGHTYELLOW_EX}{ctx.lastfm.username}{Fore.RESET}'s library finished",
            log,
        ), suppress(CommandError):
            await self.bot.db.execute(
                """
                UPDATE lastfm.config
                SET last_indexed = NOW()
                WHERE user_id = $1
                """,
                ctx.author.id,
            )

            async for library, items in self.index(ctx.lastfm, limit=10_000):
                if library == "artists":
                    await self.bot.db.execute(
                        """
                        DELETE FROM lastfm.artists
                        WHERE user_id = $1
                        AND NOT artist = ANY($2::CITEXT[])
                        """,
                        ctx.author.id,
                        [
                            artist.name
                            for artist in items
                            if isinstance(
                                artist,
                                lastfm.user.top_artists.ArtistItem,
                            )
                        ],
                    )

                    await self.bot.db.executemany(
                        """
                        INSERT INTO lastfm.artists (
                            user_id,
                            username,
                            artist,
                            plays
                        ) VALUES ($1, $2, $3, $4)
                        ON CONFLICT (user_id, artist) DO UPDATE
                        SET plays = EXCLUDED.plays
                        """,
                        [
                            (
                                ctx.author.id,
                                ctx.lastfm.username,
                                artist.name,
                                artist.playcount,
                            )
                            for artist in items
                            if isinstance(
                                artist,
                                lastfm.user.top_artists.ArtistItem,
                            )
                        ],
                    )

                if library == "albums":
                    await self.bot.db.execute(
                        """
                        DELETE FROM lastfm.albums
                        WHERE user_id = $1
                        """,
                        ctx.author.id,
                    )

                    await self.bot.db.executemany(
                        """
                        INSERT INTO lastfm.albums (
                            user_id,
                            username,
                            artist,
                            album,
                            plays
                        ) VALUES ($1, $2, $3, $4, $5)
                        ON CONFLICT (user_id, artist, album) DO UPDATE
                        SET plays = EXCLUDED.plays
                        """,
                        [
                            (
                                ctx.author.id,
                                ctx.lastfm.username,
                                album.artist.name,
                                album.name,
                                album.playcount,
                            )
                            for album in items
                            if isinstance(
                                album,
                                lastfm.user.top_albums.AlbumItem,
                            )
                        ],
                    )

                elif library == "tracks":
                    await self.bot.db.execute(
                        """
                        DELETE FROM lastfm.tracks
                        WHERE user_id = $1
                        """,
                        ctx.author.id,
                    )

                    await self.bot.db.executemany(
                        """
                        INSERT INTO lastfm.tracks (
                            user_id,
                            username,
                            artist,
                            track,
                            plays
                        ) VALUES ($1, $2, $3, $4, $5)
                        ON CONFLICT (user_id, artist, track) DO UPDATE
                        SET plays = EXCLUDED.plays
                        """,
                        [
                            (
                                ctx.author.id,
                                ctx.lastfm.username,
                                track.artist.name,
                                track.name,
                                track.playcount,
                            )
                            for track in items
                            if isinstance(
                                track,
                                lastfm.user.top_tracks.TrackItem,
                            )
                        ],
                    )

        await INDEX_CONCURRENCY.release(ctx)

    @Cog.listener()
    async def on_message_without_command(self, ctx: Context) -> Optional[Message]:
        command = cast(
            Optional[str],
            await self.bot.db.fetchval(
                """
                SELECT command
                FROM lastfm.config
                WHERE user_id = $1
                """,
                ctx.author.id,
            ),
        )
        if not command:
            return

        message = ctx.message
        if message.content.lower().startswith(command.lower()):
            member = next(
                (
                    mention
                    for mention in message.mentions
                    if isinstance(mention, Member)
                ),
                ctx.author,
            )

            try:
                return await self.nowplaying(ctx, member=member)
            except CommandError as exc:
                return await ctx.warn(*exc.args)

    async def index(
        self,
        user: lastfm.User | lastfm.Config,
        limit: Optional[int] = None,
    ) -> AsyncGenerator[
        Tuple[
            Literal["artists", "albums", "tracks"],
            List[
                lastfm.user.top_artists.ArtistItem
                | lastfm.user.top_albums.AlbumItem
                | lastfm.user.top_tracks.TrackItem
            ],
        ],
        None,
    ]:
        if isinstance(user, lastfm.Config):
            user = await lastfm.User.fetch(user.username)

        if limit and limit >= user.track_count:
            return

        for library in ("artists", "albums", "tracks"):
            pages = min(ceil(getattr(user, f"{library[:-1]}_count", 0) / 1000), 10)
            items: List[
                lastfm.user.top_artists.ArtistItem
                | lastfm.user.top_albums.AlbumItem
                | lastfm.user.top_tracks.TrackItem
            ] = []

            log.debug(
                f"Gathering {Fore.LIGHTRED_EX}{plural(pages):page}{Fore.RESET} from {Fore.LIGHTMAGENTA_EX}{library}{Fore.RESET} library for {Fore.LIGHTYELLOW_EX}{user.name}{Fore.RESET}."
            )
            for page in await gather(
                *[
                    getattr(lastfm.user, f"Top{library.capitalize()}").fetch(
                        user.name,
                        limit=1000,
                        page=page + 1,
                    )
                    for page in range(pages)
                ]
            ):
                items.extend(page)

            yield library, items

    async def claim_crown(
        self,
        ctx: Context,
        member: Member,
        artist: str,
    ) -> Optional[Message]:
        """
        Claim or steal an artist crown.
        """

        old_holder_id = cast(
            Optional[int],
            await self.bot.db.fetchval(
                """
                SELECT user_id
                FROM lastfm.crowns
                WHERE guild_id = $1
                AND artist = $2
                """,
                ctx.guild.id,
                artist,
            ),
        )
        await self.bot.db.execute(
            """
            INSERT INTO lastfm.crowns (
                guild_id,
                user_id,
                artist
            ) VALUES ($1, $2, $3)
            ON CONFLICT (guild_id, artist)
            DO UPDATE SET user_id = EXCLUDED.user_id
            """,
            ctx.guild.id,
            member.id,
            artist,
        )

        old_holder = ctx.guild.get_member(old_holder_id) if old_holder_id else None
        if not old_holder:
            return await ctx.neutral(
                f"`{member}` claimed the crown for **{artist}**",
                no_reference=True,
            )

        elif old_holder != member:
            return await ctx.neutral(
                f"`{member}` took the crown from `{old_holder}` for **{artist}**",
                no_reference=True,
            )

    @command(aliases=["now", "np", "fm"], usage="[member]", brief="@yurrion")
    async def nowplaying(
        self,
        ctx: Context,
        *,
        member: Member = parameter(
            default=lambda ctx: ctx.author,
        ),
    ) -> Message:
        """
        View your current Last.fm track.
        """

        config = await lastfm.Config.fetch(self.bot, member.id)
        if not config:
            if member == ctx.author:
                return await ctx.warn(
                    "You haven't set your Last.fm account yet",
                    f"Use [`{ctx.clean_prefix}lastfm set <username>`](https://last.fm/join) to connect it",
                )

            return await ctx.warn(f"**{member}** hasn't set their Last.fm account yet")

        await ctx.typing()
        user, tracks = await gather(
            lastfm.User.fetch(config.username),
            lastfm.user.RecentTracks.fetch(config.username, limit=1),
        )
        if not tracks:
            return await ctx.warn(
                f"Couldn't retrieve any **recent tracks** for **{config.username}**"
            )

        track = tracks[0]
        track.data = track
        try:
            track.data = await lastfm.Track.fetch(
                track.name,
                track.artist.text,
                username=config.username,
            )
        except CommandError:
            ...

        script: Optional[Script] = None
        if config.embed_mode == "default":
            embed = Embed(color=config.embed_color)
            embed.set_author(
                url=user.url,
                icon_url=user.avatar,
                name=user.realname or user.name,
            )
            if track.image[-1].text:
                embed.set_thumbnail(url=track.image[-1].text)

            embed.add_field(
                name="**Track**",
                value=f"[{track.name}]({track.url})",
                inline=True,
            )
            embed.add_field(
                name="**Artist**",
                value=f"[{track.artist.name}]({track.artist.url})",
                inline=True,
            )
            embed.set_footer(
                text=" ∙ ".join(
                    [
                        f"Plays: {getattr(track.data, 'plays', 0):,}",
                        f"Scrobbles: {user.scrobbles:,}",
                        f"Album: {(track.album.text or 'N/A')[:16]}",
                    ]
                )
            )

        elif config.embed_mode == "compact":
            embed = Embed(color=config.embed_color)
            embed.set_author(
                url=user.url,
                icon_url=user.avatar,
                name=user.realname or user.name,
            )
            if track.image[-1].text:
                embed.set_thumbnail(url=track.image[-1].text)

            embed.add_field(
                name="**Now Playing**",
                value=f"[{track.name}]({track.url})\nby [{track.artist.name}]({track.artist.url})",
                inline=True,
            )
            embed.set_footer(
                text=" ∙ ".join(
                    [
                        f"Plays: {getattr(track.data, 'plays', 0):,}",
                        f"Scrobbles: {user.scrobbles:,}",
                    ],
                ),
            )

        elif config.embed_mode == "minimal":
            embed = Embed(color=config.embed_color)
            embed.set_author(
                url=user.url,
                icon_url=user.avatar,
                name=user.realname or user.name,
            )
            if track.image[-1].text:
                embed.set_thumbnail(url=track.image[-1].text)

            embed.add_field(
                name="**Now Playing**",
                value=f"[{track.name}]({track.url})\nby [{track.artist.name}]({track.artist.url})",
                inline=True,
            )

        else:
            variables = await Variables.construct(
                ctx,
                user,
                track,
                self.spotify_client,
            )
            script = Script(
                config.embed_mode,
                [ctx.author, *variables],
            )

            embed = script.embed
            if not embed:
                return await ctx.warn(
                    "Your custom **embed mode** doesn't have an embed",
                    f"You can use `{ctx.clean_prefix}lastfm mode default` to reset it",
                )

        if config.color == 1337:
            embed.color = await track.color(self.bot.redis)

        try:
            message = await ctx.send(
                embed=embed,
                view=script.view if script else None,
            )
        except HTTPException as exc:
            return await ctx.warn(
                "Something is wrong with your **embed mode**",
                codeblock(exc.text),
            )

        if not config.reactions_disabled:
            reactions = config.reactions or ["👍", "👎"]
            for reaction in reactions:
                await message.add_reaction(reaction)

        return message

    @group(
        aliases=["lfm", "lf"],
        invoke_without_command=True,
    )
    async def lastfm(self, ctx: Context) -> Message:
        """
        Interact with your Last.fm account and check the available commands for Last.FM.
        """

        return await ctx.send_help(ctx.command)

    @lastfm.command(
        name="set",
        aliases=["connect", "login"],
        max_concurrency=INDEX_CONCURRENCY,
        usage="<username>",
        brief="yurrion",
    )
    async def lastfm_set(
        self,
        ctx: Context,
        username: str,
    ) -> Message:
        """
        Connect your Last.fm account to zyn's Last.FM system.
        """

        user = await lastfm.User.fetch(username)
        config = await lastfm.Config.fetch(self.bot, ctx.author.id)
        if config:
            await ctx.prompt(
                f"You've already connected your Last.fm account as **{config.username}**",
                "Are you sure you want to overwrite it? You'll lose all crowns and library data",
            )

        await self.bot.db.execute(
            """
            INSERT INTO lastfm.config (user_id, username)
            VALUES ($1, $2) ON CONFLICT (user_id) DO UPDATE
            SET username = EXCLUDED.username
            """,
            ctx.author.id,
            user.name,
        )

        message = await ctx.approve(
            f"Successfully  set your Last.fm account as **{username}**"
        )

        with capture_time(f"Indexed {user.name}'s library", log):
            await gather(
                *[
                    self.bot.db.execute(query, ctx.author.id)
                    for query in (
                        "DELETE FROM lastfm.artists WHERE user_id = $1",
                        "DELETE FROM lastfm.albums WHERE user_id = $1",
                        "DELETE FROM lastfm.tracks WHERE user_id = $1",
                    )
                ]
            )

            async for library, items in self.index(user):
                if library == "artists":
                    await self.bot.db.executemany(
                        """
                        INSERT INTO lastfm.artists (
                            user_id,
                            username,
                            artist,
                            plays
                        ) VALUES ($1, $2, $3, $4)
                        ON CONFLICT (user_id, artist) DO UPDATE
                        SET plays = EXCLUDED.plays
                        """,
                        [
                            (
                                ctx.author.id,
                                user.name,
                                artist.name,
                                artist.playcount,
                            )
                            for artist in items
                            if isinstance(
                                artist,
                                lastfm.user.top_artists.ArtistItem,
                            )
                        ],
                    )

                elif library == "albums":
                    await self.bot.db.executemany(
                        """
                        INSERT INTO lastfm.albums (
                            user_id,
                            username,
                            artist,
                            album,
                            plays
                        ) VALUES ($1, $2, $3, $4, $5)
                        ON CONFLICT (user_id, artist, album) DO UPDATE
                        SET plays = EXCLUDED.plays
                        """,
                        [
                            (
                                ctx.author.id,
                                user.name,
                                album.artist.name,
                                album.name,
                                album.playcount,
                            )
                            for album in items
                            if isinstance(
                                album,
                                lastfm.user.top_albums.AlbumItem,
                            )
                        ],
                    )

                elif library == "tracks":
                    await self.bot.db.executemany(
                        """
                        INSERT INTO lastfm.tracks (
                            user_id,
                            username,
                            artist,
                            track,
                            plays
                        ) VALUES ($1, $2, $3, $4, $5)
                        ON CONFLICT (user_id, artist, track) DO UPDATE
                        SET plays = EXCLUDED.plays
                        """,
                        [
                            (
                                ctx.author.id,
                                user.name,
                                track.artist.name,
                                track.name,
                                track.playcount,
                            )
                            for track in items
                            if isinstance(
                                track,
                                lastfm.user.top_tracks.TrackItem,
                            )
                        ],
                    )

        return message

    @lastfm.command(
        name="index",
        aliases=["refresh", "update"],
        max_concurrency=INDEX_CONCURRENCY,
    )
    @cooldown(1, 60 * 60 * 2, BucketType.user)
    async def lastfm_index(self, ctx: Context) -> Message:
        """
        Refresh your local Last.fm library.

        This command is intended to be a cache of your Last.fm library,
        which means that this command doesn't revalidate your current track.
        If your track is outdated, reconnect your Spotify on Last.fm.
        """

        await self.bot.db.execute(
            """
            UPDATE lastfm.config
            SET last_indexed = NOW()
            WHERE user_id = $1
            """,
            ctx.author.id,
        )

        async with ctx.loading("Refreshing your **Last.fm library**"):
            async for library, items in self.index(ctx.lastfm):
                await ctx.neutral(
                    f"Saving `{len(items):,}` {library} from your Last.fm library...",
                    patch=ctx.response,
                )

                if library == "artists":
                    await self.bot.db.execute(
                        """
                        DELETE FROM lastfm.artists
                        WHERE user_id = $1
                        AND NOT artist = ANY($2::CITEXT[])
                        """,
                        ctx.author.id,
                        [
                            artist.name
                            for artist in items
                            if isinstance(
                                artist,
                                lastfm.user.top_artists.ArtistItem,
                            )
                        ],
                    )

                    await self.bot.db.executemany(
                        """
                        INSERT INTO lastfm.artists (
                            user_id,
                            username,
                            artist,
                            plays
                        ) VALUES ($1, $2, $3, $4)
                        ON CONFLICT (user_id, artist) DO UPDATE
                        SET plays = EXCLUDED.plays
                        """,
                        [
                            (
                                ctx.author.id,
                                ctx.lastfm.username,
                                artist.name,
                                artist.playcount,
                            )
                            for artist in items
                            if isinstance(
                                artist,
                                lastfm.user.top_artists.ArtistItem,
                            )
                        ],
                    )

                elif library == "albums":
                    await self.bot.db.execute(
                        """
                        DELETE FROM lastfm.albums
                        WHERE user_id = $1
                        """,
                        ctx.author.id,
                    )

                    await self.bot.db.executemany(
                        """
                        INSERT INTO lastfm.albums (
                            user_id,
                            username,
                            artist,
                            album,
                            plays
                        ) VALUES ($1, $2, $3, $4, $5)
                        ON CONFLICT (user_id, artist, album) DO UPDATE
                        SET plays = EXCLUDED.plays
                        """,
                        [
                            (
                                ctx.author.id,
                                ctx.lastfm.username,
                                album.artist.name,
                                album.name,
                                album.playcount,
                            )
                            for album in items
                            if isinstance(
                                album,
                                lastfm.user.top_albums.AlbumItem,
                            )
                        ],
                    )

                elif library == "tracks":
                    await self.bot.db.execute(
                        """
                        DELETE FROM lastfm.tracks
                        WHERE user_id = $1
                        """,
                        ctx.author.id,
                    )

                    await self.bot.db.executemany(
                        """
                        INSERT INTO lastfm.tracks (
                            user_id,
                            username,
                            artist,
                            track,
                            plays
                        ) VALUES ($1, $2, $3, $4, $5)
                        ON CONFLICT (user_id, artist, track) DO UPDATE
                        SET plays = EXCLUDED.plays
                        """,
                        [
                            (
                                ctx.author.id,
                                ctx.lastfm.username,
                                track.artist.name,
                                track.name,
                                track.playcount,
                            )
                            for track in items
                            if isinstance(
                                track,
                                lastfm.user.top_tracks.TrackItem,
                            )
                        ],
                    )

        return await ctx.approve(
            "Your **Last.fm library** has been refreshed",
            patch=ctx.response,
        )

    @lastfm.group(
        name="color",
        aliases=["colour"],
        invoke_without_command=True,
    )
    async def lastfm_color(
        self,
        ctx: Context,
        color: Color,
    ) -> Message:
        """
        Set a custom color for the now playing embed.
        """

        await self.bot.db.execute(
            """
            UPDATE lastfm.config
            SET color = $2
            WHERE user_id = $1
            """,
            ctx.author.id,
            color.value,
        )

        return await ctx.approve(
            f"Successfully set your **embed color** to `{color}`", color=color
        )

    @lastfm_color.command(
        name="dominant",
        aliases=["artwork", "album"],
    )
    async def lastfm_color_dominant(self, ctx: Context) -> Message:
        """
        Set the embed color to the dominant color of the album artwork.
        """

        await self.bot.db.execute(
            """
            UPDATE lastfm.config
            SET color = $2
            WHERE user_id = $1
            """,
            ctx.author.id,
            1337,
        )

        return await ctx.approve(
            "Your **embed color** will now match the album artwork"
        )

    @lastfm.group(
        name="mode",
        aliases=["script"],
        invoke_without_command=True,
    )
    async def lastfm_mode(
        self,
        ctx: Context,
        *,
        style: Union[Literal["default", "compact", "minimal"], Script],
    ) -> Message:
        """
        Set a custom embed for the now playing command.

        Predefined styles:
        > `default` - A detailed embed with all information.
        > `compact` - A compact embed with only the essentials.
        > `minimal` - A minimal embed with only the track and artist.

        You can also use a custom embed script to create your own embed.
        Available variables can be found via our [documentation](https://docs.zyn.bot/intro/#last-fm).
        """

        if isinstance(style, Script) and not style.embed:
            return await ctx.warn(
                "Your script doesn't have an **embed**",
                "Custom styling is restricted to only the embed",
            )

        await self.bot.db.execute(
            """
            UPDATE lastfm.config
            SET embed_mode = $2
            WHERE user_id = $1
            """,
            ctx.author.id,
            (style.template if isinstance(style, Script) else style),
        )

        return await ctx.approve(
            f"Successfully set your **embed mode** to **{style}**"
            if not isinstance(style, Script)
            else "Your custom **embed mode** has been set"
        )

    @lastfm_mode.command(
        name="view",
        aliases=["show", "check"],
    )
    async def lastfm_mode_view(self, ctx: Context) -> Message:
        """
        View your custom Last.FM embed mode to display stuff such as nowplaying.
        """

        if ctx.lastfm.embed_mode in ("default", "compact", "minimal", None):
            return await ctx.neutral(
                f"You're using the **{ctx.lastfm.embed_mode}** embed mode"
            )

        return await ctx.send(
            embed=Embed(
                color=ctx.lastfm.embed_color,
                title="Your custom embed script",
                description=codeblock(ctx.lastfm.embed_mode),
            ),
        )

    @lastfm_mode.command(
        name="remove",
        aliases=[
            "reset",
            "delete",
            "del",
            "rm",
        ],
    )
    async def lastfm_mode_remove(self, ctx: Context) -> Message:
        """
        Remove your current custom embed mode from zyn's database.
        """

        return await ctx.invoke(self.lastfm_mode, style="default")

    @lastfm.group(
        name="reactions",
        aliases=["reacts", "react", "cr"],
        invoke_without_command=True,
    )
    async def lastfm_reactions(
        self,
        ctx: Context,
        upvote: str,
        downvote: str,
    ) -> Message:
        """
        Set custom reactions for the now playing command.

        By default, the reactions are 👍 and 👎.
        """

        reactions = [upvote, downvote]
        for reaction in reactions:
            try:
                await ctx.message.add_reaction(reaction)
            except (HTTPException, TypeError):
                return await ctx.warn(
                    f"I'm not able to use **{reaction}**",
                    "Try using an emoji from this server",
                )

        await self.bot.db.execute(
            """
            UPDATE lastfm.config
            SET reactions = $2
            WHERE user_id = $1
            """,
            ctx.author.id,
            reactions,
        )
        return await ctx.approve(
            f"Now reacting to **now playing** with {upvote} and {downvote}"
        )

    @lastfm_reactions.command(
        name="disable",
        aliases=["none", "off"],
    )
    async def lastfm_reactions_disable(self, ctx: Context) -> Message:
        """
        Disable reactions for the now playing command.
        """

        await self.bot.db.execute(
            """
            UPDATE lastfm.config
            SET reactions = ARRAY['disabled']
            WHERE user_id = $1
            """,
            ctx.author.id,
        )
        return await ctx.approve("No longer adding reactions to **now playing**")

    @lastfm_reactions.command(
        name="remove",
        aliases=[
            "reset",
            "delete",
            "del",
            "rm",
        ],
    )
    async def lastfm_reactions_remove(self, ctx: Context) -> Message:
        """
        Remove your custom reactions from zyn's database.
        """

        return await ctx.invoke(self.lastfm_reactions, upvote="👍", downvote="👎")

    @lastfm.group(
        name="command",
        aliases=["cmd", "cc"],
        invoke_without_command=True,
    )
    async def lastfm_command(self, ctx: Context, command: Range[str, 1, 12]) -> Message:
        """
        Set a custom command for the now playing command.

        The command will be invoked without a prefix.
        It can be any length between 1 and 12 characters.
        """

        await self.bot.db.execute(
            """
            UPDATE lastfm.config
            SET command = $2
            WHERE user_id = $1
            """,
            ctx.author.id,
            command,
        )
        return await ctx.approve(
            f"Successfully set your **now playing** command to **{command}**"
        )

    @lastfm_command.command(
        name="remove",
        aliases=[
            "reset",
            "delete",
            "del",
            "rm",
        ],
    )
    async def lastfm_command_remove(self, ctx: Context) -> Message:
        """
        Remove your custom now playing command.
        """

        await self.bot.db.execute(
            """
            UPDATE lastfm.config
            SET command = NULL
            WHERE user_id = $1
            """,
            ctx.author.id,
        )
        return await ctx.approve("Successfully removed your **now playing** command")

    @lastfm.command(
        name="recent",
        aliases=[
            "recenttracks",
            "recentlyplayed",
            "recently",
            "recentfor",
        ],
        usage="[member]",
        brief="@yurrion",
    )
    async def lastfm_recent(
        self,
        ctx: Context,
        member: Optional[
            Annotated[
                Member,
                StrictMember,
            ]
        ] = None,
        *,
        artist: Optional[str] = parameter(
            default=None,
            converter=interface.ArtistSearch,
        ),
    ) -> Message:
        """
        View your or a member's recently played tracks.
        """

        member = member or ctx.author
        config = await lastfm.Config.fetch(self.bot, member.id)
        if not config:
            if member == ctx.author:
                return await ctx.warn(
                    "You haven't set your Last.fm account yet",
                    f"Use [`{ctx.clean_prefix}lastfm set <username>`](https://last.fm/join) to connect it",
                )

            return await ctx.warn(f"**{member}** hasn't set their Last.fm account yet")

        tracks = await lastfm.user.RecentTracks.fetch(config.username, limit=100)
        if not tracks:
            return await ctx.warn(f"**{member}** hasn't scrobbled any tracks yet")

        entries = [
            f"[**{shorten(track.name)}**]({track.url}) by **{track.artist.name}**"
            for track in tracks[:100]
            if not artist or track.artist.name.lower() == artist.lower()
        ]
        if not entries and artist:
            return await ctx.warn(
                f"**{member}** hasn't listened to **{artist}** recently"
            )

        paginator = Paginator(
            ctx,
            entries=entries,
            embed=Embed(
                color=ctx.lastfm.embed_color,
                title=f"{config.username}'s recent tracks"
                + (f" by {artist}" if artist else ""),
            ),
        )
        return await paginator.start()

    @lastfm.command(
        name="favorites",
        aliases=[
            "favs",
            "loved",
            "loves",
            "likes",
        ],
        usage="[member]",
        brief="@yurrion",
    )
    async def lastfm_favorites(
        self,
        ctx: Context,
        member: Optional[
            Annotated[
                Member,
                StrictMember,
            ]
        ] = None,
        *,
        artist: Optional[str] = parameter(
            default=None,
            converter=interface.ArtistSearch,
        ),
    ) -> Message:
        """
        View your or a member's favorite tracks.
        """

        member = member or ctx.author
        config = await lastfm.Config.fetch(self.bot, member.id)
        if not config:
            if member == ctx.author:
                return await ctx.warn(
                    "You haven't set your Last.fm account yet",
                    f"Use [`{ctx.clean_prefix}lastfm set <username>`](https://last.fm/join) to connect it",
                )

            return await ctx.warn(f"**{member}** hasn't set their Last.fm account yet")

        tracks = await lastfm.user.LovedTracks.fetch(config.username, limit=100)
        if not tracks:
            return await ctx.warn(f"**{member}** hasn't loved any tracks yet")

        entries = [
            f"[**{shorten(track.name)}**]({track.url}) by **{track.artist.name}**"
            for track in tracks[:100]
            if not artist or track.artist.name.lower() == artist.lower()
        ]
        if not entries and artist:
            return await ctx.warn(
                f"**{member}** hasn't loved any tracks by **{artist}**"
            )

        paginator = Paginator(
            ctx,
            entries=entries,
            embed=Embed(
                color=ctx.lastfm.embed_color,
                title=f"{config.username}'s favorite tracks"
                + (f" by {artist}" if artist else ""),
            ),
        )
        return await paginator.start()

    @lastfm.command(
        name="collage",
        aliases=["chart"],
        usage="[member] [timeframe]",
        brief="@yurrion 30d",
    )
    @max_concurrency(1, BucketType.user)
    async def lastfm_collage(
        self,
        ctx: Context,
        member: Optional[
            Annotated[
                Member,
                StrictMember,
            ]
        ] = None,
        *,
        timeframe: Timeframe = parameter(
            default=Timeframe("overall"),
            description="The backlog period.",
        ),
    ) -> Message:
        """
        View a collage of your or a member's top albums.
        """
        member = member or ctx.author
        config = await lastfm.Config.fetch(self.bot, member.id)
        if not config:
            if member == ctx.author:
                return await ctx.warn(
                    "You haven't set your Last.fm account yet",
                    f"Use [`{ctx.clean_prefix}lastfm set <username>`](https://last.fm/join) to connect it",
                )

            return await ctx.warn(f"**{member}** hasn't set their Last.fm account yet")

        async with ctx.typing():
            response = await self.bot.session.post(
                "https://generator.musicorumapp.com/generate",
                json={
                    "theme": "grid",
                    "options": {
                        "user": config.username,
                        "period": timeframe.period,
                        "top": "albums",
                        "size": 3,
                        "names": False,
                        "playcount": False,
                        "story": False,
                    },
                },
            )
            if response.status != 200:
                return await ctx.warn(
                    "Something went wrong while generating your collage"
                )

            data = await response.json()
            buffer = b64decode(data["base64"].replace("data:image/jpeg;base64", ""))
            image = BytesIO(buffer)

        embed = Embed(
            color=ctx.lastfm.embed_color,
            title=f"{config.username}'s {timeframe} album collage",
        )
        embed.set_image(url="attachment://collage.png")
        return await ctx.send(
            embed=embed,
            file=File(image, filename="collage.png"),
        )

    @lastfm.command(
        name="topartists",
        aliases=[
            "topartist",
            "artists",
            "tar",
            "ta",
        ],
        usage="[member] [timeframe]",
        brief="@yurrion 30d",
    )
    async def lastfm_topartists(
        self,
        ctx: Context,
        member: Optional[
            Annotated[
                Member,
                StrictMember,
            ]
        ] = None,
        *,
        timeframe: Timeframe = parameter(
            default=Timeframe("overall"),
            description="The backlog period.",
        ),
    ) -> Message:
        """
        View your or a member's top artists.
        """

        member = member or ctx.author
        config = await lastfm.Config.fetch(self.bot, member.id)
        if not config:
            if member == ctx.author:
                return await ctx.warn(
                    "You haven't set your Last.fm account yet",
                    f"Use [`{ctx.clean_prefix}lastfm set <username>`](https://last.fm/join) to connect it",
                )

            return await ctx.warn(f"**{member}** hasn't set their Last.fm account yet")

        artists = await lastfm.user.TopArtists.fetch(
            config.username,
            period=timeframe.period,
        )
        if not artists:
            return await ctx.warn(
                f"**{member}** hasn't scrobbled any artists"
                + (
                    f" in the last **{timeframe}**"
                    if timeframe.period != "overall"
                    else "!"
                )
            )

        entries = [
            f"[**{artist.name}**]({artist.url}) ({plural(artist.playcount):play})"
            for artist in artists[:100]
        ]

        paginator = Paginator(
            ctx,
            entries=entries,
            embed=Embed(
                color=ctx.lastfm.embed_color,
                title=f"{config.username}'s {timeframe} top artists",
            ),
        )
        return await paginator.start()

    @lastfm.command(
        name="topalbums",
        aliases=[
            "topalbum",
            "albums",
            "tab",
            "tl",
        ],
        usage="[member] [timeframe]",
        brief="@yurrion 30d",
    )
    async def lastfm_topalbums(
        self,
        ctx: Context,
        member: Optional[
            Annotated[
                Member,
                StrictMember,
            ]
        ] = None,
        *,
        timeframe: Timeframe = parameter(
            default=Timeframe("overall"),
            description="The backlog period.",
        ),
    ) -> Message:
        """
        View your or a member's top albums.
        """

        member = member or ctx.author
        config = await lastfm.Config.fetch(self.bot, member.id)
        if not config:
            if member == ctx.author:
                return await ctx.warn(
                    "You haven't set your Last.fm account yet",
                    f"Use [`{ctx.clean_prefix}lastfm set <username>`](https://last.fm/join) to connect it",
                )

            return await ctx.warn(f"**{member}** hasn't set their Last.fm account yet")

        albums = await lastfm.user.TopAlbums.fetch(
            config.username,
            period=timeframe.period,
        )
        if not albums:
            return await ctx.warn(
                f"**{member}** hasn't scrobbled any albums"
                + (
                    f" in the last **{timeframe}**"
                    if timeframe.period != "overall"
                    else "!"
                )
            )

        entries = [
            f"[**{shorten(album.name)}**]({album.url}) by **{album.artist.name}** ({plural(album.playcount):play})"
            for album in albums[:100]
        ]

        paginator = Paginator(
            ctx,
            entries=entries,
            embed=Embed(
                color=ctx.lastfm.embed_color,
                title=f"{config.username}'s {timeframe} top albums",
            ),
        )
        return await paginator.start()

    @lastfm.command(
        name="toptracks",
        aliases=[
            "toptrack",
            "tracks",
            "ttr",
            "tt",
        ],
        usage="[member] [timeframe]",
        brief="@yurrion 30d",
    )
    async def lastfm_toptracks(
        self,
        ctx: Context,
        member: Optional[
            Annotated[
                Member,
                StrictMember,
            ]
        ] = None,
        *,
        timeframe: Timeframe = parameter(
            default=Timeframe("overall"),
            description="The backlog period.",
        ),
    ) -> Message:
        """
        View your or a member's top tracks.
        """

        member = member or ctx.author
        config = await lastfm.Config.fetch(self.bot, member.id)
        if not config:
            if member == ctx.author:
                return await ctx.warn(
                    "You haven't set your Last.fm account yet",
                    f"Use [`{ctx.clean_prefix}lastfm set <username>`](https://last.fm/join) to connect it",
                )

            return await ctx.warn(f"**{member}** hasn't set their Last.fm account yet")

        tracks = await lastfm.user.TopTracks.fetch(
            config.username,
            period=timeframe.period,
        )
        if not tracks:
            return await ctx.warn(
                f"**{member}** hasn't scrobbled any tracks"
                + (
                    f" in the last **{timeframe}**"
                    if timeframe.period != "overall"
                    else "!"
                )
            )

        entries = [
            f"[**{shorten(track.name)}**]({track.url}) by **{track.artist.name}** ({plural(track.playcount):play})"
            for track in tracks[:100]
        ]

        paginator = Paginator(
            ctx,
            entries=entries,
            embed=Embed(
                color=ctx.lastfm.embed_color,
                title=f"{config.username}'s {timeframe} top tracks",
            ),
        )
        return await paginator.start()

    @lastfm.command(
        name="overview",
        aliases=["ov"],
        usage="[member] [search]",
        brief="@yurrion Good Days",
    )
    async def lastfm_overview(
        self,
        ctx: Context,
        member: Optional[
            Annotated[
                Member,
                StrictMember,
            ]
        ] = None,
        *,
        search: str = parameter(
            converter=interface.Artist,
            default=interface.Artist.fallback,
        ),
    ) -> Message:
        """
        View your or a member's artist overview.
        """

        member = member or ctx.author
        config = await lastfm.Config.fetch(self.bot, member.id)
        if not config:
            if member == ctx.author:
                return await ctx.warn(
                    "You haven't set your Last.fm account yet",
                    f"Use [`{ctx.clean_prefix}lastfm set <username>`](https://last.fm/join) to connect it",
                )

            return await ctx.warn(f"**{member}** hasn't set their Last.fm account yet")

        artist = await lastfm.Artist.fetch(
            search,
            username=config.username,
        )
        if not artist:
            return await ctx.warn(
                f"**{member}** hasn't scrobbled **{search}**",
            )

        albums = await self.bot.db.fetch(
            """
            SELECT album, plays
            FROM lastfm.albums
            WHERE user_id = $1
            AND artist = $2
            ORDER BY plays DESC
            """,
            member.id,
            artist.name,
        )
        tracks = await self.bot.db.fetch(
            """
            SELECT track, plays
            FROM lastfm.tracks
            WHERE user_id = $1
            AND artist = $2
            ORDER BY plays DESC
            """,
            member.id,
            artist.name,
        )
        if not albums and not tracks:
            return await ctx.warn(
                f"No albums or tracks in your library for **{artist}**"
                if member == ctx.author
                else f"No albums or tracks in **{member}**'s library for **{artist}**"
            )

        embed = Embed(
            color=ctx.lastfm.embed_color,
            title=f"{config.username}'s overview for {artist}",
        )
        embed.set_thumbnail(url=artist.image[-1].text)
        embed.description = f"You have {plural(artist.plays, '**'):play} for [**{artist}**]({artist.url})"
        if artist.similar.artist:
            embed.description += f"\n> Similar to {', '.join(f'[`{shorten(similar.name, 12)}`]({similar.url})' for similar in artist.similar.artist[:3])}"

        if albums:
            embed.add_field(
                name="**Albums**",
                value="\n".join(
                    f"`{index + 1}`"
                    f" [**{shorten(record['album'], 16)}**]({artist.url}/{quote_plus(record['album'])})"
                    f" ({plural(record['plays']):play})"
                    for index, record in enumerate(albums[:5])
                )
                + (
                    f"\n> +`{len(albums) - 5}` other albums..."
                    if len(albums) > 5
                    else ""
                ),
            )

        if tracks:
            embed.add_field(
                name="**Tracks**",
                value="\n".join(
                    f"`{index + 1}`"
                    f" [**{shorten(record['track'], 16)}**]({artist.url}/{quote_plus(record['track'])})"
                    f" ({plural(record['plays']):play})"
                    for index, record in enumerate(tracks[:5])
                )
                + (
                    f"\n> +`{len(tracks) - 5}` other tracks..."
                    if len(tracks) > 5
                    else ""
                ),
            )

        return await ctx.send(embed=embed)

    @lastfm.command(
        name="artist",
        aliases=[
            "playsartist",
            "playsa",
            "plays",
        ],
        usage="[member] [search]",
        brief="@yurrion SZA",
    )
    async def lastfm_artist(
        self,
        ctx: Context,
        member: Optional[
            Annotated[
                Member,
                StrictMember,
            ]
        ] = None,
        *,
        search: str = parameter(
            converter=interface.Artist,
            default=interface.Artist.fallback,
        ),
    ) -> Message:
        """
        View how many plays you have for an artist.
        """

        member = member or ctx.author
        config = await lastfm.Config.fetch(self.bot, member.id)
        if not config:
            if member == ctx.author:
                return await ctx.warn(
                    "You haven't set your Last.fm account yet",
                    f"Use [`{ctx.clean_prefix}lastfm set <username>`](https://last.fm/join) to connect it",
                )

            return await ctx.warn(f"**{member}** hasn't set their Last.fm account yet")

        artist = await lastfm.Artist.fetch(
            search,
            username=config.username,
        )
        if not artist:
            return await ctx.warn(
                f"**{member}** hasn't scrobbled **{search}**",
            )

        return await ctx.neutral(
            f"{'You have' if member == ctx.author else f'**{member}** has'} {plural(artist.plays, '**'):play} for **{artist}**",
        )

    @lastfm.command(
        name="album",
        aliases=[
            "playsalbum",
            "playsal",
        ],
        usage="[member] [album]",
        brief="@yurrion I love you.",
    )
    async def lastfm_album(
        self,
        ctx: Context,
        member: Optional[
            Annotated[
                Member,
                StrictMember,
            ]
        ] = None,
        *,
        search: interface.AlbumSearch = parameter(
            converter=interface.AlbumSearch,
            default=interface.AlbumSearch.fallback,
        ),
    ) -> Message:
        """
        View how many plays you have for an album.
        """

        member = member or ctx.author
        config = await lastfm.Config.fetch(self.bot, member.id)
        if not config:
            if member == ctx.author:
                return await ctx.warn(
                    "You haven't set your Last.fm account yet",
                    f"Use [`{ctx.clean_prefix}lastfm set <username>`](https://last.fm/join) to connect it",
                )

            return await ctx.warn(f"**{member}** hasn't set their Last.fm account yet")

        album = await lastfm.Album.fetch(
            search.name,
            search.artist,
            username=config.username,
        )
        if not album:
            return await ctx.warn(
                f"**{member}** hasn't scrobbled **{search}**",
            )

        return await ctx.neutral(
            f"{'You have' if member == ctx.author else f'**{member}** has'} {plural(album.plays, '**'):play} for [**{album}**]({album.url}) by **{album.artist}**",
        )

    @lastfm.command(
        name="track",
        aliases=[
            "playstrack",
            "playst",
            "song",
        ],
        usage="[member] [search]",
        brief="@yurrion I'm God",
    )
    async def lastfm_track(
        self,
        ctx: Context,
        member: Optional[
            Annotated[
                Member,
                StrictMember,
            ]
        ] = None,
        *,
        search: interface.TrackSearch = parameter(
            converter=interface.TrackSearch,
            default=interface.TrackSearch.fallback,
        ),
    ) -> Message:
        """
        View how many plays you have for a track.
        """

        member = member or ctx.author
        config = await lastfm.Config.fetch(self.bot, member.id)
        if not config:
            if member == ctx.author:
                return await ctx.warn(
                    "You haven't set your Last.fm account yet",
                    f"Use [`{ctx.clean_prefix}lastfm set <username>`](https://last.fm/join) to connect it",
                )

            return await ctx.warn(f"**{member}** hasn't set their Last.fm account yet")

        track = await lastfm.Track.fetch(
            search.name,
            search.artist,
            username=config.username,
        )
        if not track:
            return await ctx.warn(
                f"**{member}** hasn't scrobbled **{search}**",
            )

        return await ctx.neutral(
            f"{'You have' if member == ctx.author else f'**{member}** has'} {plural(track.plays, '**'):play} for [**{track}**]({track.url}) by **{track.artist}**",
        )

    @lastfm.command(name="crown", usage="<artist>", brief="SZA")
    async def lastfm_crown(
        self,
        ctx: Context,
        *,
        artist: str = parameter(
            converter=interface.ArtistSearch,
            default=interface.ArtistSearch.fallback,
        ),
    ) -> Message:
        """
        View the crown holder for an artist.
        """

        crown = await self.bot.db.fetchrow(
            """
            SELECT user_id, claimed_at, (
                    SELECT plays
                    FROM lastfm.artists
                    WHERE user_id = crown.user_id
                    AND artist = crown.artist
            ) AS plays
            FROM lastfm.crowns crown
            WHERE guild_id = $1
            AND artist = $2
            """,
            ctx.guild.id,
            artist,
        )
        if not crown or not (member := ctx.guild.get_member(crown["user_id"])):
            return await ctx.warn(
                f"Nobody has claimed the crown for **{artist}** yet",
                f"Use `{ctx.clean_prefix}lastfm whoknows {artist}` to claim it",
            )

        return await ctx.neutral(
            f"The crown for **{artist}** was claimed {format_dt(crown['claimed_at'], 'R')}"
            f" by `{member}` with {plural(crown['plays'], '**'):play}"
        )

    @lastfm.command(name="crowns", usage="<member>", brief="@yurrion")
    async def lastfm_crowns(
        self,
        ctx: Context,
        *,
        member: Member = parameter(
            default=lambda ctx: ctx.author,
        ),
    ) -> Message:
        """
        View your or a member's artist crowns.
        """

        crowns = [
            f"**{crown['artist']}** ({plural(crown['plays']):play})"
            for crown in await self.bot.db.fetch(
                """
                SELECT artist, (
                    SELECT plays
                    FROM lastfm.artists
                    WHERE user_id = crown.user_id
                    AND artist = crown.artist
                ) AS plays
                FROM lastfm.crowns crown
                WHERE guild_id = $1
                AND user_id = $2
                ORDER BY plays DESC
                """,
                ctx.guild.id,
                member.id,
            )
        ]
        if not crowns:
            return await ctx.warn(
                "You haven't claimed any crowns yet",
                (
                    f"Use `{ctx.clean_prefix}lastfm whoknows` to claim crowns"
                    if member == ctx.author
                    else f"**{member}** hasn't claimed any crowns yet"
                ),
            )

        paginator = Paginator(
            ctx,
            entries=crowns,
            embed=Embed(
                color=ctx.lastfm.embed_color,
                title=f"{member}'s crowns",
            ),
        )
        return await paginator.start()

    @lastfm.command(
        name="mostcrowns",
        aliases=["mc"],
    )
    async def lastfm_mostcrowns(self, ctx: Context) -> Message:
        """
        View the top crown holders.
        """

        holders = [
            f"[**{member}**](https://last.fm/user/{crown['username']}) has {plural(crown['crowns'], '**'):crown}"
            for crown in await self.bot.db.fetch(
                """
                SELECT user_id, COUNT(*) AS crowns, (
                    SELECT username
                    FROM lastfm.config
                    WHERE user_id = crown.user_id
                ) AS username
                FROM lastfm.crowns crown
                WHERE guild_id = $1
                GROUP BY user_id
                ORDER BY crowns DESC
                """,
                ctx.guild.id,
            )
            if (member := ctx.guild.get_member(crown["user_id"]))
        ]
        if not holders:
            return await ctx.warn(
                "Nobody has claimed any crowns yet",
                f"Use `{ctx.clean_prefix}lastfm whoknows` to claim crowns",
            )

        paginator = Paginator(
            ctx,
            entries=holders,
            embed=Embed(
                color=ctx.lastfm.embed_color,
                title="Highest crown holders",
            ),
        )
        return await paginator.start()

    @lastfm.group(
        name="hide",
        aliases=["unhide"],
        invoke_without_command=True,
        description="manage guild",
    )
    @has_permissions(manage_guild=True)
    async def lastfm_hide(
        self,
        ctx: Context,
        *,
        member: Member,
    ) -> Message:
        """
        Hide a member from appearing on who knows.
        """

        result = await self.bot.db.execute(
            """
            DELETE FROM lastfm.hidden
            WHERE guild_id = $1
            AND user_id = $2
            """,
            ctx.guild.id,
            member.id,
        )
        if result == "DELETE 0":
            await self.bot.db.execute(
                """
                INSERT INTO lastfm.hidden (guild_id, user_id)
                VALUES ($1, $2)
                """,
                ctx.guild.id,
                member.id,
            )

            return await ctx.approve(f"No longer showing **{member}** on **who knows**")

        return await ctx.approve(
            f"Now allowing **{member}** to appear on **who knows**"
        )

    @lastfm_hide.command(name="list", aliases=["ls"], description="manage guild")
    @has_permissions(manage_guild=True)
    async def lastfm_hide_list(self, ctx: Context) -> Message:
        """
        View all hidden members from zyn's LastFM.
        """

        members = [
            f"{member.mention} (`{member.id}`)"
            for record in await self.bot.db.fetch(
                """
                SELECT user_id
                FROM lastfm.hidden
                WHERE guild_id = $1
                """,
                ctx.guild.id,
            )
            if (member := ctx.guild.get_member(record["user_id"]))
        ]
        if not members:
            return await ctx.warn("No members are hidden")

        paginator = Paginator(
            ctx,
            entries=members,
            embed=Embed(
                title="Hidden Members",
            ),
        )
        return await paginator.start()

    @lastfm.command(
        name="whoknows",
        aliases=["wk"],
        cooldown=WHOKNOWS_COOLDOWN,
        usage="[artist]",
        brief="SZA",
    )
    async def lastfm_whoknows(
        self,
        ctx: Context,
        *,
        artist: str = parameter(
            converter=interface.Artist,
            default=interface.Artist.fallback,
        ),
    ) -> Message:
        """
        View the top listeners of an artist.
        """

        records = await self.bot.db.fetch(
            """
            SELECT user_id, username, plays
            FROM lastfm.artists artist
            WHERE artist = $1
            AND user_id = ANY($3::BIGINT[])
            AND NOT EXISTS (
                SELECT 1
                FROM lastfm.hidden
                WHERE guild_id = $2
                AND user_id = artist.user_id
            )
            ORDER BY plays DESC
            LIMIT 100
            """,
            artist,
            ctx.guild.id,
            [member.id for member in ctx.guild.members],
        )
        listeners: List[str] = []
        crown_holder: Optional[Member] = None

        for record in records:
            member = ctx.guild.get_member(record["user_id"])
            if not member:
                continue

            rank = len(listeners) + 1
            if rank == 1 and len(records) > 1 and record["plays"] >= 5:
                rank = "👑"
                crown_holder = member
            else:
                rank = f"`{rank}`"

            listeners.append(
                f"{rank} [**{member}**](https://last.fm/user/{record['username']}) has {plural(record['plays'], '**'):play}"
            )

        if not listeners:
            return await ctx.warn(
                f"Nobody has listened to **{artist}** yet",
            )

        paginator = Paginator(
            ctx,
            entries=listeners,
            counter=False,
            embed=Embed(
                color=ctx.lastfm.embed_color,
                title=f"Who knows {artist}?",
            ),
        )
        message = await paginator.start()

        if crown_holder:
            await self.claim_crown(ctx, crown_holder, artist)

        return message

    @lastfm.command(
        name="wkalbum",
        aliases=[
            "whoknowsalbum",
            "wka",
        ],
        cooldown=WHOKNOWS_COOLDOWN,
        usage="[album]",
        brief="I Love you.",
    )
    async def lastfm_wkalbum(
        self,
        ctx: Context,
        *,
        album: interface.AlbumSearch = parameter(
            converter=interface.AlbumSearch,
            default=interface.AlbumSearch.fallback,
        ),
    ) -> Message:
        """
        View the top listeners of an album.
        """

        records = await self.bot.db.fetch(
            """
            SELECT user_id, username, plays
            FROM lastfm.albums album
            WHERE album = $1
            AND artist = $2
            AND user_id = ANY($4::BIGINT[])
            AND NOT EXISTS (
                SELECT 1
                FROM lastfm.hidden
                WHERE guild_id = $3
                AND user_id = album.user_id
            )
            ORDER BY plays DESC
            LIMIT 100
            """,
            album.name,
            album.artist,
            ctx.guild.id,
            [member.id for member in ctx.guild.members],
        )
        listeners: List[str] = []

        for record in records:
            member = ctx.guild.get_member(record["user_id"])
            if not member:
                continue

            listeners.append(
                f"[**{member}**](https://last.fm/user/{record['username']}) has {plural(record['plays'], '**'):play}"
            )

        if not listeners:
            return await ctx.warn(
                f"Nobody has listened to **{album}** by **{album.artist}** yet"
            )

        paginator = Paginator(
            ctx,
            entries=listeners,
            embed=Embed(
                color=ctx.lastfm.embed_color,
                title=f"Who knows {shorten(album.name)} by {album.artist}?",
            ),
        )
        return await paginator.start()

    @lastfm.command(
        name="wktrack",
        aliases=[
            "whoknowstrack",
            "wkt",
        ],
        cooldown=WHOKNOWS_COOLDOWN,
        usage="[track]",
        brief="I'm God",
    )
    async def lastfm_wktrack(
        self,
        ctx: Context,
        *,
        track: interface.TrackSearch = parameter(
            converter=interface.TrackSearch,
            default=interface.TrackSearch.fallback,
        ),
    ) -> Message:
        """
        View the top listeners of a track.
        """

        records = await self.bot.db.fetch(
            """
            SELECT user_id, username, plays
            FROM lastfm.tracks track
            WHERE track = $1
            AND artist = $2
            AND user_id = ANY($4::BIGINT[])
            AND NOT EXISTS (
                SELECT 1
                FROM lastfm.hidden
                WHERE guild_id = $3
                AND user_id = track.user_id
            )
            ORDER BY plays DESC
            LIMIT 100
            """,
            track.name,
            track.artist,
            ctx.guild.id,
            [member.id for member in ctx.guild.members],
        )
        listeners: List[str] = []

        for record in records:
            member = ctx.guild.get_member(record["user_id"])
            if not member:
                continue

            listeners.append(
                f"[**{member}**](https://last.fm/user/{record['username']}) has {plural(record['plays'], '**'):play}"
            )

        if not listeners:
            return await ctx.warn(
                f"Nobody has listened to **{track}** by **{track.artist}** yet"
            )

        paginator = Paginator(
            ctx,
            entries=listeners,
            embed=Embed(
                color=ctx.lastfm.embed_color,
                title=f"Who knows {shorten(track.name)} by {track.artist}?",
            ),
        )
        return await paginator.start()

    @lastfm.command(
        name="globalwhoknows",
        aliases=["globalwk", "gwk"],
        cooldown=WHOKNOWS_COOLDOWN,
        usage="[artist]",
        brief="SZA",
    )
    async def lastfm_globalwhoknows(
        self,
        ctx: Context,
        *,
        artist: str = parameter(
            converter=interface.Artist,
            default=interface.Artist.fallback,
        ),
    ) -> Message:
        """
        View the top listeners of an artist globally.
        """

        records = await self.bot.db.fetch(
            """
            SELECT user_id, username, plays
            FROM lastfm.artists artist
            WHERE artist = $1
            ORDER BY plays DESC
            LIMIT 100
            """,
            artist,
        )
        listeners: List[str] = []

        for record in records:
            user = self.bot.get_user(record["user_id"])
            if not user:
                continue

            listeners.append(
                f"[**{user}**](https://last.fm/user/{record['username']}) has {plural(record['plays'], '**'):play}"
            )

        if not listeners:
            return await ctx.warn(
                f"Nobody has listened to **{artist}** yet",
            )

        paginator = Paginator(
            ctx,
            entries=listeners,
            embed=Embed(
                color=ctx.lastfm.embed_color,
                title=f"Who knows {artist}?",
            ),
        )
        return await paginator.start()

    @lastfm.command(
        name="globalwkalbum",
        aliases=[
            "globalwka",
            "gwka",
        ],
        cooldown=WHOKNOWS_COOLDOWN,
        usage="[album]",
        brief="I Love you.",
    )
    async def lastfm_globalwkalbum(
        self,
        ctx: Context,
        *,
        album: interface.AlbumSearch = parameter(
            converter=interface.AlbumSearch,
            default=interface.AlbumSearch.fallback,
        ),
    ) -> Message:
        """
        View the top listeners of an album globally.
        """

        records = await self.bot.db.fetch(
            """
            SELECT user_id, username, plays
            FROM lastfm.albums
            WHERE album = $1
            AND artist = $2
            ORDER BY plays DESC
            LIMIT 100
            """,
            album.name,
            album.artist,
        )
        listeners: List[str] = []

        for record in records:
            user = self.bot.get_user(record["user_id"])
            if not user:
                continue

            listeners.append(
                f"[**{user}**](https://last.fm/user/{record['username']}) has {plural(record['plays'], '**'):play}"
            )

        if not listeners:
            return await ctx.warn(
                f"Nobody has listened to **{album}** by **{album.artist}** yet"
            )

        paginator = Paginator(
            ctx,
            entries=listeners,
            embed=Embed(
                color=ctx.lastfm.embed_color,
                title=f"Who knows {shorten(album.name)} by {album.artist}?",
            ),
        )
        return await paginator.start()

    @lastfm.command(
        name="globalwktrack",
        aliases=[
            "globalwkt",
            "gwkt",
        ],
        cooldown=WHOKNOWS_COOLDOWN,
        usage="[track]",
        brief="I'm God",
    )
    async def lastfm_globalwktrack(
        self,
        ctx: Context,
        *,
        track: interface.TrackSearch = parameter(
            converter=interface.TrackSearch,
            default=interface.TrackSearch.fallback,
        ),
    ) -> Message:
        """
        View the top listeners of a track globally.
        """

        records = await self.bot.db.fetch(
            """
            SELECT user_id, username, plays
            FROM lastfm.tracks
            WHERE track = $1
            AND artist = $2
            ORDER BY plays DESC
            LIMIT 100
            """,
            track.name,
            track.artist,
        )
        listeners: List[str] = []

        for record in records:
            user = self.bot.get_user(record["user_id"])
            if not user:
                continue

            listeners.append(
                f"[**{user}**](https://last.fm/user/{record['username']}) has {plural(record['plays'], '**'):play}"
            )

        if not listeners:
            return await ctx.warn(
                f"Nobody has listened to **{track}** by **{track.artist}** yet"
            )

        paginator = Paginator(
            ctx,
            entries=listeners,
            embed=Embed(
                color=ctx.lastfm.embed_color,
                title=f"Who knows {shorten(track.name)} by {track.artist}?",
            ),
        )
        return await paginator.start()

    @lastfm.command(
        name="taste",
        aliases=["compare", "match"],
    )
    async def lastfm_taste(
        self,
        ctx: Context,
        *,
        member: Member,
    ) -> Message:
        """
        Compare your music taste with another member.
        """

        artists = await self.bot.db.fetch(
            """
            SELECT
                author.artist,
                COALESCE(author.plays, 0) AS author_plays,
                COALESCE(member.plays, 0) AS member_plays,
                CASE
                    WHEN author.plays > member.plays THEN '>'
                    WHEN author.plays < member.plays THEN '<'
                    ELSE '='
                END AS symbol
            FROM lastfm.artists AS author
            JOIN lastfm.artists AS member
            ON author.artist = member.artist
            WHERE author.user_id = $1
            AND member.user_id = $2
            ORDER BY author.plays DESC
            """,
            ctx.author.id,
            member.id,
        )
        if not artists:
            return await ctx.warn(
                f"You don't share any artists with **{member}**",
            )

        largest_library = cast(
            int,
            await self.bot.db.fetchval(
                """
                SELECT GREATEST(
                    (
                        SELECT COUNT(*)
                        FROM lastfm.artists
                        WHERE user_id = $1
                    ),
                    (
                        SELECT COUNT(*)
                        FROM lastfm.artists
                        WHERE user_id = $2
                    )
                )
                """,
                ctx.author.id,
                member.id,
            ),
        )
        entries: List[str] = []
        for artist in artists[:10]:
            name = shorten(artist["artist"], 16)
            padding = " " * (20 - len(name))

            entries.append(
                f"{artist['artist']}{padding} {artist['author_plays']:,} {artist['symbol']} {artist['member_plays']:,}"
            )

        embed = Embed(
            color=ctx.lastfm.embed_color,
            title=f"Comparision between {ctx.author.display_name} and {member.display_name}",
            description=(
                f"You both share {plural(len(artists), '**'):artist} (`{len(artists) / largest_library:.2%}`)\n>>> "
                + codeblock("\n".join(entries))
            ),
        )
        return await ctx.send(embed=embed)

    @command(aliases=["sp"], usage="[song]", brief="Good Days")
    async def spotify(
        self,
        ctx: Context,
        *,
        query: Optional[str] = None,
    ) -> Message:
        """
        Search a query on Spotify.
        """

        async with ctx.typing():
            if not query:
                username = cast(
                    Optional[str],
                    await self.bot.db.fetchval(
                        """
                        SELECT username
                        FROM lastfm.config
                        WHERE user_id = $1
                        """,
                        ctx.author.id,
                    ),
                )
                if not username:
                    return await ctx.send_help(ctx.command)

                recent_tracks = await lastfm.user.RecentTracks.fetch(username)
                if not recent_tracks:
                    return await ctx.send_help(ctx.command)

                track = recent_tracks[0]
                query = f"{track} - {track.artist}"

            tracks = await self.spotify_client.search_tracks(query, 10)
            if not tracks:
                return await ctx.warn(f"No results found for **{query}**")

            paginator = Paginator(
                ctx,
                entries=[track.link for track in tracks],
            )
            return await paginator.start()
