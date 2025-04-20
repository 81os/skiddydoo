import asyncio
import re
from textwrap import shorten
from typing import List, TypedDict
from asyncpg import UniqueViolationError
from tools import CompositeMetaClass, MixinMeta
from tools.client.context import Context

from discord.ext.commands import Cog, group, Range
from discord.utils import escape_mentions, escape_markdown, format_dt
from discord import (
    Color,
    DMChannel,
    Embed,
    Forbidden,
    GroupChannel,
    Member,
    Message,
    PartialMessageable,
)
from logging import getLogger

from tools.formatter import plural
from tools.paginator import Paginator

log = getLogger("zyn/highlight")


class HighlightRecord(TypedDict):
    guild_id: int
    user_id: int
    word: str


class Highlight(MixinMeta, metaclass=CompositeMetaClass):
    """
    Receive keyword notifications.
    """

    @Cog.listener("on_message")
    async def highlight_listener(self, message: Message) -> None:
        if not message.guild or message.author.bot:
            return

        records: List[HighlightRecord] = [
            record
            for record in await self.bot.db.fetch(
                """
                SELECT DISTINCT ON (user_id) *
                FROM highlights
                WHERE guild_id = $1
                AND POSITION(word IN $2) > 0
                """,
                message.guild.id,
                message.content.lower(),
            )
            if record["user_id"] != message.author.id
            and (member := message.guild.get_member(record["user_id"]))
            and message.channel.permissions_for(member).view_channel
        ]
        if not records:
            return

        for record in records:
            if record["word"] not in message.content.lower():
                continue

            member = message.guild.get_member(record["user_id"])
            if member:
                self.bot.dispatch("highlight_dispatch", message, member, record["word"])

    @Cog.listener()
    async def on_highlight_dispatch(
        self,
        message: Message,
        member: Member,
        keyword: str,
    ) -> None:
        """
        Dispatch a highlight notification.
        """

        if member in message.mentions:
            return

        elif isinstance(message.channel, (DMChannel, GroupChannel, PartialMessageable)):
            return

        if await self.bot.redis.ratelimited(
            f"highlight:{message.channel.id}:{member.id}",
            limit=1,
            timespan=30,
        ):
            return

        try:
            await self.bot.wait_for(
                "member_activity",
                check=lambda channel, _member: channel == message.channel
                and _member == member,
                timeout=10,
            )
        except asyncio.TimeoutError:
            ...
        else:
            return

        embed = Embed(
            color=Color.dark_embed(),
        )
        embed.set_author(
            name=f"highlight by {message.author.display_name} • {message.guild}",
            icon_url=message.author.display_avatar,
        )
        embed.description = f"Keyword [*`{escape_markdown(keyword)}`*]({message.jump_url}) was said in {message.jump_url}\n>>> "

        messages: List[str] = []
        pattern = re.compile(re.escape(keyword), re.IGNORECASE)

        for message in sorted(
            [
                message
                async for message in message.channel.history(
                    limit=5,
                    around=message,
                )
            ],
            key=lambda m: m.created_at,
        ):
            if not message.content:
                continue

            content = shorten(
                escape_markdown(message.content),
                width=50,
                placeholder="..",
            )
            if keyword in message.content.lower():
                content = pattern.sub("__\\g<0>__", message.content)

            fmt_dt = format_dt(message.created_at, "T")
            messages.append(
                f"[{fmt_dt}]({message.jump_url}) **{escape_markdown(message.author.name)}:** {content}"
            )

        if not messages or not any("__" in message for message in messages):
            return

        embed.description += "\n".join(messages)

        try:
            await member.send(embed=embed)
        except Forbidden:
            await self.bot.db.execute(
                """
                DELETE FROM highlights
                AND user_id = $1
                """,
                member.id,
            )

    @group(
        aliases=["hl", "snitch"],
        invoke_without_command=True,
    )
    async def highlight(self, ctx: Context) -> Message:
        """
        Receive keyword notifications.
        """

        return await ctx.send_help(ctx.command)

    @highlight.command(name="add", aliases=["create"], usage="<word>", brief="really?")
    async def highlight_add(self, ctx: Context, *, word: Range[str, 2, 32]) -> Message:
        """
        Add a keyword to highlight.
        """

        word = word.lower()
        if escape_mentions(word) != word:
            return await ctx.warn("Mentions cannot be used in your highlights")

        try:
            await self.bot.db.execute(
                """
                INSERT INTO highlights (guild_id, user_id, word)
                VALUES ($1, $2, $3)
                """,
                ctx.guild.id,
                ctx.author.id,
                word,
            )
        except UniqueViolationError:
            return await ctx.warn(
                f"You're already receiving notifications for `{word}`"
            )

        return await ctx.approve(f"You will now receive notifications for `{word}`")

    @highlight.command(
        name="remove", aliases=["delete", "del", "rm"], usage="<word>", brief="really?"
    )
    async def highlight_remove(self, ctx: Context, *, word: str) -> Message:
        """
        Remove a keyword from your highlights.
        """

        word = word.lower()
        result = await self.bot.db.execute(
            """
            DELETE FROM highlights
            WHERE guild_id = $1
            AND user_id = $2
            AND word = $3
            """,
            ctx.guild.id,
            ctx.author.id,
            word,
        )
        if result == "DELETE 0":
            return await ctx.warn(f"You're not receiving notifications for `{word}`")

        return await ctx.approve(
            f"You will no longer receive notifications for `{word}`"
        )

    @highlight.command(
        name="clear",
        aliases=["clean", "reset"],
    )
    async def highlight_clear(self, ctx: Context) -> Message:
        """
        Remove all your keyword highlights.
        """

        await ctx.prompt(
            "Are you sure you want to remove all keywords?",
        )

        result = await self.bot.db.execute(
            """
            DELETE FROM highlights
            WHERE guild_id = $1
            AND user_id = $2
            """,
            ctx.guild.id,
            ctx.author.id,
        )
        if result == "DELETE 0":
            return await ctx.warn("You don't have any highlights!")

        return await ctx.approve(
            f"Successfully  removed {plural(result, md='`'):keyword highlight}"
        )

    @highlight.command(
        name="list",
        aliases=["ls"],
    )
    async def highlight_list(self, ctx: Context) -> Message:
        """
        View all your keyword highlights.
        """

        keywords = [
            f"**{record['word']}**"
            for record in await self.bot.db.fetch(
                """
                SELECT word
                FROM highlights
                WHERE guild_id = $1
                """,
                ctx.guild.id,
            )
        ]
        if not keywords:
            return await ctx.warn("You have not setup any highlights")

        paginator = Paginator(
            ctx,
            entries=keywords,
            embed=Embed(title="Keyword Highlights"),
        )
        return await paginator.start()
