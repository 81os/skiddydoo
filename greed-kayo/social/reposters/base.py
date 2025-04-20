from __future__ import annotations

import asyncio
import re
from contextlib import suppress
from io import BytesIO
from logging import getLogger
from typing import TYPE_CHECKING, List, Optional, TypedDict, cast

from aiohttp import ClientPayloadError
from colorama import Fore, Style
from discord import HTTPException, Message
from discord.ext.commands import BadArgument
from discord.http import Route
from discord.utils import find

import config
from cogs.social.reposters.extraction import Information, download
from main import zyn
from tools.client import Context

if TYPE_CHECKING:
    from cogs.social.social import Social

log = getLogger("zyn/social")


class ReposterSettings(TypedDict):
    reposter_prefix: bool
    disabled: bool


class Reposter:
    """
    Base class for all Social Reposters.
    """

    bot: zyn
    name: str
    regex: List[str]

    def __init__(
        self,
        bot: zyn,
        *,
        name: str = "",
        regex: List[str] = [],
        add_listener: bool = True,
    ):
        self.bot = bot
        self.name = name
        self.regex = regex
        if add_listener:
            self.bot.add_listener(self.listener, "on_message_without_command")

    def __str__(self) -> str:
        return self.name

    def __repr__(self) -> str:
        return f"<Reposter name={self.name!r} regex={self.regex!r}>"

    async def dispatch(
        self,
        ctx: Context,
        data: Information,
        buffer: Optional[BytesIO] = None,
    ) -> Message:
        """
        The embed dispatcher.
        """

        raise NotImplementedError

    async def nsfw_error(
        self,
        ctx: Context,
        data: Information,
    ) -> Message:
        """
        The nsfw error dispatcher.
        """

        return await ctx.warn(
            f"That [**{self.name}**]({data.webpage_url}) post is marked as **NSFW**!",
            "You can only view it in **NSFW channels**",
        )

    def match(self, url: str) -> Optional[re.Match[str]]:
        """
        Match the given url against the regex.
        """

        for pattern in self.regex:
            if match := re.search(pattern, url):
                return match

    async def fetch(self, url: str) -> Optional[Information]:
        """
        Fetch the information from the given url.
        """

        return await download(url)

    async def listener(self, ctx: Context) -> Optional[Message]:
        """
        Listener for the reposters regex.
        """

        if ctx.author.bot or not (url := self.match(ctx.message.content)):
            return

        record: Optional[ReposterSettings] = await self.bot.db.fetchrow(
            """
            SELECT
                s.reposter_prefix,
                rd.channel_id IS NOT NULL AS disabled
            FROM
                settings AS s
            LEFT JOIN
                reposters.disabled rd ON rd.guild_id = s.guild_id AND rd.channel_id = $2 AND rd.reposter = $3
            WHERE
                s.guild_id = $1
            """,
            ctx.guild.id,
            ctx.channel.id,
            self.name,
        )
        if record:
            if record["reposter_prefix"] and not ctx.message.content.lower().startswith(
                (
                    "zyn",
                    ctx.guild.me.display_name,
                )
            ):
                return

            elif record["disabled"]:
                return

        key = f"reposter:{ctx.channel.id}"
        if await self.bot.redis.ratelimited(key, 2, 8):
            return

        async with ctx.typing():
            try:
                data = await asyncio.wait_for(self.fetch(url[0]), timeout=15)
            except asyncio.TimeoutError:
                data = None

            if not data:
                return await ctx.warn(
                    f"That [**{self.name}**]({url[0]}) post could not be found!",
                    delete_after=3,
                )

            elif (
                hasattr(data, "age_limit")
                and data.age_limit == 18
                and hasattr(ctx.channel, "is_nsfw")
                and not ctx.channel.is_nsfw()  # type: ignore
            ):
                return await self.nsfw_error(ctx, data)

            log.info(
                f" {Fore.RESET}".join(
                    [
                        f"Reposting {Fore.LIGHTCYAN_EX}{Style.BRIGHT}{self.name}{Style.NORMAL}",
                        f"post {Fore.LIGHTRED_EX}{data.id}",
                        f"from {Fore.LIGHTMAGENTA_EX}{ctx.author}",
                        f"@ {Fore.LIGHTYELLOW_EX}{ctx.guild}",
                        f"/ {Fore.LIGHTBLUE_EX}{ctx.channel}{Fore.RESET}.",
                    ]
                )
            )
            buffer: Optional[bytes] = None
            if hasattr(data, "url") and data.url:
                if hasattr(data, "duration") and data.duration and data.duration > 600:
                    return await ctx.warn(
                        f"That [**{self.name}**]({data.webpage_url}) post is too long to repost!",
                        delete_after=3,
                    )

                response = await self.bot.session.get(
                    data.url,
                    headers=(
                        data.http_headers.dict()
                        if hasattr(data, "http_headers") and data.http_headers
                        else {}
                    ),
                    proxy=config.WARP,
                )
                if not response.ok:
                    return await ctx.warn(
                        f"Failed to fetch that [**{self.name}**]({data.webpage_url}) post!",
                        delete_after=3,
                    )

                try:
                    buffer = await response.read()
                except ClientPayloadError:
                    return await ctx.warn(
                        f"Failed to read the buffer for that [**{self.name}**]({data.webpage_url}) post!",
                        f"This is more than likely an issue with **{self.name}** which we have no control over",
                        delete_after=3,
                    )

                if len(buffer) >= ctx.guild.filesize_limit:
                    return await ctx.warn(
                        f"That [**{self.name}**]({data.webpage_url}) post is too large to repost!",
                        delete_after=3,
                    )

            try:
                await self.dispatch(
                    ctx,
                    data,
                    BytesIO(buffer) if buffer else None,
                )
            except HTTPException:
                return

        with suppress(HTTPException):
            if ctx.settings.reposter_delete:
                await ctx.message.delete()

            elif ctx.message.embeds:
                await self.bot.http.request(
                    Route(
                        "PATCH",
                        f"/channels/{ctx.channel.id}/messages/{ctx.message.id}",
                    ),
                    json={"flags": 4},  # removes embeds...
                )

    @classmethod
    async def convert(cls, ctx: Context, argument: str) -> Reposter:
        social = cast(
            Optional["Social"],
            ctx.bot.get_cog("Social"),
        )
        if not social:
            raise ValueError("Social cog is not loaded.")

        reposter = find(
            lambda reposter: reposter.name.lower() == argument.lower(),
            social.reposters,
        )
        if not reposter:
            raise BadArgument(f"Reposter `{argument}` not found!")

        return reposter
