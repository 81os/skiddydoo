import asyncio
from datetime import datetime, timedelta
from logging import getLogger
from typing import List, Literal, Optional, Union

from asyncpg import UniqueViolationError
from discord import (
    AllowedMentions,
    Colour,
    Embed,
    HTTPException,
    Message,
    TextChannel,
    Thread,
)
from discord.ext.commands import Cog, CommandError, group, has_permissions
from discord.ext.tasks import loop
from discord.utils import format_dt, sleep_until, utcnow
from humanize import naturaldelta
from pydantic import BaseModel, Field
from yarl import URL

import config

from tools import CompositeMetaClass, MixinMeta, quietly_delete
from tools.client import Context
from tools.formatter import plural
from tools.paginator import Paginator

log = getLogger("zyn/epic")


class CosmeticImages(BaseModel):
    icon: Optional[str]
    gallery: Optional[str]
    featured: Optional[str]
    resize_available: Optional[bool] = Field(False, alias="resizeAvailable")


class CosmeticHistory(BaseModel):
    occurrences: int
    first_seen: datetime = Field(alias="firstSeen")
    last_seen: datetime = Field(alias="lastSeen")
    dates: List[datetime]


class Cosmetic(BaseModel):
    id: str
    type: str
    name: str
    price: str
    price_icon: Union[Literal[False], str] = Field(alias="priceIcon")
    rarity: str
    description: str
    images: CosmeticImages
    history: Union[Literal[False], CosmeticHistory]

    @property
    def color(self) -> Colour:
        """
        Get the color of the cosmetic based on its rarity.
        """

        try:
            return Colour(
                {
                    "frozen": 0xC4DFF7,
                    "lava": 0xD19635,
                    "legendary": 0xE67E22,
                    "dark": 0xFF42E7,
                    "marvel": 0x761B1B,
                    "dc": 0x243461,
                    "star_wars": 0x081737,
                    "gaming_legends": 0x312497,
                    "icon_series": 0x3FB8C7,
                    "slurp": 0x12A9A4,
                    "shadow": 0x191919,
                    "epic": 0xC751F8,
                    "rare": 0x3DABF5,
                    "uncommon": 0x51A50B,
                    "common": 0x838383,
                }[self.rarity]
            )
        except KeyError:
            return Colour.dark_embed()

    @classmethod
    async def convert(cls, ctx: Context, argument: str) -> "Cosmetic":
        response = await ctx.bot.session.get(
            URL.build(
                scheme="https",
                host="fnbr.co",
                path="/api/images",
                query={
                    "search": argument,
                    "limit": 5,
                },
            ),
            headers={
                "x-api-key": config.AUTHORIZATION.FNBR,
            },
        )
        if not response.ok:
            raise CommandError(
                f"The Fortnite API raised an error (`{response.status}`)"
            )

        data = await response.json()
        if not data["data"]:
            raise CommandError(
                f"No cosmetic found for **{argument}**",
                "Please make sure you're using the [correct name](https://fnbr.co/list)",
            )

        if len(data["data"]) > 1:
            embed = Embed(
                title="Multiple Cosmetics Found",
                description=(
                    "Please select a cosmetic from the list below\n"
                    + "\n".join(
                        f"> `{index + 1}` **{cosmetic['name']}** ({cosmetic['type'].title()})"
                        for index, cosmetic in enumerate(data["data"])
                    )
                ),
            )
            prompt = await ctx.reply(embed=embed)

            try:
                message = await ctx.bot.wait_for(
                    "message",
                    check=lambda m: (
                        m.content
                        and m.content.isdigit()
                        and m.author == ctx.author
                        and m.channel == ctx.channel
                    ),
                    timeout=60,
                )
            except asyncio.TimeoutError as exc:
                raise CommandError("You took too long to reply") from exc

            else:
                await quietly_delete(message)

            finally:
                await quietly_delete(prompt)

            try:
                index = int(message.content) - 1
                if index < 0:
                    raise ValueError

                data = data["data"][index]
            except (IndexError, ValueError) as exc:
                raise CommandError(
                    "Invalid selection, please use the number next to the cosmetic"
                ) from exc

            return cls(**data)

        return cls(**data["data"][0])


client_id = "3f69e56c7649492c8cc29f1af08a8a12"
client_secret = "b51ee9cb12234f50a69efa67ef53812e"
login_url = URL.build(
    scheme="https",
    host="www.epicgames.com",
    path="/id/login",
    query={
        "redirectUrl": URL.build(
            scheme="https",
            host="www.epicgames.com",
            path="/id/api/redirect",
            query={"clientId": client_id, "responseType": "code"},
        ).human_repr()
    },
)


