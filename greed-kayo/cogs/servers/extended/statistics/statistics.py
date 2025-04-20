from __future__ import annotations

import re
from datetime import timedelta
from logging import getLogger
from typing import List, Literal, Optional, Union, cast

from discord import (
    CategoryChannel,
    Embed,
    ForumChannel,
    HTTPException,
    Message,
    RateLimited,
    StageChannel,
    TextChannel,
    VoiceChannel,
)
from discord.ext.commands import group, has_permissions
from discord.ext.tasks import loop
from discord.utils import utcnow
from humanfriendly import format_timespan

from tools import CompositeMetaClass, MixinMeta
from tools.client import Context
from tools.formatter import plural
from tools.paginator import Paginator

log = getLogger("zyn/counter")
ALLOWED_CHANNEL = Union[
    TextChannel, CategoryChannel, VoiceChannel, StageChannel, ForumChannel
]
NUMBER_PATTERN = r"\d{1,3}(,\d{3})*"


class Statistics(MixinMeta, metaclass=CompositeMetaClass):
    """
    Set channels to display server statistics.
    """

    async def cog_load(self) -> None:
        self.update_statistics.start()
        return await super().cog_load()

    async def cog_unload(self) -> None:
        self.update_statistics.cancel()
        return await super().cog_unload()

    @loop(minutes=10)
    async def update_statistics(self) -> None:
        """
        Update all statistic channels.
        """

        records = await self.bot.db.fetch(
            """
            SELECT channel_id, option
            FROM counter
            WHERE last_update < NOW() - INTERVAL '10 minutes'
            AND (rate_limited_until IS NULL OR rate_limited_until < NOW())
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

            option = cast(
                Literal["members", "boosts"],
                record["option"],
            )
            if option == "members":
                value = len(channel.guild.members)

            elif option == "boosts":
                value = channel.guild.premium_subscription_count

            else:
                continue

            if not re.search(NUMBER_PATTERN, channel.name):
                name = f"{channel.name} {value:,}"

            else:
                name = re.sub(NUMBER_PATTERN, f"{value:,}", channel.name)

            if channel.name == name:
                continue

            try:
                await channel.edit(
                    name=name,
                    reason=f"Updated {option} counter",
                )
            except RateLimited as exc:
                log.warning(
                    "Rate limited for %s while updating %s counter in %s (%s).",
                    format_timespan(exc.retry_after),
                    option,
                    channel.guild,
                    channel.guild.id,
                )
                await self.bot.db.execute(
                    """
                    UPDATE counter
                    SET rate_limited_until = $2
                    WHERE channel_id = $1
                    """,
                    channel_id,
                    utcnow() + timedelta(seconds=exc.retry_after),
                )

            except HTTPException:
                log.warning(
                    "Failed to update %s counter in %s (%s).",
                    option,
                    channel.guild,
                    channel.guild.id,
                )
                scheduled_deletion.append(channel_id)

            else:
                await self.bot.db.execute(
                    """
                    UPDATE counter
                    SET last_update = NOW()
                    WHERE channel_id = $1
                    """,
                    channel_id,
                )

        if scheduled_deletion:
            await self.bot.db.execute(
                """
                DELETE FROM counter
                WHERE channel_id = ANY($1::BIGINT[])
                """,
                scheduled_deletion,
            )

    @group(
        aliases=["counter", "stats"],
        invoke_without_command=True,
    )
    @has_permissions(manage_channels=True)
    async def statistics(self, ctx: Context) -> Message:
        """
        Set channels to display server statistics such as member and boost count.
        """

        return await ctx.send_help(ctx.command)

    @statistics.command(
        name="set",
        aliases=["add", "create"],
        description="manage channels",
        usage="<option|members|boosts>",
        brief="members",
    )
    @has_permissions(manage_channels=True)
    async def statistics_set(
        self,
        ctx: Context,
        option: Literal["members", "boosts"],
        *,
        channel: ALLOWED_CHANNEL,
    ) -> Message:
        """
        Set a channel to display server statistics.
        """

        counter_id = cast(
            Optional[int],
            await self.bot.db.fetchval(
                """
                SELECT channel_id
                FROM counter
                WHERE guild_id = $1
                AND option = $2
                """,
                ctx.guild.id,
                option,
            ),
        )
        if counter_id:
            counter = ctx.guild.get_channel(counter_id)
            if counter:
                return await ctx.warn(
                    f"The counter for `{option}` is already being displayed on [`{counter}`]({counter.jump_url})"
                )

            await self.bot.db.execute(
                """
                DELETE FROM counter
                WHERE guild_id = $1
                AND option = $2
                """,
                ctx.guild.id,
                option,
            )

        try:
            await channel.edit(
                name=f"{option.title()}: {(len(ctx.guild.members) if option == 'members' else ctx.guild.premium_subscription_count):,}",
                reason=f"Set as {option} counter by {ctx.author} ({ctx.author.id})",
            )
        except RateLimited as exc:
            return await ctx.warn(
                f"Rate limited while setting `{option}` counter on [`{channel}`]({channel.jump_url})",
                f"Please wait **{format_timespan(int(exc.retry_after))}** before trying again",
            )

        await self.bot.db.execute(
            """
            INSERT INTO counter (guild_id, channel_id, option)
            VALUES ($1, $2, $3)
            ON CONFLICT (guild_id, channel_id)
            DO UPDATE SET option = EXCLUDED.option
            """,
            ctx.guild.id,
            channel.id,
            option,
        )

        return await ctx.approve(
            f"Now displaying `{option}` on [`{channel}`]({channel.jump_url})"
        )

    @statistics.command(
        name="remove",
        aliases=["delete", "del", "rm"],
        description="manage channels",
        usage="<channel>",
        brief="1251659791856828426",
    )
    @has_permissions(manage_channels=True)
    async def statistics_remove(
        self,
        ctx: Context,
        *,
        channel: ALLOWED_CHANNEL,
    ) -> Message:
        """
        Remove a channel from displaying server statistics.
        """

        result = await self.bot.db.execute(
            """
            DELETE FROM counter
            WHERE guild_id = $1
            AND channel_id = $2
            """,
            ctx.guild.id,
            channel.id,
        )
        if result == "DELETE 0":
            return await ctx.warn(
                f"The channel [`{channel}`]({channel.jump_url}) is not displaying any statistics"
            )

        return await ctx.approve(
            f"No longer displaying statistics on [`{channel}`]({channel.jump_url})"
        )

    @statistics.command(
        name="clear", aliases=["clean", "reset"], description="manage channels"
    )
    @has_permissions(manage_channels=True)
    async def statistics_clear(self, ctx: Context) -> Message:
        """
        Remove all channels from displaying server statistics.
        """

        await ctx.prompt(
            "Are you sure you want to remove all counter channels?",
        )

        result = await self.bot.db.execute(
            """
            DELETE FROM counter
            WHERE guild_id = $1
            """,
            ctx.guild.id,
        )
        if result == "DELETE 0":
            return await ctx.warn("No counter channels exist for this server")

        return await ctx.approve(
            f"Successfully removed {plural(result, md='`'):counter channel}"
        )

    @statistics.command(name="list", aliases=["ls"], description="manage channels")
    @has_permissions(manage_channels=True)
    async def statistics_list(self, ctx: Context) -> Message:
        """
        View all channels displaying server statistics.
        """

        channels = [
            f"[`{channel}`]({channel.jump_url}) - {record['option'].title()}"
            for record in await self.bot.db.fetch(
                """
                SELECT channel_id, option
                FROM counter
                WHERE guild_id = $1
                """,
                ctx.guild.id,
            )
            if (channel := ctx.guild.get_channel(record["channel_id"]))
        ]
        if not channels:
            return await ctx.warn("No counter channels exist for this server")

        paginator = Paginator(
            ctx,
            entries=channels,
            embed=Embed(title="Counter Channels"),
        )
        return await paginator.start()
