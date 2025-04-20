from __future__ import annotations

from contextlib import suppress
from typing import TYPE_CHECKING, Optional

from discord import Member, Role
from discord.ext.commands import (
    BadArgument,
    CommandError,
    MemberConverter,
    RoleConverter,
    RoleNotFound,
    check,
)
from discord.utils import find
import config

if TYPE_CHECKING:
    from tools.client import Context


class FuzzyRole(RoleConverter):
    async def convert(self, ctx: Context, argument: str) -> Role:
        with suppress(CommandError, BadArgument):
            return await super().convert(ctx, argument)

        role = find(
            lambda r: (
                r.name.lower() == argument.lower() or r.name.lower() in argument.lower()
            ),
            ctx.guild.roles,
        )
        if not role:
            raise RoleNotFound(argument)

        return role


class StrictRole(FuzzyRole):
    check_dangerous: bool
    check_integrated: bool
    allow_default: bool

    def __init__(
        self,
        *,
        check_dangerous: bool = False,
        check_integrated: bool = True,
        allow_default: bool = False,
    ) -> None:
        self.check_dangerous = check_dangerous
        self.check_integrated = check_integrated
        self.allow_default = allow_default
        super().__init__()

    @staticmethod
    def dangerous(role: Role) -> bool:
        return any(
            value
            and permission
            in (
                "administrator",
                "kick_members",
                "ban_members",
                "manage_guild",
                "manage_roles",
                "manage_channels",
                "manage_emojis",
                "manage_webhooks",
                "manage_nicknames",
                "mention_everyone",
            )
            for permission, value in role.permissions
        )

    async def check(self, ctx: Context, role: Role) -> None:
        bot = ctx.guild.me
        author = ctx.author
        if self.check_dangerous and self.dangerous(role):
            raise BadArgument(
                f"{role.mention} is a dangerous role and cannot be assigned!"
            )

        if self.check_integrated and role.managed:
            raise BadArgument(
                f"{role.mention} is an integrated role and cannot be assigned!"
            )

        if not self.allow_default and role.is_default():
            raise BadArgument(
                f"{role.mention} is the default role and cannot be assigned!"
            )

        elif role >= bot.top_role and bot.id != ctx.guild.owner_id:
            raise BadArgument(f"{role.mention} is higher than my highest role!")

        elif role >= author.top_role and author.id != ctx.guild.owner_id:
            raise BadArgument(f"{role.mention} is higher than your highest role!")

    async def convert(self, ctx: Context, argument: str) -> Role:
        role = await super().convert(ctx, argument)

        await self.check(ctx, role)
        return role


class TouchableMember(MemberConverter):
    """
    Check if a member is punishable.
    """

    allow_author: bool

    def __init__(self, *, allow_author: bool = False) -> None:
        self.allow_author = allow_author
        super().__init__()

    async def check(self, ctx: Context, member: Member) -> None:
        bot = ctx.guild.me
        author = ctx.author
        command = ctx.command.qualified_name
        if author == member and not self.allow_author:
            raise BadArgument(f"You're not allowed to **{command}** yourself!")

        elif (
            member.top_role >= bot.top_role
            and bot.id != ctx.guild.owner_id
            and (member != bot if command == "nickname" else True)
        ):
            raise BadArgument(f"{member.mention} is higher than my highest role!")

        elif member.top_role >= author.top_role and author.id != ctx.guild.owner_id:
            raise BadArgument(
                f"You're not allowed to **{command}** {member.mention} due to hierarchy!"
            )

    async def convert(self, ctx: Context, argument: str) -> Member:
        member = await super().convert(ctx, argument)

        await self.check(ctx, member)
        return member


def Donator():
    """Check if the user is a donator"""

    async def predicate(ctx: Context) -> Optional[bool]:
        cache_key = f"donor-{ctx.author.id}"
        cached_value = await ctx.bot.redis.get(cache_key)

        if cached_value:
            return cached_value

        async with ctx.bot.session.get(
            f"https://top.gg/api/bots/{ctx.bot.user.id}/check",
            params={"userId": ctx.author.id},
            headers={"Authorization": config.API.TOPGG},
        ) as response:
            data = await response.json()

        if "voted" in data and data["voted"] == 1:
            await ctx.bot.redis.set(cache_key, True, 3600 * 12)
            return True

        check_premium: bool = bool(
            await ctx.db.fetchval(
                """
                SELECT EXISTS(
                    SELECT 1
                    FROM donators
                    WHERE user_id = $1
                )
                """,
                ctx.author.id,
            )
        )

        if check_premium:
            return True

        raise BadArgument(
            f"You must either vote me on [**top.gg**](https://top.gg/bot/{ctx.bot.user.id}/vote) or have premium status to use this command!"
        )

    return check(predicate)  # type: ignore


class TicketChecks:
    @staticmethod
    async def is_ticket_channel(ctx: Context) -> bool:
        check = await ctx.bot.db.fetchrow(
            "SELECT * FROM tickets.opened WHERE guild_id = $1 AND channel_id = $2",
            ctx.guild.id,
            ctx.channel.id,
        )
        if check is None:
            await ctx.warn("This command must be used in an opened ticket channel.")
            return False
        return True

    @staticmethod
    async def has_manage_ticket_permission(ctx: Context) -> bool:
        support_role_id = await ctx.bot.db.fetchval(
            "SELECT support_id FROM tickets.setup WHERE guild_id = $1", ctx.guild.id
        )
        role: Role = ctx.guild.get_role(support_role_id) if support_role_id else None

        if (
            role
            and role not in ctx.author.roles
            and not ctx.author.guild_permissions.manage_channels
        ):
            await ctx.warn(
                f"Only members with the {role.mention} role or those with `manage_channels` permission can manage tickets."
            )
            return False

        if not role and not ctx.author.guild_permissions.manage_channels:
            await ctx.warn(
                "Only members with `manage_channels` permission can manage tickets."
            )
            return False

        return True

    @staticmethod
    async def ensure_ticket_exists(ctx: Context) -> bool:
        exists = await ctx.bot.db.fetchval(
            "SELECT 1 FROM tickets.setup WHERE guild_id = $1", ctx.guild.id
        )
        if not exists:
            await ctx.bot.db.execute(
                "INSERT INTO tickets.setup (guild_id) VALUES ($1)", ctx.guild.id
            )
        return True
