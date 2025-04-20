from contextlib import suppress
from itertools import groupby
from logging import getLogger
from typing import List, Optional, cast, Union

from discord import (
    Embed,
    HTTPException,
    Member,
    Message,
    MessageType,
    PartialMessage,
    TextChannel,
    Thread,
)
from discord.ext.commands import Cog, command, Range, flag, group, has_permissions
from humanfriendly import format_timespan
from xxhash import xxh32_hexdigest

from collections import defaultdict
import asyncio
from tools import CompositeMetaClass, MixinMeta
from tools.client import Context, FlagConverter
from tools.formatter import codeblock, plural, vowel
from tools.paginator import Paginator
from tools.parser import Script

log = getLogger("zyn/system")


class Flags(FlagConverter):
    delete_after: Range[int, 3, 120] = flag(
        aliases=["self_destruct"],
        description="Delete the message after a certain amount of time.",
        default=0,
    )


class System(MixinMeta, metaclass=CompositeMetaClass):
    join_queue = defaultdict(list)
    locks = defaultdict(asyncio.Lock)
    """
    The System mixin provides tools for automating messages.
    """

    def welcome_key(self, member: Member) -> str:
        return xxh32_hexdigest(f"welcome.{member.guild.id}:{member.id}")

    async def notify_failure(
        self,
        system: str,
        channel: TextChannel | Thread,
        member: Member,
        script: Script,
        exc: HTTPException,
    ) -> Optional[Message]:
        """
        Notify the server owner of a system message failure.
        """

        owner = channel.guild.owner
        if not owner:
            return None

        embed = Embed(
            title=f"{system.title()} Message Failure",
            description=(
                f"Failed to send {system.lower()} message for **{member}** "
                f"in {channel.mention}\n" + codeblock(exc.text)
            ),
        )
        if len(script.template) <= 1024:
            embed.add_field(
                name="**Script**",
                value=codeblock(script.template),
            )

        with suppress(HTTPException):
            return await owner.send(
                embed=embed,
                content=(
                    codeblock(script.template) if len(script.template) > 1024 else None
                ),
            )

    @Cog.listener("on_member_join")
    async def welcome_send(self, member: Member) -> List[Message]:
        """
        Send the greet messages for the member.
        """

        guild = member.guild
        records = await self.bot.db.fetch(
            """
            SELECT channel_id, template, delete_after
            FROM welcome_message
            WHERE guild_id = $1
            """,
            guild.id,
        )

        sent_messages: List[Message] = []
        scheduled_deletion: List[int] = []
        for record in records:
            channel_id = cast(
                int,
                record["channel_id"],
            )
            channel = cast(
                Optional[TextChannel | Thread],
                guild.get_channel_or_thread(channel_id),
            )
            if not channel:
                scheduled_deletion.append(channel_id)
                continue

            script = Script(
                record["template"],
                [guild, member, channel],
            )

            try:
                message = await script.send(channel)
            except HTTPException as exc:
                await self.notify_failure("greet", channel, member, script, exc)
                scheduled_deletion.append(channel_id)
            else:
                if record["delete_after"]:
                    await message.delete(delay=record["delete_after"])
                else:
                    sent_messages.append(message)

        if scheduled_deletion:
            log.info(
                "Scheduled deletion of %s greet message%s for %s (%s).",
                len(scheduled_deletion),
                "s" if len(scheduled_deletion) > 1 else "",
                guild,
                guild.id,
            )

            await self.bot.db.execute(
                """
                DELETE FROM welcome_message
                WHERE channel_id = ANY($1::BIGINT[])
                """,
                scheduled_deletion,
            )

        if sent_messages:
            key = self.welcome_key(member)
            await self.bot.redis.sadd(
                key,
                *[f"{message.channel.id}.{message.id}" for message in sent_messages],
                ex=3000,
            )

            log.debug(
                "Sent %s greet message%s for %r in %s (%s).",
                len(sent_messages),
                "s" if len(sent_messages) > 1 else "",
                member.name,
                guild,
                guild.id,
            )

        return sent_messages

    @Cog.listener("on_message")
    async def welcome_system(self, message: Message):
        """
        Add the system welcome message to redis.
        """

        if message.type != MessageType.new_member:
            return

        elif not isinstance(message.author, Member):
            return

        key = self.welcome_key(message.author)
        await self.bot.redis.sadd(
            key,
            f"{message.channel.id}.{message.id}",
            ex=3000,
        )

    @Cog.listener("on_member_remove")
    async def welcome_delete(self, member: Member):
        """
        Remove welcome messages when a member leaves.
        """

        guild = member.guild
        key = self.welcome_key(member)
        identifiers = await self.bot.redis.smembers(key)
        if not identifiers:
            return

        removal = cast(
            Optional[bool],
            await self.bot.db.fetchval(
                """
                SELECT welcome_removal
                FROM settings
                WHERE guild_id = $1
                """,
                member.guild.id,
            ),
        )
        if not removal:
            return

        partial_messages: List[PartialMessage] = []
        for identifier in identifiers:
            channel_id, message_id = identifier.split(".")
            channel = guild.get_channel_or_thread(int(channel_id))
            if not isinstance(channel, (TextChannel, Thread)):
                continue

            message = channel.get_partial_message(int(message_id))
            partial_messages.append(message)

        for channel, messages in groupby(
            partial_messages, lambda message: message.channel
        ):
            if not isinstance(channel, (TextChannel, Thread)):
                continue

            with suppress(HTTPException):
                await channel.delete_messages(messages)

    @Cog.listener("on_member_remove")
    async def goodbye_send(self, member: Member) -> List[Message]:
        """
        Send the leave messages for the member.
        """

        guild = member.guild
        records = await self.bot.db.fetch(
            """
            SELECT channel_id, template, delete_after
            FROM goodbye_message
            WHERE guild_id = $1
            """,
            guild.id,
        )

        sent_messages: List[Message] = []
        scheduled_deletion: List[int] = []
        for record in records:
            channel_id = cast(
                int,
                record["channel_id"],
            )
            channel = cast(
                Optional[TextChannel | Thread],
                guild.get_channel_or_thread(channel_id),
            )
            if not channel:
                scheduled_deletion.append(channel_id)
                continue

            script = Script(
                record["template"],
                [guild, member, channel],
            )

            try:
                message = await script.send(channel)
            except HTTPException as exc:
                await self.notify_failure("leave", channel, member, script, exc)
                scheduled_deletion.append(channel_id)
            else:
                sent_messages.append(message)
                if record["delete_after"]:
                    await message.delete(delay=record["delete_after"])

        if scheduled_deletion:
            log.info(
                "Scheduled deletion of %s leave message%s for %s (%s).",
                len(scheduled_deletion),
                "s" if len(scheduled_deletion) > 1 else "",
                guild,
                guild.id,
            )

            await self.bot.db.execute(
                """
                DELETE FROM goodbye_message
                WHERE channel_id = ANY($1::BIGINT[])
                """,
                scheduled_deletion,
            )

        elif sent_messages:
            log.debug(
                "Sent %s leave message%s for %r in %s (%s).",
                len(sent_messages),
                "s" if len(sent_messages) > 1 else "",
                member.name,
                guild,
                guild.id,
            )

        return sent_messages

    @Cog.listener("on_member_boost")
    async def boost_send(self, member: Member) -> List[Message]:
        """
        Send the boost messages for the member.
        """

        guild = member.guild
        records = await self.bot.db.fetch(
            """
            SELECT channel_id, template, delete_after
            FROM boost_message
            WHERE guild_id = $1
            """,
            guild.id,
        )

        sent_messages: List[Message] = []
        scheduled_deletion: List[int] = []
        for record in records:
            channel_id = cast(
                int,
                record["channel_id"],
            )
            channel = cast(
                Optional[TextChannel | Thread],
                guild.get_channel_or_thread(channel_id),
            )
            if not channel:
                scheduled_deletion.append(channel_id)
                continue

            script = Script(
                record["template"],
                [guild, member, channel],
            )

            try:
                message = await script.send(channel)
            except HTTPException as exc:
                await self.notify_failure("boost", channel, member, script, exc)
                scheduled_deletion.append(channel_id)
            else:
                sent_messages.append(message)
                if record["delete_after"]:
                    await message.delete(delay=record["delete_after"])

        if scheduled_deletion:
            log.info(
                "Scheduled deletion of %s boost message%s for %s (%s).",
                len(scheduled_deletion),
                "s" if len(scheduled_deletion) > 1 else "",
                guild,
                guild.id,
            )

            await self.bot.db.execute(
                """
                DELETE FROM boost_message
                WHERE channel_id = ANY($1::BIGINT[])
                """,
                scheduled_deletion,
            )

        elif sent_messages:
            log.debug(
                "Sent %s boost message%s for %r in %s (%s)..",
                len(sent_messages),
                "s" if len(sent_messages) > 1 else "",
                member.name,
                guild,
                guild.id,
            )

        return sent_messages

    @group(
        aliases=["greet", "welc", "wlc"],
        invoke_without_command=True,
        description="manage guild",
    )
    @has_permissions(manage_guild=True)
    async def welcome(self, ctx: Context) -> Message:
        """
        The base command for managing greet messages.
        Welcome messages are sent when a user joins the server.
        """

        return await ctx.send_help(ctx.command)

    @welcome.command(name="removal", aliases=["deletion"], description="manage guild")
    @has_permissions(manage_guild=True)
    async def welcome_removal(self, ctx: Context) -> Message:
        """
        Toggle welcome message deletion on member removal.
        """

        await ctx.settings.update(welcome_removal=not ctx.settings.welcome_removal)
        return await ctx.approve(
            f"Welcome messages will **{'now' if ctx.settings.welcome_removal else 'no longer'}** be deleted on member removal"
        )

    @welcome.command(
        name="add",
        aliases=["create"],
        description="manage guild",
        usage="<channel> <script>",
        brief="#general Welcome",
    )
    @has_permissions(manage_guild=True)
    async def welcome_add(
        self,
        ctx: Context,
        channel: TextChannel | Thread,
        *,
        script: Script,
    ) -> Message:
        """
        Add a greet message to a channel.
        """

        template, flags = await Flags().find(ctx, script.template)
        if not template:
            return await ctx.warn("You must provide a greet message")

        records = len(
            [
                record
                for record in await self.bot.db.fetch(
                    """
                    SELECT channel_id
                    FROM welcome_message
                    WHERE guild_id = $1
                    """,
                    ctx.guild.id,
                )
                if ctx.guild.get_channel_or_thread(record["channel_id"])
            ]
        )
        if records >= 2:
            return await ctx.warn("You can't have more than `2` greet messages")

        await self.bot.db.execute(
            """
            INSERT INTO welcome_message (
                guild_id,
                channel_id,
                template,
                delete_after
            )
            VALUES ($1, $2, $3, $4)
            ON CONFLICT (guild_id, channel_id)
            DO UPDATE SET
                template = EXCLUDED.template,
                delete_after = EXCLUDED.delete_after
            """,
            ctx.guild.id,
            channel.id,
            template,
            flags.delete_after,
        )

        return await ctx.approve(
            f"Added {vowel(script.format)} greet message to {channel.mention}",
            *(
                [
                    f"The message will be deleted after **{format_timespan(flags.delete_after)}**"
                ]
                if flags.delete_after
                else []
            ),
        )

    @welcome.command(
        name="remove",
        aliases=["delete", "del", "rm"],
        description="manage guild",
        usage="<channel>",
        brief="#welcome",
    )
    @has_permissions(manage_guild=True)
    async def welcome_remove(self, ctx: Context, channel: TextChannel) -> Message:
        """
        Remove an existing greet message.
        """

        result = await self.bot.db.execute(
            """
            DELETE FROM welcome_message
            WHERE guild_id = $1
            AND channel_id = $2
            """,
            ctx.guild.id,
            channel.id,
        )
        if result == "DELETE 0":
            return await ctx.warn(f"A greet message in {channel.mention} doesn't exist")

        return await ctx.approve(
            f"No longer sending greet messages in {channel.mention}"
        )

    @welcome.command(
        name="view",
        aliases=["show"],
        description="manage guild",
        usage="<channel>",
        brief="#welcome",
    )
    @has_permissions(manage_guild=True)
    async def welcome_view(self, ctx: Context, channel: TextChannel) -> Message:
        """
        View an existing greet message.
        """

        template = cast(
            Optional[str],
            await self.bot.db.fetchval(
                """
                SELECT template
                FROM welcome_message
                WHERE guild_id = $1
                AND channel_id = $2
                """,
                ctx.guild.id,
                channel.id,
            ),
        )
        if not template:
            return await ctx.warn(f"A greet message in {channel.mention} doesn't exist")

        script = Script(template, [ctx.guild, ctx.author, channel])

        await ctx.reply(codeblock(script.template))
        return await script.send(ctx.channel)

    @welcome.command(
        name="clear", aliases=["clean", "reset"], description="manage guild"
    )
    @has_permissions(manage_guild=True)
    async def welcome_clear(self, ctx: Context) -> Message:
        """
        Remove all greet messages.
        """

        await ctx.prompt(
            "Are you sure you want to remove all greet messages?",
        )

        result = await self.bot.db.execute(
            """
            DELETE FROM welcome_message
            WHERE guild_id = $1
            """,
            ctx.guild.id,
        )
        if result == "DELETE 0":
            return await ctx.warn("No greet messages exist for this server")

        return await ctx.approve(
            f"Successfully  removed {plural(result, md='`'):greet message}"
        )

    @welcome.command(name="list", aliases=["ls"], description="manage guild")
    @has_permissions(manage_guild=True)
    async def welcome_list(self, ctx: Context) -> Message:
        """
        View all welcome channels.
        """

        channels = [
            f"{channel.mention} (`{channel.id}`)"
            for record in await self.bot.db.fetch(
                """
                SELECT channel_id
                FROM welcome_message
                WHERE guild_id = $1
                """,
                ctx.guild.id,
            )
            if (channel := ctx.guild.get_channel_or_thread(record["channel_id"]))
        ]
        if not channels:
            return await ctx.warn("No greet messages exist for this server")

        paginator = Paginator(
            ctx,
            entries=channels,
            embed=Embed(title="Welcome Channels"),
        )
        return await paginator.start()

    @group(
        aliases=["leave", "bye"],
        invoke_without_command=True,
        description="manage guild",
    )
    @has_permissions(manage_guild=True)
    async def goodbye(self, ctx: Context) -> Message:
        """
        Base command for managing leave messages.
        Goodbye messages are sent when a user leaves the server.
        """

        return await ctx.send_help(ctx.command)

    @goodbye.command(
        name="add",
        aliases=["create"],
        description="manage guild",
        usage="<channel> <script>",
        brief="#goodbye Bye :(",
    )
    @has_permissions(manage_guild=True)
    async def goodbye_add(
        self,
        ctx: Context,
        channel: TextChannel | Thread,
        *,
        script: Script,
    ) -> Message:
        """
        Add a leave message to a channel.
        """

        template, flags = await Flags().find(ctx, script.template)
        if not template:
            return await ctx.warn("You must provide a greet message")

        records = len(
            [
                record
                for record in await self.bot.db.fetch(
                    """
                    SELECT channel_id
                    FROM goodbye_message
                    WHERE guild_id = $1
                    """,
                    ctx.guild.id,
                )
                if ctx.guild.get_channel_or_thread(record["channel_id"])
            ]
        )
        if records >= 2:
            return await ctx.warn("You can't have more than `2` leave messages")

        await self.bot.db.execute(
            """
            INSERT INTO goodbye_message (
                guild_id,
                channel_id,
                template,
                delete_after
            )
            VALUES ($1, $2, $3, $4)
            ON CONFLICT (guild_id, channel_id)
            DO UPDATE SET
                template = EXCLUDED.template,
                delete_after = EXCLUDED.delete_after
            """,
            ctx.guild.id,
            channel.id,
            template,
            flags.delete_after,
        )

        return await ctx.approve(
            f"Added {vowel(script.format)} leave message to {channel.mention}",
            *(
                [
                    f"The message will be deleted after **{format_timespan(flags.delete_after)}**"
                ]
                if flags.delete_after
                else []
            ),
        )

    @goodbye.command(
        name="remove",
        aliases=["delete", "del", "rm"],
        description="manage guild",
        usage="<channel>",
        brief="#goodbye",
    )
    @has_permissions(manage_guild=True)
    async def goodbye_remove(self, ctx: Context, channel: TextChannel) -> Message:
        """
        Remove an existing leave message.
        """

        result = await self.bot.db.execute(
            """
            DELETE FROM goodbye_message
            WHERE guild_id = $1
            AND channel_id = $2
            """,
            ctx.guild.id,
            channel.id,
        )
        if result == "DELETE 0":
            return await ctx.warn(f"A leave message in {channel.mention} doesn't exist")

        return await ctx.approve(
            f"No longer sending leave messages in {channel.mention}"
        )

    @goodbye.command(
        name="view",
        aliases=["show"],
        description="manage guild",
        usage="<channel>",
        brief="#goodbye",
    )
    @has_permissions(manage_guild=True)
    async def goodbye_view(self, ctx: Context, channel: TextChannel) -> Message:
        """
        View an existing leave message.
        """

        template = cast(
            Optional[str],
            await self.bot.db.fetchval(
                """
                SELECT template
                FROM goodbye_message
                WHERE guild_id = $1
                AND channel_id = $2
                """,
                ctx.guild.id,
                channel.id,
            ),
        )
        if not template:
            return await ctx.warn(f"A leave message in {channel.mention} doesn't exist")

        script = Script(template, [ctx.guild, ctx.author, channel])

        await ctx.reply(codeblock(script.template))
        return await script.send(ctx.channel)

    @goodbye.command(
        name="clear", aliases=["clean", "reset"], description="manage guild"
    )
    @has_permissions(manage_guild=True)
    async def goodbye_clear(self, ctx: Context) -> Message:
        """
        Remove all leave messages.
        """

        await ctx.prompt(
            "Are you sure you want to remove all leave messages?",
        )

        result = await self.bot.db.execute(
            """
            DELETE FROM goodbye_message
            WHERE guild_id = $1
            """,
            ctx.guild.id,
        )
        if result == "DELETE 0":
            return await ctx.warn("No leave messages exist for this server")

        return await ctx.approve(
            f"Successfully  removed {plural(result, md='`'):leave message}"
        )

    @goodbye.command(name="list", aliases=["ls"], description="manage guild")
    @has_permissions(manage_guild=True)
    async def goodbye_list(self, ctx: Context) -> Message:
        """
        View all goodbye channels.
        """

        channels = [
            f"{channel.mention} (`{channel.id}`)"
            for record in await self.bot.db.fetch(
                """
                SELECT channel_id
                FROM goodbye_message
                WHERE guild_id = $1
                """,
                ctx.guild.id,
            )
            if (channel := ctx.guild.get_channel_or_thread(record["channel_id"]))
        ]
        if not channels:
            return await ctx.warn("No leave messages exist for this server")

        paginator = Paginator(
            ctx,
            entries=channels,
            embed=Embed(title="Goodbye Channels"),
        )
        return await paginator.start()

    @group(invoke_without_command=True, description="manage guild")
    @has_permissions(manage_guild=True)
    async def boost(self, ctx: Context) -> Message:
        """
        Base command for managing boost messages.
        Boost messages are sent when a user boosts the server.
        """
        return await ctx.send_help(ctx.command)

    @boost.command(
        name="add",
        aliases=["create"],
        description="manage guild",
        usage="<channel> <script>",
        brief="#boosters Thank you for boosting",
    )
    @has_permissions(manage_guild=True)
    async def boost_add(
        self,
        ctx: Context,
        channel: Union[TextChannel, Thread],
        *,
        script: Script,
    ) -> Message:
        """
        Add a boost message to a channel.
        """
        template, flags = await Flags().find(ctx, script.template)
        if not template:
            return await ctx.warn("You must provide a greet message")

        records = len(
            [
                record
                for record in await self.bot.db.fetch(
                    """
                    SELECT channel_id
                    FROM boost_message
                    WHERE guild_id = $1
                    """,
                    ctx.guild.id,
                )
                if ctx.guild.get_channel_or_thread(record["channel_id"])
            ]
        )
        if records >= 2:
            return await ctx.warn("You can't have more than `2` boost messages")

        await self.bot.db.execute(
            """
            INSERT INTO boost_message (
                guild_id,
                channel_id,
                template,
                delete_after
            )
            VALUES ($1, $2, $3, $4)
            ON CONFLICT (guild_id, channel_id)
            DO UPDATE SET
                template = EXCLUDED.template,
                delete_after = EXCLUDED.delete_after
            """,
            ctx.guild.id,
            channel.id,
            template,
            flags.delete_after,
        )

        return await ctx.approve(
            f"Added {vowel(script.format)} boost message to {channel.mention}",
            *(
                [
                    f"The message will be deleted after **{format_timespan(flags.delete_after)}**"
                ]
                if flags.delete_after
                else []
            ),
        )

    @boost.command(
        name="remove",
        aliases=["delete", "del", "rm"],
        description="manage guild",
        usage="<channel>",
        brief="#boosters",
    )
    @has_permissions(manage_guild=True)
    async def boost_remove(self, ctx: Context, channel: TextChannel) -> Message:
        """
        Remove an existing boost message.
        """
        result = await self.bot.db.execute(
            """
            DELETE FROM boost_message
            WHERE guild_id = $1
            AND channel_id = $2
            """,
            ctx.guild.id,
            channel.id,
        )
        if result == "DELETE 0":
            return await ctx.warn(f"A boost message in {channel.mention} doesn't exist")

        return await ctx.approve(
            f"No longer sending boost messages in {channel.mention}"
        )

    @boost.command(
        name="view",
        aliases=["show"],
        description="manage guild",
        usage="<channel>",
        brief="#boosters",
    )
    @has_permissions(manage_guild=True)
    async def boost_view(self, ctx: Context, channel: TextChannel) -> Message:
        """
        View an existing boost message.
        """
        template = cast(
            Optional[str],
            await self.bot.db.fetchval(
                """
                SELECT template
                FROM boost_message
                WHERE guild_id = $1
                AND channel_id = $2
                """,
                ctx.guild.id,
                channel.id,
            ),
        )
        if not template:
            return await ctx.warn(f"A boost message in {channel.mention} doesn't exist")

        script = Script(template, [ctx.guild, ctx.author, channel])

        await ctx.reply(codeblock(script.template))
        return await script.send(ctx.channel)

    @boost.command(name="clear", aliases=["clean", "reset"], description="manage guild")
    @has_permissions(manage_guild=True)
    async def boost_clear(self, ctx: Context) -> Message:
        """
        Remove all boost messages.
        """
        await ctx.prompt(
            "Are you sure you want to remove all boost messages?",
        )

        result = await self.bot.db.execute(
            """
            DELETE FROM boost_message
            WHERE guild_id = $1
            """,
            ctx.guild.id,
        )
        if result == "DELETE 0":
            return await ctx.warn("No boost messages exist for this server")

        return await ctx.approve(
            f"Successfully removed {plural(result, md='`'):boost message}"
        )

    @boost.command(name="list", aliases=["ls"], description="manage guild")
    @has_permissions(manage_guild=True)
    async def boost_list(self, ctx: Context) -> Message:
        """
        View all boost channels.
        """
        channels = [
            f"{channel.mention} (`{channel.id}`)"
            for record in await self.bot.db.fetch(
                """
                SELECT channel_id
                FROM boost_message
                WHERE guild_id = $1
                """,
                ctx.guild.id,
            )
            if (channel := ctx.guild.get_channel_or_thread(record["channel_id"]))
        ]
        if not channels:
            return await ctx.warn("No boost messages exist for this server")

        paginator = Paginator(
            ctx,
            entries=channels,
            embed=Embed(title="Boost Channels"),
        )
        return await paginator.start()

    @command(
        description="manage guild",
        aliases=["poj", "autoping"],
        brief="#joins --self_destruct 3",
    )
    @has_permissions(manage_guild=True)
    async def pingonjoin(
        self, ctx: Context, channel: Optional[TextChannel] = None, *, flags: Flags
    ):
        """
        Enable or disable ping on join for a channel.
        """
        guild_id = ctx.guild.id

        if channel is None:
            await self.bot.db.execute(
                "DELETE FROM pingonjoin WHERE guild_id = $1", guild_id
            )
            await ctx.send("Disabled ping on join for this server.")
        else:
            await self.bot.db.execute(
                """INSERT INTO pingonjoin (guild_id, channel_id, delete_after)
                VALUES ($1, $2, $3)
                ON CONFLICT (guild_id) DO UPDATE 
                SET channel_id = $2, delete_after = $3""",
                guild_id,
                channel.id,
                flags.delete_after,
            )
            await ctx.send(
                f"Enabled ping on join for {channel.mention}. Delete after: {flags.delete_after} seconds."
            )

    @Cog.listener("on_member_join")
    async def on_pingonjoin(self, member: Member):
        """
        Send a ping message to a channel when a new member joins.
        """
        guild_id = member.guild.id
        data = await self.bot.db.fetchrow(
            "SELECT channel_id, delete_after FROM pingonjoin WHERE guild_id = $1",
            guild_id,
        )

        if data:
            channel = member.guild.get_channel(data["channel_id"])
            if channel:
                async with self.locks[guild_id]:
                    self.join_queue[guild_id].append(member.mention)
                    if len(self.join_queue[guild_id]) == 1:
                        await asyncio.sleep(1)
                        mentions = " ".join(self.join_queue[guild_id])
                        try:
                            message = await channel.send(f"{mentions}")
                            self.join_queue[guild_id].clear()
                            if data["delete_after"]:
                                await message.delete(delay=data["delete_after"])
                        except Exception as e:
                            log.exception(f"Failed to send or delete message: {e}")
