import asyncio
import re
from contextlib import suppress
from datetime import timedelta
from io import BytesIO
from logging import getLogger
from time import perf_counter
from typing import Annotated, Callable, List, Literal, Optional, cast
from zipfile import ZipFile

from discord import (
    AuditLogAction,
    AuditLogEntry,
    Color,
    Embed,
    Emoji,
    File,
    Guild,
    HTTPException,
    Member,
    Message,
    NotFound,
    NotificationLevel,
    Object,
    PartialEmoji,
    RateLimited,
    Role,
    StageChannel,
    TextChannel,
    Thread,
    User,
    VoiceChannel,
)
from discord.abc import GuildChannel
from discord.ext.commands import (
    BadArgument,
    BucketType,
    Cog,
    CommandError,
    Greedy,
    MaxConcurrency,
    Range,
    check,
    command,
    cooldown,
    group,
    has_permissions,
    max_concurrency,
    parameter,
)
from discord.utils import MISSING, format_dt, get, utcnow
from humanfriendly import format_timespan
from humanize import precisedelta
from xxhash import xxh64_hexdigest

import config
from cogs.servers.extended.security.antinuke import Settings
from main import zyn
from tools import (
    convert_image,
    enlarge_emoji,
    quietly_delete,
    strip_roles,
    unicode_emoji,
    url_to_mime,
)
from tools.client import Context
from tools.conversion import (
    Duration,
    PartialAttachment,
    StrictMember,
    StrictRole,
    StrictUser,
    TouchableMember,
)
from tools.formatter import codeblock, human_join, plural
from tools.paginator import Paginator
from tools.parser import Script

log = getLogger("zyn/mod")
MASS_ROLE_CONCURRENCY = MaxConcurrency(1, per=BucketType.guild, wait=False)


