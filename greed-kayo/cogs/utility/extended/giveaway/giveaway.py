from contextlib import suppress
from datetime import datetime, timedelta, timezone
from logging import getLogger
from typing import List, Optional, cast

from discord import Embed, HTTPException, Message, TextChannel
from discord.ext.commands import group, hybrid_group, has_permissions, parameter
from discord.ext.tasks import loop

from tools import CompositeMetaClass, MixinMeta
from tools.client import Context
from tools.conversion import Duration
from tools.paginator import Paginator

from .models import GiveawayEntry

log = getLogger("zyn/giveaway")


class Giveaway(MixinMeta, metaclass=CompositeMetaClass):
    """
    Various giveaway commands, including starting, ending, and rerolling giveaways.
    """

    async def cog_load(self) -> None:
        self.check_giveaways.start()
        return await super().cog_load()

    async def cog_unload(self) -> None:
        self.check_giveaways.cancel()
        return await super().cog_unload()

    @loop(seconds=15)
    async def check_giveaways(self):
        """
        Check if a giveaway has ended.
        """

        giveaways = [
            GiveawayEntry.from_record(self.bot, record)
            for record in await self.bot.db.fetch(
                """
                SELECT *
                FROM giveaway
                WHERE ends_at <= NOW()
                AND ended = FALSE
                """,
            )
        ]

        scheduled_deletion: List[GiveawayEntry] = []
        for giveaway in giveaways:
            if not giveaway.channel:
                scheduled_deletion.append(giveaway)
                continue

            message = await giveaway.message()
            if not message:
                scheduled_deletion.append(giveaway)
                continue

            if not message.reactions:
                scheduled_deletion.append(giveaway)
                continue

            with suppress(HTTPException):
                await self.draw_giveaway(giveaway, message)

        if scheduled_deletion:
            await self.bot.db.executemany(
                """
                DELETE FROM giveaway
                WHERE guild_id = $1
                AND channel_id = $2
                AND message_id = $3
                """,
                [
                    (
                        giveaway.guild_id,
                        giveaway.channel_id,
                        giveaway.message_id,
                    )
                    for giveaway in scheduled_deletion
                ],
            )

    async def draw_giveaway(
        self,
        giveaway: GiveawayEntry,
        message: Message,
    ):
        """
        Choose winners and end the giveaway.
        """

        await giveaway.end()
        winners = await giveaway.draw_winners(message)
        await message.edit(
            content="🎉 **GIVEAWAY ENDED** 🎉",
            embed=giveaway.embed(winners),
        )

        if winners:
            await message.reply(
                content=(
                    f"Congratulations {' '.join(w.mention for w in winners)}"
                    f" You won **{giveaway.prize}**"
                ),
            )

    @hybrid_group(
        aliases=["gw"], invoke_without_command=True, description="manage messages"
    )
    @has_permissions(manage_messages=True)
    async def giveaway(self, ctx: Context) -> Message:
        """
        Manage giveaways.
        """

        return await ctx.send_help(ctx.command)

    @giveaway.command(
        name="start",
        aliases=["create"],
        description="manage messages",
        usage="[channel] <duration> [winners=1] <prize>",
        brief="#giveaway 1d 1 Nitro",
    )
    @has_permissions(manage_messages=True)
    async def giveaway_start(
        self,
        ctx: Context,
        channel: Optional[TextChannel],
        duration: timedelta = parameter(
            converter=Duration(
                min=timedelta(minutes=5),
                max=timedelta(weeks=4),
            ),
        ),
        winners: Optional[int] = 1,
        *,
        prize: str,
    ) -> Optional[Message]:
        """
        Start a giveaway.

        The duration must be between 15 seconds and 1 month.
        If multiple winners are specified, the prize will
        automatically contain the winners, eg: `2x $10`.
        """

        channel = cast(TextChannel, channel or ctx.channel)
        if not isinstance(channel, TextChannel):
            return await ctx.warn("You can only start giveaways in text channels")

        created_at = ctx.message.created_at.astimezone(timezone.utc)
        ends_at = created_at + duration

        giveaway = GiveawayEntry(
            bot=self.bot,
            guild_id=ctx.guild.id,
            user_id=ctx.author.id,
            channel_id=channel.id,
            prize=prize,
            emoji="🎉",
            winners=min(max(1, winners or 1), 25),
            ends_at=ends_at,
        )
        message = await channel.send(
            content="🎉 **GIVEAWAY** 🎉",
            embed=giveaway.embed(),
        )
        await message.add_reaction("🎉")

        await giveaway.save(message)
        if channel == ctx.channel:
            return await ctx.add_check()

        return await ctx.approve(
            f"Giveaway started in {channel.mention} for [**{prize}**]({message.jump_url})",
        )

    @giveaway.command(
        name="end",
        aliases=["stop"],
        description="manage messages",
        usage="<giveaway>",
        brief="1251960361939243138",
    )
    @has_permissions(manage_messages=True)
    async def giveaway_end(
        self,
        ctx: Context,
        giveaway: GiveawayEntry = parameter(
            default=GiveawayEntry.fallback,
        ),
    ) -> Optional[Message]:
        """
        End a giveaway.
        """

        if giveaway.is_ended:
            return await ctx.warn("That giveaway has already ended")

        message = await giveaway.message()
        if not message:
            return await ctx.warn("That giveaway no longer exists")

        await self.draw_giveaway(giveaway, message)
        if message.channel == ctx.channel:
            return await ctx.add_check()

        return await ctx.approve(
            f"Giveaway ended for [**{giveaway.prize}**]({message.jump_url})"
        )

    @giveaway.command(
        name="reroll",
        aliases=["redraw"],
        description="manage messages",
        usage="<giveaway>",
        brief="1251960361939243138",
    )
    @has_permissions(manage_messages=True)
    async def giveaway_reroll(
        self,
        ctx: Context,
        giveaway: GiveawayEntry = parameter(
            default=GiveawayEntry.fallback,
        ),
    ) -> Optional[Message]:
        """
        Reroll a giveaway.
        """

        if not giveaway.is_ended:
            return await ctx.warn("That giveaway hasn't ended yet")

        message = await giveaway.message()
        if not message:
            return await ctx.warn("That giveaway no longer exists")

        await self.draw_giveaway(giveaway, message)
        if message.channel == ctx.channel:
            return await ctx.add_check()

        return await ctx.approve(
            f"Giveaway rerolled for [**{giveaway.prize}**]({message.jump_url})"
        )

    @giveaway.command(
        name="entrants",
        aliases=["entries"],
        description="manage messages",
        usage="<giveaway>",
        brief="1251960361939243138",
    )
    @has_permissions(manage_messages=True)
    async def giveaway_entrants(
        self,
        ctx: Context,
        giveaway: GiveawayEntry = parameter(
            default=GiveawayEntry.fallback,
        ),
    ) -> Optional[Message]:
        """
        View all giveaway entrants.
        """

        message = await giveaway.message()
        if not message:
            return await ctx.warn("That giveaway no longer exists")

        entries = await giveaway.entrants(message)
        if not entries:
            return await ctx.warn("No one has entered that giveaway")

        paginator = Paginator(
            ctx,
            entries=[f"**{member}** (`{member.id}`)" for member in entries],
            embed=Embed(title="Giveaway Entrants"),
        )
        return await paginator.start()

    @giveaway.command(name="list", aliases=["ls"], description="manage messages")
    @has_permissions(manage_messages=True)
    async def giveaway_list(self, ctx: Context) -> Message:
        """
        View all active giveaways.
        """

        giveaways = [
            GiveawayEntry.from_record(self.bot, record)
            for record in await self.bot.db.fetch(
                """
                SELECT *
                FROM giveaway
                WHERE guild_id = $1
                """,
                ctx.guild.id,
            )
        ]
        if not giveaways:
            return await ctx.warn("No giveaways exist for this server")

        paginator = Paginator(
            ctx,
            entries=[
                (
                    f"**{giveaway.prize}**"
                    f" - [`{giveaway.message_id}`]({giveaway.message_url})"
                    + (" [ENDED]" if giveaway.is_ended else "")
                )
                for giveaway in giveaways
            ],
            embed=Embed(title="Giveaways"),
        )
        return await paginator.start()
