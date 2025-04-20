from secrets import token_urlsafe
from typing import Optional, cast

import discord
from discord import Embed, HTTPException, Message, TextChannel
from discord.ext.commands import (
    BucketType,
    Range,
    cooldown,
    flag,
    group,
    has_permissions,
)
from discord.utils import get

from tools import CompositeMetaClass, MixinMeta
from tools.client import Context, FlagConverter
from tools.formatter import codeblock, vowel
from tools.paginator import Paginator
from tools.parser import Script


class Flags(FlagConverter):
    username: Optional[Range[str, 1, 80]] = flag(
        aliases=["name"],
        description="The name of the webhook.",
    )
    avatar_url: Optional[str] = flag(
        aliases=["avatar"],
        description="The avatar URL of the webhook.",
    )


class Webhook(MixinMeta, metaclass=CompositeMetaClass):
    """
    Forward messages through webhooks.
    """

    @group(
        aliases=["hook", "wh"],
        invoke_without_command=True,
        description="manage webhooks",
    )
    @has_permissions(manage_webhooks=True)
    async def webhook(self, ctx: Context) -> Message:
        """
        Forward messages through webhooks.
        """

        return await ctx.send_help(ctx.command)

    @webhook.command(
        name="create",
        aliases=["new"],
        description="manage webhooks",
        usage="[channel] [name]",
        brief="#updates Fortnite",
    )
    @cooldown(6, 480, BucketType.guild)
    @has_permissions(manage_webhooks=True)
    async def webhook_create(
        self,
        ctx: Context,
        channel: Optional[TextChannel],
        *,
        name: Optional[str],
    ) -> Message:
        """
        Create a new webhook.
        """

        channel = cast(TextChannel, channel or ctx.channel)
        if not isinstance(channel, TextChannel):
            return await ctx.warn("You can only create webhooks in text channels")

        webhook: Optional[discord.Webhook] = None
        webhook_id = cast(
            Optional[int],
            await self.bot.db.fetchval(
                """
                SELECT webhook_id
                FROM webhook
                WHERE guild_id = $1
                AND channel_id = $2
                """,
                ctx.guild.id,
                channel.id,
            ),
        )
        if webhook_id:
            webhooks = await channel.webhooks()
            webhook = get(webhooks, id=webhook_id)

        identifier = token_urlsafe(6)
        webhook = webhook or await channel.create_webhook(
            name=name or f"Webhook {identifier}",
            reason=f"Webhook created by {ctx.author} ({ctx.author.id})",
        )

        await self.bot.db.execute(
            """
            INSERT INTO webhook (
                identifier,
                guild_id,
                channel_id,
                author_id,
                webhook_id
            ) VALUES ($1, $2, $3, $4, $5)
            ON CONFLICT (channel_id, webhook_id) DO UPDATE
            SET identifier = EXCLUDED.identifier
            """,
            identifier,
            ctx.guild.id,
            channel.id,
            ctx.author.id,
            webhook.id,
        )
        return await ctx.approve(
            f"Successfully created a new **webhook** with the identifier `{identifier}`"
        )

    @webhook.command(
        name="delete",
        aliases=["del"],
        description="manage webhooks",
        usage="<identifier>",
        brief="<identifier-string>",
    )
    @has_permissions(manage_webhooks=True)
    async def webhook_delete(self, ctx: Context, identifier: str) -> Message:
        """
        Delete an existing webhook.
        """

        data = await self.bot.db.fetchrow(
            """
            DELETE FROM webhook
            WHERE guild_id = $1
            AND identifier = $2
            RETURNING channel_id, webhook_id
            """,
            ctx.guild.id,
            identifier,
        )
        if not data:
            return await ctx.warn("No webhook exists with that identifier")

        channel = cast(Optional[TextChannel], self.bot.get_channel(data["channel_id"]))
        if channel:
            webhooks = await channel.webhooks()
            webhook = get(webhooks, id=data["webhook_id"])
            if webhook:
                await webhook.delete(
                    reason=f"Webhook deleted by {ctx.author} ({ctx.author.id})"
                )

        return await ctx.approve(
            f"Successfully deleted the webhook with the identifier `{identifier}`"
        )

    @webhook.command(
        name="list",
        aliases=["ls"],
        description="manage webhooks",
    )
    @has_permissions(manage_webhooks=True)
    async def webhook_list(self, ctx: Context) -> Message:
        """
        View all existing webhooks.
        """

        webhooks = [
            f"{channel.mention} - `{record['identifier']}` via {author.mention if author else '**Unknown User**'}"
            for record in await self.bot.db.fetch(
                """
                SELECT identifier, channel_id, author_id
                FROM webhook
                WHERE guild_id = $1
                """,
                ctx.guild.id,
            )
            if (channel := ctx.guild.get_channel(record["channel_id"]))
            and (author := ctx.guild.get_member(record["author_id"]))
        ]
        if not webhooks:
            return await ctx.warn("No webhooks exist in this server")

        paginator = Paginator(
            ctx,
            entries=webhooks,
            embed=Embed(title="Webhooks"),
        )
        return await paginator.start()

    @webhook.command(
        name="forward",
        aliases=["send", "fwd"],
        description="manage webhooks",
        usage="<identifier> <script>",
        brief="<identifier-string> Hello World",
    )
    @has_permissions(manage_webhooks=True)
    async def webhook_forward(
        self,
        ctx: Context,
        identifier: str,
        *,
        script: Script,
    ) -> Optional[Message]:
        """
        Forward a message through a webhook.
        """

        script.template, flags = await Flags().find(ctx, script.template)
        if not script:
            return await ctx.warn("You must provide a template to forward")

        data = await self.bot.db.fetchrow(
            """
            SELECT webhook_id, channel_id
            FROM webhook
            WHERE guild_id = $1
            AND identifier = $2
            """,
            ctx.guild.id,
            identifier,
        )
        if not data:
            return await ctx.warn("No webhook exists with that identifier")

        channel = cast(Optional[TextChannel], self.bot.get_channel(data["channel_id"]))
        if not channel:
            return await ctx.warn("The channel for this webhook no longer exists")

        webhooks = await channel.webhooks()
        webhook = get(webhooks, id=data["webhook_id"])
        if not webhook:
            return await ctx.warn("The webhook for this identifier no longer exists")

        try:
            message = await script.send(
                webhook,
                wait=True,
                username=flags.username or (webhook.name or ctx.guild.name),
                avatar_url=flags.avatar_url or (webhook.avatar or ctx.guild.icon),
            )
        except HTTPException as exc:
            return await ctx.warn(
                "Something is wrong with your **script**",
                codeblock(exc.text),
            )

        if channel != ctx.channel:
            return await ctx.approve(
                f"Successfully  forwarded {vowel(script.format)} to {channel.mention} via **{message.author.name}**"
            )

        return await ctx.add_check()

    @webhook.command(
        name="edit",
        aliases=["update"],
        description="manage webhooks",
        usage="<message> <script>",
        brief="https://discord.com/channels/1135484270740246578/1143553248284909568/1251950384474493020 Not Hello World!",
    )
    @has_permissions(manage_webhooks=True)
    async def webhook_edit(
        self,
        ctx: Context,
        message: Message,
        *,
        script: Script,
    ) -> Optional[Message]:
        """
        Edit a message sent by a webhook.
        """

        if message.guild != ctx.guild:
            return await ctx.warn("The message must be in this server")

        elif not isinstance(message.channel, TextChannel):
            return await ctx.warn(
                f"That [`message`]({message.jump_url})  was not sent in a text channel"
            )

        elif not message.webhook_id:
            return await ctx.warn(
                f"That [`message`]({message.jump_url})  not sent by a webhook"
            )

        webhooks = await message.channel.webhooks()
        webhook = get(webhooks, id=message.webhook_id)
        if not webhook:
            return await ctx.warn(
                f"The webhook for that [`message`]({message.jump_url})  no longer exists"
            )

        try:
            await script.edit(message, webhook=webhook)
        except HTTPException as exc:
            return await ctx.warn(
                "Something is wrong with your **script**",
                codeblock(exc.text),
            )

        return await ctx.add_check()
