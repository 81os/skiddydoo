from discord import (
    Member,
    Role,
    SelectOption,
    VoiceChannel,
    Guild,
    Embed,
    ButtonStyle,
    WebhookMessage,
)
from discord.ui import button, Select
from typing import List, Dict, Optional

from tools import View, Button
from tools.client.context import Interaction
from logging import getLogger
from main import zyn
import config

log = getLogger("cogs/voicemaster/interface")


class DisconnectMembers(Select):
    def __init__(self, member: Member) -> None:
        self.member = member
        self.guild = member.guild
        self.channel = member.voice.channel if member.voice else None

        options = self._generate_options() if self.channel else []
        super().__init__(
            placeholder="Choose members to disconnect...",
            min_values=1,
            max_values=len(options),
            options=options,
        )

    def _generate_options(self) -> List[SelectOption]:
        """Generate options for the select menu based on channel members."""
        return [
            SelectOption(value=str(m.id), label=f"{m} ({m.id})", emoji="👤")
            for m in self.channel.members
        ]

    async def callback(self, interaction: Interaction):
        await interaction.response.defer(ephemeral=True)

        if not self.channel:
            await interaction.followup.send(
                "The channel is no longer available.", ephemeral=True
            )
            return

        results = await self._disconnect_members()
        message = f"Successfully **disconnected** {results['disconnected']} member{'s' if results['disconnected'] != 1 else ''}. Failed: `{results['failed']}`."
        await interaction.followup.send(message, ephemeral=True)

    async def _disconnect_members(self) -> Dict[str, int]:
        disconnected, failed = 0, 0

        for member_id in self.values:
            member = self.guild.get_member(int(member_id))
            if member and member.voice and member.voice.channel == self.channel:
                try:
                    await member.move_to(None)
                    disconnected += 1
                except Exception as e:
                    print(f"Failed to disconnect {member.name}: {e}")
                    failed += 1
            else:
                failed += 1

        return {"disconnected": disconnected, "failed": failed}


