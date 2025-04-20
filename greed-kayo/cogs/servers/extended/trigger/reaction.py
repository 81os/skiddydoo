from typing import List, cast

from asyncpg import UniqueViolationError
from discord import Embed, HTTPException, Message, NotFound
from discord.ext.commands import Cog, Range, group, has_permissions
from xxhash import xxh64_hexdigest

from tools import CompositeMetaClass, MixinMeta
from tools.client import Context
from tools.formatter import plural
from tools.paginator import Paginator
from logging import getLogger

log = getLogger("reactions")


class Reaction(MixinMeta, metaclass=CompositeMetaClass):
    """
    Automatically react to messages.
    """

    @Cog.listener("on_message_without_command")
    async def reaction_listener(self, ctx: Context) -> None:
        reactions = cast(
            List[str],
            await self.bot.db.fetchval(
                """
                SELECT ARRAY_AGG(emoji)
                FROM reaction_trigger
                WHERE guild_id = $1
                AND LOWER($2) LIKE '%' || LOWER(trigger) || '%'
                GROUP BY trigger
                """,
                ctx.guild.id,
                ctx.message.content,
            ),
        )
        if not reactions:
            return

        KEY = xxh64_hexdigest(f"reactions:{ctx.author.id}")
        if await self.bot.redis.ratelimited(KEY, 1, 3):
            return

        scheduled_deletion: List[str] = []
        for reaction in reactions:
            try:
                await ctx.message.add_reaction(reaction)
            except NotFound:
                scheduled_deletion.append(reaction)
            except (HTTPException, TypeError):
                ...

        if scheduled_deletion:
            await self.bot.db.execute(
                """
                DELETE FROM reaction_trigger
                WHERE guild_id = $1
                AND emoji = ANY($2::TEXT[])
                """,
                ctx.guild.id,
                scheduled_deletion,
            )

        await self.bot.process_commands(ctx.message)

    @group(
        aliases=["react", "rt", "autoreaction"],
        invoke_without_command=True,
    )
    @has_permissions(manage_messages=True)
    async def reaction(self, ctx: Context) -> Message:
        """
        Automatically react to messages.
        """

        return await ctx.send_help(ctx.command)

    @reaction.command(
        name="add",
        aliases=["create"],
        description="manage messages",
        usage="<emoji> <trigger>",
        brief=":skull: skull",
    )
    @has_permissions(manage_messages=True)
    async def reaction_add(
        self,
        ctx: Context,
        emoji: str,
        *,
        trigger: Range[str, 1, 50],
    ) -> Message:
        """
        Add a new reaction trigger.
        """

        try:
            await ctx.message.add_reaction(emoji)
        except (HTTPException, TypeError):
            return await ctx.warn("I couldn't add the reaction to the message")

        records = cast(
            int,
            await self.bot.db.fetchval(
                """
                SELECT COUNT(*)
                FROM reaction_trigger
                WHERE guild_id = $1
                AND trigger = LOWER($2)
                """,
                ctx.guild.id,
                trigger,
            ),
        )
        if records >= 3:
            return await ctx.warn("You can't have more than `3` reactions per trigger")

        try:
            await self.bot.db.execute(
                """
                INSERT INTO reaction_trigger (
                    guild_id,
                    trigger,
                    emoji
                ) VALUES (
                    $1,
                    $2,
                    $3
                )
                """,
                ctx.guild.id,
                trigger,
                emoji,
            )
        except UniqueViolationError:
            return await ctx.warn(
                f"A reaction trigger with {emoji} for **{trigger}** already exists"
            )

        return await ctx.approve(f"Now reacting with {emoji} for **{trigger}**")

    @reaction.command(
        name="remove",
        aliases=["delete", "del", "rm"],
        description="manage messages",
        usage="<emoji> <trigger>",
        brief=":skull: skull",
    )
    @has_permissions(manage_messages=True)
    async def reaction_remove(
        self,
        ctx: Context,
        emoji: str,
        *,
        trigger: Range[str, 1, 50],
    ) -> Message:
        """
        Remove a reaction trigger.
        """

        result = await self.bot.db.execute(
            """
            DELETE FROM reaction_trigger
            WHERE guild_id = $1
            AND trigger = LOWER($2)
            """,
            ctx.guild.id,
            trigger,
        )
        if result == "DELETE 0":
            return await ctx.warn(
                f"No reaction trigger with {emoji} for **{trigger}** exists"
            )

        return await ctx.approve(f"No longer reacting with {emoji} for **{trigger}**")

    @reaction.command(
        name="clear",
        aliases=["clean", "reset"],
        description="manage messages",
    )
    @has_permissions(manage_messages=True)
    async def reaction_clear(self, ctx: Context) -> Message:
        """
        Remove all reaction triggers.
        """

        await ctx.prompt(
            "Are you sure you want to remove all reaction triggers?",
        )

        result = await self.bot.db.execute(
            """
            DELETE FROM reaction_trigger
            WHERE guild_id = $1
            """,
            ctx.guild.id,
        )
        if result == "DELETE 0":
            return await ctx.warn("No reaction triggers exist for this server")

        return await ctx.approve(
            f"Successfully removed {plural(result, md='`'):reaction trigger}"
        )

    @reaction.command(name="list", aliases=["ls"], description="manage messages")
    @has_permissions(manage_guild=True)
    async def reaction_list(self, ctx: Context) -> Message:
        """
        View all reaction triggers.
        """

        triggers = [
            f"**{record['trigger']}** | {', '.join(record['emojis'])}"
            for record in await self.bot.db.fetch(
                """
                SELECT
                    trigger,
                    ARRAY_AGG(emoji) AS emojis
                FROM reaction_trigger
                WHERE guild_id = $1
                GROUP BY trigger
                """,
                ctx.guild.id,
            )
        ]
        if not triggers:
            return await ctx.warn("No reaction triggers exist for this server")

        paginator = Paginator(
            ctx,
            entries=triggers,
            embed=Embed(
                title="Reaction Triggers",
            ),
        )
        return await paginator.start()
