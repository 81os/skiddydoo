from typing import Annotated, List, Optional, Union, cast

from asyncpg import UniqueViolationError
from discord import Embed, Member, Message, Role, TextChannel
from discord.ext.commands import BadArgument, Command, Converter, group, has_permissions

from tools import CompositeMetaClass, MixinMeta
from tools.client import Context
from tools.conversion.discord import TouchableMember
from tools.formatter import plural
from tools.paginator import Paginator


class CommandConverter(Converter):
    async def convert(self, ctx: Context, argument: str) -> Command:
        command = ctx.bot.get_command(argument)
        if command is None:
            raise BadArgument(f"Command `{argument}` not found")

        elif command.qualified_name.startswith("command"):
            raise BadArgument("You cannot disable this command")

        return command


class CommandManagement(MixinMeta, metaclass=CompositeMetaClass):
    """
    The Commands mixin allows server administrators
    to disable or enable specific commands.
    """

    async def cog_load(self) -> None:
        self.bot.add_check(self.check_command_restrictions)
        return await super().cog_load()

    async def cog_unload(self) -> None:
        self.bot.remove_check(self.check_command_restrictions)
        return await super().cog_unload()

    async def check_command_restrictions(self, ctx: Context) -> bool:
        """
        Check the restrictions for a command.

        If the command is disabled in the current channel,
        or the user doesn't have a role which is allowed to use the command.
        """

        if (
            not ctx.guild
            or not ctx.command
            or not isinstance(ctx.author, Member)
            or ctx.author.guild_permissions.administrator
        ):
            return True

        elif await self.bot.db.fetchrow(
            """
            SELECT 1
            FROM commands.ignore
            WHERE guild_id = $1
            AND (
                target_id = $2
                OR target_id = $3
            )
            """,
            ctx.guild.id,
            ctx.author.id,
            ctx.channel.id,
        ):
            return False

        elif await self.bot.db.fetchrow(
            """
            SELECT 1
            FROM commands.disabled
            WHERE guild_id = $1
            AND channel_id = $2
            AND (
                command = $3
                OR command = $4
            )
            """,
            ctx.guild.id,
            ctx.channel.id,
            ctx.command.qualified_name,
            (
                ctx.command.parent.qualified_name  # type: ignore
                if ctx.command.parent
                else None
            ),
        ):
            return False

        elif await self.bot.db.fetchrow(
            """
                SELECT 1
                FROM commands.restricted
                WHERE guild_id = $1
                AND NOT role_id = ANY($2::BIGINT[])
                AND (
                    command = $3
                    OR command = $4
                )
                """,
            ctx.guild.id,
            [role.id for role in ctx.author.roles],
            ctx.command.qualified_name,
            (
                ctx.command.parent.qualified_name  # type: ignore
                if ctx.command.parent
                else None
            ),
        ):
            return False

        return True

    @group(invoke_without_command=True, description="administrator")
    @has_permissions(administrator=True)
    async def ignore(
        self,
        ctx: Context,
        *,
        target: Union[TextChannel, Member],
    ) -> Message:
        """
        Prevent a channel or member from invoking commands.
        """

        result = cast(
            bool,
            await self.bot.db.fetchval(
                """
                INSERT INTO commands.ignore (guild_id, target_id)
                VALUES ($1, $2)
                ON CONFLICT (guild_id, target_id) DO NOTHING
                RETURNING TRUE
                """,
                ctx.guild.id,
                target.id,
            ),
        )
        if not result:
            return await ctx.warn(f"{target.mention} is already being ignored")

        return await ctx.approve(f"Now ignoring {target.mention}")

    @ignore.command(
        name="remove",
        aliases=[
            "delete",
            "del",
            "rm",
        ],
        description="administrator",
        usage="<target|channel|member>",
        brief="@yurrion",
    )
    @has_permissions(administrator=True)
    async def ignore_remove(
        self,
        ctx: Context,
        *,
        target: Union[TextChannel, Member],
    ) -> Message:
        """
        Remove an entity from being ignored.
        """

        result = await self.bot.db.execute(
            """
            DELETE FROM commands.ignore
            WHERE guild_id = $1
            AND target_id = $2
            """,
            ctx.guild.id,
            target.id,
        )
        if not result:
            return await ctx.warn(f"{target.mention} isn't being ignored")

        return await ctx.approve(f"Now allowing {target.mention} to invoke commands")

    @ignore.command(name="list", aliases=["ls"], description="administrator")
    @has_permissions(administrator=True)
    async def ignore_list(self, ctx: Context) -> Message:
        """
        View all entities being ignored.
        """

        targets = [
            f"**{target}** (`{target.id}`)"
            for record in await self.bot.db.fetch(
                """
                SELECT target_id
                FROM commands.ignore
                WHERE guild_id = $1
                """,
                ctx.guild.id,
            )
            if (target := ctx.guild.get_member(record["target_id"]))
            or (target := ctx.guild.get_channel(record["target_id"]))
        ]
        if not targets:
            return await ctx.warn("No members are being ignored")

        paginator = Paginator(
            ctx,
            entries=targets,
            embed=Embed(title="Ignored Entities"),
        )
        return await paginator.start()

    @group(aliases=["cmd"], invoke_without_command=True, description="administrator")
    @has_permissions(administrator=True)
    async def command(self, ctx: Context) -> Message:
        """
        Configure command restrictions.

        If you were to run this command on a command like `voicemaster`,
        it would disable or restrict every subcommand as well.

        Moderators are able to use the command regardless of the settings.
        """

        return await ctx.send_help(ctx.command)

    @group(
        name="disable",
        invoke_without_command=True,
        description="administrator",
        usage="[channel] <command>",
        brief="#general ban",
    )
    @has_permissions(administrator=True)
    async def command_disable(
        self,
        ctx: Context,
        channel: Optional[TextChannel],
        *,
        command: Annotated[
            Command,
            CommandConverter,
        ],
    ) -> Message:
        """
        Disable a command in a specific channel.

        If no channel is provided, the command will be disabled globally.
        """

        if channel is None and not ctx.guild.text_channels:
            return await ctx.warn("This server has no text channels")

        channel_ids: List[int] = [
            record["channel_id"]
            for record in await self.bot.db.fetch(
                """
                SELECT channel_id
                FROM commands.disabled
                WHERE guild_id = $1
                AND command = $2
                """,
                ctx.guild.id,
                command.qualified_name,
            )
        ]
        if channel and channel.id in channel_ids:
            return await ctx.warn(
                f"The command **{command.qualified_name}** is already disabled in {channel.mention}"
            )

        elif not channel and all(
            channel_id in channel_ids for channel_id in ctx.guild.text_channels
        ):
            return await ctx.warn(
                f"The command **{command.qualified_name}** is already disabled in all channels"
            )

        await self.bot.db.executemany(
            """
            INSERT INTO commands.disabled (guild_id, channel_id, command)
            VALUES ($1, $2, $3)
            ON CONFLICT (guild_id, channel_id, command)
            DO NOTHING
            """,
            [
                (ctx.guild.id, channel.id, command.qualified_name)
                for channel in (
                    ctx.guild.text_channels if channel is None else [channel]
                )
            ],
        )

        if not channel:
            return await ctx.approve(
                f"Disabled command **{command.qualified_name}** in {plural(len(ctx.guild.text_channels), md='**'):channel}"
            )

        return await ctx.approve(
            f"Disabled command **{command.qualified_name}** in {channel.mention}"
        )

    @command_disable.command(name="list", aliases=["ls"], description="administrator")
    @has_permissions(administrator=True)
    async def command_disable_list(self, ctx: Context) -> Message:
        """
        View all command restrictions.
        """

        commands = [
            f"**{record['command']}** - {', '.join(channel.mention for channel in channels[:2])}"
            + (f" (+{len(channels) - 2})" if len(channels) > 2 else "")
            for record in await self.bot.db.fetch(
                """
                SELECT command, ARRAY_AGG(channel_id) AS channel_ids
                FROM commands.disabled
                WHERE guild_id = $1
                GROUP BY guild_id, command
                """,
                ctx.guild.id,
            )
            if (
                channels := [
                    channel
                    for channel_id in record["channel_ids"]
                    if (channel := ctx.guild.get_channel(channel_id))
                ]
            )
        ]
        if not commands:
            return await ctx.warn("No commands are disabled for this server")

        paginator = Paginator(
            ctx,
            entries=commands,
            embed=Embed(
                title="Commands Disabled",
            ),
        )
        return await paginator.start()

    @command.command(
        name="enable",
        description="administrator",
        usage="[channel] <command>",
        brief="#general ban",
    )
    @has_permissions(administrator=True)
    async def command_enable(
        self,
        ctx: Context,
        channel: Optional[TextChannel],
        *,
        command: Annotated[
            Command,
            CommandConverter,
        ],
    ) -> Message:
        """
        Enable a command in a specific channel.

        If no channel is provided, the command will be enabled globally.
        """

        channel_ids: List[int] = [
            record["channel_id"]
            for record in await self.bot.db.fetch(
                """
                SELECT channel_id
                FROM commands.disabled
                WHERE guild_id = $1
                AND command = $2
                """,
                ctx.guild.id,
                command.qualified_name,
            )
        ]
        if channel and channel.id not in channel_ids:
            return await ctx.warn(
                f"The command **{command.qualified_name}** is already enabled in {channel.mention}"
            )

        elif not channel and not channel_ids:
            return await ctx.warn(
                f"The command **{command.qualified_name}** is already enabled in all channels"
            )

        await self.bot.db.execute(
            """
            DELETE FROM commands.disabled
            WHERE guild_id = $1
            AND command = $2
            AND channel_id = ANY($3::BIGINT[])
            """,
            ctx.guild.id,
            command.qualified_name,
            channel_ids if channel is None else [channel.id],
        )

        if not channel:
            return await ctx.approve(
                f"Enabled command **{command.qualified_name}** in {plural(len(channel_ids), md='**'):channel}"
            )

        return await ctx.approve(
            f"Enabled command **{command.qualified_name}** in {channel.mention}"
        )

    @group(
        name="restrict",
        aliases=["allow"],
        invoke_without_command=True,
        description="administrator",
        usage="<role> <command>",
        brief="@Admin ban",
    )
    @has_permissions(administrator=True)
    async def command_restrict(
        self,
        ctx: Context,
        role: Role,
        *,
        command: Annotated[
            Command,
            CommandConverter,
        ],
    ) -> Message:
        """
        Restrict a command to a specific role.

        This will remove an existing restriction if one exists.
        """

        try:
            await self.bot.db.execute(
                """
                INSERT INTO commands.restricted (guild_id, role_id, command)
                VALUES ($1, $2, $3)
                """,
                ctx.guild.id,
                role.id,
                command.qualified_name,
            )
        except UniqueViolationError:
            await self.bot.db.execute(
                """
                DELETE FROM commands.restricted
                WHERE guild_id = $1
                AND role_id = $2
                AND command = $3
                """,
                ctx.guild.id,
                role.id,
                command.qualified_name,
            )
            return await ctx.approve(
                f"Removed the restriction on **{command.qualified_name}** for {role.mention}"
            )

        return await ctx.approve(
            f"Now allowing {role.mention} to use **{command.qualified_name}**"
        )

    @command_restrict.command(name="list", aliases=["ls"], description="administrator")
    @has_permissions(administrator=True)
    async def command_restrict_list(self, ctx: Context) -> Message:
        """
        View all command restrictions.
        """

        commands = [
            f"**{record['command']}** - {', '.join(role.mention for role in roles)}"
            for record in await self.bot.db.fetch(
                """
                SELECT command, ARRAY_AGG(role_id) AS role_ids
                FROM commands.restricted
                WHERE guild_id = $1
                GROUP BY guild_id, command
                """,
                ctx.guild.id,
            )
            if (
                roles := [
                    role
                    for role_id in record["role_ids"]
                    if (role := ctx.guild.get_role(role_id))
                ]
            )
        ]
        if not commands:
            return await ctx.warn("No restrictions exist for this server")

        paginator = Paginator(
            ctx,
            entries=commands,
            embed=Embed(
                title="Command Restrictions",
            ),
        )
        return await paginator.start()