class Moderation(Cog):
    def __init__(self, bot: zyn):
        self.bot = bot

    @property
    def actions(self) -> dict[str, str]:
        return {
            "guild_update": "updated server",
            "channel_create": "created channel",
            "channel_update": "updated channel",
            "channel_delete": "deleted channel",
            "overwrite_create": "created channel permission in",
            "overwrite_update": "updated channel permission in",
            "overwrite_delete": "deleted channel permission in",
            "kick": "kicked member",
            "member_prune": "pruned members in",
            "ban": "banned member",
            "unban": "unbanned member",
            "member_update": "updated member",
            "member_role_update": "updated member roles for",
            "member_disconnect": "disconnected member",
            "member_move": "moved member",
            "bot_add": "added bot",
            "role_create": "created role",
            "role_update": "updated role",
            "role_delete": "deleted role",
            "invite_create": "created invite",
            "invite_update": "updated invite",
            "invite_delete": "deleted invite",
            "webhook_create": "created webhook",
            "webhook_update": "updated webhook",
            "webhook_delete": "deleted webhook",
            "emoji_create": "created emoji",
            "emoji_update": "updated emoji",
            "emoji_delete": "deleted emoji",
            "message_delete": "deleted message by",
            "message_bulk_delete": "bulk deleted messages in",
            "message_pin": "pinned message by",
            "message_unpin": "unpinned message by",
            "integration_create": "created integration",
            "integration_update": "updated integration",
            "integration_delete": "deleted integration",
            "sticker_create": "created sticker",
            "sticker_update": "updated sticker",
            "sticker_delete": "deleted sticker",
            "thread_create": "created thread",
            "thread_update": "updated thread",
            "thread_delete": "deleted thread",
        }

    async def reconfigure_settings(
        self,
        guild: Guild,
        channel: TextChannel | Thread,
        new_channel: TextChannel | Thread,
    ) -> List[str]:
        """
        Update server wide settings for a channel.
        """

        reconfigured: List[str] = []
        config_map = {
            "System Channel": "system_channel",
            "Public Updates Channel": "public_updates_channel",
            "Rules Channel": "rules_channel",
            "AFK Channel": "afk_channel",
        }
        for name, attr in config_map.items():
            value = getattr(channel.guild, attr, None)
            if value == channel:
                await guild.edit(**{attr: new_channel})  # type: ignore
                reconfigured.append(name)

        for table in (
            "logging",
            "gallery",
            "sticky_message",
            "welcome_message",
            "goodbye_message",
            "boost_message",
            ("disboard.config", "last_channel_id"),
            "commands.disabled",
            "fortnite.rotation",
            "feeds.youtube",
            "alerts.twitch",
            "feeds.twitter",
            "feeds.tiktok",
            "feeds.pinterest",
            "feeds.reddit",
            "feeds.instagram",
            "feeds.twitter",
        ):
            table_name = table if isinstance(table, str) else table[0]
            column = "channel_id" if isinstance(table, str) else table[1]
            result = await self.bot.db.execute(
                f"""
                UPDATE {table_name}
                SET {column} = $2
                WHERE {column} = $1
                """,
                channel.id,
                new_channel.id,
            )
            if result != "UPDATE 0":
                pretty_name = (
                    table_name.replace("_", " ")
                    .replace(".", " ")
                    .title()
                    .replace("Feeds Youtube", "YouTube Notifications")
                    .replace("Alerts Twitch", "Twitch Notifications")
                    .replace("Feeds Twitter", "Twitter Notifications")
                    .replace("Feeds Tiktok", "TikTok Notifications")
                    .replace("Feeds Pinterest", "Pinterest Notifications")
                    .replace("Feeds Reddit", "Subreddit Notifications")
                    .replace("Feeds Twitter", "Twitter Notifications")
                    .replace("Feeds Instagram", "Instagram Notifications")
                )
                reconfigured.append(pretty_name)

        return reconfigured

    def hardban_key(self, guild: Guild) -> str:
        return xxh64_hexdigest(f"hardban:{guild.id}")

    def restore_key(self, guild: Guild, member: Member) -> str:
        return xxh64_hexdigest(f"roles:{guild.id}:{member.id}")

    def forcenick_key(self, guild: Guild, member: Member) -> str:
        return xxh64_hexdigest(f"forcenick:{guild.id}:{member.id}")

    @Cog.listener()
    async def on_message_delete(self, message: Message):
        if (
            not message.guild
            or message.guild.id != 1128849931269062688
            or not isinstance(message.channel, TextChannel)
            or not isinstance(message.author, Member)
            or message.author.guild_permissions.administrator
        ):
            return

        if not await self.bot.redis.ratelimited(f"deletion:{message.author.id}", 5, 30):
            return

        channel = message.channel

        overwrite = channel.overwrites_for(message.author)
        overwrite.view_channel = False
        await channel.set_permissions(
            message.author,
            overwrite=overwrite,
        )
        await channel.send(f"{message.author.mention} was purging")

    @Cog.listener()
    async def on_member_remove(self, member: Member):
        if member.bot:
            return

        role_ids = [r.id for r in member.roles if r.is_assignable()]
        if role_ids:
            key = self.restore_key(member.guild, member)
            await self.bot.redis.set(key, role_ids, ex=3600)

    @Cog.listener("on_member_join")
    async def restore_roles(self, member: Member):
        key = self.restore_key(member.guild, member)
        role_ids = cast(
            Optional[List[int]],
            await self.bot.redis.get(key),
        )
        if not role_ids:
            return

        roles = [
            role
            for role_id in role_ids
            if (role := member.guild.get_role(role_id)) is not None
            and role.is_assignable()
            and role not in member.roles
        ]
        if not roles:
            return

        record = await self.bot.db.fetchrow(
            """
            SELECT
                reassign_roles,
                reassign_ignore_ids
            FROM settings
            WHERE guild_id = $1
            """,
            member.guild.id,
        )
        if not record or not record["reassign_roles"]:
            return

        roles = [role for role in roles if role.id not in record["reassign_ignore_ids"]]
        if not roles:
            return

        await self.bot.redis.delete(key)
        with suppress(HTTPException):
            await member.add_roles(*roles, reason="Restoration of previous roles")
            log.info(
                "Restored %s for %s (%s) in %s (%s).",
                format(plural(len(roles)), "role"),
                member,
                member.id,
                member.guild,
                member.guild.id,
            )

    @Cog.listener("on_member_join")
    async def hardban_event(self, member: Member):
        key = self.hardban_key(member.guild)
        if not await self.bot.redis.sismember(key, str(member.id)):
            return

        with suppress(HTTPException):
            await member.ban(reason="User is hard banned")

    @Cog.listener("on_audit_log_entry_member_update")
    async def forcenick_audit(self, entry: AuditLogEntry):
        if (
            not entry.user
            or not entry.target
            or not entry.user.bot
            or entry.user == self.bot.user
        ):
            return

        elif not isinstance(entry.target, Member):
            return

        key = self.forcenick_key(entry.guild, entry.target)
        if hasattr(entry.after, "nick"):
            removed = await self.bot.redis.delete(key)
            if removed:
                log.warning(
                    "Safely removed forced nickname for %s (%s) in %s (%s).",
                    entry.target,
                    entry.target.id,
                    entry.guild,
                    entry.guild.id,
                )

    async def do_removal(
        self,
        ctx: Context,
        amount: int,
        predicate: Callable[[Message], bool] = lambda _: True,
        *,
        before: Optional[Message] = None,
        after: Optional[Message] = None,
    ) -> List[Message]:
        """
        A helper function to do bulk message removal.
        """

        if not ctx.channel.permissions_for(ctx.guild.me).manage_messages:
            raise CommandError("I don't have permission to delete messages")

        if not before:
            before = ctx.message

        def check(message: Message) -> bool:
            if message.created_at < (utcnow() - timedelta(weeks=2)):
                return False

            elif message.pinned:
                return False

            return predicate(message)

        await quietly_delete(ctx.message)
        messages = await ctx.channel.purge(
            limit=amount,
            check=check,
            before=before,
            after=after,
        )
        if not messages:
            raise CommandError("No messages were found, try a larger search?")

        return messages

    @command(hidden=True)
    @check(lambda ctx: ctx.author.id in config.CLIENT.OWNER_IDS)
    async def me(self, ctx: Context) -> None:
        """
        Clean up your messages.
        """

        await self.do_removal(
            ctx,
            100,
            lambda message: bool(
                message.author == ctx.author
                or (
                    message.reference
                    and isinstance(message.reference.resolved, Message)
                    and message.reference.resolved.author == ctx.author
                )
            ),
        )

    @command(
        aliases=["bc"], description="manage messages", usage="[amount]", brief="100"
    )
    @has_permissions(manage_messages=True)
    async def cleanup(
        self,
        ctx: Context,
        amount: Annotated[
            int,
            Range[int, 1, 1000],
        ] = 100,
    ):
        """
        Remove bot commands and messages, must be 100 or less at once.
        """

        await self.do_removal(
            ctx,
            amount,
            lambda message: (
                message.author.bot
                or message.content.startswith(
                    (ctx.clean_prefix, ",", ";", ".", "!", "$")
                )
            ),
        )

    @group(
        aliases=["prune", "rm", "c"],
        invoke_without_command=True,
    )
    @max_concurrency(1, BucketType.channel)
    @has_permissions(manage_messages=True)
    async def purge(
        self,
        ctx: Context,
        user: Optional[
            Annotated[
                Member,
                StrictMember,
            ]
            | Annotated[
                User,
                StrictUser,
            ]
        ],
        amount: Annotated[
            int,
            Range[int, 1, 1000],
        ],
    ):
        """
        Base command for mass message removal.
        """

        await self.do_removal(
            ctx,
            amount,
            lambda message: message.author == user if user else True,
        )

    @purge.command(
        name="embeds",
        aliases=["embed"],
        description="manage messages",
        usage="[amount]",
        brief="100",
    )
    @has_permissions(manage_messages=True)
    async def purge_embeds(
        self,
        ctx: Context,
        amount: Annotated[
            int,
            Range[int, 1, 1000],
        ] = 100,
    ):
        """
        Remove messages which have embeds.
        """

        await self.do_removal(
            ctx,
            amount,
            lambda message: bool(message.embeds),
        )

    @purge.command(
        name="files",
        aliases=["file"],
        description="manage messages",
        usage="[amount]",
        brief="100",
    )
    @has_permissions(manage_messages=True)
    async def purge_files(
        self,
        ctx: Context,
        amount: Annotated[
            int,
            Range[int, 1, 1000],
        ] = 100,
    ):
        """
        Remove messages which have files.
        """

        await self.do_removal(
            ctx,
            amount,
            lambda message: bool(message.attachments),
        )

    @purge.command(
        name="images",
        aliases=["image"],
        description="manage messages",
        usage="[amount]",
        brief="100",
    )
    @has_permissions(manage_messages=True)
    async def purge_images(
        self,
        ctx: Context,
        amount: Annotated[
            int,
            Range[int, 1, 1000],
        ] = 100,
    ):
        """
        Remove messages which have images.
        """

        await self.do_removal(
            ctx,
            amount,
            lambda message: bool(message.attachments or message.embeds),
        )

    @purge.command(
        name="stickers",
        aliases=["sticker"],
        description="manage messages",
        usage="[amount]",
        brief="100",
    )
    @has_permissions(manage_messages=True)
    async def purge_stickers(
        self,
        ctx: Context,
        amount: Annotated[
            int,
            Range[int, 1, 1000],
        ] = 100,
    ):
        """
        Remove messages which have stickers.
        """

        await self.do_removal(
            ctx,
            amount,
            lambda message: bool(message.stickers),
        )

    @purge.command(
        name="voice",
        aliases=["vm"],
        description="manage messages",
        usage="[amount]",
        brief="100",
    )
    @has_permissions(manage_messages=True)
    async def purge_voice(
        self,
        ctx: Context,
        amount: Annotated[
            int,
            Range[int, 1, 1000],
        ] = 100,
    ):
        """
        Remove voice messages.
        """

        await self.do_removal(
            ctx,
            amount,
            lambda message: any(
                attachment.waveform for attachment in message.attachments
            ),
        )

    @purge.command(
        name="system",
        aliases=["sys"],
        description="manage messages",
        usage="[amount]",
        brief="100",
    )
    @has_permissions(manage_messages=True)
    async def purge_system(
        self,
        ctx: Context,
        amount: Annotated[
            int,
            Range[int, 1, 1000],
        ] = 100,
    ):
        """
        Remove system messages.
        """

        await self.do_removal(ctx, amount, lambda message: message.is_system())

    @purge.command(
        name="mentions",
        aliases=["mention"],
        description="manage messages",
        usage="[amount]",
        brief="100",
    )
    @has_permissions(manage_messages=True)
    async def purge_mentions(
        self,
        ctx: Context,
        amount: Annotated[
            int,
            Range[int, 1, 1000],
        ] = 100,
    ):
        """
        Remove messages which have mentions.
        """

        await self.do_removal(
            ctx,
            amount,
            lambda message: bool(message.mentions),
        )

    @purge.command(
        name="emojis",
        aliases=[
            "emotes",
            "emoji",
            "emote",
        ],
        description="manage messages",
        usage="[amount]",
        brief="100",
    )
    @has_permissions(manage_messages=True)
    async def purge_emojis(
        self,
        ctx: Context,
        amount: Annotated[
            int,
            Range[int, 1, 1000],
        ] = 100,
    ):
        """
        Remove messages which have custom emojis.
        """

        custom_emoji = re.compile(r"<a?:[a-zA-Z0-9\_]+:([0-9]+)>")

        await self.do_removal(
            ctx,
            amount,
            lambda message: bool(message.content)
            and bool(custom_emoji.search(message.content)),
        )

    @purge.command(
        name="invites",
        aliases=[
            "invite",
            "inv",
        ],
        description="manage messages",
        usage="[amount]",
        brief="100",
    )
    @has_permissions(manage_messages=True)
    async def purge_invites(
        self,
        ctx: Context,
        amount: Annotated[
            int,
            Range[int, 1, 1000],
        ] = 100,
    ):
        """
        Remove messages which have invites.
        """

        invite_link = re.compile(
            r"(?:https?://)?discord(?:\.gg|app\.com/invite)/[a-zA-Z0-9]+/?"
        )

        await self.do_removal(
            ctx,
            amount,
            lambda message: bool(message.content)
            and bool(invite_link.search(message.content)),
        )

    @purge.command(
        name="links",
        aliases=["link"],
        description="manage messages",
        usage="[amount]",
        brief="100",
    )
    @has_permissions(manage_messages=True)
    async def purge_links(
        self,
        ctx: Context,
        amount: Annotated[
            int,
            Range[int, 1, 1000],
        ] = 100,
    ):
        """
        Remove messages which have links.
        """

        await self.do_removal(
            ctx,
            amount,
            lambda message: bool(message.content) and "http" in message.content.lower(),
        )

    @purge.command(
        name="contains",
        aliases=["contain"],
        description="manage messages",
        usage="<substring> [amount]",
        brief="frick 100",
    )
    @has_permissions(manage_messages=True)
    async def purge_contains(
        self,
        ctx: Context,
        substring: Annotated[
            str,
            Range[str, 2],
        ],
        amount: Annotated[
            int,
            Range[int, 1, 1000],
        ] = 100,
    ):
        """
        Remove messages which contain a substring.

        The substring must be at least 3 characters long.
        """

        await self.do_removal(
            ctx,
            amount,
            lambda message: bool(message.content)
            and substring.lower() in message.content.lower(),
        )

    @purge.command(
        name="startswith",
        aliases=[
            "prefix",
            "start",
            "sw",
        ],
        description="manage messages",
        usage="<substring> [amount]",
        brief="frick! 100",
    )
    @has_permissions(manage_messages=True)
    async def purge_startswith(
        self,
        ctx: Context,
        substring: Annotated[
            str,
            Range[str, 3],
        ],
        amount: Annotated[
            int,
            Range[int, 1, 1000],
        ] = 100,
    ):
        """
        Remove messages which start with a substring.

        The substring must be at least 3 characters long.
        """

        await self.do_removal(
            ctx,
            amount,
            lambda message: bool(message.content)
            and message.content.lower().startswith(substring.lower()),
        )

    @purge.command(
        name="endswith",
        aliases=[
            "suffix",
            "end",
            "ew",
        ],
        description="manage messages",
        usage="<substring> [amount]",
        brief="dude! 100",
    )
    @has_permissions(manage_messages=True)
    async def purge_endswith(
        self,
        ctx: Context,
        substring: Annotated[
            str,
            Range[str, 3],
        ],
        amount: Annotated[
            int,
            Range[int, 1, 1000],
        ] = 100,
    ):
        """
        Remove messages which end with a substring.

        The substring must be at least 3 characters long.
        """

        await self.do_removal(
            ctx,
            amount,
            lambda message: bool(message.content)
            and message.content.lower().endswith(substring.lower()),
        )

    @purge.command(
        name="humans",
        aliases=["human"],
        description="manage messages",
        usage="[amount]",
        brief="100",
    )
    @has_permissions(manage_messages=True)
    async def purge_humans(
        self,
        ctx: Context,
        amount: Annotated[
            int,
            Range[int, 1, 1000],
        ] = 100,
    ):
        """
        Remove messages which are not from a bot.
        """

        await self.do_removal(
            ctx,
            amount,
            lambda message: not message.author.bot,
        )

    @purge.command(
        name="bots",
        aliases=["bot"],
        description="manage messages",
        usage="[amount]",
        brief="100",
    )
    @has_permissions(manage_messages=True)
    async def purge_bots(
        self,
        ctx: Context,
        amount: Annotated[
            int,
            Range[int, 1, 1000],
        ] = 100,
    ):
        """
        Remove messages which are from a bot.
        """

        await self.do_removal(
            ctx,
            amount,
            lambda message: message.author.bot,
        )

    @purge.command(
        name="webhooks",
        aliases=["webhook"],
        description="manage messages",
        usage="[amount]",
        brief="100",
    )
    @has_permissions(manage_messages=True)
    async def purge_webhooks(
        self,
        ctx: Context,
        amount: Annotated[
            int,
            Range[int, 1, 1000],
        ] = 100,
    ):
        """
        Remove messages which are from a webhook.
        """

        await self.do_removal(
            ctx,
            amount,
            lambda message: bool(message.webhook_id),
        )

    @purge.command(
        name="before",
        description="manage messages",
        usage="[message]",
        brief="1251628229538877520",
    )
    @has_permissions(manage_messages=True)
    async def purge_before(
        self,
        ctx: Context,
        message: Optional[Message],
    ):
        """
        Remove messages before a target message.
        """

        message = message or ctx.replied_message
        if not message:
            return await ctx.send_help(ctx.command)

        if message.channel != ctx.channel:
            return await ctx.send_help(ctx.command)

        await self.do_removal(
            ctx,
            300,
            before=message,
        )

    @purge.command(
        name="after",
        aliases=["upto", "up"],
        description="manage messages",
        usage="[message]",
        brief="1251628229538877520",
    )
    @has_permissions(manage_messages=True)
    async def purge_after(
        self,
        ctx: Context,
        message: Optional[Message],
    ):
        """
        Remove messages after a target message.
        """

        message = message or ctx.replied_message
        if not message:
            return await ctx.send_help(ctx.command)

        if message.channel != ctx.channel:
            return await ctx.send_help(ctx.command)

        await self.do_removal(
            ctx,
            300,
            after=message,
        )

    @purge.command(
        name="between",
        description="manage messages",
        usage="[start] [finish]",
        brief="1251627604910542969 1251628229538877520",
    )
    @has_permissions(manage_messages=True)
    async def purge_between(
        self,
        ctx: Context,
        start: Message,
        finish: Message,
    ):
        """
        Remove messages between two messages.
        """

        if start.channel != ctx.channel or finish.channel != ctx.channel:
            return await ctx.send_help(ctx.command)

        await self.do_removal(
            ctx,
            2000,
            after=start,
            before=finish,
        )

    @purge.command(
        name="except",
        aliases=[
            "besides",
            "schizo",
        ],
        description="manage messages",
        usage="<member> [amount]",
        brief="@yurrion 100",
    )
    @has_permissions(manage_messages=True)
    async def purge_except(
        self,
        ctx: Context,
        member: Member,
        amount: Annotated[
            int,
            Range[int, 1, 1000],
        ] = 500,
    ):
        """
        Remove messages not sent by a member.
        """

        await self.do_removal(ctx, amount, lambda message: message.author != member)

    @purge.command(
        name="reactions",
        aliases=["reaction", "react"],
        description="manage messages",
        usage="[amount]",
        brief="100",
    )
    @has_permissions(manage_messages=True)
    @max_concurrency(1, BucketType.channel)
    async def purge_reactions(
        self,
        ctx: Context,
        amount: Annotated[
            int,
            Range[int, 1, 1000],
        ] = 100,
    ):
        """
        Remove reactions from messages.

        This command is by no means quick,
        therefore it will take a while to complete.
        """

        total_removed: int = 0
        async with ctx.typing():
            async for message in ctx.channel.history(limit=amount, before=ctx.message):
                if len(message.reactions):
                    total_removed += sum(
                        reaction.count for reaction in message.reactions
                    )
                    await message.clear_reactions()

        return await ctx.approve(
            f"Successfully removed {plural(total_removed, md='`'):reaction}"
        )

    async def do_mass_role(
        self,
        ctx: Context,
        role: Role,
        predicate: Callable[[Member], bool] = lambda _: True,
        *,
        action: Literal["add", "remove"] = "add",
        failure_message: Optional[str] = None,
    ) -> Message:
        """
        A helper method to mass add or remove a role from members.
        """

        if not failure_message:
            failure_message = (
                f"Everyone you can manage already has {role.mention}"
                if action == "add"
                else f"Nobody you can manage has {role.mention}"
            )

        if not ctx.guild.chunked:
            await ctx.guild.chunk(cache=True)

        members = []
        for member in ctx.guild.members:
            if not predicate(member):
                continue

            # We want to check if the member already has the role if we're adding it,
            # or if they don't have the role if we're removing it.
            if (role in member.roles) == (action == "add"):
                continue

            try:
                await TouchableMember(allow_author=True).check(ctx, member)
            except BadArgument:  # Indicates that the member is not touchable.
                continue

            members.append(member)

        if not members:
            return await ctx.warn(failure_message)

        word = "to" if action == "add" else "from"

        pending_message = await ctx.neutral(
            f"Starting to **{action}** {role.mention} "
            f"{word} {plural(len(members), md='`'):member}...",
            f"This will take around **{format_timespan(len(members))}**",
        )

        failed: List[Member] = []
        try:
            async with ctx.typing():
                for member in members:
                    try:
                        if action == "add":
                            await member.add_roles(
                                role,
                                reason=f"Mass role {action} by {ctx.author}",
                            )
                        else:
                            await member.remove_roles(
                                role,
                                reason=f"Mass role {action} by {ctx.author}",
                            )

                    except HTTPException:
                        failed.append(member)
                        if len(failed) >= 10:
                            break

        finally:
            await quietly_delete(pending_message)

        result = [
            f"{action.title()[:5]}ed {role.mention} {word} {plural(len(members) - len(failed), md='`'):member}"
        ]
        if failed:
            result.append(
                f"Failed {action[:5]}ing {role.mention} {word} {plural(len(failed), md='`'):member}: {', '.join(member.mention for member in failed)}"
            )

        return await ctx.approve(*result)

    @group(
        aliases=["r"],
        invoke_without_command=True,
    )
    @has_permissions(manage_roles=True)
    async def role(
        self,
        ctx: Context,
        member: Annotated[
            Member,
            TouchableMember(
                allow_author=True,
            ),
        ],
        *,
        role: Annotated[
            Role,
            StrictRole,
        ],
    ) -> Message:
        """
        Base command for role management.
        This command will add or remove a role from a member.
        """

        if role in member.roles:
            return await ctx.invoke(self.role_remove, member=member, role=role)

        return await ctx.invoke(self.role_add, member=member, role=role)

    @role.command(
        name="add",
        aliases=["grant"],
        description="manage roles",
        usage="<member> <role>",
        brief="@yurrion @Admin",
    )
    @has_permissions(manage_roles=True)
    async def role_add(
        self,
        ctx: Context,
        member: Annotated[
            Member,
            TouchableMember(
                allow_author=True,
            ),
        ],
        *,
        role: Annotated[
            Role,
            StrictRole,
        ],
    ) -> Message:
        """
        Add a role to a member.
        """

        if role in member.roles:
            return await ctx.warn(f"{member.mention} already has {role.mention}")

        reason = f"Added by {ctx.author.name} ({ctx.author.id})"
        await member.add_roles(role, reason=reason)
        return await ctx.approve(f"Added {role.mention} to {member.mention}")

    @role.command(
        name="remove",
        aliases=["rm"],
        description="manage roles",
        usage="<member> <role>",
        brief="@yurrion @Admin",
    )
    @has_permissions(manage_roles=True)
    async def role_remove(
        self,
        ctx: Context,
        member: Annotated[
            Member,
            TouchableMember(
                allow_author=True,
            ),
        ],
        *,
        role: Annotated[
            Role,
            StrictRole,
        ],
    ) -> Message:
        """
        Remove a role from a member.
        """

        if role not in member.roles:
            return await ctx.warn(f"{member.mention} doesn't have {role.mention}")

        reason = f"Removed by {ctx.author.name} ({ctx.author.id})"
        await member.remove_roles(role, reason=reason)
        return await ctx.approve(f"Removed {role.mention} from {member.mention}")

    @role.command(
        name="restore",
        aliases=["re"],
        description="manage roles",
        usage="<member>",
        brief="@yurrion",
    )
    @has_permissions(manage_roles=True)
    async def role_restore(
        self,
        ctx: Context,
        member: Annotated[
            Member,
            TouchableMember,
        ],
    ) -> Message:
        """
        Restore a member's previous roles.
        """

        key = self.restore_key(ctx.guild, member)
        role_ids = cast(
            Optional[List[int]],
            await self.bot.redis.getdel(key),
        )
        if not role_ids:
            return await ctx.warn(f"No roles to restore for {member.mention}")

        roles = [
            role
            for role_id in role_ids
            if (role := ctx.guild.get_role(role_id)) is not None
            and role.is_assignable()
            and role not in member.roles
            and await StrictRole().check(ctx, role)
        ]
        if not roles:
            return await ctx.warn(f"{member.mention} doesn't have any previous roles")

        await member.add_roles(
            *roles,
            reason=f"Restoration of previous roles by {ctx.author.name} ({ctx.author.id})",
        )
        return await ctx.approve(
            f"Restored {human_join([role.mention for role in roles], final='and')} to {member.mention}"
        )

    @role.command(
        name="create",
        aliases=["make"],
        description="manage roles",
        usage="[color] [hoist] <name>",
        brief="#FFFFFF true Yuri",
    )
    @has_permissions(manage_roles=True)
    async def role_create(
        self,
        ctx: Context,
        color: Optional[Color] = None,
        hoist: Optional[bool] = None,
        *,
        name: Range[str, 1, 100],
    ) -> Message:
        """
        Create a role.
        """

        if len(ctx.guild.roles) >= 250:
            return await ctx.warn("This server has too many roles (`250`)")

        config = await Settings.fetch(self.bot, ctx.guild)
        if (
            config
            and config.role
            and not config.is_whitelisted(ctx.author)
            and await config.check_threshold(self.bot, ctx.author, "role")
        ):
            await strip_roles(
                ctx.author,
                dangerous=True,
                reason="Antinuke role threshold reached",
            )
            return await ctx.warn(
                "You've exceeded the antinuke threshold for **role creation**",
                "Your **administrative permissions** have been revoked",
            )

        reason = f"Created by {ctx.author.name} ({ctx.author.id})"
        role = await ctx.guild.create_role(
            name=name,
            color=color or Color.default(),
            hoist=hoist or False,
            reason=reason,
        )
        return await ctx.approve(f"Successfully created {role.mention}")

    @role.command(
        name="delete",
        aliases=["del"],
        description="manage roles",
        usage="<role>",
        brief="@Admin",
    )
    @has_permissions(manage_roles=True)
    async def role_delete(
        self,
        ctx: Context,
        *,
        role: Annotated[
            Role,
            StrictRole,
        ],
    ) -> Optional[Message]:
        """
        Delete a role.
        """

        if role.members:
            await ctx.prompt(
                f"{role.mention} has {plural(len(role.members), md='`'):member}, are you sure you want to delete it?",
            )

        config = await Settings.fetch(self.bot, ctx.guild)
        if (
            config
            and config.role
            and not config.is_whitelisted(ctx.author)
            and await config.check_threshold(self.bot, ctx.author, "role")
        ):
            await strip_roles(
                ctx.author,
                dangerous=True,
                reason="Antinuke role threshold reached",
            )
            return await ctx.warn(
                "You've exceeded the antinuke threshold for **role deletion**",
                "Your **administrative permissions** have been revoked",
            )

        await role.delete()
        return await ctx.add_check()

    @role.command(
        name="color",
        aliases=["colour"],
        description="manage roles",
        usage="<role> <color>",
        brief="@Admin white",
    )
    @has_permissions(manage_roles=True)
    async def role_color(
        self,
        ctx: Context,
        role: Annotated[
            Role,
            StrictRole(
                check_integrated=False,
            ),
        ],
        *,
        color: Color,
    ) -> Message:
        """
        Change a role's color.
        """

        reason = f"Changed by {ctx.author.name} ({ctx.author.id})"
        await role.edit(color=color, reason=reason)
        return await ctx.approve(f"Changed {role.mention}'s color to `{color}`")

    @role.command(
        name="rename",
        aliases=["name"],
        description="manage roles",
        usage="<role> <name>",
        brief="@Admin @Cheesecake",
    )
    @has_permissions(manage_roles=True)
    async def role_rename(
        self,
        ctx: Context,
        role: Annotated[
            Role,
            StrictRole(
                check_integrated=False,
            ),
        ],
        *,
        name: Range[str, 1, 100],
    ) -> None:
        """
        Change a role's name.
        """

        reason = f"Changed by {ctx.author.name} ({ctx.author.id})"
        await role.edit(name=name, reason=reason)
        return await ctx.add_check()

    @role.command(
        name="hoist", description="manage roles", usage="<role>", brief="@Admin"
    )
    @has_permissions(manage_roles=True)
    async def role_hoist(
        self,
        ctx: Context,
        *,
        role: Annotated[
            Role,
            StrictRole(
                check_integrated=False,
            ),
        ],
    ) -> Message:
        """
        Toggle if a role should appear in the member list.
        """

        reason = f"Changed by {ctx.author.name} ({ctx.author.id})"
        await role.edit(hoist=not role.hoist, reason=reason)
        return await ctx.approve(
            f"{role.mention} is {'now' if role.hoist else 'no longer'} hoisted"
        )

    @role.command(
        name="mentionable", description="manage roles", usage="<role>", brief="@Admin"
    )
    @has_permissions(manage_roles=True)
    async def role_mentionable(
        self,
        ctx: Context,
        *,
        role: Annotated[
            Role,
            StrictRole(
                check_integrated=False,
            ),
        ],
    ) -> Message:
        """
        Toggle if a role should be mentionable.
        """

        reason = f"Changed by {ctx.author.name} ({ctx.author.id})"
        await role.edit(mentionable=not role.mentionable, reason=reason)
        return await ctx.approve(
            f"{role.mention} is {'now' if role.mentionable else 'no longer'} mentionable"
        )

    @role.command(
        name="icon",
        description="manage roles",
        usage="<role> <icon|attatchment|url>",
        brief="@Admin https://r2.zyn.bot/zyn.png",
    )
    @has_permissions(manage_roles=True)
    async def role_icon(
        self,
        ctx: Context,
        role: Annotated[
            Role,
            StrictRole(
                check_integrated=False,
            ),
        ],
        icon: PartialEmoji | PartialAttachment | str = parameter(
            default=PartialAttachment.fallback,
        ),
    ) -> Message:
        """
        Change a role's icon.
        """

        if ctx.guild.premium_tier < 2:
            return await ctx.warn(
                "Role icons are only available for **level 2** boosted servers"
            )

        reason = f"Changed by {ctx.author.name} ({ctx.author.id})"
        if isinstance(icon, str) and icon in ("none", "remove", "delete"):
            if not role.display_icon:
                return await ctx.warn(f"{role.mention} doesn't have an icon")

            await role.edit(display_icon=None, reason=reason)
            return await ctx.approve(f"Removed {role.mention}'s icon")

        buffer: bytes | str
        processing: Optional[Message] = None

        if isinstance(icon, str):
            buffer = icon
        elif isinstance(icon, PartialEmoji):
            buffer = await icon.read()
            if icon.animated:
                processing = await ctx.neutral(
                    "Converting animated emoji to a static image..."
                )
                buffer = await convert_image(buffer, "png")  # type: ignore

        elif icon.is_gif():
            processing = await ctx.neutral("Converting GIF to a static image...")
            buffer = await convert_image(icon.buffer, "png")  # type: ignore

        elif not icon.is_image():
            return await ctx.warn("The attachment must be an image")

        else:
            buffer = icon.buffer

        if processing:
            await processing.delete(delay=0.5)

        await role.edit(
            display_icon=buffer,
            reason=reason,
        )
        return await ctx.approve(
            f"Changed {role.mention}'s icon to "
            + (
                f"[**image**]({icon.url})"
                if isinstance(icon, PartialAttachment)
                else f"**{icon}**"
            )
        )

    @role.group(
        name="all",
        aliases=["everyone"],
        description="manage channels",
        brief="@member",
        invoke_without_command=True,
        max_concurrency=MASS_ROLE_CONCURRENCY,
    )
    @has_permissions(manage_roles=True)
    async def role_all(
        self,
        ctx: Context,
        *,
        role: Annotated[
            Role,
            StrictRole,
        ],
    ) -> Message:
        """
        Add a role to everyone.
        """

        return await self.do_mass_role(ctx, role)

    @role_all.command(
        name="remove",
        aliases=["rm"],
        max_concurrency=MASS_ROLE_CONCURRENCY,
        description="manage roles",
        usage="<role>",
        brief="@Admin",
    )
    @has_permissions(manage_roles=True)
    async def role_all_remove(
        self,
        ctx: Context,
        *,
        role: Annotated[
            Role,
            StrictRole,
        ],
    ) -> Message:
        """
        Remove a role from everyone.
        """

        return await self.do_mass_role(
            ctx,
            role,
            action="remove",
        )

    @role.group(
        name="humans",
        description="manage roles",
        brief="@members",
        invoke_without_command=True,
        max_concurrency=MASS_ROLE_CONCURRENCY,
    )
    @has_permissions(manage_roles=True)
    async def role_humans(
        self,
        ctx: Context,
        *,
        role: Annotated[
            Role,
            StrictRole,
        ],
    ) -> Message:
        """
        Add a role to all humans.
        """

        return await self.do_mass_role(
            ctx,
            role,
            lambda member: not member.bot,
        )

    @role_humans.command(
        name="remove",
        aliases=["rm"],
        max_concurrency=MASS_ROLE_CONCURRENCY,
        description="manage roles",
        usage="<role>",
        brief="@Admin",
    )
    @has_permissions(manage_roles=True)
    async def role_humans_remove(
        self,
        ctx: Context,
        *,
        role: Annotated[
            Role,
            StrictRole,
        ],
    ) -> Message:
        """
        Remove a role from all humans.
        """

        return await self.do_mass_role(
            ctx,
            role,
            lambda member: not member.bot,
            action="remove",
        )

    @role.group(
        name="bots",
        invoke_without_command=True,
        description="manage roles",
        brief="@bots",
        max_concurrency=MASS_ROLE_CONCURRENCY,
    )
    @has_permissions(manage_roles=True)
    async def role_bots(
        self,
        ctx: Context,
        *,
        role: Annotated[
            Role,
            StrictRole,
        ],
    ) -> Message:
        """
        Add a role to all bots.
        """

        return await self.do_mass_role(
            ctx,
            role,
            lambda member: member.bot,
        )

    @role_bots.command(
        name="remove",
        aliases=["rm"],
        max_concurrency=MASS_ROLE_CONCURRENCY,
        description="manage roles",
        usage="<role>",
        brief="@Admin",
    )
    @has_permissions(manage_roles=True)
    async def role_bots_remove(
        self,
        ctx: Context,
        *,
        role: Annotated[
            Role,
            StrictRole,
        ],
    ) -> Message:
        """
        Remove a role from all bots.
        """

        return await self.do_mass_role(
            ctx,
            role,
            lambda member: member.bot,
            action="remove",
        )

    @role.group(
        name="has",
        aliases=["with", "in"],
        description="manage roles",
        brief="@mod",
        invoke_without_command=True,
        max_concurrency=MASS_ROLE_CONCURRENCY,
    )
    @has_permissions(manage_roles=True)
    async def role_has(
        self,
        ctx: Context,
        role: Annotated[
            Role,
            StrictRole(
                check_integrated=False,
            ),
        ],
        *,
        assign_role: Annotated[
            Role,
            StrictRole,
        ],
    ) -> Message:
        """
        Add a role to everyone with a role.
        """

        return await self.do_mass_role(
            ctx,
            assign_role,
            lambda member: role in member.roles,
        )

    @role_has.command(
        name="remove",
        aliases=["rm"],
        max_concurrency=MASS_ROLE_CONCURRENCY,
        description="manage roles",
        usage="<role> <role|remove>",
        brief="@NotStaff @Staff",
    )
    @has_permissions(manage_roles=True)
    async def role_has_remove(
        self,
        ctx: Context,
        role: Annotated[
            Role,
            StrictRole(
                check_integrated=False,
            ),
        ],
        *,
        remove_role: Annotated[
            Role,
            StrictRole,
        ],
    ) -> Message:
        """
        Remove a role from everyone with a role.
        """

        return await self.do_mass_role(
            ctx,
            remove_role,
            lambda member: role in member.roles,
            action="remove",
        )

    @group(
        aliases=["lock"],
        brief="#chat",
        description="manage channels",
        invoke_without_command=True,
    )
    @has_permissions(manage_channels=True)
    async def lockdown(
        self,
        ctx: Context,
        channel: Optional[TextChannel | Thread],
        *,
        reason: str = "No reason provided",
    ) -> Message:
        """
        Prevent members from sending messages.
        """

        channel = cast(TextChannel | Thread, channel or ctx.channel)
        if not isinstance(channel, (TextChannel | Thread)):
            return await ctx.warn("You can only lock text channels")

        if (
            isinstance(channel, Thread)
            and channel.locked
            or isinstance(channel, TextChannel)
            and channel.overwrites_for(ctx.settings.lock_role).send_messages
        ):
            return await ctx.warn(f"{channel.mention} is already locked")

        if isinstance(channel, Thread):
            await channel.edit(
                locked=True,
                reason=f"{ctx.author.name} / {reason}",
            )
        else:
            overwrite = channel.overwrites_for(ctx.settings.lock_role)
            overwrite.send_messages = False
            await channel.set_permissions(
                ctx.settings.lock_role,
                overwrite=overwrite,
                reason=f"{ctx.author.name} / {reason}",
            )

        return await ctx.approve(f"Successfully locked down {channel.mention}")

    @lockdown.command(
        name="all",
        description="manage guild",
        usage="[reason]",
        brief="Preventing a raid.",
    )
    @has_permissions(manage_guild=True)
    @max_concurrency(1, BucketType.guild)
    @cooldown(1, 30, BucketType.guild)
    async def lockdown_all(
        self,
        ctx: Context,
        *,
        reason: str = "No reason provided",
    ) -> Message:
        """
        Prevent members from sending messages in all channels.
        """

        if not ctx.settings.lock_ignore:
            await ctx.prompt(
                "Are you sure you want to lock **ALL** channels?",
                "You haven't ignored any important channels yet",
            )

        await ctx.neutral("Locking down all channels...")
        async with ctx.typing():
            start = perf_counter()
            for channel in ctx.guild.text_channels:
                if (
                    channel.overwrites_for(ctx.settings.lock_role).send_messages
                    is False
                    or channel in ctx.settings.lock_ignore
                ):
                    continue

                overwrite = channel.overwrites_for(ctx.settings.lock_role)
                overwrite.send_messages = False
                await channel.set_permissions(
                    ctx.settings.lock_role,
                    overwrite=overwrite,
                    reason=f"{ctx.author.name} / {reason} (SERVER LOCKDOWN)",
                )

        return await ctx.approve(
            f"Successfully locked down {plural(len(ctx.guild.text_channels) - len(ctx.settings.lock_ignore), md='`'):channel} in `{perf_counter() - start:.2f}s`",
            patch=ctx.response,
        )

    @lockdown.command(
        name="role",
        description="manage channels, manage roles",
        usage="<role>",
        brief="@Admin",
    )
    @has_permissions(manage_channels=True, manage_roles=True)
    async def lockdown_role(
        self,
        ctx: Context,
        *,
        role: Annotated[
            Role,
            StrictRole(
                check_integrated=False,
                allow_default=True,
            ),
        ],
    ) -> Message:
        """
        Set the role which will be locked from sending messages.
        """

        await ctx.settings.update(lock_role_id=role.id)
        return await ctx.approve(f"Now locking {role.mention} from sending messages")

    @lockdown.group(
        name="ignore",
        description="manage channels",
        aliases=["exempt"],
        brief="#chat",
        invoke_without_command=True,
    )
    @has_permissions(manage_channels=True)
    async def lockdown_ignore(
        self,
        ctx: Context,
        *,
        channel: TextChannel,
    ) -> Message:
        """
        Ignore a channel from being unintentionally locked.
        """

        if channel in ctx.settings.lock_ignore:
            return await ctx.warn(f"{channel.mention} is already being ignored")

        ctx.settings.lock_ignore_ids.append(channel.id)
        await ctx.settings.update()
        return await ctx.approve(f"Now ignoring {channel.mention} from lockdown")

    @lockdown_ignore.command(
        name="remove",
        aliases=["delete", "del", "rm"],
        description="manage channels",
        usage="<channel>",
        brief="#general",
    )
    @has_permissions(manage_channels=True)
    async def lockdown_ignore_remove(
        self,
        ctx: Context,
        *,
        channel: TextChannel,
    ) -> Message:
        """
        Remove a channel from being ignored.
        """

        if channel not in ctx.settings.lock_ignore:
            return await ctx.warn(f"{channel.mention} isn't being ignored")

        ctx.settings.lock_ignore_ids.remove(channel.id)
        await ctx.settings.update()
        return await ctx.approve(f"No longer ignoring {channel.mention} from lockdown")

    @lockdown_ignore.command(
        name="list",
        aliases=["ls"],
        description="manage channels",
    )
    @has_permissions(manage_channels=True)
    async def lockdown_ignore_list(self, ctx: Context) -> Message:
        """
        View all channels being ignored.
        """

        if not ctx.settings.lock_ignore:
            return await ctx.warn("No channels are being ignored")

        paginator = Paginator(
            ctx,
            entries=[
                f"{channel.mention} (`{channel.id}`)"
                for channel in ctx.settings.lock_ignore
            ],
            embed=Embed(title="Ignored Channels"),
        )
        return await paginator.start()

    @group(
        aliases=["unlock"],
        invoke_without_command=True,
    )
    @has_permissions(manage_channels=True)
    async def unlockdown(
        self,
        ctx: Context,
        channel: Optional[TextChannel | Thread],
        *,
        reason: str = "No reason provided",
    ) -> Message:
        """
        Allow members to send messages.
        """

        channel = cast(TextChannel | Thread, channel or ctx.channel)
        if not isinstance(channel, (TextChannel | Thread)):
            return await ctx.warn("You can only unlock text channels")

        if (
            isinstance(channel, Thread)
            and not channel.locked
            or isinstance(channel, TextChannel)
            and channel.overwrites_for(ctx.settings.lock_role).send_messages is True
        ):
            return await ctx.warn(f"{channel.mention} is already unlocked")

        if isinstance(channel, Thread):
            await channel.edit(
                locked=False,
                reason=f"{ctx.author.name} / {reason}",
            )
        else:
            overwrite = channel.overwrites_for(ctx.settings.lock_role)
            overwrite.send_messages = True
            await channel.set_permissions(
                ctx.settings.lock_role,
                overwrite=overwrite,
                reason=f"{ctx.author.name} / {reason}",
            )

        return await ctx.approve(f"Successfully unlocked {channel.mention}")

    @unlockdown.command(
        name="all",
        description="manage guild",
        usage="[reason]",
        brief="Preventing a raid.",
    )
    @has_permissions(manage_guild=True)
    @max_concurrency(1, BucketType.guild)
    @cooldown(1, 30, BucketType.guild)
    async def unlockdown_all(
        self,
        ctx: Context,
        *,
        reason: str = "No reason provided",
    ) -> Message:
        """
        Allow members to send messages in all channels.
        """

        if not ctx.settings.lock_ignore:
            await ctx.prompt(
                "Are you sure you want to unlock **ALL** channels?",
                "You haven't ignored any important channels yet",
            )

        await ctx.neutral("Unlocking all channels...")
        async with ctx.typing():
            start = perf_counter()
            for channel in ctx.guild.text_channels:
                if (
                    channel.overwrites_for(ctx.settings.lock_role).send_messages is True
                    or channel in ctx.settings.lock_ignore
                ):
                    continue

                overwrite = channel.overwrites_for(ctx.settings.lock_role)
                overwrite.send_messages = True
                await channel.set_permissions(
                    ctx.settings.lock_role,
                    overwrite=overwrite,
                    reason=f"{ctx.author.name} / {reason} (SERVER UNLOCKDOWN)",
                )

        return await ctx.approve(
            f"Successfully unlocked {plural(len(ctx.guild.text_channels) - len(ctx.settings.lock_ignore), md='`'):channel} in `{perf_counter() - start:.2f}s`",
            patch=ctx.response,
        )

    @command(
        aliases=["private", "priv"],
        description="manage channels",
        usage="[channel] [target(member|role)]",
        brief="#general @Members",
    )
    @has_permissions(manage_channels=True)
    async def hide(
        self,
        ctx: Context,
        channel: Optional[TextChannel | VoiceChannel],
        target: Optional[Member | Role],
        *,
        reason: str = "No reason provided",
    ) -> Message:
        """
        Hide a channel from a member or role in the server.
        """

        channel = cast(TextChannel, channel or ctx.channel)
        if not isinstance(channel, (TextChannel, VoiceChannel)):
            return await ctx.warn("You can only hide text & voice channels")

        target = target or ctx.settings.lock_role

        if channel.overwrites_for(target).read_messages is False:
            return await ctx.warn(
                f"{channel.mention} is already hidden for {target.mention}"
                if target != ctx.settings.lock_role
                else f"{channel.mention} is already hidden"
            )

        overwrite = channel.overwrites_for(target)
        overwrite.read_messages = False
        await channel.set_permissions(
            target,
            overwrite=overwrite,
            reason=f"{ctx.author.name} / {reason}",
        )

        return await ctx.approve(
            f"{channel.mention} is now hidden for {target.mention}"
            if target != ctx.settings.lock_role
            else f"{channel.mention} is now hidden"
        )

    @command(
        aliases=["unhide", "public"],
        description="manage channels",
        usage="[channel] [target(member|role)]",
        brief="#general @Member",
    )
    @has_permissions(manage_channels=True)
    async def reveal(
        self,
        ctx: Context,
        channel: Optional[TextChannel | VoiceChannel],
        target: Optional[Member | Role],
        *,
        reason: str = "No reason provided",
    ) -> Message:
        """
        Reveal a channel to a member or role.
        """

        channel = cast(TextChannel, channel or ctx.channel)
        if not isinstance(channel, (TextChannel, VoiceChannel)):
            return await ctx.warn("You can only hide text & voice channels")

        target = target or ctx.settings.lock_role

        if channel.overwrites_for(target).read_messages is True:
            return await ctx.warn(
                f"{channel.mention} is already revealed for {target.mention}"
                if target != ctx.settings.lock_role
                else f"{channel.mention} is already revealed"
            )

        overwrite = channel.overwrites_for(target)
        overwrite.read_messages = True
        await channel.set_permissions(
            target,
            overwrite=overwrite,
            reason=f"{ctx.author.name} / {reason}",
        )

        return await ctx.approve(
            f"{channel.mention} is now revealed for {target.mention}"
            if target != ctx.settings.lock_role
            else f"{channel.mention} is now revealed"
        )

    @group(
        aliases=["slowmo", "slow"],
        invoke_without_command=True,
    )
    @has_permissions(manage_channels=True)
    async def slowmode(
        self,
        ctx: Context,
        channel: Optional[TextChannel],
        delay: timedelta = parameter(
            converter=Duration(
                min=timedelta(seconds=0),
                max=timedelta(hours=6),
            ),
        ),
    ) -> Message:
        """
        Set the slowmode for a channel.
        """

        channel = cast(TextChannel, channel or ctx.channel)
        if not isinstance(channel, TextChannel):
            return await ctx.warn("You can only set the slowmode for text channels")

        if channel.slowmode_delay == delay.seconds:
            return await ctx.warn(
                f"{channel.mention} already has a slowmode of **{precisedelta(delay)}**"
            )

        await channel.edit(slowmode_delay=delay.seconds)
        return await ctx.approve(
            f"Set the slowmode for {channel.mention} to **{precisedelta(delay)}**"
        )

    @slowmode.command(
        name="disable",
        aliases=["off"],
        description="manage channels",
        usage="[channel]",
        brief="#general",
    )
    @has_permissions(manage_channels=True)
    async def slowmode_disable(
        self,
        ctx: Context,
        channel: Optional[TextChannel],
    ) -> Message:
        """
        Disable slowmode for a channel.
        """

        channel = cast(TextChannel, channel or ctx.channel)
        if not isinstance(channel, TextChannel):
            return await ctx.warn("You can only set the slowmode for text channels")

        if channel.slowmode_delay == 0:
            return await ctx.warn(f"{channel.mention} already has slowmode disabled")

        await channel.edit(slowmode_delay=0)
        return await ctx.approve(f"Disabled slowmode for {channel.mention}")

    @command(
        aliases=["naughty", "sfw"],
        description="manage channels",
        usage="[channel]",
        brief="#general",
    )
    @has_permissions(manage_channels=True)
    async def nsfw(
        self,
        ctx: Context,
        channel: Optional[TextChannel],
    ) -> Message:
        """
        Mark a channel as NSFW or SFW.
        """

        channel = cast(TextChannel, channel or ctx.channel)
        if not isinstance(channel, TextChannel):
            return await ctx.warn("You can only mark text channels as NSFW")

        await channel.edit(
            nsfw=not channel.is_nsfw(),
            reason=f"Changed by {ctx.author.name} ({ctx.author.id})",
        )
        return await ctx.approve(
            f"Marked {channel.mention} as **{'NSFW' if channel.is_nsfw() else 'SFW'}**"
        )

    @group(invoke_without_command=True)
    @has_permissions(manage_channels=True)
    async def topic(
        self,
        ctx: Context,
        channel: Optional[TextChannel],
        *,
        text: Range[str, 1, 1024],
    ) -> Message:
        """
        Set a channel's topic.
        """

        channel = cast(TextChannel, channel or ctx.channel)
        if not isinstance(channel, TextChannel):
            return await ctx.warn("You can only set the topic for text channels")

        try:
            await channel.edit(
                topic=text, reason=f"Changed by {ctx.author.name} ({ctx.author.id})"
            )
        except RateLimited as exc:
            retry_after = timedelta(seconds=exc.retry_after)
            return await ctx.warn(
                f"The channel is currently ratelimited, try again in **{precisedelta(retry_after)}**"
            )

        except HTTPException as exc:
            return await ctx.warn(
                f"Failed to set the topic for {channel.mention}", codeblock(exc.text)
            )

        return await ctx.approve(f"Set the topic for {channel.mention} to `{text}`")

    @topic.command(
        name="remove",
        aliases=["delete", "del", "rm"],
        description="manage channels",
        usage="[channel]",
        brief="#general",
    )
    @has_permissions(manage_channels=True)
    async def topic_remove(
        self,
        ctx: Context,
        channel: Optional[TextChannel],
    ) -> Message:
        """
        Remove a channel's topic.
        """

        channel = cast(TextChannel, channel or ctx.channel)
        if not isinstance(channel, TextChannel):
            return await ctx.warn("You can only remove the topic for text channels")

        if not channel.topic:
            return await ctx.warn(f"{channel.mention} doesn't have a topic")

        try:
            await channel.edit(
                topic="", reason=f"Changed by {ctx.author.name} ({ctx.author.id})"
            )
        except RateLimited as exc:
            retry_after = timedelta(seconds=exc.retry_after)
            return await ctx.warn(
                f"The channel is currently ratelimited, try again in **{precisedelta(retry_after)}**"
            )

        except HTTPException as exc:
            return await ctx.warn(
                f"Failed to remove the topic for {channel.mention}",
                codeblock(exc.text),
            )

        return await ctx.approve(f"Removed the topic for {channel.mention}")

    @group(invoke_without_command=True)
    @has_permissions(manage_channels=True)
    async def drag(
        self,
        ctx: Context,
        *members: Annotated[
            Member,
            TouchableMember,
        ],
        channel: Optional[VoiceChannel | StageChannel] = None,
    ) -> Message:
        """
        Drag member(s) to the voice channel.
        """

        if not channel:
            if not ctx.author.voice or not ctx.author.voice.channel:
                return await ctx.warn("You aren't in a voice channel")

            channel = ctx.author.voice.channel

        moved: int = 0
        for member in members:
            if member in channel.members:
                continue

            with suppress(HTTPException):
                await member.move_to(
                    channel,
                    reason=f"{ctx.author} dragged member",
                )

                moved += 1

        return await ctx.approve(
            f"Moved `{moved}`/`{len(members)}` member{'s' if moved != 1 else ''} to {channel.mention}"
        )

    @drag.command(
        name="all",
        aliases=["everyone"],
        description="manage channels",
        usage="<channel>",
        brief="#general",
    )
    @has_permissions(manage_channels=True)
    @max_concurrency(1, BucketType.member)
    @cooldown(1, 10, BucketType.member)
    async def drag_all(
        self,
        ctx: Context,
        *,
        channel: VoiceChannel | StageChannel,
    ) -> Message:
        """
        Move all members to another voice channel.
        """

        if not ctx.author.voice or not ctx.author.voice.channel:
            return await ctx.warn("You aren't in a voice channel")

        elif ctx.author.voice.channel == channel:
            return await ctx.warn(f"You're already connected to {channel.mention}")

        members = ctx.author.voice.channel.members
        moved = 0
        for member in members:
            with suppress(HTTPException):
                await member.move_to(
                    channel,
                    reason=f"{ctx.author} moved all members",
                )

                moved += 1

        return await ctx.approve(
            f"Moved `{moved}`/`{len(members)}` member{'s' if moved != 1 else ''} to {channel.mention}"
        )

    @command(
        aliases=["mvall"],
        description="manage channels",
        usage="[channel] <to channel>",
        brief="#game-night #movie-night",
    )
    @has_permissions(manage_channels=True)
    async def moveall(
        self,
        ctx: Context,
        *,
        channel: VoiceChannel | StageChannel,
    ) -> Message:
        """
        Move all members to another voice channel.
        This is an alias for the `drag all` command.
        """

        return await ctx.invoke(self.drag_all, channel=channel)

    @command(aliases=["newmembers"], usage="[amount]", brief="5")
    async def newusers(
        self,
        ctx: Context,
        *,
        amount: Range[int, 5, 100] = 10,
    ) -> Message:
        """
        View a list of the newest members.

        This is useful to check for suspicious members.
        The amount parameter is limited to 100 results.
        """

        if not ctx.guild.chunked:
            await ctx.guild.chunk(cache=True)

        members = sorted(
            ctx.guild.members,
            key=lambda member: (member.joined_at or ctx.guild.created_at),
            reverse=True,
        )[:amount]

        paginator = Paginator(
            ctx,
            entries=[
                f"{member.mention} joined {format_dt(member.joined_at or ctx.guild.created_at, 'R')}"
                for member in members
            ],
            embed=Embed(title="New Members"),
        )
        return await paginator.start()

    @command(
        description="view audit log",
        usage="[user] [action]",
        brief="@yurrion ban_members",
    )
    @has_permissions(view_audit_log=True)
    async def audit(
        self,
        ctx: Context,
        user: Optional[Member | User],
        action: Optional[str],
    ) -> Message:
        """
        View server audit log entries
        """

        _action = (action or "").lower().replace(" ", "_")
        if action and not self.actions.get(_action):
            return await ctx.warn(f"`{action}` isn't a valid action")

        entries: List[str] = []
        async for entry in ctx.guild.audit_logs(
            limit=100,
            user=user or MISSING,
            action=getattr(AuditLogAction, _action, MISSING),
        ):
            target: Optional[str] = None
            if entry.target:
                with suppress(TypeError):
                    if isinstance(entry.target, GuildChannel):
                        target = f"[#{entry.target}]({entry.target.jump_url})"
                    elif isinstance(entry.target, Role):
                        target = f"@{entry.target}"
                    elif isinstance(entry.target, Object):
                        target = f"`{entry.target.id}`"
                    else:
                        target = str(entry.target)

            entries.append(
                f"**{entry.user}** {self.actions.get(entry.action.name, entry.action.name.replace('_', ' '))} "
                + (f"**{target}**" if target and "`" not in target else target or "")
            )

        if not entries:
            return await ctx.warn(
                "No **audit log** entries found"
                + (f" for **{user}**" if user else "")
                + (f" with action **{action}**" if action else "")
                + "!"
            )

        paginator = Paginator(
            ctx,
            entries=entries,
            embed=Embed(title="Audit Log"),
        )
        return await paginator.start()

    @command(
        aliases=["boot", "k"],
        description="kick members",
        usage="<member> [reason]",
        brief="@yurrion Repeatedly ignoring server rules",
    )
    @has_permissions(kick_members=True)
    @max_concurrency(1, BucketType.member)
    async def kick(
        self,
        ctx: Context,
        member: Annotated[
            Member,
            TouchableMember,
        ],
        *,
        reason: str = "No reason provided",
    ) -> Optional[Message]:
        """
        Kick a member from the server.
        """

        if member.premium_since:
            await ctx.prompt(
                f"Are you sure you want to **kick** {member.mention}?",
                "They are currently boosting the server",
            )

        config = await Settings.fetch(self.bot, ctx.guild)
        if (
            config
            and config.kick
            and not config.is_whitelisted(ctx.author)
            and await config.check_threshold(self.bot, ctx.author, "kick")
        ):
            await strip_roles(
                ctx.author, dangerous=True, reason="Antinuke kick threshold reached"
            )
            return await ctx.warn(
                "You've exceeded the antinuke threshold for **kicks**",
                "Your **administrative permissions** have been revoked",
            )

        await member.kick(reason=f"{ctx.author} / {reason}")
        if ctx.settings.invoke_kick:
            script = Script(
                ctx.settings.invoke_kick,
                [
                    ctx.guild,
                    ctx.channel,
                    member,
                    (reason, "reason"),
                    (ctx.author, "moderator"),
                ],
            )
            with suppress(HTTPException):
                return await script.send(ctx)

        return await ctx.add_check()

    @group(
        aliases=["hb"],
        invoke_without_command=True,
    )
    @has_permissions(ban_members=True)
    async def hardban(
        self,
        ctx: Context,
        user: Member | User,
        history: Optional[Range[int, 0, 7]] = None,
        *,
        reason: str = "No reason provided",
    ) -> Optional[Message]:
        """
        Permanently ban a user from the server.

        Only the server owner is able to unban them.
        Re-running this command will remove the hard ban.
        """

        if isinstance(user, Member):
            await TouchableMember().check(ctx, user)

        config = await Settings.fetch(self.bot, ctx.guild)
        if not config.is_trusted(ctx.author):
            return await ctx.warn(
                "You must be a **trusted administrator** to use this command"
            )

        key = self.hardban_key(ctx.guild)
        if await self.bot.redis.srem(key, str(user.id)):
            with suppress(NotFound):
                await ctx.guild.unban(
                    user, reason=f"Hard ban removed by {ctx.author} ({ctx.author.id})"
                )

            return await ctx.approve(f"Hard ban removed for **{user}**")

        await self.bot.redis.sadd(key, str(user.id))
        await ctx.guild.ban(
            user,
            delete_message_days=history or 0,
            reason=f"{ctx.author} / {reason}",
        )
        if ctx.settings.invoke_ban:
            script = Script(
                ctx.settings.invoke_ban,
                [
                    ctx.guild,
                    ctx.channel,
                    user,
                    (reason, "reason"),
                    (ctx.author, "moderator"),
                ],
            )
            with suppress(HTTPException):
                return await script.send(ctx)

        return await ctx.add_check()

    @hardban.command(
        name="list",
        aliases=["ls"],
        description="ban members",
    )
    @has_permissions(ban_members=True)
    async def hardban_list(self, ctx: Context) -> Message:
        """
        View all hard banned users.
        """

        config = await Settings.fetch(self.bot, ctx.guild)
        if not config.is_trusted(ctx.author):
            return await ctx.warn(
                "You must be a **trusted administrator** to use this command"
            )

        key = self.hardban_key(ctx.guild)
        if not await self.bot.redis.exists(key):
            return await ctx.warn("No users are hard banned")

        user_ids = await self.bot.redis.smembers(key)
        paginator = Paginator(
            ctx,
            entries=[
                f"**{self.bot.get_user(int(user_id)) or 'Unkown User'}** (`{user_id}`)"
                for user_id in user_ids
            ],
            embed=Embed(title="Hard Banned Users"),
        )
        return await paginator.start()

    @command(
        aliases=["deport", "b"],
        description="ban members",
        usage="<member> [history] [reason]",
        brief="@yurrion 7d Not following the servers rules.",
    )
    @has_permissions(ban_members=True)
    @max_concurrency(1, BucketType.member)
    async def ban(
        self,
        ctx: Context,
        user: Member | User,
        history: Optional[Range[int, 0, 7]] = None,
        *,
        reason: str = "No reason provided",
    ) -> Optional[Message]:
        """
        Ban a user from the server.
        """

        if isinstance(user, Member):
            await TouchableMember().check(ctx, user)
            if user.premium_since:
                await ctx.prompt(
                    f"Are you sure you want to **ban** {user.mention}?",
                    "They are currently boosting the server",
                )

        config = await Settings.fetch(self.bot, ctx.guild)
        if (
            config.ban
            and not config.is_whitelisted(ctx.author)
            and await config.check_threshold(self.bot, ctx.author, "ban")
        ):
            await strip_roles(
                ctx.author, dangerous=True, reason="Antinuke ban threshold reached"
            )
            return await ctx.warn(
                "You've exceeded the antinuke threshold for **bans**",
                "Your **administrative permissions** have been revoked",
            )

        await ctx.guild.ban(
            user,
            delete_message_seconds=history or 0,
            reason=f"{ctx.author} / {reason}",
        )
        if ctx.settings.invoke_ban:
            script = Script(
                ctx.settings.invoke_ban,
                [
                    ctx.guild,
                    ctx.channel,
                    user,
                    (reason, "reason"),
                    (ctx.author, "moderator"),
                ],
            )
            with suppress(HTTPException):
                return await script.send(ctx)

        return await ctx.add_check()

    @command(
        description="ban members",
        usage="<member> [history] [reason]",
        brief="@yurrion 7d Not following the servers rules.",
    )
    @has_permissions(ban_members=True)
    @max_concurrency(1, BucketType.member)
    async def softban(
        self,
        ctx: Context,
        member: Annotated[
            Member,
            TouchableMember,
        ],
        history: Optional[Range[int, 1, 7]] = None,
        *,
        reason: str = "No reason provided",
    ) -> Optional[Message]:
        """
        Ban then unban a member from the server.

        This is used to cleanup messages from the member.
        """

        if member.premium_since:
            await ctx.prompt(
                f"Are you sure you want to **ban** {member.mention}?",
                "They are currently boosting the server",
            )

        config = await Settings.fetch(self.bot, ctx.guild)
        if (
            config.ban
            and not config.is_whitelisted(ctx.author)
            and await config.check_threshold(self.bot, ctx.author, "ban")
        ):
            await strip_roles(
                ctx.author, dangerous=True, reason="Antinuke ban threshold reached"
            )
            return await ctx.warn(
                "You've exceeded the antinuke threshold for **bans**",
                "Your **administrative permissions** have been revoked",
            )

        await ctx.guild.ban(
            member,
            delete_message_days=history or 0,
            reason=f"{ctx.author} / {reason}",
        )
        await ctx.guild.unban(member)
        if ctx.settings.invoke_ban:
            script = Script(
                ctx.settings.invoke_ban,
                [
                    ctx.guild,
                    ctx.channel,
                    member,
                    (reason, "reason"),
                    (ctx.author, "moderator"),
                ],
            )
            with suppress(HTTPException):
                return await script.send(ctx)

        return await ctx.add_check()

    @group(
        aliases=["pardon", "unb"],
        invoke_without_command=True,
    )
    @has_permissions(ban_members=True)
    async def unban(
        self,
        ctx: Context,
        user: User,
        *,
        reason: str = "No reason provided",
    ):
        """
        Unban a user from the server.
        """

        key = self.hardban_key(ctx.guild)
        if await self.bot.redis.sismember(key, str(user.id)):
            config = await Settings.fetch(self.bot, ctx.guild)
            if not config.is_trusted(ctx.author):
                return await ctx.warn(
                    "You must be a **trusted administrator** to unban hard banned users"
                )

            await self.bot.redis.srem(key, str(user.id))

        try:
            await ctx.guild.unban(user, reason=f"{ctx.author} / {reason}")
        except NotFound:
            return await ctx.warn("That user is not banned")

        if ctx.settings.invoke_unban:
            script = Script(
                ctx.settings.invoke_unban,
                [
                    ctx.guild,
                    ctx.channel,
                    user,
                    (reason, "reason"),
                    (ctx.author, "moderator"),
                ],
            )
            with suppress(HTTPException):
                return await script.send(ctx)

        return await ctx.add_check()

    @unban.command(name="all", description="ban members")
    @has_permissions(ban_members=True)
    @max_concurrency(1, BucketType.guild)
    async def unban_all(self, ctx: Context) -> Optional[Message]:
        """
        Unban all banned users from the server.
        """

        key = self.hardban_key(ctx.guild)
        hardban_ids = await self.bot.redis.smembers(key)

        users = [
            entry.user
            async for entry in ctx.guild.bans()
            if str(entry.user.id) not in hardban_ids
        ]
        if not users:
            return await ctx.warn("There are no banned users")

        await ctx.prompt(
            f"Are you sure you want to unban {plural(users, md='`'):user}?",
        )

        async with ctx.typing():
            for user in users:
                with suppress(HTTPException):
                    await ctx.guild.unban(
                        user, reason=f"{ctx.author} ({ctx.author.id}) / UNBAN ALL"
                    )

        return await ctx.add_check()

    @group(
        aliases=["nick", "n"],
        invoke_without_command=True,
    )
    @has_permissions(manage_nicknames=True)
    async def nickname(
        self,
        ctx: Context,
        member: Annotated[
            Member,
            TouchableMember(
                allow_author=True,
            ),
        ],
        *,
        nickname: Range[str, 1, 32],
    ) -> Optional[Message]:
        """
        Change a member's nickname.
        """

        key = self.forcenick_key(ctx.guild, member)
        if await self.bot.redis.exists(key):
            return await ctx.warn(
                f"{member.mention} has a forced nickname",
                f"Use `{ctx.prefix}nickname remove {member}` to reset it",
            )

        await member.edit(
            nick=nickname,
            reason=f"{ctx.author} ({ctx.author.id})",
        )
        return await ctx.add_check()

    @nickname.command(
        name="remove",
        aliases=["reset", "rm"],
        description="manage nicknames",
        usage="<member>",
        brief="@yurrion",
    )
    @has_permissions(manage_nicknames=True)
    async def nickname_remove(
        self,
        ctx: Context,
        member: Annotated[
            Member,
            TouchableMember,
        ],
    ) -> None:
        """
        Reset a member's nickname.
        """

        key = self.forcenick_key(ctx.guild, member)
        await self.bot.redis.delete(key)

        await member.edit(
            nick=None,
            reason=f"{ctx.author} ({ctx.author.id})",
        )
        return await ctx.add_check()

    @nickname.group(
        name="force",
        description="manage nicknames",
        aliases=["lock"],
        brief="@yurrion yuri",
        invoke_without_command=True,
    )
    @has_permissions(manage_nicknames=True)
    async def nickname_force(
        self,
        ctx: Context,
        member: Annotated[
            Member,
            TouchableMember,
        ],
        *,
        nickname: Range[str, 1, 32],
    ) -> None:
        """
        Force a member's nickname.
        """

        key = self.forcenick_key(ctx.guild, member)
        await self.bot.redis.set(key, nickname)

        await member.edit(
            nick=nickname,
            reason=f"{ctx.author} ({ctx.author.id})",
        )
        return await ctx.add_check()

    @nickname_force.command(
        name="cancel",
        aliases=["stop"],
        description="manage nicknames",
        usage="<member>",
        brief="@yurrion",
    )
    @has_permissions(manage_nicknames=True)
    async def nickname_force_cancel(
        self,
        ctx: Context,
        member: Annotated[
            Member,
            TouchableMember,
        ],
    ) -> Optional[Message]:
        """
        Cancel a member's forced nickname.
        """

        key = self.forcenick_key(ctx.guild, member)
        if not await self.bot.redis.delete(key):
            return await ctx.warn(f"{member.mention} doesn't have a forced nickname")

        await member.edit(
            nick=None,
            reason=f"{ctx.author} ({ctx.author.id})",
        )
        return await ctx.add_check()

    @group(
        aliases=[
            "mute",
            "tmo",
            "to",
        ],
        invoke_without_command=True,
    )
    @has_permissions(moderate_members=True)
    async def timeout(
        self,
        ctx: Context,
        member: Annotated[
            Member,
            TouchableMember,
        ],
        duration: timedelta = parameter(
            converter=Duration(
                min=timedelta(seconds=60),
                max=timedelta(days=27),
            ),
            default=timedelta(minutes=5),
        ),
        *,
        reason: str = "No reason provided",
    ) -> Optional[Message]:
        """
        Timeout a member from the server.
        """

        await member.timeout(
            duration,
            reason=f"{ctx.author} / {reason}",
        )
        if ctx.settings.invoke_timeout:
            script = Script(
                ctx.settings.invoke_timeout,
                [
                    ctx.guild,
                    ctx.channel,
                    member,
                    (reason, "reason"),
                    (ctx.author, "moderator"),
                    (format_timespan(duration), "duration"),
                    (format_dt(utcnow() + duration, "R"), "expires"),
                    (str(int((utcnow() + duration).timestamp())), "expires_timestamp"),
                ],
            )
            with suppress(HTTPException):
                return await script.send(ctx)

        return await ctx.add_check()

    @timeout.command(name="list", aliases=["ls"], description="moderate members")
    @has_permissions(moderate_members=True)
    async def timeout_list(self, ctx: Context) -> Message:
        """
        View all timed out members.
        """

        members = list(
            filter(
                lambda member: member.is_timed_out(),
                ctx.guild.members,
            )
        )
        if not members:
            return await ctx.warn("No members are currently timed out")

        paginator = Paginator(
            ctx,
            entries=[
                f"{member.mention} - expires {format_dt(member.timed_out_until or utcnow(), 'R')}"
                for member in sorted(
                    members,
                    key=lambda member: member.timed_out_until or utcnow(),
                )
            ],
            embed=Embed(
                title="Timed Out Members",
            ),
        )
        return await paginator.start()

    @group(
        aliases=[
            "unmute",
            "untmo",
            "unto",
            "utmo",
            "uto",
        ],
        invoke_without_command=True,
    )
    @has_permissions(moderate_members=True)
    async def untimeout(
        self,
        ctx: Context,
        member: Annotated[
            Member,
            TouchableMember,
        ],
        *,
        reason: str = "No reason provided",
    ) -> Optional[Message]:
        """
        Lift a member's timeout.
        """

        if not member.is_timed_out():
            return await ctx.warn("That member isn't timed out")

        await member.timeout(
            None,
            reason=f"{ctx.author} / {reason}",
        )
        if ctx.settings.invoke_untimeout:
            script = Script(
                ctx.settings.invoke_untimeout,
                [
                    ctx.guild,
                    ctx.channel,
                    member,
                    (reason, "reason"),
                    (ctx.author, "moderator"),
                ],
            )
            with suppress(HTTPException):
                return await script.send(ctx)

        return await ctx.add_check()

    @untimeout.command(name="all", description="moderate members")
    @max_concurrency(1, BucketType.guild)
    async def untimeout_all(self, ctx: Context) -> Optional[Message]:
        """
        Lift all timeouts.
        """

        members = list(
            filter(
                lambda member: member.is_timed_out(),
                ctx.guild.members,
            )
        )
        if not members:
            return await ctx.warn("No members are currently timed out")

        async with ctx.typing():
            for member in members:
                with suppress(HTTPException):
                    await member.timeout(
                        None,
                        reason=f"{ctx.author} ({ctx.author.id}) lifted all timeouts",
                    )

        return await ctx.add_check()

    @group(
        aliases=["emote", "e", "jumbo"],
        invoke_without_command=True,
    )
    @has_permissions(manage_emojis=True)
    async def emoji(self, ctx: Context, emoji: PartialEmoji | str) -> Message:
        """
        Various emoji management commands.
        """

        if isinstance(emoji, str):
            url, name = unicode_emoji(emoji)
        else:
            url, name = emoji.url, emoji.name

        response = await self.bot.session.get(url)
        if not response.ok:
            return await ctx.send_help(ctx.command)

        buffer = await response.read()
        _, suffix = url_to_mime(url)

        image, suffix = await enlarge_emoji(buffer, suffix[1:])
        if not image:
            return await ctx.warn("There was an issue downloading that emoji")

        try:
            return await ctx.send(
                file=File(
                    BytesIO(image),
                    filename=f"{name}.{suffix}",
                ),
            )
        except HTTPException:
            return await ctx.warn("The enlarged emoji was too large to send")

    @emoji.group(
        name="add",
        description="manage emojis",
        aliases=[
            "create",
            "upload",
            "steal",
        ],
        invoke_without_command=True,
    )
    @has_permissions(manage_emojis=True)
    async def emoji_add(
        self,
        ctx: Context,
        image: PartialEmoji | PartialAttachment = parameter(
            default=PartialAttachment.fallback,
        ),
        *,
        name: Optional[Range[str, 2, 32]],
    ) -> Optional[Message]:
        """
        Add an emoji to the server.
        """

        if not image.url:
            return await ctx.send_help(ctx.command)

        elif len(ctx.guild.emojis) == ctx.guild.emoji_limit:
            return await ctx.warn("The server is at the **maximum** amount of emojis")

        try:
            await ctx.guild.create_custom_emoji(
                name=name
                or (image.name if isinstance(image, PartialEmoji) else image.filename),
                image=(
                    await image.read()
                    if isinstance(image, PartialEmoji)
                    else image.buffer
                ),
                reason=f"Created by {ctx.author} ({ctx.author.id})",
            )
        except RateLimited as exc:
            retry_after = timedelta(seconds=exc.retry_after)
            return await ctx.warn(
                f"The server is currently ratelimited, try again in **{precisedelta(retry_after)}**"
            )

        except HTTPException as exc:
            return await ctx.warn("Failed to create the emoji", codeblock(exc.text))

        return await ctx.add_check()

    @emoji_add.command(
        name="reactions",
        aliases=[
            "reaction",
            "reacts",
            "react",
        ],
        description="manage emojis",
        usage="[message]",
        brief="1251630921451307129",
    )
    @has_permissions(manage_emojis=True)
    async def emoji_add_reactions(
        self,
        ctx: Context,
        message: Optional[Message],
    ) -> Message:
        """
        Add emojis from the reactions on a message.
        """

        message = message or ctx.replied_message
        if not message:
            async for _message in ctx.channel.history(limit=25, before=ctx.message):
                if _message.reactions:
                    message = _message
                    break

        if not message:
            return await ctx.send_help(ctx.command)

        elif not message.reactions:
            return await ctx.warn("That message doesn't have any reactions")

        added_emojis: List[Emoji] = []
        async with ctx.typing():
            for reaction in message.reactions:
                if not reaction.is_custom_emoji():
                    continue

                emoji = reaction.emoji
                if isinstance(emoji, str):
                    continue

                try:
                    emoji = await ctx.guild.create_custom_emoji(
                        name=emoji.name,
                        image=await emoji.read(),
                        reason=f"Created by {ctx.author} ({ctx.author.id})",
                    )
                except RateLimited as exc:
                    return await ctx.warn(
                        f"Ratelimited after {plural(added_emojis, md='`'):emoji}",
                        f"Please wait **{format_timespan(int(exc.retry_after))}** before trying again",
                        patch=ctx.response,
                    )

                except HTTPException:
                    if (
                        len(ctx.guild.emojis) + len(added_emojis)
                        > ctx.guild.emoji_limit
                    ):
                        return await ctx.warn(
                            "The maximum amount of emojis has been reached",
                            patch=ctx.response,
                        )

                    break

                added_emojis.append(emoji)

        return await ctx.approve(
            f"Added {plural(added_emojis, md='`'):emoji} to the server"
            + (
                f" (`{len(message.reactions) - len(added_emojis)}` failed)"
                if len(added_emojis) < len(message.reactions)
                else ""
            )
        )

    @emoji_add.command(
        name="many",
        aliases=["bulk", "batch"],
        description="manage emojis",
        usage="<emojis...>",
        brief=":emoji_1: :emoji_2: :emoji_3: ...",
    )
    @has_permissions(manage_emojis=True)
    async def emoji_add_many(
        self,
        ctx: Context,
        *emojis: PartialEmoji,
    ) -> Message:
        """
        Add multiple emojis to the server.
        """

        if not emojis:
            return await ctx.send_help(ctx.command)

        elif len(emojis) > 50:
            return await ctx.warn("You can only add up to **50 emojis** at a time")

        elif len(ctx.guild.emojis) + len(emojis) > ctx.guild.emoji_limit:
            return await ctx.warn(
                "The server doesn't have enough space for all the emojis",
            )

        added_emojis: List[Emoji] = []
        async with ctx.typing():
            for emoji in emojis:
                try:
                    emoji = await ctx.guild.create_custom_emoji(
                        name=emoji.name,
                        image=await emoji.read(),
                        reason=f"Created by {ctx.author} ({ctx.author.id})",
                    )
                except RateLimited as exc:
                    return await ctx.warn(
                        f"Ratelimited after {plural(added_emojis, md='`'):emoji}",
                        f"Please wait **{format_timespan(int(exc.retry_after))}** before trying again",
                        patch=ctx.response,
                    )

                except HTTPException:
                    if len(ctx.guild.emojis) + len(emojis) > ctx.guild.emoji_limit:
                        return await ctx.warn(
                            "The maximum amount of emojis has been reached",
                            patch=ctx.response,
                        )

                    break

                added_emojis.append(emoji)

        return await ctx.approve(
            f"Added {plural(added_emojis, md='`'):emoji} to the server"
            + (
                f" (`{len(emojis) - len(added_emojis)}` failed)"
                if len(added_emojis) < len(emojis)
                else ""
            )
        )

    @emoji.command(
        name="rename",
        aliases=["name"],
        description="manage emojis",
        usage="<emoji> <name>",
        brief=":hello_world: hello",
    )
    @has_permissions(manage_emojis=True)
    async def emoji_rename(
        self,
        ctx: Context,
        emoji: Emoji,
        *,
        name: str,
    ) -> Message:
        """
        Rename an existing emoji.
        """

        if emoji.guild_id != ctx.guild.id:
            return await ctx.warn("That emoji is not in this server")

        elif len(name) < 2:
            return await ctx.warn(
                "The emoji name must be at least **2 characters** long"
            )

        name = name[:32].replace(" ", "_")
        await emoji.edit(
            name=name,
            reason=f"Updated by {ctx.author} ({ctx.author.id})",
        )

        return await ctx.approve(f"Renamed the emoji to **{name}**")

    @emoji.command(
        name="delete",
        aliases=["remove", "del"],
        description="manage emojis",
        usage="<emoji>",
        brief=":hello_world:",
    )
    @has_permissions(manage_emojis=True)
    async def emoji_delete(
        self,
        ctx: Context,
        emoji: Emoji,
    ) -> Optional[Message]:
        """
        Delete an existing emoji.
        """

        if emoji.guild_id != ctx.guild.id:
            return await ctx.warn("That emoji is not in this server")

        await emoji.delete(reason=f"Deleted by {ctx.author} ({ctx.author.id})")
        return await ctx.add_check()

    @emoji.group(
        name="archive",
        description="manage emojis",
        aliases=["zip"],
        invoke_without_command=True,
    )
    @has_permissions(manage_emojis=True)
    @cooldown(1, 30, BucketType.guild)
    async def emoji_archive(self, ctx: Context) -> Message:
        """
        Archive all emojis into a zip file.
        """

        if ctx.guild.premium_tier < 2:
            return await ctx.warn(
                "The server must have at least Level 2 to use this command"
            )

        await ctx.neutral("Starting the archival process...")

        async with ctx.typing():
            buffer = BytesIO()
            with ZipFile(buffer, "w") as zip:
                for index, emoji in enumerate(ctx.guild.emojis):
                    name = f"{emoji.name}.{emoji.animated and 'gif' or 'png'}"
                    if name in zip.namelist():
                        name = (
                            f"{emoji.name}_{index}.{emoji.animated and 'gif' or 'png'}"
                        )

                    __buffer = await emoji.read()

                    zip.writestr(name, __buffer)

            buffer.seek(0)

        if ctx.response:
            with suppress(HTTPException):
                await ctx.response.delete()

        return await ctx.reply(
            file=File(
                buffer,
                filename=f"{ctx.guild.name}_emojis.zip",
            ),
        )

    @emoji_archive.command(
        name="restore", aliases=["load"], description="manage emojis"
    )
    @has_permissions(manage_emojis=True)
    @max_concurrency(1, BucketType.guild)
    async def emoji_archive_restore(
        self,
        ctx: Context,
        attachment: PartialAttachment = parameter(
            default=PartialAttachment.fallback,
        ),
    ) -> Message:
        """
        Restore emojis from an archive.
        """

        if not attachment.is_archive():
            return await ctx.warn("The attachment must be a zip archive")

        await ctx.neutral("Starting the restoration process...")

        emojis: List[Emoji] = []
        buffer = BytesIO(attachment.buffer)
        with ZipFile(buffer, "r") as zip:
            if len(zip.namelist()) > (ctx.guild.emoji_limit - len(ctx.guild.emojis)):
                return await ctx.warn(
                    "The server doesn't have enough space for all the emojis in the archive",
                    patch=ctx.response,
                )

            for name in zip.namelist():
                if not name.endswith((".png", ".gif")):
                    continue

                name = name[:-4]
                if get(ctx.guild.emojis, name=name):
                    continue

                try:
                    emoji = await ctx.guild.create_custom_emoji(
                        name=name[:-4],
                        image=zip.read(name),
                        reason=f"Archive loaded by {ctx.author} ({ctx.author.id})",
                    )
                except RateLimited as exc:
                    return await ctx.warn(
                        f"Ratelimited after {plural(emojis, md='`'):emoji}",
                        f"Please wait **{format_timespan(int(exc.retry_after))}** before trying again",
                        patch=ctx.response,
                    )

                except HTTPException:
                    if len(ctx.guild.emojis) == ctx.guild.emoji_limit:
                        return await ctx.warn(
                            "The maximum amount of emojis has been reached",
                            patch=ctx.response,
                        )

                    break

                emojis.append(emoji)

        if ctx.response:
            await quietly_delete(ctx.response)

        return await ctx.approve(
            f"Restored {plural(emojis, md='`'):emoji} from [`{attachment.filename}`]({attachment.url})"
        )

    @group(
        name="set",
        aliases=["edit"],
        invoke_without_command=True,
    )
    @has_permissions(manage_guild=True)
    async def guild_set(self, ctx: Context) -> Message:
        """
        Various server related commands.
        """

        return await ctx.send_help(ctx.command)

    @guild_set.command(
        name="name",
        aliases=["n"],
        description="manage guild",
        usage="<name>",
        brief="zyn",
    )
    @has_permissions(manage_guild=True)
    async def guild_set_name(
        self,
        ctx: Context,
        *,
        name: Range[str, 1, 100],
    ) -> Optional[Message]:
        """
        Change the server's name.
        """

        try:
            await ctx.guild.edit(
                name=name,
                reason=f"{ctx.author} ({ctx.author.id})",
            )
        except HTTPException:
            return await ctx.warn("Failed to change the server's name")

        return await ctx.add_check()

    @guild_set.command(
        name="icon",
        aliases=[
            "pfp",
            "i",
        ],
        description="manage guild",
        usage="<attatchment|url>",
        brief="https://r2.zyn.bot/zyn.png",
    )
    @has_permissions(manage_guild=True)
    async def guild_set_icon(
        self,
        ctx: Context,
        attachment: PartialAttachment = parameter(
            default=PartialAttachment.fallback,
        ),
    ) -> Optional[Message]:
        """
        Change the server's icon.
        """

        if not attachment.is_image():
            return await ctx.warn("The attachment must be an image")

        await ctx.guild.edit(
            icon=attachment.buffer,
            reason=f"{ctx.author} ({ctx.author.id})",
        )
        return await ctx.add_check()

    @guild_set.command(
        name="splash",
        aliases=["background", "bg"],
        description="manage guilds",
        usage="<attatchment|url>",
        brief="https://r2.zyn.bot/zyn.png",
    )
    @has_permissions(manage_guild=True)
    async def guild_set_splash(
        self,
        ctx: Context,
        attachment: PartialAttachment = parameter(
            default=PartialAttachment.fallback,
        ),
    ) -> Optional[Message]:
        """
        Change the server's splash.
        """

        if not attachment.is_image():
            return await ctx.warn("The attachment must be an image")

        await ctx.guild.edit(
            splash=attachment.buffer,
            reason=f"{ctx.author} ({ctx.author.id})",
        )
        return await ctx.add_check()

    @guild_set.command(
        name="banner",
        aliases=["b"],
        description="manage guild",
        usage="<attatchment|url>",
        brief="https://r2.zyn.bot/zyn.png",
    )
    @check(lambda ctx: bool(ctx.guild and ctx.guild.premium_tier >= 2))
    @has_permissions(manage_guild=True)
    async def guild_set_banner(
        self,
        ctx: Context,
        attachment: PartialAttachment = parameter(
            default=PartialAttachment.fallback,
        ),
    ) -> Optional[Message]:
        """
        Change the server's banner.
        """

        if not attachment.is_image():
            return await ctx.warn("The attachment must be an image")

        await ctx.guild.edit(
            banner=attachment.buffer,
            reason=f"{ctx.author} ({ctx.author.id})",
        )
        return await ctx.add_check()

    @guild_set.group(
        name="system",
        aliases=["sys"],
        invoke_without_command=True,
    )
    @has_permissions(manage_guild=True)
    async def guild_set_system(
        self,
        ctx: Context,
        *,
        channel: TextChannel,
    ) -> None:
        """
        Change the server's system channel.
        """

        await ctx.guild.edit(
            system_channel=channel,
            reason=f"{ctx.author} ({ctx.author.id})",
        )
        return await ctx.add_check()

    @guild_set_system.group(
        name="welcome",
        aliases=["welc"],
        description="manage guild",
        invoke_without_command=True,
    )
    @has_permissions(manage_guild=True)
    async def guild_set_system_welcome(self, ctx: Context) -> Message:
        """
        Toggle integrated welcome messages.
        """

        flags = ctx.guild.system_channel_flags
        flags.join_notifications = not flags.join_notifications

        await ctx.guild.edit(
            system_channel_flags=flags,
            reason=f"{ctx.author} ({ctx.author.id})",
        )
        return await ctx.approve(
            f"{'Now' if flags.join_notifications else 'No longer'} sending integrated **welcome messages**"
        )

    @guild_set_system_welcome.command(
        name="sticker", aliases=["stickers", "wave"], description="manage guild"
    )
    @has_permissions(manage_guild=True)
    async def guild_set_system_welcome_sticker(self, ctx: Context) -> Message:
        """
        Toggle replying with a welcome sticker.
        """

        flags = ctx.guild.system_channel_flags
        flags.join_notification_replies = not flags.join_notification_replies

        await ctx.guild.edit(
            system_channel_flags=flags,
            reason=f"{ctx.author} ({ctx.author.id})",
        )
        return await ctx.approve(
            f"{'Now' if flags.join_notification_replies else 'No longer'} adding a **welcome sticker**"
        )

    @guild_set_system.command(
        name="boost", aliases=["boosts"], description="manage guild"
    )
    @has_permissions(manage_guild=True)
    async def guild_set_system_boost(self, ctx: Context) -> Message:
        """
        Toggle integrated boost messages.
        """

        flags = ctx.guild.system_channel_flags
        flags.premium_subscriptions = not flags.premium_subscriptions

        await ctx.guild.edit(
            system_channel_flags=flags,
            reason=f"{ctx.author} ({ctx.author.id})",
        )
        return await ctx.approve(
            f"{'Now' if flags.premium_subscriptions else 'No longer'} sending integrated **boost messages**"
        )

    @guild_set.command(
        name="notifications",
        aliases=["notis", "noti"],
        description="manage guild",
        usage="<all|mentions>",
        brief="all",
    )
    @has_permissions(manage_guild=True)
    async def guild_set_notifications(
        self,
        ctx: Context,
        option: Literal["all", "mentions"],
    ) -> None:
        """
        Change the server's default notification settings.
        """

        await ctx.guild.edit(
            default_notifications=(
                NotificationLevel.all_messages
                if option == "all"
                else NotificationLevel.only_mentions
            ),
            reason=f"{ctx.author} ({ctx.author.id})",
        )
        return await ctx.add_check()

    @command(description="manage channels")
    @has_permissions(manage_channels=True)
    async def nuke(self, ctx: Context) -> Message:
        """
        Clone the current channel.
        This action is irreversable and will delete the channel.
        """

        channel = ctx.channel
        if not isinstance(channel, TextChannel):
            return await ctx.warn("You can only nuke text channels")

        await ctx.prompt(
            "Are you sure you want to **nuke** this channel?",
            "This action is **irreversable** and will delete the channel",
        )

        new_channel = await channel.clone(
            reason=f"Nuked by {ctx.author} ({ctx.author.id})",
        )
        reconfigured = await self.reconfigure_settings(ctx.guild, channel, new_channel)
        await asyncio.gather(
            *[
                new_channel.edit(position=channel.position),
                channel.delete(reason=f"Nuked by {ctx.author} ({ctx.author.id})"),
            ]
        )

        embed = Embed(
            title="Channel Nuked",
            description=f"This channel has been nuked by {ctx.author.mention}",
        )
        if reconfigured:
            embed.add_field(
                name="**Reconfigured Settings**",
                value=">>> " + "\n".join(reconfigured),
            )

        return await new_channel.send(embed=embed)

    @command(
        description="manage messages", usage="[message]", brief="1249032244157481001"
    )
    @has_permissions(manage_messages=True)
    async def pin(
        self,
        ctx: Context,
        message: Optional[Message],
    ) -> Optional[Message]:
        """
        Pin a specific message.
        """

        message = message or ctx.replied_message
        if not message:
            async for message in ctx.channel.history(limit=1, before=ctx.message):
                break

        if not message:
            return await ctx.send_help(ctx.command)

        elif message.guild != ctx.guild:
            return await ctx.warn("The message must be in this server")

        elif message.pinned:
            return await ctx.warn(
                f"That [`message`]({message.jump_url}) is already pinned"
            )

        await message.pin(reason=f"{ctx.author} ({ctx.author.id})")

    @command(
        description="manage messages", usage="[message]", brief="1249032244157481001"
    )
    @has_permissions(manage_messages=True)
    async def unpin(
        self,
        ctx: Context,
        message: Optional[Message],
    ) -> Optional[Message]:
        """
        Unpin a specific message.
        """

        message = message or ctx.replied_message
        if not message:
            return await ctx.send_help(ctx.command)

        elif message.guild != ctx.guild:
            return await ctx.warn("The message must be in this server")

        elif not message.pinned:
            return await ctx.warn(f"That [`message`]({message.jump_url}) is not pinned")

        await message.unpin(reason=f"{ctx.author} ({ctx.author.id})")
        return await ctx.add_check()

    @group(name="channel", invoke_without_command=True)
    async def channel(self, ctx: Context):
        """Manage channels"""
        return await ctx.send_help(ctx.command)

    @channel.command(name="create", brief="chat", description="manage channels")
    @has_permissions(manage_channels=True)
    async def create(self, ctx: Context, name: str) -> Message:
        """Create a new text channel"""
        new_channel = await ctx.guild.create_text_channel(name)
        await ctx.add_check()

    @channel.command(name="delete", brief="chat", description="manage channels")
    @has_permissions(manage_channels=True)
    async def delete(self, ctx: Context, channel: TextChannel) -> Message:
        """Delete a text channel"""
        await channel.delete()
        await ctx.add_check()

    @channel.command(name="rename", brief="chat general", description="manage channels")
    @has_permissions(manage_channels=True)
    async def rename(self, ctx, channel: TextChannel, new_name):
        """Rename a text channel"""
        await channel.edit(name=new_name)
        await ctx.add_check()

    @channel.command(name="private", brief="chat true", description="manage channels")
    @has_permissions(manage_channels=True)
    async def private(self, ctx: Context, channel: TextChannel, state: bool) -> Message:
        """Turn on/off private mode for a channel"""
        overwrite = channel.overwrites_for(ctx.guild.default_role)
        overwrite.read_messages = state
        await channel.set_permissions(ctx.guild.default_role, overwrite=overwrite)
        await ctx.approve(f"Private mode for {channel.mention} set to {state}")

    @channel.command(
        name="attachments", brief="chat true", description="manage channels"
    )
    @has_permissions(manage_channels=True)
    async def attachments(
        self, ctx: Context, channel: TextChannel, state: bool
    ) -> Message:
        """Turn on/off attachment permissions for a channel"""
        overwrite = channel.overwrites_for(ctx.guild.default_role)
        overwrite.attach_files = state
        await channel.set_permissions(ctx.guild.default_role, overwrite=overwrite)
        await ctx.approve(
            f"Attachment permissions for {channel.mention} set to {state}"
        )

    @channel.command(name="permit", description="manage channels", brief="yurrion")
    @has_permissions(manage_channels=True)
    async def permit(
        self, ctx, channel: TextChannel, member: TouchableMember
    ) -> Message:
        """Allow a member to view a channel"""
        overwrite = channel.overwrites_for(member)
        overwrite.read_messages = True
        await channel.set_permissions(member, overwrite=overwrite)
        await ctx.approve(f"Allowed {member.mention} to view {channel.mention}")

    @channel.command(name="revoke", description="manage channels", brief="yurrion")
    @has_permissions(manage_channels=True)
    async def revoke(
        self, ctx, channel: TextChannel, member: TouchableMember
    ) -> Message:
        """Revoke a member's permission to view a channel"""
        overwrite = channel.overwrites_for(member)
        overwrite.read_messages = False
        await channel.set_permissions(member, overwrite=overwrite)
        await ctx.approve(
            f"Revoked {member.mention}'s permission to view {channel.mention}"
        )
