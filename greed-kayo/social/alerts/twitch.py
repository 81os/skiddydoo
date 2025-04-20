from logging import getLogger
from typing import List, Optional

from discord import (
    AllowedMentions,
    Embed,
    HTTPException,
    Message,
    Role,
    TextChannel,
    Thread,
)
from discord.ext.commands import Cog, group, has_permissions
from discord.ext.tasks import loop
from discord.utils import format_dt

from cogs.social.models import TwitchStream, TwitchUser
from tools import CompositeMetaClass, MixinMeta
from tools.client import Context
from tools.formatter import plural, vowel
from tools.paginator import Paginator
from tools.parser import Script

log = getLogger("zyn/alerts")


class TwitchAlerts(MixinMeta, metaclass=CompositeMetaClass):
    """
    This class will handle all the Twitch alerts.
    """

    async def cog_load(self) -> None:
        self.twitch_alerts.start()
        return await super().cog_load()

    async def cog_unload(self) -> None:
        self.twitch_alerts.cancel()
        return await super().cog_unload()

    @loop(minutes=10)
    async def twitch_alerts(self):
        """
        Check for new Twitch streams.
        """

        records = await self.bot.db.fetch(
            """
            SELECT
                guild_id,
                channel_id,
                twitch_id,
                last_stream_id,
                role_id,
                template
            FROM alerts.twitch
            """,
        )
        if not records:
            return

        streams = await TwitchStream.fetch(
            self.bot.session,
            user_ids=list({record["twitch_id"] for record in records}),
        )
        if not streams:
            return

        for stream in streams:
            records = [
                record for record in records if record["twitch_id"] == stream.user_id
            ]

            if not records or stream.id == records[0]["last_stream_id"]:
                continue

            await self.bot.db.execute(
                """
                UPDATE alerts.twitch
                SET last_stream_id = $2
                WHERE twitch_id = $1
                """,
                stream.user_id,
                stream.id,
            )
            self.bot.dispatch(
                "twitch_alert",
                stream,
                records,
            )

    @twitch_alerts.before_loop
    async def before_twitch_alerts(self):
        await self.bot.wait_until_ready()

    @Cog.listener()
    async def on_twitch_alert(
        self,
        stream: TwitchStream,
        records: List[dict],
    ) -> List[Message]:
        """
        Send the Twitch alert to the channels.
        """

        sent_messages: List[Message] = []
        scheduled_deletion: List[int] = []
        for record in records:
            guild = self.bot.get_guild(record["guild_id"])
            if not guild:
                scheduled_deletion.append(record["channel_id"])
                continue

            channel = guild.get_channel_or_thread(record["channel_id"])
            if not isinstance(channel, (TextChannel, Thread)):
                scheduled_deletion.append(record["channel_id"])
                continue

            try:
                if record["template"]:
                    script = Script(
                        record["template"],
                        [
                            stream,
                            channel.guild,
                        ],
                    )

                    message = await script.send(
                        channel,
                        allowed_mentions=AllowedMentions.all(),
                    )
                else:
                    role = channel.guild.get_role(record["role_id"])

                    embed = Embed(
                        url=stream.url,
                        title=f"{stream.user_name} is now live!",
                        description=f"*{stream.title}*",
                        timestamp=stream.started_at,
                    )
                    embed.set_image(url=stream.thumbnail)
                    embed.set_footer(text="Twitch")

                    message = await channel.send(
                        content=role.mention if role else None,
                        embed=embed,
                        allowed_mentions=AllowedMentions.all(),
                    )
            except HTTPException:
                scheduled_deletion.append(record["channel_id"])
                continue
            else:
                sent_messages.append(message)

        if scheduled_deletion:
            log.info(
                "Scheduled deletion of %s Twitch notification%s for %s (%s).",
                len(scheduled_deletion),
                "s" if len(scheduled_deletion) > 1 else "",
                stream.user_name,
                stream.user_id,
            )

            await self.bot.db.execute(
                """
                DELETE FROM alerts.twitch
                WHERE channel_id = ANY($1::BIGINT[])
                """,
                scheduled_deletion,
            )

        elif sent_messages:
            log.info(
                "Sent %s Twitch notification%s for %s (%s).",
                len(sent_messages),
                "s" if len(sent_messages) > 1 else "",
                stream.user_name,
                stream.id,
            )

        return sent_messages

    @group(
        aliases=["live"],
        invoke_without_command=True,
    )
    async def twitch(self, ctx: Context, user: TwitchUser) -> Message:
        """
        Look up a user on Twitch.
        """

        stream = await TwitchStream.fetch(
            self.bot.session,
            user_ids=[user.id],
        )

        embed = Embed(
            url=user.url,
            title=(
                f"{user.display_name} (@{user.login})"
                if user.login != user.display_name
                else user.login
            ),
            description=user.description,
        )
        embed.set_thumbnail(url=user.profile_image_url)

        embed.add_field(
            name="**Status**",
            value="Live" if stream else "Offline",
        )
        embed.add_field(
            name="**Created**",
            value=format_dt(user.created_at),
        )

        return await ctx.send(embed=embed)

    @twitch.command(
        name="add",
        aliases=["feed"],
        description="manage channels",
        usage="<channel> <user>",
        brief="#twitch Sanchovies",
    )
    @has_permissions(manage_channels=True)
    async def twitch_add(
        self,
        ctx: Context,
        channel: TextChannel | Thread,
        twitch_user: TwitchUser,
    ) -> Message:
        """
        Add a channel to receive stream alerts.
        """

        await self.bot.db.execute(
            """
            INSERT INTO alerts.twitch (
                guild_id,
                channel_id,
                twitch_id,
                twitch_login
            )
            VALUES ($1, $2, $3, $4)
            ON CONFLICT (guild_id, twitch_id)
            DO UPDATE SET channel_id = EXCLUDED.channel_id
            """,
            ctx.guild.id,
            channel.id,
            twitch_user.id,
            twitch_user.login,
        )
        return await ctx.approve(
            f"Now streaming notifications for [**{twitch_user}**]({twitch_user.url}) in {channel.mention}"
        )

    @twitch.command(
        name="remove",
        aliases=["delete", "del", "rm"],
        description="manage channels",
        usage="<channel> <twitch user>",
        brief="#twitch Sanchovies",
    )
    @has_permissions(manage_channels=True)
    async def twitch_remove(
        self,
        ctx: Context,
        channel: Optional[TextChannel],
        twitch_user: TwitchUser,
    ) -> Message:
        """
        Remove a channel from receiving stream alerts.
        """

        result = await self.bot.db.execute(
            """
            DELETE FROM alerts.twitch
            WHERE guild_id = $1
            AND twitch_id = $2
            """,
            ctx.guild.id,
            twitch_user.id,
        )
        if result == "DELETE 0":
            return await ctx.warn(
                f"[**{twitch_user}**]({twitch_user.url}) is not being streamed in this server"
            )

        return await ctx.approve(
            f"No longer streaming notifications for [**{twitch_user}**]({twitch_user.url})"
        )

    @twitch.command(
        name="message",
        aliases=["msg", "template"],
        description="manage channels & mention everyone",
        usage="<twitch user> <script>",
        brief="Sanchovies Sanchovies is now live",
    )
    @has_permissions(manage_channels=True, mention_everyone=True)
    async def twitch_message(
        self,
        ctx: Context,
        twitch_user: TwitchUser,
        *,
        script: Script,
    ) -> Message:
        """
        Set a custom message for a Twitch stream alert.

        Available Variables:
        > `{stream}`: The stream.
        > `{guild}`: The guild.
        """

        result = await self.bot.db.execute(
            """
            UPDATE alerts.twitch
            SET template = $3
            WHERE guild_id = $1
            AND twitch_id = $2
            """,
            ctx.guild.id,
            twitch_user.id,
            script.template,
        )
        if result == "UPDATE 0":
            return await ctx.warn(
                f"[**{twitch_user}**]({twitch_user.url}) is not being streamed in this server"
            )

        return await ctx.approve(
            f"Successfully  set {vowel(script.format)} message for [**{twitch_user}**]({twitch_user.url})"
        )

    @twitch.group(
        name="role",
        description="manage channels, mention everyone",
        aliases=["mention"],
        invoke_without_command=True,
    )
    @has_permissions(manage_channels=True, mention_everyone=True)
    async def twitch_role(
        self,
        ctx: Context,
        twitch_user: TwitchUser,
        *,
        role: Role,
    ) -> Message:
        """
        Set a role to mention for a Twitch stream alert.

        This is useful for pinging without a custom message.
        """

        result = await self.bot.db.execute(
            """
            UPDATE alerts.twitch
            SET role_id = $3
            WHERE guild_id = $1
            AND twitch_id = $2
            """,
            ctx.guild.id,
            twitch_user.id,
            role.id,
        )
        if result == "UPDATE 0":
            return await ctx.warn(
                f"[**{twitch_user}**]({twitch_user.url}) is not being streamed in this server"
            )

        return await ctx.approve(
            f"Now mentioning {role.mention} for [**{twitch_user}**]({twitch_user.url}) streams"
        )

    @twitch_role.command(
        name="remove",
        aliases=["delete", "del", "rm"],
        description="manage channels & mention everyone",
        usage="<twitch user>",
        brief="Sanchovies",
    )
    @has_permissions(manage_channels=True, mention_everyone=True)
    async def twitch_role_remove(
        self,
        ctx: Context,
        twitch_user: TwitchUser,
    ) -> Message:
        """
        Remove a role from being mentioned for a Twitch stream alert.
        """

        result = await self.bot.db.execute(
            """
            UPDATE alerts.twitch
            SET role_id = NULL
            WHERE guild_id = $1
            AND twitch_id = $2
            """,
            ctx.guild.id,
            twitch_user.id,
        )
        if result == "UPDATE 0":
            return await ctx.warn(
                f"[**{twitch_user}**]({twitch_user.url}) is not being streamed in this server"
            )

        return await ctx.approve(
            f"No longer mentioning a role for [**{twitch_user}**]({twitch_user.url}) streams"
        )

    @twitch.command(
        name="clear", aliases=["clean", "reset"], description="manage channels"
    )
    @has_permissions(manage_channels=True)
    async def twitch_clear(self, ctx: Context) -> Message:
        """
        Remove all Twitch alerts.
        """

        await ctx.prompt(
            "Are you sure you want to remove all Twitch alerts?",
        )

        result = await self.bot.db.execute(
            """
            DELETE FROM alerts.twitch
            WHERE guild_id = $1
            """,
            ctx.guild.id,
        )
        if result == "DELETE 0":
            return await ctx.warn("No Twitch alerts exist for this server")

        return await ctx.approve(
            f"Successfully  removed {plural(result, md='`'):Twitch alert}"
        )

    @twitch.command(name="list", aliases=["ls"], description="manage channels")
    @has_permissions(manage_guild=True)
    async def twitch_list(self, ctx: Context) -> Message:
        """
        View all Twitch alerts.
        """

        channels = [
            f"{channel.mention} - [**{record['twitch_login']}**](https://twitch.tv/{record['twitch_login']})"
            for record in await self.bot.db.fetch(
                """
                SELECT channel_id, twitch_login
                FROM alerts.twitch
                WHERE guild_id = $1
                """,
                ctx.guild.id,
            )
            if (channel := ctx.guild.get_channel_or_thread(record["channel_id"]))
        ]
        if not channels:
            return await ctx.warn("No Twitch alerts exist for this server")

        paginator = Paginator(
            ctx,
            entries=channels,
            embed=Embed(
                title="Twitch Alerts",
            ),
        )
        return await paginator.start()
