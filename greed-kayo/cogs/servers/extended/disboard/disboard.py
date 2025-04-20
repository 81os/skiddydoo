from typing import List, Optional, cast

from discord import AllowedMentions, Embed, HTTPException, Message, TextChannel
from discord.ext.commands import Cog, group, has_permissions
from discord.ext.tasks import loop
from discord.utils import format_dt

from tools import CompositeMetaClass, MixinMeta
from tools.client import Context
from tools.formatter import codeblock, plural, vowel
from tools.paginator import Paginator
from tools.parser import Script

from .models import DisboardRecord, DisboardV, DisboardVariables


class Disboard(MixinMeta, metaclass=CompositeMetaClass):
    """
    Receive a reminder to bump your server every 2 hours.
    """

    async def cog_load(self) -> None:
        self.check_bump.start()
        return await super().cog_load()

    async def cog_unload(self) -> None:
        self.check_bump.cancel()
        return await super().cog_unload()

    @loop(minutes=5)
    async def check_bump(self) -> None:
        """
        Check if the server can be bumped.
        """

        disboard = self.bot.get_user(302050872383242240)
        if not disboard:
            return

        records = cast(
            List[DisboardRecord],
            await self.bot.db.fetch(
                """
                SELECT *
                FROM disboard.config
                WHERE status = TRUE
                AND guild_id = ANY($1::BIGINT[])
                AND next_bump < NOW()
                """,
                [guild.id for guild in disboard.mutual_guilds],
            ),
        )

        scheduled_deletion: List[int] = []
        for record in records:
            guild = self.bot.get_guild(record["guild_id"])
            if not guild:
                scheduled_deletion.append(record["guild_id"])
                continue

            channel: Optional[TextChannel] = None
            for channel_id in [record["channel_id"], record["last_channel_id"]]:
                channel = cast(
                    Optional[TextChannel],
                    guild.get_channel(channel_id),
                )
                if channel:
                    break

            if not channel:
                continue

            last_user = guild.get_member(record["last_user_id"]) or guild.me
            variables = DisboardVariables(last_user=last_user)
            script = Script(
                record["message"]
                or "it's been 2 hours since the last bump, can someone </bump:947088344167366698> the server?",
                [guild, channel, last_user, variables],
            )
            try:
                await script.send(channel, allowed_mentions=AllowedMentions.all())
            except HTTPException:
                await self.bot.db.execute(
                    """
                    UPDATE disboard.config
                    SET last_channel_id = NULL
                    WHERE guild_id = $1
                    """,
                    guild.id,
                )
            finally:
                await self.bot.db.execute(
                    """
                    UPDATE disboard.config
                    SET next_bump = NOW() + INTERVAL '2 hours'
                    WHERE guild_id = $1
                    """,
                    guild.id,
                )

        if scheduled_deletion:
            await self.bot.db.execute(
                """
                DELETE FROM disboard.config
                WHERE guild_id = ANY($1::BIGINT[])
                """,
                scheduled_deletion,
            )

    @Cog.listener("on_message")
    async def bump_listener(self, message: Message):
        """
        Listen for the bump message.
        """

        if (
            not message.guild
            or message.author.id != 302050872383242240
            or not message.interaction_metadata
            or not message.embeds
            or not message.embeds[0].description
            or "Bump done" not in message.embeds[0].description
        ):
            return

        user = message.interaction_metadata.user
        await self.bot.db.execute(
            """
            INSERT INTO disboard.bump (guild_id, user_id)
            VALUES ($1, $2)
            """,
            message.guild.id,
            user.id,
        )

        record = cast(
            Optional[DisboardV],
            await self.bot.db.fetchrow(
                """
                UPDATE disboard.config
                SET
                    last_user_id = $2,
                    last_channel_id = $3,
                    next_bump = NOW() + INTERVAL '2 hours'
                WHERE guild_id = $1
                AND status = TRUE
                RETURNING (
                    SELECT thank_message
                    FROM disboard.config
                    WHERE guild_id = $1
                ) AS thank_message,
                (
                    SELECT COUNT(*)
                    FROM disboard.bump
                    WHERE guild_id = $1
                    AND user_id = $2
                ) AS user_bumps,
                (
                    SELECT COUNT(*)
                    FROM disboard.bump
                    WHERE guild_id = $1
                ) AS bumps
                """,
                message.guild.id,
                user.id,
                message.channel.id,
            ),
        )
        if not record or not record["thank_message"]:
            return

        variables = DisboardVariables(
            last_user=user,
            user_bumps=record["user_bumps"],
            bumps=record["bumps"],
        )

        channel = cast(
            TextChannel,
            message.channel,
        )
        script = Script(
            record["thank_message"],
            [message.guild, channel, user, variables],
        )
        try:
            await script.send(channel)
        except HTTPException:
            await self.bot.db.execute(
                """
                UPDATE disboard.config
                SET thank_message = NULL
                WHERE guild_id = $1
                """,
                message.guild.id,
            )

    @group(
        aliases=[
            "bumpreminder",
            "bump",
        ],
        invoke_without_command=True,
        description="manage channel",
    )
    @has_permissions(manage_channels=True)
    async def disboard(self, ctx: Context) -> Message:
        """
        Recieve a reminder to bump your server every 2 hours.
        """

        return await ctx.send_help(ctx.command)

    @disboard.command(name="toggle", aliases=["switch"], description="manage channel")
    @has_permissions(manage_channels=True)
    async def disboard_toggle(self, ctx: Context) -> Message:
        """
        Toggle the bump reminder system.
        """

        status = cast(
            bool,
            await self.bot.db.fetchval(
                """
                INSERT INTO disboard.config (guild_id)
                VALUES ($1)
                ON CONFLICT (guild_id)
                DO UPDATE SET status = NOT disboard.config.status
                RETURNING status
                """,
                ctx.guild.id,
            ),
        )

        return await ctx.approve(
            f"{'Now receiving' if status else 'No longer receiving'} **bump reminders**"
        )

    @disboard.group(
        name="channel",
        description="manage channels",
        invoke_without_command=True,
    )
    @has_permissions(manage_channels=True)
    async def disboard_channel(self, ctx: Context, *, channel: TextChannel) -> Message:
        """
        Set the channel to receive bump reminders.

        If no channel is provided, the last bumped channel will be used.
        """

        channel = channel or ctx.channel
        await self.bot.db.execute(
            """
            UPDATE disboard.config
            SET channel_id = $2
            WHERE guild_id = $1
            """,
            ctx.guild.id,
            channel.id,
        )

        return await ctx.approve(f"Now sending **bump reminders** to {channel.mention}")

    @disboard_channel.command(
        name="remove", aliases=["delete", "del", "rm"], description="manage channels"
    )
    @has_permissions(manage_channels=True)
    async def disboard_channel_remove(self, ctx: Context) -> Message:
        """
        Remove the channel to receive bump reminders.
        """

        await self.bot.db.execute(
            """
            UPDATE disboard.config
            SET channel_id = NULL
            WHERE guild_id = $1
            """,
            ctx.guild.id,
        )

        return await ctx.approve(
            "Now sending **bump reminders** to the **last bumped** channel"
        )

    @disboard.group(
        name="message",
        description="manage channels",
        aliases=["msg", "template"],
        invoke_without_command=True,
    )
    @has_permissions(manage_channels=True)
    async def disboard_message(self, ctx: Context, *, script: Script) -> Message:
        """
        Set the bump reminder message.

        Available variables:
        > `{user}`: The last user which bumped the server.
        > `{disboard}`: The slash command to bump the server.
        """

        await self.bot.db.execute(
            """
            INSERT INTO disboard.config (guild_id, message)
            VALUES ($1, $2)
            ON CONFLICT (guild_id)
            DO UPDATE SET message = EXCLUDED.message
            """,
            ctx.guild.id,
            script.template,
        )

        return await ctx.approve(
            f"Successfully  set {vowel(script.format)} **bump reminder** message"
        )

    @disboard_message.command(
        name="remove", aliases=["delete", "del", "rm"], description="manage channels"
    )
    @has_permissions(manage_channels=True)
    async def disboard_message_remove(self, ctx: Context) -> Message:
        """
        Remove the bump reminder message.
        """

        await self.bot.db.execute(
            """
            UPDATE disboard.config
            SET message = NULL
            WHERE guild_id = $1
            """,
            ctx.guild.id,
        )

        return await ctx.approve("Now using the **default** bump reminder message")

    @disboard_message.group(
        name="thank",
        aliases=["thanks"],
        description="manage channels",
        invoke_without_command=True,
    )
    @has_permissions(manage_channels=True)
    async def disboard_message_thank(self, ctx: Context, *, script: Script) -> Message:
        """
        Set the thank you message.

        Available variables:
        > `{user}`: The user which bumped the server.
        > `{disboard}`: The slash command to bump the server.
        > `{disboard.bumps}`: The total number of server bumps.
        > `{disboard.user_bumps}`: The total number of bumps by the user.
        """

        await self.bot.db.execute(
            """
            INSERT INTO disboard.config (guild_id, thank_message)
            VALUES ($1, $2)
            ON CONFLICT (guild_id)
            DO UPDATE SET thank_message = EXCLUDED.thank_message
            """,
            ctx.guild.id,
            script.template,
        )

        return await ctx.approve(
            f"Successfully  set {vowel(script.format)} **thank you** message"
        )

    @disboard_message_thank.command(
        name="remove", aliases=["delete", "del", "rm"], description="manage channels"
    )
    @has_permissions(manage_channels=True)
    async def disboard_message_thank_remove(self, ctx: Context) -> Message:
        """
        Remove the thank you message.
        """

        await self.bot.db.execute(
            """
            UPDATE disboard.config
            SET thank_message = NULL
            WHERE guild_id = $1
            """,
            ctx.guild.id,
        )

        return await ctx.approve("No longer sending a **thank you** message")

    @disboard.command(
        name="settings", aliases=["config"], description="manage channels"
    )
    @has_permissions(manage_channels=True)
    async def disboard_settings(self, ctx: Context) -> Message:
        """
        View the bump reminder settings.
        """

        record: Optional[DisboardRecord] = await self.bot.db.fetchrow(
            """
            SELECT *
            FROM disboard.config
            WHERE guild_id = $1
            """,
            ctx.guild.id,
        )
        if not record:
            return await ctx.warn("The **bump reminder** system has not been enabled")

        channel = cast(
            Optional[TextChannel],
            ctx.guild.get_channel(record["channel_id"] or record["last_channel_id"]),
        )

        embed = Embed(
            url=f"https://disboard.org/server/{ctx.guild.id}",
            title="Bump Reminder",
            description=(
                f"Bump reminders are **{'enabled' if record['status'] else 'disabled'}**"
                "\n>>> "
                + "\n".join(
                    [
                        f"**Channel:** {channel.mention if channel else 'Last bumped channel'}"
                        + (
                            " (last bumped)"
                            if not record["channel_id"] and channel
                            else ""
                        ),
                        f"**Next Bump:** {format_dt(record['next_bump'], 'R') if record['next_bump'] else 'Not recorded yet'}",
                    ]
                )
            ),
        )
        embed.add_field(
            name="**Message**",
            value=codeblock(
                record["message"] or "it's been 2 hours, can someone /bump the server?"
            ),
            inline=False,
        )
        if record["thank_message"]:
            embed.add_field(
                name="**Thank Message**",
                value=codeblock(record["thank_message"]),
            )

        return await ctx.send(embed=embed)

    @disboard.command(
        name="leaderboard", aliases=["lb", "bumps"], description="manage channels"
    )
    async def disboard_leaderboard(self, ctx: Context) -> Message:
        """
        View the most bumpers.
        """

        members = [
            f"**{member}** bumped {plural(record['bumps'], '**'):time}"
            for record in await self.bot.db.fetch(
                """
                SELECT user_id, COUNT(*) AS bumps
                FROM disboard.bump
                WHERE guild_id = $1
                GROUP BY user_id
                ORDER BY COUNT(*) DESC
                """,
                ctx.guild.id,
            )
            if (member := ctx.guild.get_member(record["user_id"]))
        ]
        if not members:
            return await ctx.warn("No members have bumped the server")

        paginator = Paginator(
            ctx,
            entries=members,
            embed=Embed(title="Bump Leaderboard"),
        )
        return await paginator.start()
