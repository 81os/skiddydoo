import re
from contextlib import suppress
from typing import Optional, cast

from discord import Embed, File, HTTPException, Member, Message, Reaction, User
from discord.ext.commands import (
    BucketType,
    Cog,
    command,
    cooldown,
    group,
    has_permissions,
)
from discord.utils import format_dt, utcnow
from humanize import naturaldelta

from tools import CompositeMetaClass, MixinMeta
from tools.client import Context
from tools.formatter import plural
from tools.paginator import Paginator

from .models import MessageSnipe, ReactionSnipe

INVITE_PATTERN = re.compile(
    r"(?:(?:https?://)?(?:www)?discord(?:app)?\.(?:(?:com|gg)/invite/[a-z0-9-_]+)|(?:https?://)?(?:www)?discord\.gg/[a-z0-9-_]+)"
)
LINK_PATTERN = re.compile(r"(https?://\S+)")


class Snipe(MixinMeta, metaclass=CompositeMetaClass):
    """
    Snipe deletion events.
    """

    @Cog.listener("on_message_delete")
    async def push_snipe(self, message: Message) -> None:
        """
        Push a message to the snipe cache.
        """

        await MessageSnipe.push(self.bot.redis, message)

    @Cog.listener("on_reaction_remove")
    async def push_reaction_snipe(
        self,
        reaction: Reaction,
        user: User,
    ) -> None:
        """
        Push a reaction to the snipe cache.
        """

        await ReactionSnipe.push(self.bot.redis, reaction, user)

    @group(aliases=["sn", "s"], invoke_without_command=True)
    @cooldown(2, 5, BucketType.member)
    async def snipe(self, ctx: Context, index: int = 1) -> Message:
        """
        Snipe the last deleted message.
        """

        message = await MessageSnipe.get(self.bot.redis, ctx.channel.id, index)
        snipes = await self.bot.redis.llen(MessageSnipe.key(ctx.channel.id))

        if not message:
            return await ctx.warn(
                f"No **sniped message** available at index `{index}`!"
                if index != 1
                else "No **messages** have been deleted recently!"
            )

        if (
            not ctx.channel.permissions_for(ctx.author).manage_messages
            and ctx.author.id not in self.bot.owner_ids
        ):
            if message.filtered:
                return await ctx.reply("bot filtered the msg lil bro")

            config = await self.bot.db.fetchrow(
                """
                    SELECT *, ARRAY(SELECT user_id FROM snipe.ignore WHERE guild_id = $1) AS ignored_ids
                    FROM snipe.filter
                    WHERE guild_id = $1
                    """,
                ctx.guild.id,
            )
            if config:
                if message.user_id in config.get("ignored_ids", []):
                    return await ctx.warn(
                        f"**{message.user_name}** is immune to being sniped!"
                    )

                if config["invites"]:
                    message.content = INVITE_PATTERN.sub(
                        "*`REDACTED INVITE`*", message.content
                    )

                if config["links"] and message.content.startswith("http"):
                    message.content = LINK_PATTERN.sub(
                        "*`REDACTED LINK`*", message.content
                    )

                for word in config["words"]:
                    if word in message.content.lower():
                        return await ctx.reply("that msg probably shouldn't be sniped")

        file: Optional[File] = None
        embed = Embed(description=message.content)
        embed.set_author(
            name=message.user_name,
            icon_url=message.user_avatar,
        )
        embed.set_footer(
            text=" • ".join(
                [
                    f"{index}/{snipes}",
                    f"Deleted {naturaldelta((utcnow() - message.deleted_at))} ago",
                ]
            ),
        )

        if message.attachments:
            for attachment in message.attachments:
                if attachment.is_image():
                    embed.set_image(url=attachment.url)
                    break

                if attachment.size > 25e6:
                    continue

                async with ctx.typing():
                    with suppress(HTTPException):
                        file = await attachment.to_file(self.bot.http)
                        break

            embed.add_field(
                name=f"**Attachment{'s' if len(message.attachments) > 1 else ''}**",
                value="\n".join([attachment.url for attachment in message.attachments]),
            )

        elif message.stickers:
            sticker_url = message.stickers[0]
            embed.set_image(url=sticker_url)

        return await ctx.reply(embed=embed, file=file)

    @snipe.command(name="clear", aliases=["wipe"], description="manage messages")
    @has_permissions(manage_messages=True)
    async def snipe_clear(self, ctx: Context) -> None:
        """
        Remove all sniped messages from the cache.
        This is an alias for the `clearsnipe` command.
        """

        return await ctx.invoke(self.clearsnipe)

    @snipe.group(name="filter", invoke_without_command=True)
    @has_permissions(manage_channels=True)
    async def snipe_filter(self, ctx: Context) -> Message:
        """
        Filter specific content from snipes.
        """

        return await ctx.send_help(ctx.command)

    @snipe_filter.command(
        name="add", description="manage messages", usage="<word>", brief="hello"
    )
    @has_permissions(manage_channels=True)
    async def snipe_filter_add(self, ctx: Context, *, word: str) -> Message:
        """
        Add a word to be filtered.
        """

        result = await self.bot.db.execute(
            """
            INSERT INTO snipe.filter (guild_id, words)
            VALUES ($1, ARRAY[$2])
            ON CONFLICT (guild_id) DO UPDATE
            SET words = ARRAY_APPEND(snipe.filter.words, $2)
            WHERE NOT snipe.filter.words @> ARRAY[$2]
            """,
            ctx.guild.id,
            word.lower(),
        )
        if result.endswith("0"):
            return await ctx.warn(f"`{word}` is already being filtered!")

        return await ctx.approve(f"Added `{word}` to the snipe filter")

    @snipe_filter.command(
        name="remove",
        aliases=[
            "delete",
            "del",
            "rm",
        ],
        description="manage channels",
        usage="<word>",
        brief="hello",
    )
    @has_permissions(manage_channels=True)
    async def snipe_filter_remove(self, ctx: Context, *, word: str) -> Message:
        """
        Remove a word from the filter.
        """

        result = await self.bot.db.execute(
            """
            UPDATE snipe.filter
            SET words = ARRAY_REMOVE(words, $2)
            WHERE guild_id = $1
            AND words @> ARRAY[$2]
            """,
            ctx.guild.id,
            word.lower(),
        )
        if result.endswith("0"):
            return await ctx.warn(f"`{word}` isn't being filtered!")

        return await ctx.approve(f"Removed `{word}` from the snipe filter")

    @snipe_filter.command(name="invites", description="manage channels")
    @has_permissions(manage_channels=True)
    async def snipe_filter_invites(self, ctx: Context) -> Message:
        """
        Toggle server invites being filtered.
        """

        status = cast(
            bool,
            await self.bot.db.fetchval(
                """
                INSERT INTO snipe.filter (guild_id, invites)
                VALUES ($1, TRUE)
                ON CONFLICT (guild_id)
                DO UPDATE SET invites = NOT snipe.filter.invites
                RETURNING invites
                """,
                ctx.guild.id,
            ),
        )

        return await ctx.approve(
            f"{'Now' if status else 'No longer'} filtering **server invites** from snipes"
        )

    @snipe_filter.command(name="links", description="manage channels")
    @has_permissions(manage_channels=True)
    async def snipe_filter_links(self, ctx: Context) -> Message:
        """
        Toggle links being filtered.
        """

        status = cast(
            bool,
            await self.bot.db.fetchval(
                """
                INSERT INTO snipe.filter (guild_id, links)
                VALUES ($1, TRUE)
                ON CONFLICT (guild_id)
                DO UPDATE SET links = NOT snipe.filter.links
                RETURNING links
                """,
                ctx.guild.id,
            ),
        )

        return await ctx.approve(
            f"{'Now' if status else 'No longer'} filtering **links** from snipes"
        )

    @snipe_filter.command(
        name="settings", aliases=["config", "view"], description="manage channels"
    )
    @has_permissions(manage_channels=True)
    async def snipe_filter_settings(self, ctx: Context) -> Message:
        """
        View the filter settings.
        """

        config = await self.bot.db.fetchrow(
            """
            SELECT invites, links, words
            FROM snipe.filter
            WHERE guild_id = $1
            """,
            ctx.guild.id,
        )
        if not config:
            return await ctx.warn("The **snipe filter** hasn't been configured yet!")

        return await ctx.send(
            embed=Embed(
                title="Snipe Filter",
                description="\n> ".join(
                    [
                        f"Filtering {plural(config['words'], '**'):word} (`{ctx.clean_prefix}snipe filter list`)",
                        f"**Invites:** {'Filtered' if config['invites'] else 'Not filtered'}",
                        f"**Links:** {'Filtered' if config['links'] else 'Not filtered'}",
                    ]
                ),
            )
        )

    @snipe_filter.command(
        name="list", aliases=["words", "ls"], description="manage channels"
    )
    @has_permissions(manage_channels=True)
    async def snipe_filter_list(self, ctx: Context) -> Message:
        """
        View all filtered words.
        """

        words = [
            f"**{record['word']}**"
            for record in await self.bot.db.fetch(
                """
                SELECT UNNEST(words) AS word
                FROM snipe.filter
                WHERE guild_id = $1
                """,
                ctx.guild.id,
            )
        ]
        if not words:
            return await ctx.warn("No words have been filtered yet!")

        paginator = Paginator(
            ctx,
            entries=words,
            embed=Embed(title="Filtered Words"),
        )
        return await paginator.start()

    @snipe_filter.command(
        name="clear", aliases=["clean", "reset"], description="manage channels"
    )
    @has_permissions(manage_channels=True)
    async def snipe_filter_clear(self, ctx: Context) -> Message:
        """
        Remove all filtered words.
        """

        await ctx.prompt(
            "Are you sure you want to remove all filtered words?",
        )

        await self.bot.db.execute(
            """
            UPDATE snipe.filter
            SET words = ARRAY[]::text[]
            WHERE guild_id = $1
            """,
            ctx.guild.id,
        )
        return await ctx.approve("Successfully  removed all filtered words")

    @snipe.group(
        name="ignore",
        aliases=["exempt"],
        invoke_without_command=True,
    )
    @has_permissions(manage_channels=True)
    async def snipe_ignore(self, ctx: Context, *, member: Member) -> Message:
        """
        Ignore a member from being sniped.
        """

        result = cast(
            bool,
            await self.bot.db.fetchval(
                """
                INSERT INTO snipe.ignore (guild_id, user_id)
                VALUES ($1, $2)
                ON CONFLICT (guild_id, user_id) DO NOTHING
                RETURNING TRUE
                """,
                ctx.guild.id,
                member.id,
            ),
        )
        if not result:
            return await ctx.warn(f"{member.mention} is already being ignored!")

        return await ctx.approve(f"Now ignoring {member.mention} from being sniped")

    @snipe_ignore.command(
        name="remove",
        aliases=[
            "delete",
            "del",
            "rm",
        ],
        description="manage channels",
    )
    @has_permissions(manage_channels=True)
    async def snipe_ignore_remove(self, ctx: Context, *, member: Member) -> Message:
        """
        Remove a member from being ignored.
        """

        result = await self.bot.db.execute(
            """
            DELETE FROM snipe.ignore
            WHERE guild_id = $1
            AND user_id = $2
            """,
            ctx.guild.id,
            member.id,
        )
        if not result:
            return await ctx.warn(f"{member.mention} isn't being ignored!")

        return await ctx.approve(f"Now allowing {member.mention} to be sniped")

    @snipe_ignore.command(name="list", aliases=["ls"], description="manage channels")
    @has_permissions(manage_channels=True)
    async def snipe_ignore_list(self, ctx: Context) -> Message:
        """
        View all members being ignored.
        """

        members = [
            f"**{member}** (`{member.id}`)"
            for record in await self.bot.db.fetch(
                """
                SELECT user_id
                FROM snipe.ignore
                WHERE guild_id = $1
                """,
                ctx.guild.id,
            )
            if (member := ctx.guild.get_member(record["user_id"]))
        ]
        if not members:
            return await ctx.warn("No members are being ignored!")

        paginator = Paginator(
            ctx,
            entries=members,
            embed=Embed(title="Ignored Members"),
        )
        return await paginator.start()

    @command(aliases=["cs"])
    @has_permissions(manage_messages=True)
    async def clearsnipe(self, ctx: Context) -> None:
        """
        Remove all sniped messages from the cache.
        """

        key = MessageSnipe.key(ctx.channel.id)
        await self.bot.redis.delete(key)

        return await ctx.add_check()

    @command(aliases=["rsnipe", "rs"])
    @cooldown(1, 3, BucketType.channel)
    async def reactionsnipe(self, ctx: Context, index: int = 1) -> Message:
        """
        Snipe the last removed reaction.
        """

        reaction = await ReactionSnipe.get(self.bot.redis, ctx.channel.id)
        if not reaction:
            return await ctx.warn(
                f"No **sniped reaction** available at index `{index}`!"
                if index != 1
                else "No **reactions** have been removed recently!"
            )

        return await ctx.neutral(
            f"**{reaction.user_name}** removed **{reaction.emoji}** [{format_dt(reaction.removed_at, 'R')}]({reaction.message_url})"
        )
