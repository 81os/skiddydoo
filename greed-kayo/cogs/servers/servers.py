from __future__ import annotations

import asyncio
from typing import List, Optional, cast

from cashews import cache
from discord import AuditLogEntry, HTTPException, Message, TextChannel
from discord.ext.commands import (
    BucketType,
    Cog,
    Range,
    cooldown,
    group,
    parameter,
    has_permissions,
)

from config import CLIENT
from main import zyn
from tools import quietly_delete
from tools.client.context import Context, ReskinConfig
from tools.conversion import PartialAttachment
from tools.conversion.discord import Donator
from tools.formatter import codeblock, plural

from .extended import Extended


class Servers(Extended, Cog):
    def __init__(self, bot: zyn):
        self.bot = bot

    @group(invoke_without_command=True)
    async def prefix(self, ctx: Context) -> Message:
        """
        View the current server prefixes.
        This can support multiple prefixes.
        """

        prefixes = ctx.settings.prefixes or [CLIENT.PREFIX]

        return await ctx.neutral(
            f"The current prefixes are: {', '.join(f'`{prefix}`' for prefix in prefixes)}"
            if len(prefixes) > 1
            else f"The current prefix is `{prefixes[0]}`"
        )

    @prefix.command(name="set", description="manage guild", usage="[prefix]", brief=";")
    @has_permissions(manage_guild=True)
    async def prefix_set(self, ctx: Context, prefix: str) -> Message:
        """
        Set the server prefix.
        """

        if not prefix:
            return await ctx.warn("You must provide a prefix")

        await ctx.prompt(
            f"Are you sure you want to set the prefix to `{prefix}`?",
            "This will overwrite all existing prefixes.",
        )

        await ctx.settings.update(prefixes=[prefix])
        return await ctx.approve(f"The prefix has been set to `{prefix}`")

    @prefix.command(name="add", description="manage guild", usage="[prefix]", brief=";")
    @has_permissions(manage_guild=True)
    async def prefix_add(self, ctx: Context, prefix: str) -> Message:
        """
        Add a prefix to the server.
        """

        if not prefix:
            return await ctx.warn("You must provide a prefix")

        elif prefix in ctx.settings.prefixes:
            return await ctx.warn(f"`{prefix}` is already a prefix")

        await ctx.settings.update(prefixes=[*ctx.settings.prefixes, prefix])
        return await ctx.approve(f"Now accepting `{prefix}` as a prefix")

    @prefix.command(
        name="remove", description="manage guild", usage="[prefix]", brief="g."
    )
    @has_permissions(manage_guild=True)
    async def prefix_remove(self, ctx: Context, prefix: str) -> Message:
        """
        Remove a prefix from the server.
        """

        if not prefix:
            return await ctx.warn("You must provide a prefix")

        elif prefix not in ctx.settings.prefixes:
            return await ctx.warn(f"`{prefix}` is not a prefix")

        await ctx.settings.update(
            prefixes=[p for p in ctx.settings.prefixes if p != prefix]
        )
        return await ctx.approve(f"No longer accepting `{prefix}` as a prefix")

    @prefix.command(name="reset", description="manage guild")
    @has_permissions(manage_guild=True)
    async def prefix_reset(self, ctx: Context) -> Message:
        """
        Reset the server prefixes.
        """

        await ctx.settings.update(prefixes=[])
        return await ctx.approve("Reset the server prefixes")

    @group(invoke_without_command=True)
    @Donator()
    async def selfprefix(self, ctx: Context) -> Message:
        """Shows the current prefix"""
        result = await self.bot.db.fetchrow(
            "SELECT prefix FROM selfprefix WHERE user_id = $1", ctx.author.id
        )
        if result:
            await ctx.neutral(f"Your current prefix is `{result['prefix']}`")
        else:
            await ctx.warn("You do not have a prefix set.")

    @selfprefix.command(name="set", descripion="donator", brief=";")
    @Donator()
    async def selfprefix_set(self, ctx: Context, *, prefix: str) -> Message:
        """Sets a new prefix"""
        if len(prefix) > 3:
            return await ctx.warn("Prefix must be shorter than 3 characters.")

        await self.bot.db.execute(
            "INSERT INTO selfprefix (user_id, prefix) VALUES ($1, $2) ON CONFLICT (user_id) DO UPDATE SET prefix = $2",
            ctx.author.id,
            prefix,
        )
        await ctx.approve(f"your prefix has been set to {prefix}")

    @selfprefix.command(name="remove", description="donator", aliases=["reset"])
    @Donator()
    async def selfprefix_remove(self, ctx: Context) -> Message:
        """Removes the current prefix"""
        await self.bot.db.execute(
            "DELETE FROM selfprefix WHERE user_id = $1", ctx.author.id
        )
        await ctx.approve("Prefix removed.")

    @group(invoke_without_command=True)
    @Donator()
    async def reskin(self, ctx: Context) -> Message:
        """
        Customize the bot's appearance.
        """

        return await ctx.send_help(ctx.command)

    @reskin.command(name="setup", aliases=["enable", "on"], description="administrator")
    @has_permissions(administrator=True)
    @cooldown(1, 120, BucketType.guild)
    async def reskin_setup(self, ctx: Context) -> Message:
        """
        Setup the webhooks for the reskin relay.
        """

        await ctx.settings.update(reskin=True)

        webhooks: List[tuple[TextChannel, int]] = [
            (channel, record["webhook_id"])
            for record in await self.bot.db.fetch(
                """
                SELECT channel_id, webhook_id
                FROM reskin.webhook
                WHERE guild_id = $1
                """,
                ctx.guild.id,
            )
            if (
                channel := cast(
                    Optional[TextChannel], ctx.guild.get_channel(record["channel_id"])
                )
            )
        ]

        await ctx.neutral(
            "Setting up the reskin webhooks...",
            "This might take a while to complete",
        )
        async with ctx.typing():
            FILTERED_NAMES = ("ticket", "log", "audit")
            for channel in ctx.guild.text_channels[:30]:
                if channel in (c for c, _ in webhooks):
                    continue

                elif any(name in channel.name.lower() for name in FILTERED_NAMES):
                    continue

                elif channel.category and any(
                    name in channel.category.name for name in FILTERED_NAMES
                ):
                    continue

                try:
                    webhook = await asyncio.wait_for(
                        channel.create_webhook(name="zyn reskin"),
                        timeout=15,
                    )
                except asyncio.TimeoutError:
                    await ctx.warn(
                        "Webhook creation timed out while setting up reskin",
                        "We've likely been rate limited, please try again later",
                    )
                    break
                except HTTPException as exc:
                    await ctx.warn(
                        "Failed to create webhooks while setting up reskin",
                        codeblock(exc.text),
                    )
                    break

                webhooks.append((channel, webhook.id))

        await self.bot.db.executemany(
            """
            INSERT INTO reskin.webhook (guild_id, channel_id, webhook_id)
            VALUES ($1, $2, $3)
            ON CONFLICT (guild_id, channel_id) DO UPDATE
            SET webhook_id = EXCLUDED.webhook_id
            """,
            [
                (ctx.guild.id, channel.id, webhook_id)
                for channel, webhook_id in webhooks
            ],
        )
        await cache.delete_match(f"reskin:webhook:{ctx.guild.id}:*")

        if ctx.response:
            await quietly_delete(ctx.response)

        return await ctx.approve(
            f"Successfully setup reskin for {plural(webhooks, md='`'):channel}"
        )

    @reskin.command(name="disable", aliases=["off"], description="administrator")
    @has_permissions(administrator=True)
    async def reskin_disable(self, ctx: Context) -> Message:
        """
        Disable the reskin system server wide.
        """

        await ctx.settings.update(reskin=False)
        return await ctx.approve("No longer reskinning messages for this server")

    @reskin.command(
        name="username", aliases=["name"], usage="<username>", brief="My Cool Reskin"
    )
    async def reskin_username(
        self,
        ctx: Context,
        *,
        username: Range[str, 1, 32],
    ) -> Message:
        """
        Set your personal reskin username.
        """

        if any(
            forbidden in username.lower()
            for forbidden in (
                "clyde",
                "discord",
                "bleed",
                "haunt",
                "dyno",
                "mee6",
                "wock",
                "melanie",
                "heal",
                "wonder",
                "rival",
            )
        ):
            return await ctx.warn(
                "That username is either reserved or forbidden",
                "Attempting to bypass this will result in a blacklist",
            )

        await self.bot.db.execute(
            """
            INSERT INTO reskin.config (user_id, username)
            VALUES ($1, $2)
            ON CONFLICT (user_id) DO UPDATE
            SET username = EXCLUDED.username
            """,
            ctx.author.id,
            username,
        )
        await ReskinConfig.revalidate(self.bot, ctx.author)

        return await ctx.approve(f"Your reskin username has been set as **{username}**")

    @reskin.command(
        name="avatar",
        aliases=["icon", "av"],
        usage="<attatchment|url>",
        brief="https://assets.zyn.bot/zyn.png",
    )
    async def reskin_avatar(
        self,
        ctx: Context,
        attachment: PartialAttachment = parameter(
            default=PartialAttachment.fallback,
        ),
    ) -> Message:
        """
        Set your personal reskin avatar.
        """

        if not attachment.is_image():
            return await ctx.warn("The attachment must be an image")

        await self.bot.db.execute(
            """
            INSERT INTO reskin.config (user_id, avatar_url)
            VALUES ($1, $2)
            ON CONFLICT (user_id) DO UPDATE
            SET avatar_url = EXCLUDED.avatar_url
            """,
            ctx.author.id,
            attachment.url,
        )
        await ReskinConfig.revalidate(self.bot, ctx.author)

        return await ctx.approve("Your reskin avatar has been set")

    @reskin.command(name="remove", aliases=["reset"])
    async def reskin_remove(self, ctx: Context) -> Message:
        """
        Remove your personal reskin settings.
        """

        await self.bot.db.execute(
            """
            DELETE FROM reskin.config
            WHERE user_id = $1
            """,
            ctx.author.id,
        )
        await ReskinConfig.revalidate(self.bot, ctx.author)

        return await ctx.approve("Your reskin settings have been removed")
