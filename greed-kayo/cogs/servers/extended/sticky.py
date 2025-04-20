import asyncio
from typing import Optional, cast

from asyncpg import UniqueViolationError
from discord import Embed, HTTPException, Message, TextChannel
from discord.ext.commands import Cog, group, has_permissions
from discord.utils import utcnow
from xxhash import xxh32_hexdigest

from tools import CompositeMetaClass, MixinMeta, quietly_delete
from tools.client import Context
from tools.formatter import codeblock, vowel
from tools.paginator import Paginator
from tools.parser import Script


class Sticky(MixinMeta, metaclass=CompositeMetaClass):
    """
    Stick messages to the bottom of a channel.
    """

    @Cog.listener("on_message")
    async def sticky_listener(self, message: Message) -> None:
        """
        Stick messages to the bottom of a channel.
        We don't want to send sticky messages constantly, so we'll
        only send them if messages haven't been sent within 3 seconds.
        """

        if (
            not message.guild
            or message.author.bot
            or not isinstance(
                message.channel,
                TextChannel,
            )
        ):
            return

        guild = message.guild
        channel = message.channel
        record = await self.bot.db.fetchrow(
            """
            SELECT message_id, template
            FROM sticky_message
            WHERE guild_id = $1
            AND channel_id = $2
            """,
            guild.id,
            channel.id,
        )
        if not record:
            return

        key = xxh32_hexdigest(f"sticky:{channel.id}")
        locked = await self.bot.redis.get(key)
        if locked:
            return

        await self.bot.redis.set(key, 1, 6)
        last_message = channel.get_partial_message(record["message_id"])
        time_since = utcnow() - last_message.created_at
        time_to_wait = 6 - time_since.total_seconds()
        if time_to_wait > 1:
            await asyncio.sleep(time_to_wait)

        script = Script(
            record["template"],
            [guild, channel, message.author],
        )

        try:
            new_message = await script.send(channel)
        except HTTPException:
            await self.bot.db.execute(
                """
                DELETE FROM sticky_message
                WHERE guild_id = $1
                AND channel_id = $2
                """,
                guild.id,
                channel.id,
            )
        else:
            await self.bot.db.execute(
                """
                UPDATE sticky_message
                SET message_id = $3
                WHERE guild_id = $1
                AND channel_id = $2
                """,
                guild.id,
                channel.id,
                new_message.id,
            )
        finally:
            await self.bot.redis.delete(key)
            await quietly_delete(last_message)

    @group(
        aliases=[
            "stickymessage",
            "stickymsg",
        ],
        invoke_without_command=True,
    )
    @has_permissions(manage_messages=True)
    async def sticky(self, ctx: Context) -> Message:
        """
        Stick messages to the bottom of a channel.
        """

        return await ctx.send_help(ctx.command)

    @sticky.command(
        name="add",
        aliases=["create"],
        description="manage messages",
        usage="<channel> <script>",
        brief="#general Make sure to follow the rules",
    )
    @has_permissions(manage_messages=True)
    async def sticky_add(
        self,
        ctx: Context,
        channel: TextChannel,
        *,
        script: Script,
    ) -> Message:
        """
        Add a sticky message to a channel.
        """

        try:
            message = await script.send(channel)
            await self.bot.db.execute(
                """
                INSERT INTO sticky_message (
                    guild_id,
                    channel_id,
                    message_id,
                    template
                )
                VALUES ($1, $2, $3, $4)
                """,
                ctx.guild.id,
                channel.id,
                message.id,
                script.template,
            )
        except UniqueViolationError:
            return await ctx.warn(
                "A sticky message already exists for that channel",
            )
        except HTTPException as exc:
            return await ctx.warn(
                "Your sticky message wasn't able to be sent", codeblock(exc.text)
            )

        return await ctx.approve(
            f"Added {vowel(script.format)} sticky message to {channel.mention}",
        )

    @sticky.command(
        name="existing",
        aliases=["from"],
        description="manage messages",
        usage="<channel> <message>",
        brief="#general https://discord.com/channels/1135484270740246578/1143553248284909568/1251954329171267685",
    )
    @has_permissions(manage_messages=True)
    async def sticky_existing(
        self,
        ctx: Context,
        channel: TextChannel,
        message: Message,
    ) -> Message:
        """
        Add a sticky message to a channel from an existing message.
        """

        script = Script.from_message(message)
        if not script:
            return await ctx.warn("That message doesn't have any content")

        return await self.sticky_add(ctx, channel, script=script)

    @sticky.command(
        name="edit",
        aliases=["update"],
        description="manage messages",
        usage="<channel> <script>",
        brief="#general Follow the rules.",
    )
    @has_permissions(manage_messages=True)
    async def sticky_edit(
        self,
        ctx: Context,
        channel: TextChannel,
        *,
        script: Script,
    ) -> Message:
        """
        Edit an existing sticky message.
        """

        message_id = cast(
            Optional[int],
            await self.bot.db.fetchval(
                """
                UPDATE sticky_message
                SET template = $3
                WHERE guild_id = $1
                AND channel_id = $2
                RETURNING message_id
                """,
                ctx.guild.id,
                channel.id,
                script.template,
            ),
        )
        if not message_id:
            return await ctx.warn(f"{channel.mention} doesn't have a sticky message")

        message = channel.get_partial_message(message_id)
        await quietly_delete(message)

        try:
            message = await script.send(channel)
        except HTTPException as exc:
            return await ctx.warn(
                "Your sticky message wasn't able to be sent", codeblock(exc.text)
            )

        await self.bot.db.execute(
            """
            UPDATE sticky_message
            SET message_id = $3
            WHERE guild_id = $1
            AND channel_id = $2
            """,
            ctx.guild.id,
            channel.id,
            message.id,
        )

        return await ctx.approve(f"Updated the sticky message in {channel.mention}")

    @sticky.command(
        name="remove",
        aliases=["delete", "del", "rm"],
        description="manage messages",
        usage="<channel>",
        brief="#general",
    )
    @has_permissions(manage_messages=True)
    async def sticky_remove(
        self,
        ctx: Context,
        channel: TextChannel,
    ) -> Message:
        """
        Remove a sticky message from a channel.
        """

        message_id = cast(
            Optional[int],
            await self.bot.db.fetchval(
                """
                DELETE FROM sticky_message
                WHERE guild_id = $1
                AND channel_id = $2
                RETURNING message_id
                """,
                ctx.guild.id,
                channel.id,
            ),
        )
        if not message_id:
            return await ctx.warn(f"{channel.mention} doesn't have a sticky message")

        message = channel.get_partial_message(message_id)
        await quietly_delete(message)

        return await ctx.approve(f"Removed the sticky message from {channel.mention}")

    @sticky.command(
        name="view",
        aliases=["show"],
        description="manage messages",
        usage="<channel>",
        brief="#general",
    )
    @has_permissions(manage_messages=True)
    async def sticky_view(
        self,
        ctx: Context,
        channel: TextChannel,
    ) -> Message:
        """
        View an existing sticky message.
        """

        template = cast(
            Optional[str],
            await self.bot.db.fetchval(
                """
                SELECT template
                FROM sticky_message
                WHERE guild_id = $1
                AND channel_id = $2
                """,
                ctx.guild.id,
                channel.id,
            ),
        )
        if not template:
            return await ctx.warn(f"{channel.mention} doesn't have a sticky message")

        script = Script(template, [ctx.guild, ctx.author, channel])

        await ctx.reply(codeblock(script.template))
        return await script.send(ctx.channel)

    @sticky.command(name="list", aliases=["ls"], description="manage messages")
    @has_permissions(manage_guild=True)
    async def sticky_list(self, ctx: Context) -> Message:
        """
        View all channels with sticky messages.
        """

        channels = [
            f"{channel.mention} (`{channel.id}`) - [Message]({message.jump_url})"
            for record in await self.bot.db.fetch(
                """
                SELECT channel_id, message_id
                FROM sticky_message
                WHERE guild_id = $1
                """,
                ctx.guild.id,
            )
            if (channel := ctx.guild.get_channel(record["channel_id"]))
            and isinstance(channel, TextChannel)
            and (message := channel.get_partial_message(record["message_id"]))
        ]
        if not channels:
            return await ctx.warn("No sticky messages exist for this server")

        paginator = Paginator(
            ctx,
            entries=channels,
            embed=Embed(title="Sticky Messages"),
        )
        return await paginator.start()
