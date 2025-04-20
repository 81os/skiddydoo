import asyncio
import re
from contextlib import suppress

from asyncpg import UniqueViolationError
from discord import Embed, HTTPException, Message, TextChannel
from discord.ext.commands import Cog, group, has_permissions
from xxhash import xxh32_hexdigest

from tools import CompositeMetaClass, MixinMeta, quietly_delete
from tools.client import Context
from tools.paginator import Paginator

IMAGE_PATTERN = re.compile(
    r"(?:([^:/?#]+):)?(?://([^/?#]*))?([^?#]*\.(?:png|jpe?g|gif))(?:\?([^#]*))?(?:#(.*))?"
)


class Gallery(MixinMeta, metaclass=CompositeMetaClass):
    """
    Restrict channels to only allow images.
    """

    @group(
        aliases=["imgonly"], invoke_without_command=True, description="manage channels"
    )
    @has_permissions(manage_channels=True)
    async def gallery(self, ctx: Context) -> Message:
        """
        Restrict channels to only allow images.
        """
        return await ctx.send_help(ctx.command)

    @gallery.command(
        name="add",
        aliases=["create"],
        description="manage channels",
        usage="<channel>",
        brief="#pictures",
    )
    @has_permissions(manage_channels=True)
    async def gallery_add(self, ctx: Context, *, channel: TextChannel) -> Message:
        """
        Add a gallery channel.
        """
        try:
            await self.bot.db.execute(
                """
                INSERT INTO gallery (guild_id, channel_id)
                VALUES ($1, $2)
                """,
                ctx.guild.id,
                channel.id,
            )
        except UniqueViolationError:
            return await ctx.warn("That channel is already a gallery channel")

        return await ctx.approve(
            f"Now restricting {channel.mention} to only allow images"
        )

    @gallery.command(
        name="remove",
        aliases=["delete", "del", "rm"],
        description="manage channels",
        usage="<channel>",
        brief="#pictures",
    )
    @has_permissions(manage_channels=True)
    async def gallery_remove(self, ctx: Context, *, channel: TextChannel) -> Message:
        """
        Remove a gallery channel.
        """
        result = await self.bot.db.execute(
            """
            DELETE FROM gallery
            WHERE guild_id = $1
            AND channel_id = $2
            """,
            ctx.guild.id,
            channel.id,
        )
        if result == "DELETE 0":
            return await ctx.warn("That channel isn't a gallery channel")

        return await ctx.approve(
            f"No longer restricting {channel.mention} to only allow images"
        )

    @gallery.command(
        name="clear", aliases=["clean", "reset"], description="manage guild"
    )
    @has_permissions(manage_guild=True)
    async def gallery_clear(self, ctx: Context) -> Message:
        """
        Remove all gallery channels.
        """
        result = await self.bot.db.execute(
            """
            DELETE FROM gallery
            WHERE guild_id = $1
            """,
            ctx.guild.id,
        )
        if result == "DELETE 0":
            return await ctx.warn("No gallery channels exist for this server")

        return await ctx.approve("Successfully removed all gallery channels")

    @gallery.command(name="list", aliases=["ls"], description="manage guild")
    @has_permissions(manage_guild=True)
    async def gallery_list(self, ctx: Context) -> Message:
        """
        View all gallery channels.
        """
        channels = [
            f"{channel.mention} (`{channel.id}`)"
            for record in await self.bot.db.fetch(
                """
                SELECT channel_id
                FROM gallery
                WHERE guild_id = $1
                """,
                ctx.guild.id,
            )
            if (channel := ctx.guild.get_channel(record["channel_id"]))
        ]
        if not channels:
            return await ctx.warn("No gallery channels exist for this server")

        paginator = Paginator(
            ctx,
            entries=channels,
            embed=Embed(title="Gallery Channels"),
        )
        return await paginator.start()

    @Cog.listener("on_message")
    async def gallery_listener(self, message: Message) -> None:
        """
        Delete messages that aren't images in gallery channels.
        """
        if (
            not message.guild
            or message.author.bot
            or not isinstance(message.channel, TextChannel)
        ):
            return

        if not await self.bot.db.fetchrow(
            """
            SELECT channel_id
            FROM gallery
            WHERE guild_id = $1
            AND channel_id = $2
            """,
            message.guild.id,
            message.channel.id,
        ):
            return

        if message.attachments or IMAGE_PATTERN.match(message.content):
            return

        key = xxh32_hexdigest(f"gallery:{message.channel.id}")
        if not await self.bot.redis.ratelimited(key, 6, 10):
            await quietly_delete(message)

        locked = await self.bot.redis.get(key)
        if locked:
            return

        await self.bot.redis.set(key, 1, 15)
        await asyncio.sleep(15)

        with suppress(HTTPException):
            await message.channel.purge(
                limit=200,
                check=lambda m: (
                    not m.attachments
                    and not IMAGE_PATTERN.match(m.content)
                    and not m.author.bot
                ),
                after=message,
            )
