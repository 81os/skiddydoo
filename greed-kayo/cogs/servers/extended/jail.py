from discord import TextChannel, Member, Message, Role
from discord.ext.commands import command, has_permissions, Cog
from discord.ext import tasks
from datetime import datetime, timedelta, timezone
import humanfriendly

from discord.abc import GuildChannel
from tools import CompositeMetaClass, MixinMeta
from tools.client import Context


class Jail(MixinMeta, metaclass=CompositeMetaClass):
    def __init__(self, bot):
        self.bot = bot
        self.check_unjail.start()

    def cog_unload(self):
        self.check_unjail.cancel()

    @command(description="Set up jail channel and role", aliases=["setme", "setjail"])
    @has_permissions(manage_guild=True)
    async def setupjail(self, ctx: Context, channel: TextChannel = None) -> Message:
        if not channel:
            channel = await ctx.guild.create_text_channel("jailed")

        role = await ctx.guild.create_role(
            name="jailed", reason="Role for jailed members"
        )
        for c in ctx.guild.channels:
            await c.set_permissions(role, send_messages=False, view_channel=False)

        await self.bot.db.execute(
            "INSERT INTO jail.channel (guild_id, channel_id, role_id) VALUES ($1, $2, $3) "
            "ON CONFLICT (guild_id) DO UPDATE SET channel_id = $2, role_id = $3",
            ctx.guild.id,
            channel.id,
            role.id,
        )
        await channel.set_permissions(
            ctx.guild.default_role, send_messages=False, view_channel=False
        )
        await ctx.approve(
            f"Jail channel set to {channel.mention} and jail role created"
        )

    @command(description="Jail a member", brief="@yurrion 2d bad boy")
    @has_permissions(manage_messages=True)
    async def jail(
        self,
        ctx: Context,
        member: Member,
        duration: str = "7 days",
        *,
        reason: str = "No reason provided",
    ) -> Message:
        """jails a member"""
        jail_channel_id, jail_role_id = await self.bot.db.fetchrow(
            "SELECT channel_id, role_id FROM jail.channel WHERE guild_id = $1",
            ctx.guild.id,
        )
        if not jail_channel_id:
            await self.setupjail(ctx)
            jail_channel_id, jail_role_id = await self.bot.db.fetchrow(
                "SELECT channel_id, role_id FROM jail.channel WHERE guild_id = $1",
                ctx.guild.id,
            )

        jail_channel = ctx.guild.get_channel(jail_channel_id)
        jail_role = ctx.guild.get_role(jail_role_id)
        if not jail_channel or not jail_role:
            return await ctx.warn(
                "Jail channel or role does not exist. Please set it up again using `setupjail`."
            )

        roles = [role.id for role in member.roles if role != ctx.guild.default_role]

        try:
            delta_seconds = humanfriendly.parse_timespan(duration)
            delta = timedelta(seconds=delta_seconds)
        except humanfriendly.InvalidTimespan:
            return await ctx.send(
                "Invalid duration format. Use formats like '1 week', '3 days', '2 hours', etc."
            )

        now = datetime.now(timezone.utc).replace(tzinfo=None)
        expires_at = now + delta

        await self.bot.db.execute(
            "INSERT INTO jail.users (user_id, guild_id, jailed_at, unjailed_at, roles, reason, duration, expires_at) VALUES ($1, $2, $3, NULL, $4, $5, $6, $7)",
            member.id,
            ctx.guild.id,
            now,
            roles,
            reason,
            delta,
            expires_at,
        )
        await member.edit(roles=[ctx.guild.default_role, jail_role])
        return await ctx.approve(
            f"{member.mention} has been jailed for {duration} because {reason}"
        )

    @command(description="Unjail a member", brief="@yurrion")
    @has_permissions(manage_messages=True)
    async def unjail(self, ctx: Context, member: Member):
        """unjails a member"""
        jailed_data = await self.bot.db.fetchrow(
            "SELECT roles FROM jail.users WHERE user_id = $1 AND guild_id = $2",
            member.id,
            ctx.guild.id,
        )
        if not jailed_data:
            return await ctx.send(f"{member.mention} is not jailed.")

        roles = [ctx.guild.get_role(role_id) for role_id in jailed_data["roles"]]
        jail_role = ctx.guild.get_role(
            await self.bot.db.fetchval(
                "SELECT role_id FROM jail.channel WHERE guild_id = $1", ctx.guild.id
            )
        )
        if jail_role in member.roles:
            await member.remove_roles(jail_role)
        await member.edit(roles=roles)
        await self.bot.db.execute(
            "DELETE FROM jail.users WHERE user_id = $1 AND guild_id = $2",
            member.id,
            ctx.guild.id,
        )
        await ctx.approve(f"{member.mention} has been unjailed.")

    @Cog.listener()
    async def on_guild_channel_create(self, channel: GuildChannel) -> None:
        jail_role_id = await self.bot.db.fetchval(
            "SELECT role_id FROM jail.channel WHERE guild_id = $1", channel.guild.id
        )
        if jail_role_id:
            jail_role = channel.guild.get_role(jail_role_id)
            await channel.set_permissions(
                jail_role, send_messages=True, view_channel=True
            )

    @tasks.loop(minutes=1)
    async def check_unjail(self):
        now = datetime.now(timezone.utc)
        jailed_users = await self.bot.db.fetch(
            "SELECT user_id, guild_id, roles FROM jail.users WHERE expires_at <= $1",
            now,
        )
        for user in jailed_users:
            guild = self.bot.get_guild(user["guild_id"])
            if guild:
                member = guild.get_member(user["user_id"])
                if member:
                    roles = [guild.get_role(role_id) for role_id in user["roles"]]
                    jail_role = guild.get_role(
                        await self.bot.db.fetchval(
                            "SELECT role_id FROM jail.channel WHERE guild_id = $1",
                            guild.id,
                        )
                    )
                    if jail_role in member.roles:
                        await member.remove_roles(jail_role)
                    await member.edit(roles=roles)
                await self.bot.db.execute(
                    "DELETE FROM jail.users WHERE user_id = $1 AND guild_id = $2",
                    user["user_id"],
                    user["guild_id"],
                )
