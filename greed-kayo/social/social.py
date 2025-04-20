from typing import List, Optional, cast, Annotated, Literal
from typing_extensions import Self
from contextlib import suppress
from cashews import cache

from asyncpraw import reddit
from asyncprawcore import AsyncPrawcoreException

from discord import (
    Embed,
    Message,
    TextChannel,
    Thread,
    Interaction,
    ButtonStyle,
    HTTPException,
    Color,
)
from discord.ext.commands import (
    Cog,
    group,
    has_permissions,
    parameter,
    FlagConverter,
    flag,
    command,
    CommandError,
)
from discord.utils import format_dt

from main import zyn
from tools.parser import Script
from tools import Button, View
from tools.client import Context
from tools.formatter import plural
from tools.paginator import Paginator
from tools.conversion import PartialAttachment, Status
from tools.conversion.discord import Donator


from .alerts import Alerts
from .feeds import feeds
from .feeds.base import Feed
from .reposters import reposters
from .reposters.base import Reposter

from .models import PinterestLens, Roblox, WeatherLocation, Github
from .models.tiktok.user import User as TikTokUser
from .models.pinterest.user import User as PinterestUser
from .models.twitter.user import User as TwitterUser


from cogs.social.models.pinterest.user import Board as PinterestBoard


class PinterestBoardSelection(View):
    value: Optional[PinterestBoard]
    boards: List[PinterestBoard]

    def __init__(self, ctx: Context, boards: List[PinterestBoard]):
        super().__init__(timeout=60)
        self.ctx = ctx
        self.boards = boards
        self.value = None
        for board in boards:
            self.add_item(
                Button(
                    style=ButtonStyle.secondary,
                    label=board.name,
                    custom_id=board.id,
                )
            )

    async def callback(self, interaction: Interaction, button: Button):
        self.value = [board for board in self.boards if board.id == button.custom_id][0]
        self.stop()


class PinterestFlags(FlagConverter):
    board: Optional[str] = flag(description="The board to stream pins from.")
    embeds: Annotated[bool, Status] = flag(
        aliases=["embed"],
        description="Display an embed for pins.",
        default=True,
    )
    new: Annotated[bool, Status] = flag(
        aliases=["recent"],
        description="Only stream newly saved pins.",
        default=True,
    )


class Subreddit(reddit.Subreddit):
    @classmethod
    @cache(ttl="1h", key="reddit:{argument}")
    async def convert(cls, ctx: Context, argument: str) -> Self:
        async with ctx.typing():
            try:
                subreddit = await ctx.bot.reddit.subreddit(
                    argument.lstrip("r/"), fetch=True
                )
            except AsyncPrawcoreException as exc:
                raise CommandError("No **Subreddit** found with that name") from exc

            return subreddit


