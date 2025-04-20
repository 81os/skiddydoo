import asyncio
from logging import getLogger
from random import uniform
from typing import Annotated, List, Literal, cast

from discord import Embed, Guild, HTTPException, Member, Message, Role
from discord.ext.commands import Cog, Range, flag, group, has_permissions
from humanfriendly import format_timespan

from tools import CompositeMetaClass, MixinMeta
from tools.client import Context, FlagConverter
from tools.conversion import StrictRole
from tools.formatter import plural
from tools.paginator import Paginator

log = getLogger("zyn/roles")


class Flags(FlagConverter):
    delay: Range[int, 1, 160] = flag(
        default=0,
        description="The delay in seconds before the role is assigned or removed.",
    )


class AutoRoles(MixinMeta, metaclass=CompositeMetaClass):
    """
    Automatically assign roles to new members.
    """

    @group(invoke_without_command=True, description="manage roles")
    @has_permissions(manage_roles=True)
    async def autorole(self, ctx: Context) -> Message:
        """
        Automatically assign roles to new members.
        """

        return await ctx.send_help(ctx.command)

    @autorole.group(
        name="reassign",
        aliases=["restore"],
        description="manage roles",
        invoke_without_command=True,
    )
    @has_permissions(manage_roles=True)
    async def autorole_reassign(self, ctx: Context) -> Message:
        """
        Toggle reassigning roles to members which rejoin.
        """

        await ctx.settings.update(reassign_roles=not ctx.settings.reassign_roles)
        return await ctx.approve(
            f"{'Now' if ctx.settings.reassign_roles else 'No longer'} reassigning roles to members which rejoin"
        )

    @autorole_reassign.group(
        name="ignore",
        aliases=["exempt"],
        description="manage roles",
        invoke_without_command=True,
    )
    @has_permissions(manage_roles=True)
    async def autorole_reassign_ignore(
        self,
        ctx: Context,
        *,
        role: Annotated[
            Role,
            StrictRole,
        ],
    ) -> Message:
        """
        Ignore a role from being unintentionally reassigned.
        """

        if role in ctx.settings.reassign_ignore:
            return await ctx.warn(f"{role.mention} is already being ignored")

        ctx.settings.reassign_ignore_ids.append(role.id)
        await ctx.settings.update()
        return await ctx.approve(f"Now ignoring {role.mention} from being reassigned")

    @autorole_reassign_ignore.command(
        name="remove",
        aliases=["delete", "del", "rm"],
        description="manage roles",
        usage="<role>",
        brief="@Admins",
    )
    @has_permissions(manage_roles=True)
    async def autorole_reassign_ignore_remove(
        self,
        ctx: Context,
        *,
        role: Annotated[
            Role,
            StrictRole,
        ],
    ) -> Message:
        """
        Remove a role from being ignored.
        """

        if role not in ctx.settings.reassign_ignore:
            return await ctx.warn(f"{role.mention} isn't being ignored")

        ctx.settings.reassign_ignore_ids.remove(role.id)
        await ctx.settings.update()
        return await ctx.approve(f"Now allowing {role.mention} to be reassigned")

    @autorole_reassign_ignore.command(
        name="list", aliases=["ls"], description="manage roles"
    )
    @has_permissions(manage_roles=True)
    async def autorole_reassign_ignore_list(self, ctx: Context) -> Message:
        """
        View all roles being ignored.
        """

        if not ctx.settings.reassign_ignore:
            return await ctx.warn("No roles are being ignored")

        paginator = Paginator(
            ctx,
            entries=[
                f"{role.mention} (`{role.id}`)" for role in ctx.settings.reassign_ignore
            ],
            embed=Embed(title="Ignored Roles"),
        )
        return await paginator.start()

    @autorole.command(
        name="add",
        aliases=["create"],
        description="manage roles",
        usage="<role> [flags]",
        brief="@Members",
    )
    @has_permissions(manage_roles=True)
    async def autorole_add(
        self,
        ctx: Context,
        role: Annotated[
            Role,
            StrictRole(check_dangerous=True),
        ],
        *,
        flags: Flags,
    ) -> Message:
        """
        Add a new auto role.
        """

        await self.bot.db.execute(
            """
                INSERT INTO auto_role (
                guild_id,
                role_id,
                action,
                delay
            ) VALUES (
                $1,
                $2,
                $3,
                $4
            )
            """,
            ctx.guild.id,
            role.id,
            "add",
            float(flags.delay),
        )

        return await ctx.approve(f"Now assigning {role.mention} to new members")

    @autorole.command(
        name="remove",
        aliases=["delete", "del", "rm"],
        description="manage roles",
        usage="<role>",
        brief="@Admins",
    )
    @has_permissions(manage_roles=True)
    async def autorole_remove(
        self,
        ctx: Context,
        role: Annotated[
            Role,
            StrictRole,
        ],
    ) -> Message:
        """
        Remove an existing auto role.
        """

        result = await self.bot.db.execute(
            """
            DELETE FROM auto_role
            WHERE guild_id = $1
            AND role_id = $2
            """,
            ctx.guild.id,
            role.id,
        )
        if result == "DELETE 0":
            return await ctx.warn(f"{role.mention} is not an existing auto role")

        return await ctx.approve(f"Successfully removed {role.mention} as an auto role")

    @autorole.command(
        name="clear", aliases=["clean", "reset"], description="manage roles"
    )
    @has_permissions(manage_roles=True)
    async def autorole_clear(self, ctx: Context) -> Message:
        """
        Remove all auto roles.
        """

        await ctx.prompt(
            "Are you sure you want to remove all auto roles?",
        )

        result = await self.bot.db.execute(
            """
            DELETE FROM auto_role
            WHERE guild_id = $1
            """,
            ctx.guild.id,
        )
        if result == "DELETE 0":
            return await ctx.warn("No auto roles exist for this server")

        return await ctx.approve(
            f"Successfully  removed {plural(result, md='`'):auto role}"
        )

    @autorole.command(name="list", aliases=["ls"], description="manage roles")
    @has_permissions(manage_roles=True)
    async def autorole_list(self, ctx: Context) -> Message:
        """
        View all auto roles.
        """

        roles = [
            f"**{record['action'].upper()}** {role.mention}"
            + (
                f" after **{format_timespan(record['delay'])}**"
                if record["delay"]
                else ""
            )
            for record in await self.bot.db.fetch(
                """
                SELECT role_id, action, delay
                FROM auto_role
                WHERE guild_id = $1
                """,
                ctx.guild.id,
            )
            if (role := ctx.guild.get_role(record["role_id"])) is not None
        ]
        if not roles:
            return await ctx.warn("No auto roles exist for this server")

        paginator = Paginator(
            ctx,
            entries=roles,
            embed=Embed(
                title="Auto Roles",
            ),
        )
        return await paginator.start()

    async def assign_auto_role(
        self,
        guild: Guild,
        role: Role,
        member_id: int,
        action: Literal["add", "remove"],
        delay: float,
    ) -> None:
        """
        Assign or remove an auto role.
        """

        delay = delay or uniform(0.5, 1.5)
        await asyncio.sleep(delay)

        member = guild.get_member(member_id)
        if (
            member is None
            or not guild.me.guild_permissions.manage_roles
            or role >= guild.me.top_role
        ):
            return

        try:
            if action == "add" and role not in member.roles:
                await member.add_roles(role, reason="Auto role")

            elif action == "remove" and role in member.roles:
                await member.remove_roles(role, reason="Auto role")

        except HTTPException:
            log.debug(
                "Failed to %s auto role %s (%s) in %s (%s).",
                action,
                role.name,
                role.id,
                member.guild.name,
                member.guild.id,
            )

    @Cog.listener("on_member_join")
    async def autorole_event(self, member: Member) -> None:
        """
        Automatically assign roles to new members.
        """

        guild = member.guild
        records = await self.bot.db.fetch(
            """
            SELECT role_id, action, delay
            FROM auto_role
            WHERE guild_id = $1
            """,
            member.guild.id,
        )

        scheduled_deletion: List[int] = []
        for record in records:
            role_id = cast(int, record["role_id"])
            role = guild.get_role(role_id)
            if not role:
                scheduled_deletion.append(role_id)
                continue

            asyncio.create_task(
                self.assign_auto_role(
                    guild,
                    role,
                    member.id,
                    record["action"],
                    record["delay"],
                )
            )

        if scheduled_deletion:
            await self.bot.db.execute(
                """
                DELETE FROM auto_role
                WHERE guild_id = $1
                AND role_id = ANY($2::BIGINT[])
                """,
                member.guild.id,
                scheduled_deletion,
            )
