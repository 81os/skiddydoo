from re import search

from asyncpg import UniqueViolationError
from discord import Embed, Message
from discord.ext.commands import Cog, group, has_permissions

from tools import CompositeMetaClass, MixinMeta
from tools.client import Context
from tools.formatter import plural
from tools.paginator import Paginator

from .entry import AliasEntry


class Alias(MixinMeta, metaclass=CompositeMetaClass):
    """
    The Alias mixin provides tools for managing command shortcuts.
    """

    def is_command(self, name: str) -> bool:
        """
        Check if a command exists.
        """

        command = self.bot.get_command(name)
        return command is not None

    def is_valid(self, name: str) -> bool:
        """
        Check if an alias is valid.
        """

        return not bool(search(r"\s", name)) and name.isprintable()

    @Cog.listener("on_message_without_command")
    async def alias_listener(self, ctx: Context) -> None:
        """
        Invokes an alias if one is provided.
        """

        prefix = ctx.prefix or ctx.clean_prefix

        try:
            potential_alias = ctx.message.content[len(prefix) :].split(" ")[0]
        except IndexError:
            return

        alias = await AliasEntry.get(ctx.guild, potential_alias)
        if alias:
            await alias(ctx)

    @group(
        aliases=["shortcut"], invoke_without_command=True, description="manage guild"
    )
    @has_permissions(manage_guild=True)
    async def alias(self, ctx: Context) -> Message:
        """
        The base command for managing command shortcuts.

        When ran, aliases will accept any additional arguments and append them to the stored alias.
        Arguments being {0}, {1}, {2}, etc.

        EG: `alias add pic role {0} pic` will invoke `pic role @user` as `pic role @user`.
        """

        return await ctx.send_help(ctx.command)

    @alias.command(
        name="add",
        aliases=["create"],
        description="manage guild",
        usage="<name> <invoke>",
        brief="b, bay",
    )
    @has_permissions(manage_guild=True)
    async def alias_add(self, ctx: Context, name: str, *, invoke: str) -> Message:
        """
        Add an alias for a command.
        """

        if self.is_command(name):
            return await ctx.warn(f"A command with the name **{name}** already exists")

        elif not self.is_valid(name):
            return await ctx.warn("Invalid alias name provided")

        command = self.bot.get_command(invoke.split(maxsplit=1)[0])
        if not command:
            return await ctx.warn("The command provided doesn't exist")

        try:
            await self.bot.db.execute(
                """
                INSERT INTO aliases (
                    guild_id,
                    name,
                    invoke,
                    command
                )
                VALUES ($1, $2, $3, $4)
                """,
                ctx.guild.id,
                name.lower(),
                invoke,
                command.qualified_name,
            )
        except UniqueViolationError:
            return await ctx.warn(f"An alias with the name **{name}** already exists")

        return await ctx.approve(f"Added shortcut **{name}** for `{invoke}`")

    @alias.command(
        name="view",
        aliases=["show"],
        description="manage guild",
        usage="<alias>",
        brief="bay",
    )
    @has_permissions(manage_guild=True)
    async def alias_view(self, ctx: Context, alias: str) -> Message:
        """
        View what an alias invokes.
        """

        invoke = await self.bot.db.fetchval(
            """
            SELECT invoke
            FROM aliases
            WHERE guild_id = $1
            AND name = $2
            """,
            ctx.guild.id,
            alias.lower(),
        )
        if not invoke:
            return await ctx.warn(f"An alias matching **{alias}** doesn't exist")

        return await ctx.approve(f"The **{alias}** shortcut invokes `{invoke}`")

    @alias.command(
        name="remove",
        aliases=["delete", "del", "rm"],
        description="manage guild",
        usage="<alias>",
        brief="bay",
    )
    @has_permissions(manage_guild=True)
    async def alias_remove(self, ctx: Context, alias: str) -> Message:
        """
        Remove an existing alias.
        """

        result = await self.bot.db.execute(
            """
            DELETE FROM aliases
            WHERE guild_id = $1
            AND name = $2
            """,
            ctx.guild.id,
            alias.lower(),
        )
        if result == "DELETE 0":
            return await ctx.warn(f"An alias matching **{alias}** doesn't exist")

        return await ctx.approve(f"Successfully  removed the shortcut **{alias}**")

    @alias.command(name="clear", aliases=["clean", "reset"], description="manage guild")
    @has_permissions(manage_guild=True)
    async def alias_clear(self, ctx: Context) -> Message:
        """
        Remove all command shortcuts.
        """

        await ctx.prompt(
            "Are you sure you want to remove all aliases?",
        )

        result = await self.bot.db.execute(
            """
            DELETE FROM aliases
            WHERE guild_id = $1
            """,
            ctx.guild.id,
        )
        if result == "DELETE 0":
            return await ctx.warn("No aliases exist for this server")

        return await ctx.approve(
            f"Successfully  removed {plural(result, md='`'):command shortcut}"
        )

    @alias.command(name="list", aliases=["ls"], description="manage guild")
    @has_permissions(manage_guild=True)
    async def alias_list(self, ctx: Context) -> Message:
        """
        View all command shortcuts.
        """

        aliases = [
            f"**{record['name']}** invokes `{record['invoke']}`"
            for record in await self.bot.db.fetch(
                """
                SELECT name, invoke, command
                FROM aliases
                WHERE guild_id = $1
                """,
                ctx.guild.id,
            )
            if self.bot.get_command(record["command"]) is not None
        ]
        if not aliases:
            return await ctx.warn("No aliases exist for this server")

        paginator = Paginator(
            ctx,
            entries=aliases,
            embed=Embed(title="Command Shortcuts"),
        )
        return await paginator.start()