class Interface(View):
    def __init__(self, bot: zyn) -> None:
        self.bot = bot
        super().__init__(timeout=None)

    async def interaction_check(self, interaction: Interaction) -> bool:
        user_voice_channel = (
            interaction.user.voice.channel if interaction.user.voice else None
        )

        if not user_voice_channel:
            await interaction.deny("You're not connected to a **voice channel**.")
            return False

        owner_id = await self.bot.db.fetchval(
            """
            SELECT owner_id FROM voicemaster.channels
            WHERE channel_id = $1
            """,
            user_voice_channel.id,
        )

        if not owner_id:
            await interaction.deny("You're not in a **VoiceMaster** channel!")
            return False

        if interaction.data["custom_id"] == "voicemaster:claim":
            if interaction.user.id == owner_id:
                await interaction.warn(
                    "You already have **ownership** of this voice channel!"
                )
                return False
            if owner_id in (member.id for member in user_voice_channel.members):
                await interaction.warn(
                    "You can't claim this **voice channel**, the owner is still active here."
                )
                return False

            return True

        if interaction.user.id != owner_id:
            await interaction.warn("You don't own a **voice channel**!")
            return False
        return True

    @button(
        emoji=config.EMOJIS.VOICEMASTER.LOCK,
        style=ButtonStyle.gray,
        custom_id="vm_lock",
    )
    async def on_lock_button_click(
        self, interaction: Interaction, button: Button
    ) -> WebhookMessage:
        channel = interaction.user.voice.channel
        owner_id = await self.bot.db.fetchval(
            "SELECT owner_id FROM voicemaster.channels WHERE channel_id = $1",
            channel.id,
        )
        if interaction.user.id == owner_id:
            await channel.set_permissions(interaction.guild.default_role, connect=False)
            await interaction.approve(
                "VoiceMaster channel has been locked. No one can join.",
            )

    @button(
        emoji=config.EMOJIS.VOICEMASTER.UNLOCK,
        style=ButtonStyle.gray,
        custom_id="vm_unlock",
    )
    async def on_unlock_button_click(
        self, interaction: Interaction, button: Button
    ) -> WebhookMessage:
        channel = interaction.user.voice.channel
        await channel.set_permissions(interaction.guild.default_role, overwrite=None)
        await interaction.approve(
            "VoiceMaster channel has been unlocked. Everyone can join.",
        )

    @button(
        emoji=config.EMOJIS.VOICEMASTER.GHOST,
        custom_id="voicemaster:ghost",
        style=ButtonStyle.gray,
    )
    async def ghost(self, interaction: Interaction, button: Button) -> WebhookMessage:
        """Hide your voice channel"""
        await interaction.user.voice.channel.set_permissions(
            interaction.guild.default_role,
            view_channel=False,
            reason=f"VoiceMaster: {interaction.user} made voice channel hidden",
        )
        return await interaction.approve(
            "Your **voice channel** has been hidden",
        )

    @button(
        emoji=config.EMOJIS.VOICEMASTER.UNGHOST,
        custom_id="voicemaster:reveal",
        style=ButtonStyle.gray,
    )
    async def reveal(self, interaction: Interaction, button: Button) -> WebhookMessage:
        """Reveal your voice channel"""
        await interaction.user.voice.channel.set_permissions(
            interaction.guild.default_role,
            view_channel=None,
            reason=f"VoiceMaster: {interaction.user} revealed voice channel",
        )
        return await interaction.approve(
            "Your **voice channel** has been revealed",
        )

    @button(
        emoji=config.EMOJIS.VOICEMASTER.CLAIM,
        custom_id="voicemaster:claim",
        style=ButtonStyle.gray,
    )
    async def claim(self, interaction: Interaction, button: Button) -> WebhookMessage:
        """Claim an inactive voice channel"""
        await self.bot.db.execute(
            """
            UPDATE voicemaster.channels
            SET owner_id = $2
            WHERE channel_id = $1
            """,
            interaction.user.voice.channel.id,
            interaction.user.id,
        )

        if interaction.user.voice.channel.name.endswith("channel"):
            try:
                await interaction.user.voice.channel.edit(
                    name=f"{interaction.user.display_name}'s channel"
                )
            except Exception:
                pass

        return await interaction.warn(
            "You are now the owner of this **channel**!",
        )

    @button(
        emoji=config.EMOJIS.VOICEMASTER.INFO,
        style=ButtonStyle.gray,
        custom_id="vm_info",
    )
    async def info(self, interaction: Interaction, button: Button) -> WebhookMessage:
        try:
            channel = interaction.user.voice.channel
            guild = interaction.guild

            locked = channel.overwrites_for(guild.default_role).connect is False
            owner_id = await self.bot.db.fetchval(
                "SELECT owner_id FROM voicemaster.channels WHERE channel_id = $1",
                channel.id,
            )

            owner_info = f"<@{owner_id}> | {owner_id}"
            created_at_timestamp = int(channel.created_at.timestamp())
            custom_timestamp = f"<t:{created_at_timestamp}:R>"

            bitrate = channel.bitrate // 1000
            connected_members = len(channel.members)

            if not interaction.response.is_done():
                await interaction.response.send_message(
                    embed=Embed(
                        title=f"{channel.name} Channel Info",
                        description=f"Owner: {owner_info}\nLocked: {'✅' if locked else '❌'}\nCreated: {custom_timestamp}\nBitrate: {bitrate} kbps\nConnected: {connected_members} member(s)",
                    ),
                    ephemeral=True,
                )
        except Exception as e:
            log.exception(e)

    @button(
        emoji=config.EMOJIS.VOICEMASTER.PLUS,
        style=ButtonStyle.gray,
        custom_id="vm_limit_plus",
    )
    async def on_limit_plus_button_click(
        self, interaction: Interaction, button: Button
    ) -> WebhookMessage:
        channel = interaction.user.voice.channel
        if channel.user_limit is None or channel.user_limit < 99:
            new_limit = (channel.user_limit or 0) + 1
            await channel.edit(user_limit=new_limit)
            await interaction.approve(
                f"User limit increased to {new_limit}.",
            )
        else:
            await interaction.warn(
                "User limit cannot be increased further.",
            )

    @button(
        emoji=config.EMOJIS.VOICEMASTER.MINUS,
        style=ButtonStyle.gray,
        custom_id="vm_limit_minus",
    )
    async def on_limit_minus_button_click(
        self, interaction: Interaction, button: Button
    ) -> WebhookMessage:
        channel = interaction.user.voice.channel
        if channel.user_limit is None or channel.user_limit > 0:
            new_limit = (channel.user_limit or 1) - 1
            await channel.edit(user_limit=new_limit if new_limit > 0 else None)
            await interaction.approve(
                (
                    f"User limit decreased to {new_limit}."
                    if new_limit > 0
                    else "User limit removed."
                ),
            )
        else:
            await interaction.warn(
                "User limit cannot be decreased further.",
            )

    @button(
        emoji=config.EMOJIS.VOICEMASTER.DELETE,
        custom_id="voicemaster:delete_vc",
        style=ButtonStyle.gray,
    )
    async def delete_vc(
        self, interaction: Interaction, button: Button
    ) -> WebhookMessage:
        voice_channel = interaction.user.voice.channel

        await voice_channel.delete()

        return await interaction.approve(
            f"The voice channel `{voice_channel.name}` has been deleted. 🗑️",
        )

    @button(
        emoji=config.EMOJIS.VOICEMASTER.REJECT,
        custom_id="voicemaster:disconnect",
        style=ButtonStyle.gray,
    )
    async def disconnect(
        self, interaction: Interaction, button: Button
    ) -> WebhookMessage:
        view = DisconnectMembers(interaction.user)

        await interaction.response.send_message(
            "Select members from the **dropdown** to disconnect.", ephemeral=True
        )