class Fortnite(MixinMeta, metaclass=CompositeMetaClass):
    """
    The Fortnite cog provides various Fortnite commands.
    """

    async def cog_load(self) -> None:
        self.fortnite_item_shop.start()
        return await super().cog_load()

    async def cog_unload(self) -> None:
        self.fortnite_item_shop.cancel()
        return await super().cog_unload()

    @property
    def shop_url(self) -> str:
        now = utcnow()
        return (
            "https://bot.fnbr.co/shop-image/"
            "fnbr-shop-"
            f"{now:%-d-%-m-%Y}"
            f".png?{now.timestamp()}"
        )

    @loop(hours=24)
    async def fortnite_item_shop(self) -> None:
        """
        Dispatch an event for the Fortnite item shop rotation.
        """

        # We attempt to check the shop from fnbr 3 times with a 3 minute delay between each attempt.
        # This is because the API has to rebuild the backend cache every time the shop rotates.
        data: Optional[dict] = None
        attempts = 3
        for _ in range(attempts):
            await asyncio.sleep(180)

            response = await self.bot.session.get(
                URL.build(
                    scheme="https",
                    host="fnbr.co",
                    path="/api/shop",
                ),
                headers={
                    "x-api-key": config.AUTHORIZATION.FNBR,
                },
            )
            if response.status == 200:
                data = await response.json()
                break

        if not data:
            log.warning(
                "The Fortnite item shop couldn't be fetched after %s attempts.",
                attempts,
            )
            return

        self.bot.dispatch("fortnite_item_shop", data["data"])

    @fortnite_item_shop.before_loop
    async def before_fortnite_item_shop(self) -> None:
        """
        Wait until 00:00 UTC to start the task.
        """

        await self.bot.wait_until_ready()

        now = utcnow()
        next_run = now.replace(hour=0, minute=0, second=0, microsecond=0)
        if now > next_run:
            next_run += timedelta(days=1)

        log.debug(
            "Fortnite item shop task will start in %s.",
            naturaldelta(next_run - now),
        )
        await sleep_until(next_run)

    @Cog.listener("on_fortnite_item_shop")
    async def dispatch_cosmetic_reminders(self, data: dict) -> None:
        """
        Send reminders for cosmetics in the item shop.
        """

        records = await self.bot.db.fetch(
            """
            SELECT
                user_id,
                ARRAY_AGG(item_id) AS item_ids
            FROM fortnite.reminder
            WHERE item_id = ANY($1::TEXT[])
            GROUP BY user_id
            """,
            [item_id for section in data["sections"] for item_id in section["items"]],
        )
        if not records:
            return

        log.info(
            "Sending Fortnite cosmetic reminders to %s user%s.",
            len(records),
            "s" if len(records) > 1 else "",
        )

        scheduled_deletion: List[int] = []
        for record in records:
            user = self.bot.get_user(record["user_id"])
            if not user:
                continue

            items: List[Cosmetic] = [
                Cosmetic(**item)
                for item in data["featured"] + data["daily"]
                if item["id"] in record["item_ids"]
            ]

            embed = Embed(
                url="https://fortnite.gg/shop",
                title="Fortnite Item Shop",
                description=(
                    (
                        "The following cosmetics are now in the item shop\n"
                        if len(items) > 1
                        else "The following cosmetic is now in the item shop\n"
                    )
                    + "\n".join(
                        f"> **{item.name}** ({item.type.title()}) for **{item.price} V-Bucks**"
                        for item in items
                    )
                ),
            )
            if len(items) == 1:
                embed.set_image(url=items[0].images.icon)
            else:
                embed.set_image(url=self.shop_url)

            try:
                await user.send(embed=embed)
            except HTTPException as exc:
                if exc.code == 50007:
                    scheduled_deletion.append(record["user_id"])
                else:
                    raise

        if scheduled_deletion:
            await self.bot.db.execute(
                """
                DELETE FROM fortnite.reminder
                WHERE user_id = ANY($1::BIGINT[])
                """,
                scheduled_deletion,
            )

    @Cog.listener("on_fortnite_item_shop")
    async def dispatch_fortnite_item_shop(self, _: dict) -> List[Message]:
        """
        Send an embed containing the Fortnite item shop.
        """

        embed = Embed(
            url="https://fortnite.gg/shop",
            title="Fortnite Item Shop",
        )
        embed.set_image(url=self.shop_url)

        records = await self.bot.db.fetch(
            """
            SELECT guild_id, channel_id, message
            FROM fortnite.rotation
            """,
        )

        sent_messages: List[Message] = []
        scheduled_deletion: List[int] = []
        for record in records:
            guild = self.bot.get_guild(record["guild_id"])
            if not guild:
                scheduled_deletion.append(record["channel_id"])
                continue

            channel = guild.get_channel_or_thread(record["channel_id"])
            if not isinstance(channel, (TextChannel, Thread)):
                scheduled_deletion.append(record["channel_id"])
                continue

            try:
                message = await channel.send(
                    content=record["message"],
                    embed=embed,
                    allowed_mentions=AllowedMentions.all(),
                )
            except HTTPException:
                scheduled_deletion.append(record["channel_id"])
            else:
                sent_messages.append(message)

        if scheduled_deletion:
            log.info(
                "Scheduled deletion of %s item shop rotation message%s.",
                len(scheduled_deletion),
                "s" if len(scheduled_deletion) > 1 else "",
            )

            await self.bot.db.execute(
                """
                DELETE FROM fortnite.rotation
                WHERE channel_id = ANY($1::BIGINT[])
                """,
                scheduled_deletion,
            )

        elif sent_messages:
            log.info(
                "Sent %s item shop rotation message%s.",
                len(sent_messages),
                "s" if len(sent_messages) > 1 else "",
            )

        return sent_messages

    @group(aliases=["fn"], invoke_without_command=True)
    async def fortnite(self, ctx: Context) -> Message:
        """
        Various Fortnite commands.
        """

        return await ctx.send_help(ctx.command)

    @fortnite.group(
        name="shop",
        invoke_without_command=True,
    )
    async def fortnite_shop(self, ctx: Context) -> Message:
        """
        View the current Fortnite item shop.
        """

        embed = Embed(
            url="https://fortnite.gg/shop",
            title="Fortnite Item Shop",
        )
        embed.set_image(url=self.shop_url)

        return await ctx.send(embed=embed)

    @fortnite_shop.command(
        name="channel",
        aliases=["set"],
        description="manage channels",
        usage="<channel>",
        brief="#fortnite",
    )
    @has_permissions(manage_channels=True)
    async def fortnite_shop_channel(
        self,
        ctx: Context,
        channel: TextChannel | Thread,
    ) -> Message:
        """
        Receive notifications when the item shop rotates.
        """

        await self.bot.db.execute(
            """
            INSERT INTO fortnite.rotation (
                guild_id,
                channel_id
            ) VALUES (
                $1,
                $2
            ) ON CONFLICT (guild_id) DO UPDATE SET
                channel_id = EXCLUDED.channel_id
            """,
            ctx.guild.id,
            channel.id,
        )

        return await ctx.approve(
            f"Now sending Fortnite item shop rotations to {channel.mention}"
        )

    @fortnite_shop.command(
        name="message",
        aliases=["msg", "template"],
        description="manage channels & mention everyone",
        usage="<message>",
        brief="https://discord.com/channels/1135484270740246578/1143553248284909568/1251961434175180857",
    )
    @has_permissions(manage_channels=True, mention_everyone=True)
    async def fortnite_shop_message(
        self,
        ctx: Context,
        *,
        message: str,
    ) -> Message:
        """
        Set the message for the item shop rotation.

        This is useful for notifying members or roles.
        """

        result = await self.bot.db.execute(
            """
            UPDATE fortnite.rotation
            SET message = $2
            WHERE guild_id = $1
            """,
            ctx.guild.id,
            message,
        )
        if result == "UPDATE 0":
            return await ctx.warn(
                "You haven't set a channel for the Fortnite item shop rotation"
            )

        return await ctx.approve(
            "Successfully  set the message for the Fortnite item shop rotation"
        )

    @fortnite_shop.command(
        name="remove", aliases=["del", "rm"], description="manage channels"
    )
    @has_permissions(manage_channels=True)
    async def fortnite_shop_remove(self, ctx: Context) -> Message:
        """
        Stop receiving notifications when the item shop rotates.
        """

        result = await self.bot.db.execute(
            """
            DELETE FROM fortnite.rotation
            WHERE guild_id = $1
            """,
            ctx.guild.id,
        )
        if result == "DELETE 0":
            return await ctx.warn(
                "You haven't set a channel for the Fortnite item shop rotation"
            )

        return await ctx.approve(
            "No longer sending Fortnite item shop rotations to this server"
        )

    @fortnite.command(
        name="view", aliases=["show"], usage="<cosmetic>", brief="The Weekend"
    )
    async def fortnite_view(
        self,
        ctx: Context,
        *,
        cosmetic: Cosmetic,
    ) -> Message:
        """
        View information about a cosmetic.
        """

        embed = Embed(
            color=cosmetic.color,
            title=cosmetic.name,
            description=(
                cosmetic.description
                + (
                    f"\n> Introduced {format_dt(cosmetic.history.first_seen, 'R')}"
                    if cosmetic.history
                    else ""
                )
            ),
        )
        if cosmetic.price_icon:
            embed.set_footer(
                text=f"{cosmetic.price} V-Bucks",
                icon_url="https://image.fnbr.co/price/icon_vbucks.png",
            )

        embed.set_thumbnail(url=cosmetic.images.icon)

        if cosmetic.history and cosmetic.history.dates:
            embed.add_field(
                name="**History**",
                value=(
                    "\n".join(
                        f"{format_dt(date, 'D')} ({format_dt(date, 'R')})"
                        for date in sorted(cosmetic.history.dates[:5], reverse=True)
                    )
                    + (
                        f"\n> +{plural(len(cosmetic.history.dates) - 5, md='`'):other occurrence}"
                        if len(cosmetic.history.dates) > 5
                        else ""
                    )
                ),
            )

        return await ctx.send(embed=embed)

    @fortnite.group(
        name="remind",
        aliases=["reminder"],
        invoke_without_command=True,
    )
    async def fortnite_remind(self, ctx: Context) -> Message:
        """
        Receive notifications when an item is in the shop.
        """

        return await ctx.send_help(ctx.command)

    @fortnite_remind.command(name="add", usage="<cosmetic>", brief="The Weekend")
    async def fortnite_remind_add(
        self,
        ctx: Context,
        *,
        cosmetic: Cosmetic,
    ) -> Message:
        """
        Add a reminder for a cosmetic.
        """

        try:
            await self.bot.db.execute(
                """
                INSERT INTO fortnite.reminder (
                    user_id,
                    item_id,
                    item_name,
                    item_type
                ) VALUES (
                    $1,
                    $2,
                    $3,
                    $4
                )
                """,
                ctx.author.id,
                cosmetic.id,
                cosmetic.name,
                cosmetic.type,
            )
        except UniqueViolationError:
            return await ctx.warn(
                f"You are already receiving notifications for **{cosmetic.name}** ({cosmetic.type.title()})"
            )

        return await ctx.approve(
            f"You'll now be notified when **{cosmetic.name}** ({cosmetic.type.title()}) is in the item shop"
        )

    @fortnite_remind.command(
        name="remove", aliases=["del", "rm"], usage="<cosmetic>", brief="The Weekend"
    )
    async def fortnite_remind_remove(
        self,
        ctx: Context,
        *,
        cosmetic: Cosmetic,
    ) -> Message:
        """
        Remove a reminder for a cosmetic.
        """

        result = await self.bot.db.execute(
            """
            DELETE FROM fortnite.reminder
            WHERE user_id = $1
            AND item_id = $2
            """,
            ctx.author.id,
            cosmetic.id,
        )
        if result == "DELETE 0":
            return await ctx.warn(
                f"You aren't receiving notifications for **{cosmetic.name}** ({cosmetic.type.title()})"
            )

        return await ctx.approve(
            f"You'll no longer be notified when **{cosmetic.name}** ({cosmetic.type.title()}) is in the item shop"
        )

    @fortnite_remind.command(
        name="clear",
        aliases=["clean", "reset"],
    )
    async def fortnite_remind_clear(self, ctx: Context) -> Message:
        """
        Remove all of your reminders.
        """

        await ctx.prompt(
            "Are you sure you want to remove all reminders?",
        )

        result = await self.bot.db.execute(
            """
            DELETE FROM fortnite.reminder
            WHERE user_id = $1
            """,
            ctx.author.id,
        )
        if result == "DELETE 0":
            return await ctx.warn(
                "You aren't receiving notifications for any cosmetics"
            )

        return await ctx.approve(
            f"Successfully  removed {plural(result, md='`'):cosmetic reminder}"
        )

    @fortnite_remind.command(name="list")
    async def fortnite_remind_list(self, ctx: Context) -> Message:
        """
        View all of your reminders.
        """

        cosmetics = [
            f"**{record['item_name']}** ({record['item_type'].title()})"
            for record in await self.bot.db.fetch(
                """
                SELECT *
                FROM fortnite.reminder
                WHERE user_id = $1
                """,
                ctx.author.id,
            )
        ]
        if not cosmetics:
            return await ctx.warn(
                "You aren't receiving notifications for any cosmetics"
            )

        paginator = Paginator(
            ctx,
            entries=cosmetics,
            embed=Embed(
                title="Cosmetic Reminders",
            ),
        )
        return await paginator.start()