class Social(Alerts, Cog):
    reposters: List[Reposter]
    feeds: List[Feed]

    def __init__(self, bot: zyn):
        self.bot = bot
        self.reposters = []
        self.feeds = []

    async def cog_load(self) -> None:
        for reposter in reposters:
            self.reposters.append(reposter(self.bot))

        for feed in feeds:
            self.feeds.append(feed(self.bot))

        return await super().cog_load()

    async def cog_unload(self) -> None:
        for reposter in self.reposters:
            self.bot.remove_listener(reposter.listener, "on_message")

        for feed in self.feeds:
            await feed.stop()

        return await super().cog_unload()

    @group(
        aliases=["event"],
        invoke_without_command=True,
        description="administrator",
    )
    @has_permissions(administrator=True)
    async def reposter(self, ctx: Context) -> Message:
        """
        Configure the bot's automatic reposters.
        """

        return await ctx.send_help(ctx.command)

    @reposter.command(name="prefix", description="administrator")
    @has_permissions(administrator=True)
    async def reposter_prefix(self, ctx: Context) -> Message:
        """
        Toggle the reposter prefix.
        """

        await ctx.settings.update(reposter_prefix=not ctx.settings.reposter_prefix)
        return await ctx.approve(
            f"{'Now' if ctx.settings.reposter_prefix else 'No longer'} using `zyn` as the reposter prefix"
        )

    @reposter.command(name="delete", aliases=["del"], description="administrator")
    @has_permissions(administrator=True)
    async def reposter_delete(self, ctx: Context) -> Message:
        """
        Toggle deleting reposted messages.
        """

        await ctx.settings.update(reposter_delete=not ctx.settings.reposter_delete)
        return await ctx.approve(
            f"Reposted messages will **{'now' if ctx.settings.reposter_delete else 'no longer'}** be deleted"
        )

    @reposter.command(name="embed", aliases=["embeds"], description="administrator")
    @has_permissions(administrator=True)
    async def reposter_embed(self, ctx: Context) -> Message:
        """
        Toggle displaying an embed upon reposting.
        """

        await ctx.settings.update(reposter_embed=not ctx.settings.reposter_embed)
        return await ctx.approve(
            f"Reposted messages will **{'now' if ctx.settings.reposter_embed else 'no longer'}** display an embed"
        )

    @reposter.group(
        name="disable",
        description="administrator",
        invoke_without_command=True,
    )
    @has_permissions(administrator=True)
    async def reposter_disable(
        self,
        ctx: Context,
        channel: Optional[TextChannel],
        *,
        reposter: Reposter,
    ) -> Message:
        """
        Disable a reposter in a specific channel.
        If no channel is provided, the reposter will be disabled globally.
        """

        if channel is None and not ctx.guild.text_channels:
            return await ctx.warn("This server has no text channels")

        channel_ids: List[int] = [
            record["channel_id"]
            for record in await self.bot.db.fetch(
                """
                SELECT channel_id
                FROM reposters.disabled
                WHERE guild_id = $1
                AND reposter = $2
                """,
                ctx.guild.id,
                reposter.name,
            )
        ]
        if channel and channel.id in channel_ids:
            return await ctx.warn(
                f"The **{reposter}** reposter is already disabled in {channel.mention}"
            )

        elif not channel and all(
            channel_id in channel_ids for channel_id in ctx.guild.text_channels
        ):
            return await ctx.warn(
                f"The **{reposter}** reposter is already disabled in all channels"
            )

        await self.bot.db.executemany(
            """
            INSERT INTO reposters.disabled (guild_id, channel_id, reposter)
            VALUES ($1, $2, $3)
            ON CONFLICT (guild_id, channel_id, reposter)
            DO NOTHING
            """,
            [
                (ctx.guild.id, channel.id, reposter.name)
                for channel in (
                    ctx.guild.text_channels if channel is None else [channel]
                )
            ],
        )

        if not channel:
            return await ctx.approve(
                f"Disabled **{reposter}** reposting in {plural(len(ctx.guild.text_channels), md='**'):channel}"
            )

        return await ctx.approve(
            f"Disabled **{reposter}** reposting in {channel.mention}"
        )

    @reposter_disable.command(name="list", aliases=["ls"], description="administrator")
    @has_permissions(administrator=True)
    async def command_disable_list(self, ctx: Context) -> Message:
        """
        View all reposter restrictions.
        """

        reposters = [
            f"**{record['reposter']}** - {', '.join(channel.mention for channel in channels[:2])}"
            + (f" (+{len(channels) - 2})" if len(channels) > 2 else "")
            for record in await self.bot.db.fetch(
                """
                SELECT reposter, ARRAY_AGG(channel_id) AS channel_ids
                FROM reposters.disabled
                WHERE guild_id = $1
                GROUP BY guild_id, reposter
                """,
                ctx.guild.id,
            )
            if (
                channels := [
                    channel
                    for channel_id in record["channel_ids"]
                    if (channel := ctx.guild.get_channel(channel_id))
                ]
            )
        ]
        if not reposters:
            return await ctx.warn("No reposters are disabled for this server")

        paginator = Paginator(
            ctx,
            entries=reposters,
            embed=Embed(
                title="Reposters Disabled",
            ),
        )
        return await paginator.start()

    @reposter.command(name="enable", description="administrator")
    @has_permissions(administrator=True)
    async def reposter_enable(
        self,
        ctx: Context,
        channel: Optional[TextChannel],
        *,
        reposter: Reposter,
    ) -> Message:
        """
        Enable a reposter in a specific channel.

        If no channel is provided, the reposter will be enabled globally.
        """

        channel_ids: List[int] = [
            record["channel_id"]
            for record in await self.bot.db.fetch(
                """
                SELECT channel_id
                FROM reposters.disabled
                WHERE guild_id = $1
                AND reposter = $2
                """,
                ctx.guild.id,
                reposter.name,
            )
        ]
        if channel and channel.id not in channel_ids:
            return await ctx.warn(
                f"The **{reposter}** reposter is already enabled in {channel.mention}"
            )

        elif not channel and not channel_ids:
            return await ctx.warn(
                f"The **{reposter}** reposter is already enabled in all channels"
            )

        await self.bot.db.execute(
            """
            DELETE FROM reposters.disabled
            WHERE guild_id = $1
            AND reposter = $2
            AND channel_id = ANY($3::BIGINT[])
            """,
            ctx.guild.id,
            reposter.name,
            channel_ids if channel is None else [channel.id],
        )

        if not channel:
            return await ctx.approve(
                f"Enabled **{reposter}** reposting in {plural(len(channel_ids), md='**'):channel}"
            )

        return await ctx.approve(
            f"Enabled **{reposter}** reposting in {channel.mention}"
        )

    @group(
        aliases=["tt"],
        invoke_without_command=True,
    )
    async def tiktok(self, ctx: Context, user: TikTokUser) -> Message:
        """
        Look up a user on TikTok.
        You can also stream their new posts.
        """

        embed = Embed(
            url=user.url,
            title=(
                f"{user.full_name} (@{user.username})"
                if user.full_name and user.full_name != user.username
                else f"@{user.username}"
            ),
            description=user.biography,
        )
        embed.set_thumbnail(url=user.avatar_url)

        embed.add_field(
            name="**Likes**",
            value=f"{user.statistics.heart_count:,}",
        )
        embed.add_field(
            name="**Following**",
            value=f"{user.statistics.following_count:,}",
        )
        embed.add_field(
            name="**Followers**",
            value=f"{user.statistics.follower_count:,}",
        )

        return await ctx.send(embed=embed)

    @tiktok.command(
        name="add",
        aliases=["feed"],
        description="manage channels",
        usage="<channel> <user>",
        brief="#tiktok Sanchovies",
    )
    @has_permissions(manage_channels=True)
    async def tiktok_add(
        self,
        ctx: Context,
        channel: TextChannel | Thread,
        user: TikTokUser,
    ) -> Message:
        """
        Add a channel to receive posts from a user.
        """

        if user.is_private:
            return await ctx.warn(
                f"You can't stream posts from [**{user}**]({user.url}) because their account is private"
            )

        if ctx.author.id not in self.bot.owner_ids:
            records = cast(
                int,
                await self.bot.db.fetchval(
                    """
                    SELECT COUNT(*)
                    FROM feeds.tiktok
                    WHERE guild_id = $1
                    AND channel_id = ANY($2::BIGINT[])
                    """,
                    ctx.guild.id,
                    [
                        _channel.id
                        for _channel in ctx.guild.text_channels
                        + list(ctx.guild.threads)
                    ],
                ),
            )
            if records >= 5:
                return await ctx.warn(
                    "You can only receive posts from **5 users** at a time"
                )

        await self.bot.db.execute(
            """
            INSERT INTO feeds.tiktok (
                guild_id,
                channel_id,
                tiktok_id,
                tiktok_name
            )
            VALUES ($1, $2, $3, $4)
            ON CONFLICT (guild_id, tiktok_id)
            DO UPDATE SET channel_id = EXCLUDED.channel_id
            """,
            ctx.guild.id,
            channel.id,
            user.id,
            user.username,
        )
        return await ctx.approve(
            f"Now streaming new posts from [**{user}**]({user.url}) to {channel.mention}"
        )

    @tiktok.command(
        name="remove",
        aliases=["delete", "del", "rm"],
        description="manage channel",
        usage="<channel> <user>",
        brief="#tiktok Sanchovies",
    )
    @has_permissions(manage_channels=True)
    async def tiktok_remove(
        self,
        ctx: Context,
        channel: Optional[TextChannel | Thread],
        user: TikTokUser,
    ) -> Message:
        """
        Remove a channel from receiving posts from a user.
        """

        result = await self.bot.db.execute(
            """
            DELETE FROM feeds.tiktok
            WHERE guild_id = $1
            AND tiktok_id = $2
            """,
            ctx.guild.id,
            user.id,
        )
        if result == "DELETE 0":
            return await ctx.warn(
                f"Posts from [**{user}**]({user.url}) are not being streamed"
            )

        return await ctx.approve(
            f"No longer streaming posts from [**{user}**]({user.url})"
        )

    @tiktok.group(
        name="message",
        aliases=["msg"],
        description="manage channles",
        invoke_without_command=True,
    )
    @has_permissions(manage_channels=True)
    async def tiktok_message(
        self,
        ctx: Context,
        channel: Optional[TextChannel | Thread],
        user: Optional[TikTokUser],
        *,
        script: Script,
    ) -> Message:
        """
        Set a message to be sent when a post is received.
        """

        if not user:
            await ctx.prompt(
                "You didn't specify a valid **TikTok username**",
                "Are you sure you want to set the message for **all** feeds?",
            )

            result = await self.bot.db.execute(
                """
                UPDATE feeds.tiktok
                SET template = $2
                WHERE guild_id = $1
                """,
                ctx.guild.id,
                script.template,
            )
            if result == "UPDATE 0":
                return await ctx.warn("No **TikTok feeds** were modified")

            return await ctx.approve(
                "Updated the post message for all **TikTok feeds**"
            )

        result = await self.bot.db.execute(
            """
            UPDATE feeds.tiktok
            SET template = $3
            WHERE guild_id = $1
            AND tiktok_id = $2
            """,
            ctx.guild.id,
            user.id,
            script.template,
        )
        if result == "UPDATE 0":
            return await ctx.warn(
                f"Posts from [**{user}**]({user.url}) are not being streamed"
            )

        return await ctx.approve(
            f"Updated the post message for [**{user}**]({user.url})"
        )

    @tiktok_message.command(
        name="remove",
        aliases=["delete", "del", "rm"],
        description="manage channel",
        usage="<channel> <user>",
    )
    @has_permissions(manage_channels=True)
    async def tiktok_message_remove(
        self,
        ctx: Context,
        channel: Optional[TextChannel | Thread],
        user: Optional[TikTokUser],
    ) -> Message:
        """
        Remove the message sent when a post is received.
        """

        if not user:
            await ctx.prompt(
                "You didn't specify a valid **TikTok username**",
                "Are you sure you want to remove the message for **all** feeds?",
            )

            result = await self.bot.db.execute(
                """
                UPDATE feeds.tiktok
                SET template = NULL
                WHERE guild_id = $1
                """,
                ctx.guild.id,
            )
            if result == "UPDATE 0":
                return await ctx.warn("No **TikTok feeds** were modified")

            return await ctx.approve("Reset the post message for all **TikTok feeds**")

        result = await self.bot.db.execute(
            """
            UPDATE feeds.tiktok
            SET template = NULL
            WHERE guild_id = $1
            AND tiktok_id = $2
            """,
            ctx.guild.id,
            user.id,
        )
        if result == "UPDATE 0":
            return await ctx.warn(
                f"Posts from [**{user}**]({user.url}) are not being streamed"
            )

        return await ctx.approve(f"Reset the post message for [**{user}**]({user.url})")

    @tiktok.command(
        name="clear",
        aliases=["clean", "reset"],
        description="manage channel",
    )
    @has_permissions(manage_channels=True)
    async def tiktok_clear(self, ctx: Context) -> Message:
        """
        Remove all TikTok feeds.
        """

        await ctx.prompt(
            "Are you sure you want to remove all **TikTok feeds**?",
        )

        result = await self.bot.db.execute(
            """
            DELETE FROM feeds.tiktok
            WHERE guild_id = $1
            """,
            ctx.guild.id,
        )
        if result == "DELETE 0":
            return await ctx.warn("No **TikTok feeds** exist for this server")

        return await ctx.approve(
            f"Successfully  removed {plural(result, md='`'):TikTok feed}"
        )

    @tiktok.command(name="list", aliases=["ls"], description="manage guild")
    @has_permissions(manage_guild=True)
    async def tiktok_list(self, ctx: Context) -> Message:
        """
        View all TikTok feeds.
        """

        channels = [
            f"{channel.mention} - [**@{record['tiktok_name']}**](https://tiktok.com/@{record['tiktok_name']})"
            for record in await self.bot.db.fetch(
                """
                SELECT channel_id, tiktok_name
                FROM feeds.tiktok
                WHERE guild_id = $1
                """,
                ctx.guild.id,
            )
            if (channel := ctx.guild.get_channel_or_thread(record["channel_id"]))
        ]
        if not channels:
            return await ctx.warn("No **TikTok feeds** exist for this server")

        paginator = Paginator(
            ctx,
            entries=channels,
            embed=Embed(title="TikTok Feeds"),
        )
        return await paginator.start()

    @group(
        aliases=["pint", "autopfp"],
        invoke_without_command=True,
    )
    async def pinterest(
        self,
        ctx: Context,
        user: PinterestUser,
    ) -> Message:
        """
        Look up a user on Pinterest.
        You can also stream saved pins from a user.
        """

        embed = Embed(
            url=user.url,
            title=(
                f"{user.full_name} (@{user.username})"
                if user.full_name and user.full_name != user.username
                else f"@{user.username}"
            )
            + (" 🔒" if user.is_private_profile else ""),
            description=user.about or user.website_url,
        )
        embed.set_thumbnail(url=user.avatar_url)

        embed.add_field(
            name="**Pins**",
            value=f"{user.pin_count:,}",
        )
        embed.add_field(
            name="**Following**",
            value=f"{user.following_count:,}",
        )
        embed.add_field(
            name="**Followers**",
            value=f"{user.follower_count:,}",
        )

        return await ctx.send(embed=embed)

    @pinterest.command(
        name="lens",
        aliases=["visual", "search"],
        usage="<attachment|url>",
        brief="https://assest.zyn.bot/zyn.png",
    )
    async def pinterest_lens(
        self,
        ctx: Context,
        attachment: PartialAttachment = parameter(
            default=PartialAttachment.fallback,
        ),
    ) -> Message:
        """
        Search an image using Pinterest Visual Search.
        """

        if not attachment.is_image():
            return await ctx.warn("The attachment must be an image")

        async with ctx.typing():
            posts = await PinterestLens.from_image(
                self.bot.session,
                attachment.buffer,
            )
            if not posts:
                return await ctx.warn(
                    f"No results were found for [`{attachment.filename}`]({attachment.url})"
                )

        paginator = Paginator(
            ctx,
            entries=[
                Embed(
                    url=post.url,
                    title=f"Pinterest Visual Search ({plural(post.repin_count):repin})",
                    description=post.description,
                ).set_image(
                    url=post.image_url,
                )
                for post in posts
            ],
        )
        return await paginator.start()

    @pinterest.command(
        name="add",
        aliases=["feed"],
        description="manage channels",
        usage="<channel> <user> [flags]",
        brief="#pinterest Pfps",
    )
    @has_permissions(manage_channels=True)
    async def pinterest_add(
        self,
        ctx: Context,
        channel: TextChannel | Thread,
        user: PinterestUser,
        *,
        flags: PinterestFlags,
    ) -> Message:
        """
        Add a channel to receive saved pins from a user.
        """

        if user.username == "teenagemaniac" and ctx.author.id not in self.bot.owner_ids:
            return await ctx.reply("no")

        elif user.is_private_profile:
            return await ctx.warn(
                f"You can't stream posts from [**{user}**]({user.url}) because their account is private"
            )

        elif not user.pin_count:
            return await ctx.warn(f"User [**{user}**]({user.url}) has no saved pins")

        if ctx.author.id not in self.bot.owner_ids:
            data = cast(
                int,
                await self.bot.db.fetchval(
                    """
                    SELECT COUNT(*)
                    FROM feeds.pinterest
                    WHERE guild_id = $1
                    AND channel_id = $2
                    """,
                    ctx.guild.id,
                    channel.id,
                ),
            )
            if data >= 3:
                return await ctx.warn(
                    "You can only receive saved pins from **3 users** per channel"
                )

            data = cast(
                int,
                await self.bot.db.fetchval(
                    """
                    SELECT COUNT(*)
                    FROM feeds.pinterest
                    WHERE guild_id = $1
                    AND channel_id = ANY($2::BIGINT[])
                    """,
                    ctx.guild.id,
                    [
                        _channel.id
                        for _channel in ctx.guild.text_channels
                        + list(ctx.guild.threads)
                    ],
                ),
            )
            if data >= 8:
                return await ctx.warn(
                    "You can only receive saved pins from **8 users** per server"
                )

        board: Optional[PinterestBoard] = None
        if flags.board:
            boards = await user.boards(self.bot.session)
            if not boards:
                return await ctx.warn(
                    f"User [**{user}**]({user.url}) doesn't have any public boards"
                )

            elif flags.board.lower() not in [board.name.lower() for board in boards]:
                view = PinterestBoardSelection(ctx, boards)
                message = await ctx.neutral(
                    "The specified board wasn't found",
                    f"Select which board from [**{user}**]({user.url}) to stream",
                    view=view,
                )

                await view.wait()
                with suppress(HTTPException):
                    await message.delete()

                if not isinstance(view.value, PinterestBoard):
                    return message

                board = view.value

            else:
                board = [
                    board
                    for board in boards
                    if flags.board.lower() in board.name.lower()
                ][0]

        await self.bot.db.execute(
            """
            INSERT INTO feeds.pinterest (
                guild_id,
                channel_id,
                pinterest_id,
                pinterest_name,
                board,
                board_id,
                embeds,
                only_new
            )
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
            ON CONFLICT (guild_id, pinterest_id)
            DO UPDATE SET
                channel_id = EXCLUDED.channel_id,
                board = EXCLUDED.board,
                board_id = EXCLUDED.board_id,
                embeds = EXCLUDED.embeds,
                only_new = EXCLUDED.only_new
            """,
            ctx.guild.id,
            channel.id,
            user.id,
            user.username,
            board.name if board else None,
            board.id if board else None,
            flags.embeds,
            flags.new,
        )
        return await ctx.approve(
            f"Now streaming **{'newly' if flags.new else 'old'} saved pins** from [**{user}**]({user.url}){f' (`{board.name}`)' if board else ''} to {channel.mention} {'with an embed' if flags.embeds else 'in batches of `3`'}",
        )

    @pinterest.command(
        name="remove",
        aliases=["delete", "del", "rm"],
        description="manage channels",
        usage="<channel> <user>",
        brief="#pinterest Pfps",
    )
    @has_permissions(manage_channels=True)
    async def pinterest_remove(
        self,
        ctx: Context,
        channel: Optional[TextChannel | Thread],
        user: PinterestUser,
    ) -> Message:
        """
        Remove a channel from receiving saved pins from a user.
        """

        result = await self.bot.db.execute(
            """
            DELETE FROM feeds.pinterest
            WHERE guild_id = $1
            AND pinterest_id = $2
            """,
            ctx.guild.id,
            user.id,
        )
        if result == "DELETE 0":
            return await ctx.warn(
                f"Saved pins from [**{user}**]({user.url}) are not being streamed"
            )

        return await ctx.approve(
            f"No longer streaming saved pins from [**{user}**]({user.url})"
        )

    @pinterest.command(
        name="embeds",
        description="manage channels",
        usage="<channel> <user>",
        brief="#pinterest Pfps",
    )
    @has_permissions(manage_channels=True)
    async def pinterest_embeds(
        self,
        ctx: Context,
        channel: Optional[TextChannel | Thread],
        user: PinterestUser,
    ) -> Message:
        """
        Enable or disable embeds when a pin is received.
        """

        status = cast(
            Optional[bool],
            await self.bot.db.fetchval(
                """
                UPDATE feeds.pinterest
                SET embeds = NOT embeds
                WHERE guild_id = $1
                AND pinterest_id = $2
                RETURNING embeds
                """,
                ctx.guild.id,
                user.id,
            ),
        )
        if status is None:
            return await ctx.warn(
                f"Saved pins from [**{user}**]({user.url}) are not being streamed"
            )

        return await ctx.approve(
            f"{'Now' if status else 'No longer'} displaying **embeds** for [**{user}**]({user.url})"
        )

    @pinterest.command(
        name="clear",
        aliases=["clean", "reset"],
        description="manage channels",
    )
    @has_permissions(manage_channels=True)
    async def pinterest_clear(self, ctx: Context) -> Message:
        """
        Remove all Pinterest feeds.
        """

        await ctx.prompt(
            "Are you sure you want to remove all **Pinterest feeds**?",
        )

        result = await self.bot.db.execute(
            """
            DELETE FROM feeds.pinterest
            WHERE guild_id = $1
            """,
            ctx.guild.id,
        )
        if result == "DELETE 0":
            return await ctx.warn("No **Pinterest feeds** exist for this server")

        return await ctx.approve(
            f"Successfully  removed {plural(result, md='`'):Pinterest feed}"
        )

    @pinterest.command(
        name="list",
        aliases=["ls"],
        description="manage guild",
    )
    @has_permissions(manage_guild=True)
    async def pinterest_list(self, ctx: Context) -> Message:
        """
        View all Pinterest feeds.
        """

        channels = [
            f"{channel.mention} - [**@{record['pinterest_name']}**](https://pinterest.com/{record['pinterest_name']}) (`{record['board'] or 'all'}`)"
            for record in await self.bot.db.fetch(
                """
                SELECT channel_id, pinterest_name, board
                FROM feeds.pinterest
                WHERE guild_id = $1
                """,
                ctx.guild.id,
            )
            if (channel := ctx.guild.get_channel_or_thread(record["channel_id"]))
        ]
        if not channels:
            return await ctx.warn("No **Pinterest feeds** exist for this server")

        paginator = Paginator(
            ctx,
            entries=channels,
            embed=Embed(title="Pinterest Feeds"),
        )
        return await paginator.start()

    @command(aliases=["rbx"])
    async def roblox(
        self,
        ctx: Context,
        user: Roblox,
    ) -> Message:
        """
        Look up a user on Roblox.
        """

        embed = Embed(
            url=user.url,
            title=(
                f"{user.display_name} (@{user.name})"
                if user.display_name and user.display_name != user.name
                else f"@{user.name}"
            )
            + (" [BANNED]" if user.is_banned else ""),
            description=f"{format_dt(user.created_at)} ({format_dt(user.created_at, 'R')})\n{user.description}",
        )
        embed.set_thumbnail(url=await user.avatar_url())

        embed.add_field(
            name="**Followers**",
            value=f"{await user.follower_count():,}",
        )
        embed.add_field(
            name="**Following**",
            value=f"{await user.following_count():,}",
        )
        embed.add_field(
            name="**Friends**",
            value=f"{await user.friend_count():,}",
        )

        if presence := await user.presence():
            embed.add_field(
                name=f"**Presence ({presence.status.title()})**",
                value=(
                    (
                        f"> **Location:** {presence.location}"
                        if presence.location
                        else ""
                    )
                    + (
                        f"\n> **Last Online:** {format_dt(presence.last_online, 'R')}"
                        if presence.last_online
                        else ""
                    )
                ),
                inline=False,
            )

        if badges := await user.badges():
            embed.add_field(
                name=f"**Badges ({len(badges)})**",
                value=", ".join(
                    f"[`{badge.name}`]({badge.url})" for badge in badges[:5]
                ),
                inline=False,
            )

        if names := await user.names():
            embed.add_field(
                name="**Name History**",
                value=", ".join((f"`{name}`" for name in names[:17])),
                inline=False,
            )

        return await ctx.send(embed=embed)

    @group(
        aliases=["tw", "x"],
        invoke_without_command=True,
    )
    async def twitter(
        self,
        ctx: Context,
        user: TwitterUser,
    ) -> Message:
        """
        Look up a user on Twitter.
        You can also stream their new tweets.
        """

        embed = Embed(
            url=user.url,
            title=(
                f"{user.name} (@{user.screen_name})"
                if user.name and user.name != user.screen_name
                else f"@{user.screen_name}"
            ),
            description=user.description,
        )
        embed.set_thumbnail(url=user.avatar_url)

        embed.add_field(
            name="**Tweets**",
            value=f"{user.statuses_count:,}",
        )
        embed.add_field(
            name="**Following**",
            value=f"{user.friends_count:,}",
        )
        embed.add_field(
            name="**Followers**",
            value=f"{user.followers_count:,}",
        )

        return await ctx.send(embed=embed)

    @twitter.command(
        name="add",
        aliases=["feed"],
        description="manage channels",
        usage="<channel> <user>",
        brief="#twitter Sanchovies",
    )
    @has_permissions(manage_channels=True)
    @Donator()
    async def twitter_add(
        self,
        ctx: Context,
        channel: TextChannel | Thread,
        user: TwitterUser,
    ) -> Message:
        """
        Add a channel to receive tweets from a user.
        """

        if ctx.author.id not in self.bot.owner_ids:
            records = cast(
                int,
                await self.bot.db.fetchval(
                    """
                    SELECT COUNT(*)
                    FROM feeds.twitter
                    WHERE guild_id = $1
                    AND channel_id = ANY($2::BIGINT[])
                    """,
                    ctx.guild.id,
                    [
                        _channel.id
                        for _channel in ctx.guild.text_channels
                        + list(ctx.guild.threads)
                    ],
                ),
            )
            if records >= 5:
                return await ctx.warn(
                    "You can only receive tweets from **5 users** at a time"
                )

        await self.bot.db.execute(
            """
            INSERT INTO feeds.twitter (
                guild_id,
                channel_id,
                twitter_id,
                twitter_name
            )
            VALUES ($1, $2, $3, $4)
            ON CONFLICT (guild_id, twitter_id)
            DO UPDATE SET channel_id = EXCLUDED.channel_id
            """,
            ctx.guild.id,
            channel.id,
            user.id,
            user.screen_name,
        )
        return await ctx.approve(
            f"Now streaming new tweets from [**{user}**]({user.url}) to {channel.mention}"
        )

    @twitter.command(
        name="remove",
        aliases=["delete", "del", "rm"],
        description="manage channels",
        usage="<channel> <user>",
        brief="#twitter Sanchovies",
    )
    @has_permissions(manage_channels=True)
    async def twitter_remove(
        self,
        ctx: Context,
        channel: Optional[TextChannel | Thread],
        user: TwitterUser,
    ) -> Message:
        """
        Remove a channel from receiving tweets from a user.
        """

        result = await self.bot.db.execute(
            """
            DELETE FROM feeds.twitter
            WHERE guild_id = $1
            AND twitter_id = $2
            """,
            ctx.guild.id,
            user.id,
        )
        if result == "DELETE 0":
            return await ctx.warn(
                f"Tweets from [**{user}**]({user.url}) are not being streamed"
            )

        return await ctx.approve(
            f"No longer streaming tweets from [**{user}**]({user.url})"
        )

    @twitter.command(
        name="color",
        aliases=["colour"],
        description="manage channels",
        usage="<channel> <color> <user>",
        brief="#twitter #FFFFFF Sanchovies",
    )
    @has_permissions(manage_channels=True)
    async def twitter_color(
        self,
        ctx: Context,
        channel: Optional[TextChannel | Thread],
        color: Literal["random"] | Color,
        user: Optional[TwitterUser],
    ) -> Message:
        """
        Set a custom color for tweet embeds.
        """

        if not user:
            await ctx.prompt(
                "You didn't specify a valid **Twitter username**",
                "Are you sure you want to set the color for **ALL** feeds?",
            )

            result = await self.bot.db.execute(
                """
                UPDATE feeds.twitter
                SET color = $2
                WHERE guild_id = $1
                """,
                ctx.guild.id,
                str(color.value) if isinstance(color, Color) else "random",
            )
            if result == "UPDATE 0":
                return await ctx.warn("No **Twitter feeds** were modified")

            return await ctx.approve(
                f"Now using {f'`{color}`' if isinstance(color, Color) else '**random colors**'} for new tweets",
                color=color if isinstance(color, Color) else None,
            )

        result = await self.bot.db.execute(
            """
            UPDATE feeds.twitter
            SET color = $3
            WHERE guild_id = $1
            AND twitter_id = $2
            """,
            ctx.guild.id,
            user.id,
            str(color.value) if isinstance(color, Color) else "random",
        )
        if result == "UPDATE 0":
            return await ctx.warn(
                f"Tweets from [**{user}**]({user.url}) are not being streamed"
            )

        return await ctx.approve(
            f"Now using {f'`{color}`' if isinstance(color, Color) else '**random colors**'} for new tweets from [**{user}**]({user.url})",
            color=color if isinstance(color, Color) else None,
        )

    @twitter.group(
        name="message",
        aliases=["msg"],
        description="manage channels",
        invoke_without_command=True,
    )
    @has_permissions(manage_channels=True)
    async def twitter_message(
        self,
        ctx: Context,
        channel: Optional[TextChannel | Thread],
        user: Optional[TwitterUser],
        *,
        script: Script,
    ) -> Message:
        """
        Set a message to be sent when a tweet is received.
        """

        if not user:
            await ctx.prompt(
                "You didn't specify a valid **Twitter username**",
                "Are you sure you want to set the message for **ALL** feeds?",
            )

            result = await self.bot.db.execute(
                """
                UPDATE feeds.twitter
                SET template = $2
                WHERE guild_id = $1
                """,
                ctx.guild.id,
                script.template,
            )
            if result == "UPDATE 0":
                return await ctx.warn("No **Twitter feeds** were modified")

            return await ctx.approve(
                "Updated the tweet message for all **Twitter feeds**"
            )

        result = await self.bot.db.execute(
            """
            UPDATE feeds.twitter
            SET template = $3
            WHERE guild_id = $1
            AND twitter_id = $2
            """,
            ctx.guild.id,
            user.id,
            script.template,
        )
        if result == "UPDATE 0":
            return await ctx.warn(
                f"Tweets from [**{user}**]({user.url}) are not being streamed"
            )

        return await ctx.approve(
            f"Updated the tweet message for [**{user}**]({user.url})"
        )

    @twitter_message.command(
        name="remove",
        aliases=["delete", "del", "rm"],
        description="manage channels",
        usage="<channel> <user>",
        brief="#twitter Sanchovies",
    )
    @has_permissions(manage_channels=True)
    async def twitter_message_remove(
        self,
        ctx: Context,
        channel: Optional[TextChannel | Thread],
        user: Optional[TwitterUser],
    ) -> Message:
        """
        Remove the message sent when a tweet is received.

        This does not apply to the tweet's embed.
        """

        if not user:
            await ctx.prompt(
                "You didn't specify a valid **Twitter username**",
                "Are you sure you want to remove the message for **ALL** feeds?",
            )

            result = await self.bot.db.execute(
                """
                UPDATE feeds.twitter
                SET template = NULL
                WHERE guild_id = $1
                """,
                ctx.guild.id,
            )
            if result == "UPDATE 0":
                return await ctx.warn("No **Twitter feeds** were modified")

            return await ctx.approve(
                "Reset the tweet message for all **Twitter feeds**"
            )

        result = await self.bot.db.execute(
            """
            UPDATE feeds.twitter
            SET template = NULL
            WHERE guild_id = $1
            AND twitter_id = $2
            """,
            ctx.guild.id,
            user.id,
        )
        if result == "UPDATE 0":
            return await ctx.warn(
                f"Tweets from [**{user}**]({user.url}) are not being streamed"
            )

        return await ctx.approve(
            f"Reset the tweet message for [**{user}**]({user.url})"
        )

    @twitter.command(
        name="clear",
        aliases=["clean", "reset"],
        description="manage channels",
    )
    @has_permissions(manage_channels=True)
    async def twitter_clear(self, ctx: Context) -> Message:
        """
        Remove all Twitter feeds.
        """

        await ctx.prompt(
            "Are you sure you want to remove all **Twitter feeds**?",
        )

        result = await self.bot.db.execute(
            """
            DELETE FROM feeds.twitter
            WHERE guild_id = $1
            """,
            ctx.guild.id,
        )
        if result == "DELETE 0":
            return await ctx.warn("No **Twitter feeds** exist for this server")

        return await ctx.approve(
            f"Successfully  removed {plural(result, md='`'):Twitter feed}"
        )

    @twitter.command(
        name="list",
        aliases=["ls"],
        description="manage guild",
    )
    @has_permissions(manage_guild=True)
    async def twitter_list(self, ctx: Context) -> Message:
        """
        View all Twitter feeds.
        """

        channels = [
            f"{channel.mention} - [**@{record['twitter_name']}**](https://twitter.com/{record['twitter_name']})"
            for record in await self.bot.db.fetch(
                """
                SELECT channel_id, twitter_name
                FROM feeds.twitter
                WHERE guild_id = $1
                """,
                ctx.guild.id,
            )
            if (channel := ctx.guild.get_channel_or_thread(record["channel_id"]))
        ]
        if not channels:
            return await ctx.warn("No **Twitter feeds** exist for this server")

        paginator = Paginator(
            ctx,
            entries=channels,
            embed=Embed(title="Twitter Feeds"),
        )
        return await paginator.start()

    @group(
        aliases=["subreddit"],
        invoke_without_command=True,
    )
    async def reddit(self, ctx: Context, *, subreddit: Subreddit) -> Message:
        """
        Look up a Subreddit.
        You can also stream new submissions.
        """

        embed = Embed(
            url=f"https://reddit.com{subreddit.url}",
            title=subreddit.title or subreddit.display_name,
        )
        embed.set_thumbnail(url=subreddit.community_icon)

        embed.add_field(
            name="**Subscribers**",
            value=f"{subreddit.subscribers:,}",
        )
        embed.add_field(
            name="**Active Users**",
            value=f"{subreddit.accounts_active:,}",
        )
        embed.set_image(url=subreddit.banner_background_image)

        return await ctx.send(embed=embed)

    @reddit.command(
        name="add",
        aliases=["feed"],
        description="manage channels",
        usage="<channel> <subreddit>",
        brief="#pets cats",
    )
    @has_permissions(manage_channels=True)
    async def reddit_add(
        self,
        ctx: Context,
        channel: TextChannel | Thread,
        subreddit: Subreddit,
    ) -> Message:
        """
        Add a channel to receive submissions from a Subreddit.
        """

        if ctx.author.id not in self.bot.owner_ids:
            records = cast(
                int,
                await self.bot.db.fetchval(
                    """
                    SELECT COUNT(*)
                    FROM feeds.reddit
                    WHERE guild_id = $1
                    AND channel_id = ANY($2::BIGINT[])
                    """,
                    ctx.guild.id,
                    [
                        _channel.id
                        for _channel in ctx.guild.text_channels
                        + list(ctx.guild.threads)
                    ],
                ),
            )
            if records >= 15:
                return await ctx.warn(
                    "You can only receive posts from **15 subreddits** at a time"
                )

        await self.bot.db.execute(
            """
            INSERT INTO feeds.reddit (
                guild_id,
                channel_id,
                subreddit_name
            )
            VALUES ($1, $2, $3)
            ON CONFLICT (guild_id, subreddit_name)
            DO UPDATE SET channel_id = EXCLUDED.channel_id
            """,
            ctx.guild.id,
            channel.id,
            subreddit.display_name,
        )
        return await ctx.approve(
            f"Now streaming new submissions from [**{subreddit.display_name_prefixed}**](https://reddit.com{subreddit.url}) to {channel.mention}"
        )

    @reddit.command(
        name="remove",
        aliases=["delete", "del", "rm"],
        description="manage channels",
        usage="<channel> <subreddit>",
        brief="#pets cats",
    )
    @has_permissions(manage_channels=True)
    async def reddit_remove(
        self,
        ctx: Context,
        channel: Optional[TextChannel | Thread],
        subreddit: Subreddit,
    ) -> Message:
        """
        Remove a channel from receiving submissions from a Subreddit.
        """

        result = await self.bot.db.execute(
            """
            DELETE FROM feeds.reddit
            WHERE guild_id = $1
            AND subreddit_name = $2
            """,
            ctx.guild.id,
            subreddit.display_name,
        )
        if result == "DELETE 0":
            return await ctx.warn(
                f"Submissions from [**{subreddit.display_name_prefixed}**](https://reddit.com{subreddit.url}) are not being streamed"
            )

        return await ctx.approve(
            f"No longer streaming submissions from [**{subreddit.display_name_prefixed}**](https://reddit.com{subreddit.url})"
        )

    @reddit.command(
        name="clear",
        aliases=["clean", "reset"],
        description="manage channels",
    )
    @has_permissions(manage_channels=True)
    async def reddit_clear(self, ctx: Context) -> Message:
        """
        Remove all Subreddit feeds.
        """

        await ctx.prompt(
            "Are you sure you want to remove all **Subreddit feeds**?",
        )

        result = await self.bot.db.execute(
            """
            DELETE FROM feeds.reddit
            WHERE guild_id = $1
            """,
            ctx.guild.id,
        )
        if result == "DELETE 0":
            return await ctx.warn("No **Subreddit feeds** exist for this server")

        return await ctx.approve(
            f"Successfully  removed {plural(result, md='`'):Subreddit feed}"
        )

    @reddit.command(
        name="list",
        aliases=["ls"],
        description="manage channels",
    )
    @has_permissions(manage_guild=True)
    async def reddit_list(self, ctx: Context) -> Message:
        """
        View all Subreddit feeds.
        """

        channels = [
            f"{channel.mention} - [**r/{record['subreddit_name']}**](https://reddit.com/r/{record['subreddit_name']})"
            for record in await self.bot.db.fetch(
                """
                SELECT channel_id, subreddit_name
                FROM feeds.reddit
                WHERE guild_id = $1
                """,
                ctx.guild.id,
            )
            if (channel := ctx.guild.get_channel_or_thread(record["channel_id"]))
        ]
        if not channels:
            return await ctx.warn("No **Subreddit feeds** exist for this server")

        paginator = Paginator(
            ctx,
            entries=channels,
            embed=Embed(title="Subreddit Feeds"),
        )
        return await paginator.start()

    @command(name="weather", usage="<place>", brief="atlanta")
    async def weather(self, ctx: Context, *, weather: WeatherLocation):
        """view the weather at a location"""

        embed = Embed(
            title=f"{weather.condition} in {weather.place}", timestamp=weather.time
        )
        embed.set_author(name=ctx.author.display_name, icon_url=ctx.author.avatar.url)
        embed.set_thumbnail(url=weather.condition_image)
        embed.add_field(
            name="Temperature",
            value=f"{weather.temp_c} °C / {weather.temp_f} °F",
            inline=False,
        )
        embed.add_field(name="Humidity", value=f"{weather.humidity}%", inline=False)
        embed.add_field(
            name="Wind",
            value=f"{weather.wind_mph} mph / {weather.wind_kph} kph",
            inline=False,
        )

        await ctx.send(embed=embed)

    @command(name="github", usage="<username>", brief="nyrrion")
    async def github(self, ctx: Context, username: str) -> Message:
        """Get a Github profile"""
        try:
            profile = await Github.scrape(self, username)

            embed = Embed(
                title=profile.username,
            )
            embed.add_field(name="Name", value=profile.name, inline=False)
            embed.add_field(name="Bio", value=profile.bio, inline=False)
            embed.add_field(
                name="Repositories", value=profile.repositories, inline=True
            )
            embed.add_field(
                name="Contributions", value=profile.contributions, inline=True
            )
            await ctx.send(embed=embed)
        except Exception as e:
            await ctx.warn(f" Github profile `{username}` is not found.")
