from discord import (
    Embed,
    PermissionOverwrite,
    Member,
    VoiceChannel,
    VoiceState,
    Message,
)
from discord.ext.commands import (
    command,
    Cog,
    has_permissions,
    bot_has_permissions,
    group,
)

from time import time
from collections import defaultdict
from typing import Optional
from discord.ext.tasks import loop
from discord.utils import get
from .Interface import Interface
from tools.client import Context
from logging import getLogger
from main import zyn
from tools.parser.variables import parse
import config
import asyncio

log = getLogger("cogs/voicemaster")


class VoiceMaster(Cog):
    def __init__(self, bot: zyn):
        self.bot = bot
        self.bot.add_view(Interface(bot))
        self.check_empty_channels.start()
        self.rate_limits = defaultdict(list)

    def cog_unload(self):
        self.check_empty_channels.cancel()

    async def is_rate_limited(
        self, member_id: int, action: str, limit: int, timespan: int
    ) -> bool:
        key = f"voicemaster:{member_id}:{action}"
        return await self.bot.redis.ratelimited(key, limit, timespan)

    @loop(minutes=5)
    async def check_empty_channels(self):
        """Check and clean up empty voice channels every 5 minutes."""
        voicemaster_channels = await self.bot.db.fetch(
            "SELECT channel_id FROM voicemaster.channels"
        )

        for record in voicemaster_channels:
            channel_id = record["channel_id"]
            channel = self.bot.get_channel(channel_id)

            if channel and isinstance(channel, VoiceChannel):
                if not any(member for member in channel.members if not member.bot):
                    if await self.is_rate_limited(
                        f"delete:{channel_id}", limit=5, timespan=2
                    ):
                        await asyncio.sleep(2)
                        continue

                    try:
                        await self.bot.db.execute(
                            "DELETE FROM voicemaster.channels WHERE channel_id = $1",
                            channel_id,
                        )
                    except Exception as db_error:
                        log.exception(
                            f"Failed to delete database entry for channel {channel_id}: {db_error}"
                        )
                        continue

                    try:
                        await channel.delete(
                            reason="VoiceMaster cleanup: Channel is empty."
                        )
                        log.info(f"Deleted empty VoiceMaster channel {channel_id}")
                    except Exception as e:
                        log.exception(f"Failed to delete channel {channel_id}: {e}")

    @check_empty_channels.before_loop
    async def before_check_empty_channels(self):
        await self.bot.wait_until_ready()
        log.info("VoiceMaster empty channel cleanup loop started.")

    def cog_unload(self):
        self.check_empty_channels.cancel()

    @Cog.listener()
    async def on_voice_state_update(
        self, member: Member, before: VoiceState, after: VoiceState
    ):
        if before.channel is None and after.channel is not None:

            if await self.is_rate_limited(member.id, "join", limit=5, timespan=2):
                await asyncio.sleep(2)

            default_role_id = await self.bot.db.fetchval(
                "SELECT default_role_id FROM voicemaster.settings WHERE guild_id = $1",
                member.guild.id,
            )
            if default_role_id:
                role = member.guild.get_role(default_role_id)
                if role:
                    await member.add_roles(role, reason="Joined VoiceMaster channel")
        elif before.channel is not None and after.channel is None:

            if await self.is_rate_limited(member.id, "leave", limit=5, timespan=2):
                await asyncio.sleep(2)

            default_role_id = await self.bot.db.fetchval(
                "SELECT default_role_id FROM voicemaster.settings WHERE guild_id = $1",
                member.guild.id,
            )
            if default_role_id:
                role = member.guild.get_role(default_role_id)
                if role:
                    await member.remove_roles(role, reason="Left VoiceMaster channel")

    @Cog.listener("on_voice_state_update")
    async def vmcreate(self, member: Member, before: VoiceState, after: VoiceState):
        """Handle creating a new voice channel when a member joins the designated channel."""
        if await self.is_rate_limited(member.id, "create", limit=5, timespan=2):
            await asyncio.sleep(2)
        channel_id = await self.bot.db.fetchval(
            "SELECT jtc_channel_id FROM voicemaster.settings WHERE guild_id = $1",
            member.guild.id,
        )

        if after.channel and after.channel.id == channel_id:
            existing_channel_id = await self.bot.db.fetchval(
                "SELECT channel_id FROM voicemaster.channels WHERE guild_id = $1 AND owner_id = $2",
                member.guild.id,
                member.id,
            )

            if existing_channel_id:
                existing_channel = get(
                    member.guild.voice_channels, id=existing_channel_id
                )
                if existing_channel:
                    try:
                        if member.voice and member.voice.channel:
                            await member.move_to(
                                existing_channel,
                                reason="You already have a voice master channel.",
                            )
                    except Exception as e:
                        log.exception(f"Failed to move member to existing channel: {e}")
                return

            category_id = await self.bot.db.fetchval(
                "SELECT category_id FROM voicemaster.settings WHERE guild_id = $1",
                member.guild.id,
            )
            category = get(member.guild.categories, id=category_id)
            channel_name_template = (
                await self.bot.db.fetchval(
                    "SELECT default_channel_name FROM voicemaster.settings WHERE guild_id = $1",
                    member.guild.id,
                )
                or "{user.name}'s Channel"
            )

            channel_name = parse(
                channel_name_template, targets=[member, (member.guild, "guild")]
            )

            new_channel = await member.guild.create_voice_channel(
                channel_name, category=category
            )

            try:
                if member.voice and member.voice.channel:
                    await member.move_to(new_channel)
            except Exception as e:
                log.exception(f"Failed to move member to new channel: {e}")

            await self.bot.db.execute(
                "INSERT INTO voicemaster.channels (channel_id, guild_id, owner_id) VALUES ($1, $2, $3)",
                new_channel.id,
                member.guild.id,
                member.id,
            )

    @Cog.listener("on_voice_state_update")
    async def vmdelete(
        self, member: Member, before: VoiceState, after: VoiceState
    ) -> Optional[VoiceChannel]:
        """Handle deleting a voice channel when the last member leaves."""
        if await self.is_rate_limited(member.id, "delete", limit=5, timespan=2):
            await asyncio.sleep(2)

        if before.channel and not after.channel and len(before.channel.members) == 0:
            channel_id = before.channel.id
            is_voicemaster_channel = await self.bot.db.fetchval(
                "SELECT EXISTS(SELECT 1 FROM voicemaster.channels WHERE channel_id = $1)",
                channel_id,
            )

            if is_voicemaster_channel:
                await self.bot.db.execute(
                    "DELETE FROM voicemaster.channels WHERE channel_id = $1", channel_id
                )

                try:
                    channel = self.bot.get_channel(channel_id)
                    if channel:
                        await channel.delete(
                            reason="VoiceMaster cleanup: Channel is empty."
                        )
                except Exception as e:
                    log.exception(f"Failed to delete channel: {e}")

    @group(name="voicemaster", aliases=["vm", "vc"], invoke_without_command=True)
    async def voicemaster(self, ctx: Context) -> Message:
        """VoiceMaster command group."""
        return await ctx.send_help(ctx.command)

    @voicemaster.command(name="setup", description="manage channels")
    @has_permissions(manage_channels=True)
    async def vmsetup(self, ctx: Context) -> Message:
        """Sets up VoiceMaster configuration."""
        guild = ctx.guild
        category_id = await self.bot.db.fetchval(
            "SELECT category_id FROM voicemaster.settings WHERE guild_id = $1", guild.id
        )
        if category_id:
            await ctx.warn(
                "VoiceMaster has already been set up for this guild. Use `voicemaster reset` to reset the configurations."
            )
            return

        category = await guild.create_category("VoiceMaster")
        await self.bot.db.execute(
            "INSERT INTO voicemaster.settings (guild_id, category_id) VALUES ($1, $2)",
            guild.id,
            category.id,
        )

        jtc = await guild.create_voice_channel("Join to Create", category=category)
        interface = await category.create_text_channel(
            "interface",
            overwrites={
                guild.default_role: PermissionOverwrite(view_channel=True),
                guild.me: PermissionOverwrite(view_channel=True, manage_channels=True),
            },
        )

        await interface.set_permissions(guild.default_role, send_messages=False)

        embed = Embed(
            title="Interface",
            description="Click the buttons below to control your voice channel.",
        )
        embed.set_author(name=ctx.guild.name, icon_url=ctx.guild.icon)
        embed.add_field(
            name="**Button Usage**",
            value="\n".join(
                [
                    f"{config.EMOJIS.VOICEMASTER.LOCK} - Lock the voice channel",
                    f"{config.EMOJIS.VOICEMASTER.UNLOCK} - Unlock the voice channel",
                    f"{config.EMOJIS.VOICEMASTER.GHOST} - Hide the voice channel",
                    f"{config.EMOJIS.VOICEMASTER.UNGHOST} - Unhide the voice channel",
                    f"{config.EMOJIS.VOICEMASTER.CLAIM} - Claim the voice channel",
                    f"{config.EMOJIS.VOICEMASTER.INFO} - View channel information",
                    f"{config.EMOJIS.VOICEMASTER.PLUS} - Increase the user limit",
                    f"{config.EMOJIS.VOICEMASTER.MINUS} - Decrease the user limit",
                    f"{config.EMOJIS.VOICEMASTER.REJECT} - Reject a user from joining",
                    f"{config.EMOJIS.VOICEMASTER.DELETE} - Delete the voice channel",
                ]
            ),
        )

        await interface.send(embed=embed, view=Interface(self.bot))
        await self.bot.db.execute(
            "UPDATE voicemaster.settings SET jtc_channel_id = $1, interface_id = $2 WHERE guild_id = $3",
            jtc.id,
            interface.id,
            guild.id,
        )
        await ctx.approve("VoiceMaster has now been configured for this guild.")

    @voicemaster.command(name="reset", description="manage channels")
    @has_permissions(manage_channels=True)
    async def vmreset(self, ctx: Context) -> Message:
        """Resets VoiceMaster configuration for the guild."""
        guild = ctx.guild
        category_id = await self.bot.db.fetchval(
            "SELECT category_id FROM voicemaster.settings WHERE guild_id = $1", guild.id
        )
        if not category_id:
            await ctx.warn("VoiceMaster has not been setup for this guild yet.")
            return

        category = guild.get_channel(category_id)
        if category:
            for channel in category.voice_channels:
                await channel.delete()
            for channel in category.text_channels:
                await channel.delete()
            await category.delete()

        await self.bot.db.execute(
            "DELETE FROM voicemaster.settings WHERE guild_id = $1", guild.id
        )
        await ctx.approve("VoiceMaster has been reset for this guild.")

    @voicemaster.command(
        name="reject",
        aliases=["kick", "ban", "remove"],
        usage="<member>",
        brief="@yurrion",
    )
    async def voicemaster_reject(self, ctx: Context, member: Member) -> Message:
        """Kicks a member from your VoiceMaster channel."""
        if not ctx.author.voice or not ctx.author.voice.channel:
            await ctx.warn("You must be in a voice channel to use this command.")
            return

        channel = ctx.author.voice.channel
        owner_id = await self.bot.db.fetchval(
            "SELECT owner_id FROM voicemaster.channels WHERE channel_id = $1",
            channel.id,
        )

        if ctx.author.id != owner_id:
            await ctx.warn(
                "You must be the owner of this VoiceMaster channel to use this command."
            )
            return

        if ctx.author.id == member.id:
            await ctx.warn("You cannot reject yourself from the channel.")
            return

        if member.voice and member.voice.channel == channel:
            await member.move_to(None)
            await channel.set_permissions(
                member, overwrite=PermissionOverwrite(connect=False)
            )
            await ctx.approve(
                f"{member.display_name} has been rejected from the VoiceMaster channel. They can no longer join."
            )

    @voicemaster.command(name="permit", usage="<member>", brief="@yurrion")
    async def voicemaster_permit(self, ctx: Context, member: Member) -> Message:
        """Permits a member to join your VoiceMaster channel."""
        if not ctx.author.voice or not ctx.author.voice.channel:
            await ctx.warn("You must be in a voice channel to use this command.")
            return

        channel = ctx.author.voice.channel
        owner_id = await self.bot.db.fetchval(
            "SELECT owner_id FROM voicemaster.channels WHERE channel_id = $1",
            channel.id,
        )

        if ctx.author.id != owner_id:
            await ctx.warn(
                "You must be the owner of this VoiceMaster channel to use this command."
            )
            return

        await channel.set_permissions(
            member, overwrite=PermissionOverwrite(connect=True)
        )
        await ctx.approve(
            f"{member.display_name} has been permitted to join the VoiceMaster channel."
        )

    @voicemaster.command(name="lock")
    async def voicemaster_lock(self, ctx: Context) -> Message:
        """Locks the VoiceMaster channel."""
        if not ctx.author.voice or not ctx.author.voice.channel:
            await ctx.warn("You must be in a voice channel to use this command.")
            return

        channel = ctx.author.voice.channel
        owner_id = await self.bot.db.fetchval(
            "SELECT owner_id FROM voicemaster.channels WHERE channel_id = $1",
            channel.id,
        )

        if ctx.author.id != owner_id:
            await ctx.warn(
                "You must be the owner of this VoiceMaster channel to use this command."
            )
            return

        await channel.set_permissions(ctx.guild.default_role, connect=False)
        await ctx.approve("VoiceMaster channel has been locked. No one can join now.")

    @voicemaster.command(name="unlock")
    async def voicemaster_unlock(self, ctx: Context) -> Message:
        """Unlocks the VoiceMaster channel."""
        if not ctx.author.voice or not ctx.author.voice.channel:
            await ctx.warn("You must be in a voice channel to use this command.")
            return

        channel = ctx.author.voice.channel
        owner_id = await self.bot.db.fetchval(
            "SELECT owner_id FROM voicemaster.channels WHERE channel_id = $1",
            channel.id,
        )

        if ctx.author.id != owner_id:
            await ctx.warn(
                "You must be the owner of this VoiceMaster channel to use this command."
            )
            return

        await channel.set_permissions(ctx.guild.default_role, connect=True)
        await ctx.approve("VoiceMaster channel has been unlocked.")

    @voicemaster.command(name="hide", aliases=["g", "ghost"])
    async def voicemaster_hide(self, ctx: Context) -> Message:
        """Hides the VoiceMaster channel."""
        if not ctx.author.voice or not ctx.author.voice.channel:
            await ctx.warn("You must be in a voice channel to use this command.")
            return

        channel = ctx.author.voice.channel
        owner_id = await self.bot.db.fetchval(
            "SELECT owner_id FROM voicemaster.channels WHERE channel_id = $1",
            channel.id,
        )

        if ctx.author.id != owner_id:
            await ctx.warn(
                "You must be the owner of this VoiceMaster channel to use this command."
            )
            return

        await channel.set_permissions(ctx.guild.default_role, view_channel=False)
        await ctx.approve("VoiceMaster channel has been hidden.")

    @voicemaster.command(name="unhide", aliases=["ug", "unghost"])
    async def voicemaster_unhide(self, ctx: Context) -> Message:
        """Unhides the VoiceMaster channel."""
        if not ctx.author.voice or not ctx.author.voice.channel:
            await ctx.warn("You must be in a voice channel to use this command.")
            return

        channel = ctx.author.voice.channel
        owner_id = await self.bot.db.fetchval(
            "SELECT owner_id FROM voicemaster.channels WHERE channel_id = $1",
            channel.id,
        )

        if ctx.author.id != owner_id:
            await ctx.warn(
                "You must be the owner of this VoiceMaster channel to use this command."
            )
            return

        await channel.set_permissions(ctx.guild.default_role, view_channel=True)
        await ctx.approve("VoiceMaster channel has been unhidden.")

    @voicemaster.command(name="bitrate")
    async def voicemaster_bitrate(self, ctx: Context, bitrate: int) -> Message:
        """Changes the bitrate of the VoiceMaster channel."""
        if not ctx.author.voice or not ctx.author.voice.channel:
            await ctx.warn("You must be in a voice channel to use this command.")
            return

        channel = ctx.author.voice.channel
        owner_id = await self.bot.db.fetchval(
            "SELECT owner_id FROM voicemaster.channels WHERE channel_id = $1",
            channel.id,
        )

        if ctx.author.id != owner_id:
            await ctx.warn(
                "You must be the owner of this VoiceMaster channel to use this command."
            )
            return

        if bitrate < 8 or bitrate > 96:
            await ctx.warn("Bitrate must be between 8 and 96 kbps.")
            return

        await channel.edit(bitrate=bitrate * 1000)
        await ctx.approve(
            f"VoiceMaster channel bitrate has been changed to {bitrate} kbps."
        )

    @voicemaster.command(name="role")
    async def voicemaster_role(self, ctx: Context, role: str) -> Message:
        """Grants a role to members who join and removes it when they leave."""
        if not ctx.author.voice or not ctx.author.voice.channel:
            await ctx.warn("You must be in a voice channel to use this command.")
            return

        channel = ctx.author.voice.channel
        owner_id = await self.bot.db.fetchval(
            "SELECT owner_id FROM voicemaster.channels WHERE channel_id = $1",
            channel.id,
        )

        if ctx.author.id != owner_id:
            await ctx.warn(
                "You must be the owner of this VoiceMaster channel to use this command."
            )
            return

        role_id = int(role.strip("<@&>"))
        role_obj = ctx.guild.get_role(role_id)
        if not role_obj:
            await ctx.warn("Role not found.")
            return

        async with self.bot.db.acquire() as conn:
            await conn.execute(
                "INSERT INTO voicemaster.roles (channel_id, role_id) VALUES ($1, $2) ON CONFLICT (channel_id) DO UPDATE SET role_id = EXCLUDED.role_id",
                channel.id,
                role_id,
            )
        await ctx.approve(f"VoiceMaster channel role has been set to {role_obj.name}.")

    @voicemaster.command(name="music")
    async def voicemaster_music(self, ctx: Context) -> Message:
        """Changes the channel to a Music Only channel (sets it to push-to-talk)."""
        if not ctx.author.voice or not ctx.author.voice.channel:
            await ctx.warn("You must be in a voice channel to use this command.")
            return

        channel = ctx.author.voice.channel
        owner_id = await self.bot.db.fetchval(
            "SELECT owner_id FROM voicemaster.channels WHERE channel_id = $1",
            channel.id,
        )

        if ctx.author.id != owner_id:
            await ctx.warn(
                "You must be the owner of this VoiceMaster channel to use this command."
            )
            return

        overwrite = channel.overwrites_for(ctx.guild.default_role)
        overwrite.update(connect=True, use_voice_activation=False)
        await channel.set_permissions(ctx.guild.default_role, overwrite=overwrite)

        await ctx.approve(
            "VoiceMaster channel has been set to Music Only mode (push-to-talk)."
        )

    @voicemaster.command(name="status")
    async def voicemaster_status(self, ctx: Context, *, status: str) -> Message:
        """Sets a status for your VoiceMaster channel."""
        if not ctx.author.voice or not ctx.author.voice.channel:
            await ctx.warn("You must be in a voice channel to use this command.")
            return

        channel = ctx.author.voice.channel
        owner_id = await self.bot.db.fetchval(
            "SELECT owner_id FROM voicemaster.channels WHERE channel_id = $1",
            channel.id,
        )

        if ctx.author.id != owner_id:
            await ctx.warn(
                "You must be the owner of this VoiceMaster channel to use this command."
            )
            return

        await channel.edit(status=status)
        await ctx.approve(f"VoiceMaster channel status has been set to: {status}")

    @voicemaster.command(name="category")
    async def voicemaster_category(self, ctx: Context, category_id: int) -> Message:
        """Redirects voice channels to a custom category."""
        if not ctx.author.voice or not ctx.author.voice.channel:
            await ctx.warn("You must be in a voice channel to use this command.")
            return

        category = get(ctx.guild.categories, id=category_id)
        if not category:
            await ctx.warn("Category not found.")
            return

        channel = ctx.author.voice.channel
        owner_id = await self.bot.db.fetchval(
            "SELECT owner_id FROM voicemaster.channels WHERE channel_id = $1",
            channel.id,
        )

        if ctx.author.id != owner_id:
            await ctx.warn(
                "You must be the owner of this VoiceMaster channel to use this command."
            )
            return

        await channel.edit(category=category)
        await ctx.approve(
            f"VoiceMaster channel has been moved to category: {category.name}"
        )

    @voicemaster.command(name="transfer")
    async def voicemaster_transfer(self, ctx: Context, member: Member) -> Message:
        """Transfers ownership of your VoiceMaster channel to another member."""
        if not ctx.author.voice or not ctx.author.voice.channel:
            await ctx.warn("You must be in a voice channel to use this command.")
            return

        if member.bot:
            await ctx.warn("You cannot transfer ownership to a bot.")
            return

        channel = ctx.author.voice.channel
        owner_id = await self.bot.db.fetchval(
            "SELECT owner_id FROM voicemaster.channels WHERE channel_id = $1",
            channel.id,
        )

        if ctx.author.id != owner_id:
            await ctx.warn(
                "You must be the owner of this VoiceMaster channel to use this command."
            )
            return

        await self.bot.db.execute(
            "UPDATE voicemaster.channels SET owner_id = $1 WHERE channel_id = $2",
            member.id,
            channel.id,
        )
        await ctx.approve(
            f"Ownership of the VoiceMaster channel has been transferred to {member.display_name}."
        )

    @voicemaster.command(name="configuration", aliases=["info"])
    async def voicemaster_configuration(self, ctx: Context) -> Message:
        """Displays the current configuration for the VoiceMaster channel."""
        if not ctx.author.voice or not ctx.author.voice.channel:
            await ctx.warn("You must be in a voice channel to use this command.")
            return

        channel = ctx.author.voice.channel
        owner_id = await self.bot.db.fetchval(
            "SELECT owner_id FROM voicemaster.channels WHERE channel_id = $1",
            channel.id,
        )
        role_id = await self.bot.db.fetchval(
            "SELECT role_id FROM voicemaster.roles WHERE channel_id = $1",
            channel.id,
        )

        role_info = f"<@&{role_id}> | {role_id}" if role_id else "No role set"
        created_at_timestamp = int(channel.created_at.timestamp())
        custom_timestamp = f"<t:{created_at_timestamp}:R>"
        bitrate = channel.bitrate // 1000
        connected_members = len(channel.members)

        embed = Embed(
            title=f"{channel} Channel Configuration",
            description=(
                f"Owner: <@{owner_id}> | {owner_id}\n"
                f"Role: {role_info}\n"
                f"Created: {custom_timestamp}\n"
                f"Bitrate: {bitrate} kbps\n"
                f"Connected: {connected_members} member(s)"
            ),
        )
        await ctx.send(embed=embed)

    @voicemaster.group(name="default", help="Default settings for VoiceMaster channels")
    async def vmdefault(self, ctx: Context) -> Message:
        """VoiceMaster default settings group."""
        ctx.send_help(ctx.command)

    @vmdefault.command(name="role")
    @has_permissions(manage_guild=True, manage_roles=True)
    async def vmdefault_role(self, ctx: Context, role: str) -> Message:
        """Sets a default role that members get for being in a VM channel."""
        role_id = int(role.strip("<@&>"))
        role_obj = ctx.guild.get_role(role_id)
        if not role_obj:
            await ctx.warn("Role not found.")
            return

        await self.bot.db.execute(
            "UPDATE voicemaster.settings SET default_role_id = $1 WHERE guild_id = $2",
            role_id,
            ctx.guild.id,
        )
        await ctx.approve(
            f"Default role for VoiceMaster channels has been set to {role_obj.name}."
        )

    @vmdefault.command(name="name")
    @has_permissions(manage_guild=True)
    async def vmdefault_name(self, ctx: Context, *, name: str) -> Message:
        """Sets the default name for new VoiceMaster channels."""

        await self.bot.db.execute(
            "UPDATE voicemaster.settings SET default_channel_name = $1 WHERE guild_id = $2",
            name,
            ctx.guild.id,
        )
        await ctx.approve(
            f"Default name for new VoiceMaster channels has been set to: {name}"
        )
