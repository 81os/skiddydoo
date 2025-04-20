from __future__ import annotations
import asyncio
from datetime import timedelta
from typing import List, Optional, cast, TYPE_CHECKING

import arrow
from asyncpg import UniqueViolationError
from discord import Embed, HTTPException, Message, TextChannel
from discord.ext.commands import group, has_permissions, parameter
from discord.ext.tasks import loop
from discord.utils import format_dt
from humanfriendly import format_timespan

from tools import CompositeMetaClass, MixinMeta
from tools.client import Context
from tools.conversion import Duration
from tools.formatter import codeblock, plural, vowel
from tools.paginator import Paginator
from tools.parser import Script

if TYPE_CHECKING:
    from cogs.moderation.moderation import Moderation


class Timer(MixinMeta, metaclass=CompositeMetaClass):
    """
    Schedule messages to be sent with an interval.
    """

    async def cog_load(self) -> None:
        self.post_timers.start()
        self.purge_channels.start()
        return await super().cog_load()

    async def cog_unload(self) -> None:
        self.post_timers.cancel()
        self.purge_channels.cancel()
        return await super().cog_unload()

    @loop(minutes=1)
    async def post_timers(self) -> None:
        """
        Post all scheduled messages.
        """

        records = await self.bot.db.fetch(
            """
            SELECT *
            FROM timer.message
            WHERE next_trigger < NOW()
            """
        )

        scheduled_deletion: List[int] = []
        for record in records:
            channel_id = cast(
                int,
                record["channel_id"],
            )
            channel = cast(
                Optional[TextChannel],
                self.bot.get_channel(channel_id),
            )
            if not channel:
                scheduled_deletion.append(channel_id)
                continue

            script = Script(
                record["template"],
                [channel.guild, channel],
            )
            try:
                await script.send(channel)
            except HTTPException:
                scheduled_deletion.append(channel_id)
                continue

            await self.bot.db.execute(
                """
                UPDATE timer.message
                SET next_trigger = NOW() + INTERVAL '1 second' * interval
                WHERE guild_id = $1
                AND channel_id = $2
                """,
                record["guild_id"],
                record["channel_id"],
            )

        if scheduled_deletion:
            await self.bot.db.execute(
                """
                DELETE FROM timer.message
                WHERE channel_id = ANY($1::BIGINT[])
                """,
                scheduled_deletion,
            )

    @loop(minutes=5)
    async def purge_channels(self) -> None:
        """
        Purge all scheduled channels.
        """

        records = await self.bot.db.fetch(
            """
            SELECT *
            FROM timer.purge
            WHERE next_trigger < NOW()
            """
        )

        scheduled_deletion: List[int] = []
        for record in records:
            channel_id = cast(
                int,
                record["channel_id"],
            )
            channel = cast(
                Optional[TextChannel],
                self.bot.get_channel(channel_id),
            )
            if not channel:
                scheduled_deletion.append(channel_id)
                continue

            new_channel: Optional[TextChannel] = None
            try:
                if record["method"] == "purge":
                    limit = 1_000
                    if record["interval"] >= 86_400:
                        limit = 5_000
                    elif record["interval"] >= 604_800:
                        limit = 10_000

                    await channel.purge(
                        limit=limit,
                        oldest_first=True,
                        check=lambda message: not message.pinned,
                        after=arrow.utcnow().shift(days=-13.5).naive,
                    )
                elif record["method"] == "nuke":
                    cog = cast(Moderation, self.bot.get_cog("Moderation"))
                    new_channel = await channel.clone(
                        reason=f"Automated nuke ({format_timespan(record['interval'])})"
                    )
                    if cog:
                        await cog.reconfigure_settings(
                            channel.guild, channel, new_channel
                        )

                    await asyncio.gather(
                        *[
                            new_channel.edit(position=channel.position),
                            channel.delete(
                                reason=f"Automated nuke ({format_timespan(record['interval'])})"
                            ),
                        ]
                    )

            except HTTPException:
                scheduled_deletion.append(channel_id)
                continue

            await self.bot.db.execute(
                """
                UPDATE timer.purge
                SET next_trigger = NOW() + INTERVAL '1 second' * interval
                WHERE guild_id = $1
                AND channel_id = $2
                """,
                record["guild_id"],
                new_channel.id if new_channel else record["channel_id"],
            )

        if scheduled_deletion:
            await self.bot.db.execute(
                """
                DELETE FROM timer.purge
                WHERE channel_id = ANY($1::BIGINT[])
                """,
                scheduled_deletion,
            )

    @group(
        aliases=["automessage", "automsg", "timers", "reminder"],
        invoke_without_command=True,
        description="manage channels",
    )
    @has_permissions(manage_channels=True)
    async def timer(self, ctx: Context) -> Message:
        """
        Post recurring messages with an interval.
        """

        return await ctx.send_help(ctx.command)

    @timer.command(
        name="add",
        aliases=["create", "new"],
        description="manage channels",
        usage="<channel> <interval> <script>",
        brief="#fortnite-updates 10d Fortnite update",
    )
    @has_permissions(manage_channels=True)
    async def timer_add(
        self,
        ctx: Context,
        channel: TextChannel,
        interval: timedelta = parameter(
            converter=Duration(
                min=timedelta(minutes=30),
                max=timedelta(days=7),
            ),
        ),
        *,
        script: Script,
    ) -> Message:
        """
        Add a new recurring message.
        """

        try:
            await self.bot.db.execute(
                """
                INSERT INTO timer.message (
                    guild_id,
                    channel_id,
                    template,
                    interval,
                    next_trigger
                )
                VALUES ($1, $2, $3, $4, $5)
                """,
                ctx.guild.id,
                channel.id,
                script.template,
                interval.total_seconds(),
                ctx.message.created_at + interval,
            )
        except UniqueViolationError:
            return await ctx.warn(
                f"A timer for {channel.mention} already exists",
                f"Use `{ctx.clean_prefix}timer remove` to remove it",
            )

        await script.send(channel)
        return await ctx.approve(
            f"Now posting {vowel(script.format)} message in {channel.mention} every **{format_timespan(interval)}**"
        )

    @timer.command(
        name="remove",
        aliases=[
            "delete",
            "del",
            "rm",
            "cancel",
        ],
        description="manage channels",
        usage="<channel>",
        brief="#fortnite-updates",
    )
    @has_permissions(manage_channels=True)
    async def timer_remove(self, ctx: Context, channel: TextChannel) -> Message:
        """
        Remove an existing recurring message.
        """

        result = await self.bot.db.execute(
            """
            DELETE FROM timer.message
            WHERE guild_id = $1
            AND channel_id = $2
            """,
            ctx.guild.id,
            channel.id,
        )
        if result == "DELETE 0":
            return await ctx.warn(
                f"A timer for {channel.mention} doesn't exist",
            )

        return await ctx.approve(f"Removed the timer for {channel.mention}")

    @timer.command(
        name="view",
        aliases=["show"],
        description="manage channels",
        usage="<channel>",
        brief="#fortnite-updates",
    )
    @has_permissions(manage_channels=True)
    async def timer_view(self, ctx: Context, channel: TextChannel) -> Message:
        """
        View an existing recurring message.
        """

        record = await self.bot.db.fetchrow(
            """
            SELECT *
            FROM timer.message
            WHERE guild_id = $1
            AND channel_id = $2
            """,
            ctx.guild.id,
            channel.id,
        )
        if not record:
            return await ctx.warn(
                f"A timer for {channel.mention} doesn't exist",
            )

        script = Script(record["template"], [ctx.guild, ctx.author, channel])
        embed = Embed(
            title=f"Timer for {channel}",
            description=codeblock(script.template),
        )
        embed.add_field(
            name="**Interval**",
            value="\n> ".join(
                [
                    f"Every **{format_timespan(record['interval'])}**",
                    f"Next post: {format_dt(record['next_trigger'], 'R')}",
                ]
            ),
        )

        await ctx.reply(embed=embed)
        return await script.send(ctx.channel)

    @timer.command(
        name="clear", aliases=["clean", "reset"], description="manage channels"
    )
    @has_permissions(manage_channels=True)
    async def timer_clear(self, ctx: Context) -> Message:
        """
        Remove all recurring messages.
        """

        await ctx.prompt(
            "Are you sure you want to remove all timers?",
        )

        result = await self.bot.db.execute(
            """
            DELETE FROM timer.message
            WHERE guild_id = $1
            """,
            ctx.guild.id,
        )
        if result == "DELETE 0":
            return await ctx.warn("No timers exist for this server")

        return await ctx.approve(
            f"Successfully  removed {plural(result, md='`'):timer}"
        )

    @timer.command(name="list", aliases=["ls"], description="manage channels")
    @has_permissions(manage_channels=True)
    async def timer_list(self, ctx: Context) -> Message:
        """
        View all recurring messages.
        """

        channels = [
            f"{channel.mention} (`{channel.id}`) - **{format_timespan(record['interval'])}**"
            for record in await self.bot.db.fetch(
                """
                SELECT channel_id, interval
                FROM timer.message
                WHERE guild_id = $1
                """,
                ctx.guild.id,
            )
            if (channel := ctx.guild.get_channel(record["channel_id"]))
        ]
        if not channels:
            return await ctx.warn("No timers exist for this server")

        paginator = Paginator(
            ctx,
            entries=channels,
            embed=Embed(title="Timers"),
        )
        return await paginator.start()

    @timer.group(
        name="purge",
        aliases=["nuke"],
        brief="#timers 60s",
        description="manage messages, manage channels",
        invoke_without_command=True,
    )
    @has_permissions(manage_channels=True, manage_messages=True)
    async def timer_purge(
        self,
        ctx: Context,
        channel: TextChannel,
        interval: timedelta = parameter(
            converter=Duration(
                min=timedelta(hours=1),
                max=timedelta(days=7),
            ),
        ),
    ) -> Message:
        """
        Automatically purge a channel.
        """

        try:
            await self.bot.db.execute(
                """
                INSERT INTO timer.purge (
                    guild_id,
                    channel_id,
                    interval,
                    next_trigger,
                    method
                )
                VALUES ($1, $2, $3, $4, $5)
                """,
                ctx.guild.id,
                channel.id,
                interval.total_seconds(),
                ctx.message.created_at + interval,
                ctx.invoked_with,
            )
        except UniqueViolationError:
            return await ctx.warn(
                f"An automated purge for {channel.mention} already exists"
                f"Use `{ctx.clean_prefix}timer purge remove` to remove it",
            )

        return await ctx.approve(
            f"Now automatically **{(ctx.invoked_with or '')[:-1]}ing** {channel.mention} every **{format_timespan(interval)}**"
        )

    @timer_purge.command(
        name="remove",
        aliases=[
            "delete",
            "del",
            "rm",
            "cancel",
        ],
        description="manage channels & messages",
        usage="<channel>",
        brief="#auto-delete",
    )
    @has_permissions(manage_channels=True, manage_messages=True)
    async def timer_purge_remove(
        self,
        ctx: Context,
        channel: TextChannel,
    ) -> Message:
        """
        Remove an automated channel purge.
        """

        result = await self.bot.db.execute(
            """
            DELETE FROM timer.purge
            WHERE guild_id = $1
            AND channel_id = $2
            """,
            ctx.guild.id,
            channel.id,
        )
        if result == "DELETE 0":
            return await ctx.warn(
                f"An automated purge for {channel.mention} doesn't exist",
            )

        return await ctx.approve(f"Removed the automated purge for {channel.mention}")

    @timer_purge.command(
        name="view",
        aliases=["show"],
        description="manage channels & messages",
        usage="<channel>",
        brief="#fortnite-updates",
    )
    @has_permissions(manage_channels=True, manage_messages=True)
    async def timer_purge_view(
        self,
        ctx: Context,
        channel: TextChannel,
    ) -> Message:
        """
        View an automated channel purge.
        """

        record = await self.bot.db.fetchrow(
            """
            SELECT *
            FROM timer.purge
            WHERE guild_id = $1
            AND channel_id = $2
            """,
            ctx.guild.id,
            channel.id,
        )
        if not record:
            return await ctx.warn(
                f"An automated purge for {channel.mention} doesn't exist",
            )

        embed = Embed(title=f"Automated {record['method']} for {channel}")
        embed.add_field(
            name="**Interval**",
            value="\n> ".join(
                [
                    f"Every **{format_timespan(record['interval'])}**",
                    f"Next {record['method']}: {format_dt(record['next_trigger'], 'R')}",
                ]
            ),
        )

        return await ctx.reply(embed=embed)

    @timer_purge.command(
        name="clear",
        aliases=["clean", "reset"],
        description="manage channels & messages",
    )
    @has_permissions(manage_channels=True, manage_messages=True)
    async def timer_purge_clear(self, ctx: Context) -> Message:
        """
        Remove all automated channel purges.
        """

        await ctx.prompt(
            "Are you sure you want to remove all automated purges?",
        )

        result = await self.bot.db.execute(
            """
            DELETE FROM timer.purge
            WHERE guild_id = $1
            """,
            ctx.guild.id,
        )
        if result == "DELETE 0":
            return await ctx.warn("No automated purges exist for this server")

        return await ctx.approve(
            f"Successfully  removed {plural(result, md='`'):automated purge}"
        )

    @timer_purge.command(
        name="list", aliases=["ls"], description="manage channels & messages"
    )
    @has_permissions(manage_channels=True, manage_messages=True)
    async def timer_purge_list(self, ctx: Context) -> Message:
        """
        View all automated channel purges.
        """

        channels = [
            f"{channel.mention} (`{channel.id}`) - **{format_timespan(record['interval'])}** (`{record['method']}`)"
            for record in await self.bot.db.fetch(
                """
                SELECT channel_id, interval, method
                FROM timer.purge
                WHERE guild_id = $1
                """,
                ctx.guild.id,
            )
            if (channel := ctx.guild.get_channel(record["channel_id"]))
        ]
        if not channels:
            return await ctx.warn("No automated purges exist for this server")

        paginator = Paginator(
            ctx,
            entries=channels,
            embed=Embed(title="Automated Purges"),
        )
        return await paginator.start()
