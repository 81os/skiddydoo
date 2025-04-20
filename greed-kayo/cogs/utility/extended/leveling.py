import asyncio
from collections import defaultdict
from typing import Optional

from discord import Embed, Interaction, Member, Message, Role, TextChannel, Forbidden
from discord.ext.commands import (
    BucketType,
    command,
    group,
    Cog,
    CooldownMapping,
    has_permissions,
)

from main import zyn
from tools import CompositeMetaClass, MixinMeta
from tools.client import Context
from tools.parser import Script
from tools.client.context import Confirmation
from tools.paginator import Paginator
from logging import getLogger

log = getLogger("cogs/leveling")


class Leveling(MixinMeta, metaclass=CompositeMetaClass):
    levelcd = CooldownMapping.from_cooldown(3, 3, BucketType.member)
    locks = defaultdict(asyncio.Lock)

    async def get_level_data(self, guild_id: int, user_id: int) -> Optional[dict]:
        return await self.bot.db.fetchrow(
            "SELECT level, xp, target_xp FROM leveling.user WHERE guild_id = $1 AND user_id = $2",
            guild_id,
            user_id,
        )

    async def update_level_data(
        self, guild_id: int, user_id: int, xp: int, level: int, target_xp: int
    ) -> None:
        await self.bot.db.execute(
            "UPDATE leveling.user SET xp = $1, level = $2, target_xp = $3 WHERE guild_id = $4 AND user_id = $5",
            xp,
            level,
            target_xp,
            guild_id,
            user_id,
        )

    async def insert_level_data(
        self, guild_id: int, user_id: int, xp: int, level: int, target_xp: int
    ) -> None:
        await self.bot.db.execute(
            "INSERT INTO leveling.user (guild_id, user_id, xp, level, target_xp) VALUES ($1, $2, $3, $4, $5)",
            guild_id,
            user_id,
            xp,
            level,
            target_xp,
        )

    async def level_replace(self, member: Member, params: str) -> str:
        check = await self.get_level_data(member.guild.id, member.id)
        if check:
            params = params.replace("{level}", str(check["level"]))
            params = params.replace("{target_xp}", str(check["target_xp"]))
        return params

    def get_cooldown(self, message: Message) -> Optional[int]:
        bucket = self.levelcd.get_bucket(message)
        return bucket.update_rate_limit()

    async def give_rewards(self, member: Member, level: int) -> None:
        try:
            results = await self.bot.db.fetch(
                "SELECT role_id FROM leveling.rewards WHERE guild_id = $1 AND level < $2",
                member.guild.id,
                level + 1,
            )
            if results:
                tasks = [
                    member.add_roles(
                        member.guild.get_role(r["role_id"]), reason="Leveled up"
                    )
                    for r in results
                    if member.guild.get_role(r["role_id"])
                    and r["role_id"] not in [role.id for role in member.roles]
                ]
                await asyncio.gather(*tasks)
        except Forbidden:
            log.error("missing permissions!")

    @Cog.listener("on_message_without_command")
    async def level_check(self, message: Message) -> None:
        if message.author.bot or message.guild is None or self.get_cooldown(message):
            return

        guild_id, user_id = message.guild.id, message.author.id
        res = await self.bot.db.fetchrow(
            "SELECT * FROM leveling.setup WHERE guild_id = $1", guild_id
        )
        if not res:
            return

        async with self.locks[user_id]:
            check = await self.get_level_data(guild_id, user_id)

            xp_gain = 6 if res["booster_boost"] and message.author.premium_since else 4
            xp = (check["xp"] + xp_gain) if check else xp_gain
            target_xp = int((100 * (check["level"] if check else 1)) ** 0.9)

            if check:
                await self.update_level_data(
                    guild_id, user_id, xp, check["level"], target_xp
                )
                await self.give_rewards(message.author, check["level"])
            else:
                await self.insert_level_data(guild_id, user_id, xp, 0, target_xp)

            if xp >= target_xp:
                level = (check["level"] if check else 0) + 1
                target_xp = int((100 * level + 1) ** 0.9)
                await self.update_level_data(guild_id, user_id, 0, level, target_xp)

                channel = (
                    message.guild.get_channel(res["channel_id"]) or message.channel
                )
                replaced_message = await self.level_replace(
                    message.author, res["message"]
                )
                script = Script(
                    replaced_message, [message.guild, message.author, message.channel]
                )
                embed_content = script.data

                await channel.send(**embed_content)
                await self.give_rewards(message.author, level)

    @Cog.listener()
    async def on_guild_role_delete(self, role: Role) -> None:
        if await self.bot.db.fetchrow(
            "SELECT * FROM leveling.rewards WHERE guild_id = $1 AND role_id = $2",
            role.guild.id,
            role.id,
        ):
            await self.bot.db.execute(
                "DELETE FROM leveling.rewards WHERE role_id = $1 AND guild_id = $2",
                role.id,
                role.guild.id,
            )

    @command()
    async def rank(self, ctx: Context, *, member: Optional[Member] = None) -> None:
        """views your level/rank"""
        member = member or ctx.author
        level = await self.get_level_data(ctx.guild.id, member.id)
        if not level:
            return await ctx.warn("This member doesn't have a rank recorded")

        embed = Embed()
        embed.set_author(name=str(member), icon_url=member.display_avatar.url)
        embed.set_thumbnail(url=member.display_avatar.url)
        embed.add_field(
            name="Statistics",
            value=f"Level: `{level['level']}`\nXP: `{level['xp']}`/`{level['target_xp']}`",
        )
        await ctx.send(embed=embed)

    @group(name="level", invoke_without_command=True)
    async def level_cmd(self, ctx: Context) -> None:
        await ctx.send_help(ctx.command)

    @level_cmd.command(name="enable", description="manage guild")
    @has_permissions(manage_guild=True)
    async def level_enable(self, ctx: Context) -> None:
        """enables the level module"""
        if await self.bot.db.fetchrow(
            "SELECT * FROM leveling.setup WHERE guild_id = $1", ctx.guild.id
        ):
            return await ctx.warn("Leveling system is **already** enabled")
        await self.bot.db.execute(
            "INSERT INTO leveling.setup (guild_id, message) VALUES ($1, $2)",
            ctx.guild.id,
            None,
        )
        await ctx.approve("Enabled the leveling system")

    @level_cmd.command(name="disable", description="manage guild")
    @has_permissions(manage_guild=True)
    async def level_disable(self, ctx: Context) -> None:
        """disables the level module"""
        confirmation = Confirmation(ctx)
        await ctx.send(
            "Are you sure you want to **disable** the leveling system? This will reset the level statistics as well.",
            view=confirmation,
        )
        await confirmation.wait()

        if confirmation.value:
            await self.bot.db.execute(
                "DELETE FROM leveling.setup WHERE guild_id = $1", ctx.guild.id
            )
            await self.bot.db.execute(
                "DELETE FROM leveling.user WHERE guild_id = $1", ctx.guild.id
            )
            await ctx.approve("Disabled the leveling system")
        else:
            await ctx.send("Action aborted.")

    @level_cmd.command(
        name="channel", description="manage guild", brief="#level-channel"
    )
    @has_permissions(manage_guild=True)
    async def level_channel(
        self, ctx: Context, *, channel: Optional[TextChannel] = None
    ) -> None:
        """sets the channel for levels"""
        await self.bot.db.execute(
            "UPDATE leveling.setup SET channel_id = $1 WHERE guild_id = $2",
            channel.id if channel else None,
            ctx.guild.id,
        )
        message = (
            f"Level up messages are going to be sent in {channel.mention}"
            if channel
            else "Level up messages are going to be sent in any channel"
        )
        await ctx.approve(message)

    @level_cmd.command(
        name="message",
        description="manage guild",
        brief="{message: Good job, {user.mention}! You leveled up to **Level {level}**}",
    )
    @has_permissions(manage_guild=True)
    async def level_message(
        self, ctx: Context, *, message: Optional[str] = None
    ) -> None:
        """Sets the level up message"""
        message = (
            message
            or "{message: Good job, {user.mention}! You leveled up to **Level {level}**}"
        )

        await self.bot.db.execute(
            "UPDATE leveling.setup SET message = $1 WHERE guild_id = $2",
            message,
            ctx.guild.id,
        )
        await ctx.approve(f"Level up message configured to:\n```{message}```")

    @level_cmd.command(name="config")
    async def level_config(self, ctx: Context) -> None:
        """views the level config"""
        check = await self.bot.db.fetchrow(
            "SELECT * FROM leveling.setup WHERE guild_id = $1", ctx.guild.id
        )
        embed = Embed()
        embed.set_author(
            name=f"Level settings for {ctx.guild.name}", icon_url=ctx.guild.icon.url
        )
        embed.add_field(
            name="Level Channel", value=ctx.guild.get_channel(check["channel_id"])
        )
        embed.add_field(
            name="Booster Multiplier",
            value="enabled" if check["booster_boost"] else "disabled",
        )
        embed.add_field(name="Message", value=check["message"], inline=False)
        await ctx.send(embed=embed)

    @level_cmd.command(name="set", description="manage guild", brief="@yurrion")
    @has_permissions(manage_guild=True)
    async def level_set(self, ctx: Context, level: int, *, member: Member) -> None:
        """sets a user level"""
        if level < 1:
            return await ctx.warn("The level cannot be **lower** than 1")
        target_xp = int((100 * level + 1) ** 0.9)
        await self.bot.db.execute(
            "INSERT INTO leveling.user (guild_id, user_id, xp, level, target_xp) VALUES ($1, $2, $3, $4, $5) "
            "ON CONFLICT (guild_id, user_id) DO UPDATE SET xp = $3, level = $4, target_xp = $5",
            ctx.guild.id,
            member.id,
            0,
            level,
            target_xp,
        )
        await ctx.approve(f"Set the level for {member.mention} to **Level {level}**")

    @level_cmd.command(name="reset", description="manage guild", brief="@yurrion")
    @has_permissions(manage_guild=True)
    async def level_reset(
        self, ctx: Context, *, member: Optional[Member] = None
    ) -> None:
        """resets a user level"""
        if member is None:
            confirmation = Confirmation(ctx)
            await ctx.send(
                "Are you sure you want to **reset** level statistics for everyone in this server?",
                view=confirmation,
            )
            await confirmation.wait()

            if confirmation.value:
                await self.bot.db.execute(
                    "DELETE FROM leveling.user WHERE guild_id = $1", ctx.guild.id
                )
                await ctx.approve("Reset level statistics for **all** members")
            else:
                await ctx.send("Action aborted.")
        else:
            confirmation = Confirmation(ctx)
            await ctx.send(
                f"Are you sure you want to **reset** level statistics for {member.mention} in this server?",
                view=confirmation,
            )
            await confirmation.wait()

            if confirmation.value:
                await self.bot.db.execute(
                    "DELETE FROM leveling.user WHERE guild_id = $1 AND user_id = $2",
                    ctx.guild.id,
                    member.id,
                )
                await ctx.approve(f"Reset level statistics for {member.mention}")
            else:
                await ctx.send("Action aborted.")

    @level_cmd.command(name="leaderboard")
    async def level_leaderboard(self, ctx: Context) -> None:
        """views the level leaderboard"""
        results = await self.bot.db.fetch(
            "SELECT * FROM leveling.user WHERE guild_id = $1", ctx.guild.id
        )
        members = sorted(results, key=lambda c: (c["level"], c["xp"]), reverse=True)
        entries = [
            f"{ctx.guild.get_member(r['user_id']).mention} - Level {r['level']} (XP: {r['xp']}/{r['target_xp']})"
            for r in members
        ]
        paginator = Paginator(
            ctx, entries=entries, embed=Embed(title="Level leaderboard"), per_page=10
        )
        await paginator.start()

    @level_cmd.group(name="rewards", invoke_without_command=True)
    async def level_rewards(self, ctx: Context) -> None:
        await ctx.send_help(ctx.command)

    @level_rewards.command(name="add", description="manage guild", brief="1, @level 1")
    @has_permissions(manage_guild=True)
    async def level_rewards_add(self, ctx: Context, level: int, *, role: Role) -> None:
        """adds a level reward"""
        if level < 1:
            return await ctx.warn("Level cannot be lower than 1")
        if await self.bot.db.fetchrow(
            "SELECT * FROM leveling.rewards WHERE guild_id = $1 AND role_id = $2",
            ctx.guild.id,
            role.id,
        ):
            return await ctx.warn(
                f"This role is **already** a reward for **Level {level}**"
            )
        await self.bot.db.execute(
            "INSERT INTO leveling.rewards (guild_id, level, role_id) VALUES ($1, $2, $3)",
            ctx.guild.id,
            level,
            role.id,
        )
        await ctx.approve(
            f"Added {role.mention} as a reward for reaching **Level {level}**"
        )

    @level_rewards.command(name="remove", description="manage guild", brief="@level 1")
    @has_permissions(manage_guild=True)
    async def level_rewards_remove(self, ctx: Context, *, role: Role) -> None:
        """removes a level reward"""
        check = await self.bot.db.fetchrow(
            "SELECT * FROM leveling.rewards WHERE guild_id = $1 AND role_id = $2",
            ctx.guild.id,
            role.id,
        )
        if check:
            await self.bot.db.execute(
                "DELETE FROM leveling.rewards WHERE guild_id = $1 AND role_id = $2",
                ctx.guild.id,
                role.id,
            )
            await ctx.approve(
                f"Removed a reward for reaching **Level {check['level']}**"
            )
        else:
            await ctx.warn("This role is **not** a reward for any level")

    @level_rewards.command(name="reset", description="manage guild")
    @has_permissions(manage_guild=True)
    async def level_rewards_reset(self, ctx: Context) -> None:
        """resets the level rewards"""
        confirmation = Confirmation(ctx)
        await ctx.send(
            "Are you sure that you want to **remove** every reward saved in this server?",
            view=confirmation,
        )
        await confirmation.wait()

        if confirmation.value:
            await self.bot.db.execute(
                "DELETE FROM leveling.rewards WHERE guild_id = $1", ctx.guild.id
            )
            await ctx.approve("Removed every reward that was saved in this server")
        else:
            await ctx.send("Action aborted.")

    @level_rewards.command(name="list")
    async def level_rewards_list(self, ctx: Context) -> None:
        """view the list of level rewards"""
        check = await self.bot.db.fetch(
            "SELECT role_id, level FROM leveling.rewards WHERE guild_id = $1",
            ctx.guild.id,
        )
        roles = sorted(check, key=lambda c: c["level"])
        entries = [
            f"{ctx.guild.get_role(r['role_id']).mention} for **Level {r['level']}**"
            for r in roles
        ]
        paginator = Paginator(
            entries=entries,
            embed=Embed(title=f"Level rewards ({len(roles)})"),
            per_page=10,
        )
        await paginator.start()
