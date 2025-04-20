from asyncio import sleep
from contextlib import suppress
from datetime import timedelta
from logging import getLogger
from typing import Annotated, Dict, List, Literal, Optional, Tuple, TypedDict, cast

from discord import Asset, Embed, Guild, HTTPException, Member, Message
from discord import Status as DiscordStatus
from discord import User
from discord.ext.commands import (
    Cog,
    Range,
    UserInputError,
    flag,
    group,
    has_permissions,
)
from discord.http import Route
from discord.utils import utcnow
from xxhash import xxh32_hexdigest

from tools import CompositeMetaClass, MixinMeta
from tools.client import Context, FlagConverter
from tools.conversion import Status
from tools.formatter import plural

log = getLogger("zyn/raid")


class Flags(FlagConverter):
    punishment: Literal["ban", "kick", "timeout"] = flag(
        description="The punishment the member will receive.",
        aliases=["action", "punish", "do"],
        default="ban",
    )

    class Schema(TypedDict):
        punishment: str


class AmountFlags(Flags):
    amount: Range[int, 3] = flag(
        description="The threshold before activation.",
        aliases=["count", "threshold"],
        default=5,
    )

    class Schema(TypedDict):
        punishment: str
        amount: int


DEFAULT_AVATAR_HASHES = [
    "157e517cdbf371a47aaead44675714a3",
    "1628fc11e7961d85181295493426b775",
    "5445ffd7ffb201a98393cbdf684ea4b1",
    "79ee349b6511e2000af8a32fb8a6974e",
    "8569adcbd36c70a7578c017bf5604ea5",
    "f7f2e9361e8a54ce6e72580ac7b967af",
    "6c5996770c985bcd6e5b68131ff2ba04",
    "c82b3fa769ed6e6ffdea579381ed5f5c",
]


class AntiRaid(MixinMeta, metaclass=CompositeMetaClass):
    """
    Protect your server from flood attacks.
    """

    def is_default(self, avatar: Optional[Asset]) -> bool:
        return not avatar or avatar.key in DEFAULT_AVATAR_HASHES

    @group(invoke_without_command=True, description="administrator")
    @has_permissions(administrator=True)
    async def antiraid(self, ctx: Context) -> Message:
        """
        The base command for managing raid security.
        """

        return await ctx.send_help(ctx.command)

    @antiraid.command(
        name="joins",
        aliases=["massjoin"],
        description="administrator",
        usage="<status> [flags]",
        brief="yes",
    )
    @has_permissions(administrator=True)
    async def antiraid_joins(
        self,
        ctx: Context,
        status: Annotated[
            bool,
            Status,
        ],
        *,
        flags: AmountFlags,
    ) -> Message:
        """
        Security against accounts which join simultaneously.

        If multiple members join within the `threshold` then the
        members will automatically be punished.
        The `threshold` must be greater than 3.
        """

        if status is False:
            await self.bot.db.execute(
                """
                UPDATE antiraid
                SET joins = NULL
                WHERE guild_id = $1
                """,
                ctx.guild.id,
            )
            return await ctx.approve("Join protection has been disabled")

        await self.bot.db.execute(
            """
            INSERT INTO antiraid (guild_id, joins)
            VALUES ($1, $2)
            ON CONFLICT (guild_id)
            DO UPDATE
            SET joins = EXCLUDED.joins
            """,
            ctx.guild.id,
            dict(flags),
        )
        return await ctx.approve(
            "Join protection has been enabled.",
            f"Threshold set as `{flags.amount}` "
            f"with punishment: **{flags.punishment}**",
        )

    @antiraid.command(
        name="mentions",
        description="administrator",
        usage="<status> [flags]",
        brief="yes",
    )
    @has_permissions(administrator=True)
    async def antiraid_mentions(
        self,
        ctx: Context,
        status: Annotated[
            bool,
            Status,
        ],
        *,
        flags: AmountFlags,
    ) -> Message:
        """
        Security against accounts that spam excessive mentions.

        If a message contains `threshold` or more mentions then the
        member will be automatically be punished.
        The `threshold` must be greater than 3.

        This only applies for user mentions. Everyone or Role
        mentions are not included.
        """

        if status is False:
            await self.bot.db.execute(
                """
                UPDATE antiraid
                SET mentions = NULL
                WHERE guild_id = $1
                """,
                ctx.guild.id,
            )
            return await ctx.approve("Mention spam protection has been disabled")

        await self.bot.db.execute(
            """
            INSERT INTO antiraid (guild_id, mentions)
            VALUES ($1, $2)
            ON CONFLICT (guild_id)
            DO UPDATE
            SET mentions = EXCLUDED.mentions
            """,
            ctx.guild.id,
            dict(flags),
        )
        return await ctx.approve(
            "Mention spam protection has been enabled.",
            f"Threshold set as `{flags.amount}` "
            f"with punishment: **{flags.punishment}**",
        )

    @antiraid.command(
        name="avatar",
        aliases=["pfp"],
        description="administrator",
        usage="<status> [flags]",
        brief="yes",
    )
    @has_permissions(administrator=True)
    async def antiraid_avatar(
        self,
        ctx: Context,
        status: Annotated[
            bool,
            Status,
        ],
        *,
        flags: Flags,
    ) -> Message:
        """
        Security against accounts which don't have an avatar.
        """

        if status is False:
            await self.bot.db.execute(
                """
                UPDATE antiraid
                SET avatar = NULL
                WHERE guild_id = $1
                """,
                ctx.guild.id,
            )
            return await ctx.approve("Default avatar protection has been disabled")

        await self.bot.db.execute(
            """
            INSERT INTO antiraid (guild_id, avatar)
            VALUES ($1, $2)
            ON CONFLICT (guild_id)
            DO UPDATE
            SET avatar = EXCLUDED.avatar
            """,
            ctx.guild.id,
            dict(flags),
        )
        return await ctx.approve(
            f"Default avatar protection has been enabled "
            f"with punishment as **{flags.punishment}**"
        )

    @antiraid.command(
        name="automation",
        aliases=[
            "selfbot",
            "browser",
            "web",
        ],
        description="administrator",
        usage="<status> [flags]",
        brief="yes",
    )
    @has_permissions(administrator=True)
    async def antiraid_automation(
        self,
        ctx: Context,
        status: Annotated[
            bool,
            Status,
        ],
        *,
        flags: Flags,
    ) -> Message:
        """
        Security against accounts which are only active on browser.

        This is a common trait of selfbots and other automation tools.
        """

        if status is False:
            await self.bot.db.execute(
                """
                UPDATE antiraid
                SET browser = NULL
                WHERE guild_id = $1
                """,
                ctx.guild.id,
            )
            return await ctx.approve("Automation protection has been disabled")

        members = list(
            filter(
                lambda member: member.web_status != DiscordStatus.offline
                and all(
                    status == DiscordStatus.offline
                    for status in [member.mobile_status, member.desktop_status]
                )
                and not member.bot
                and not member.premium_since,
                ctx.guild.members,
            )
        )
        if members:
            try:
                await ctx.prompt(
                    f"{plural(members, md='`'):member is|members are} currently only online via browser.",
                    f"Would you like to **{flags.punishment}** them now? This does not affect boosters",
                )
            except UserInputError:
                ...
            else:
                async with ctx.typing():
                    for member in members:
                        await self.do_punishment(
                            ctx.guild,
                            member,
                            punishment=flags.punishment,
                            reason="Automation detected",
                        )

        await self.bot.db.execute(
            """
            INSERT INTO antiraid (guild_id, browser)
            VALUES ($1, $2)
            ON CONFLICT (guild_id)
            DO UPDATE
            SET browser = EXCLUDED.browser
            """,
            ctx.guild.id,
            dict(flags),
        )
        return await ctx.approve(
            f"Automation protection has been enabled "
            f"with punishment as **{flags.punishment}**"
        )

    async def submit_incident(
        self,
        guild: Guild,
        members: List[Member],
    ) -> None:
        """
        Secure the server during a raid incident.
        """

        key = xxh32_hexdigest(f"incident:{guild.id}", 0x9491)
        if await self.bot.redis.exists(key):
            return

        await self.bot.redis.set(key, 1, ex=30)
        log.info(
            "Detected %s simultaneous joins within 15 seconds in %s (%s).",
            len(members),
            guild,
            guild.id,
        )

        await self.bot.db.execute(
            """
            UPDATE antiraid
            SET locked = TRUE
            WHERE guild_id = $1
            """,
            guild.id,
        )
        ends_at = utcnow() + timedelta(hours=1)

        route = Route(
            "PUT",
            "/guilds/{guild_id}/incident-actions",
            guild_id=guild.id,
        )
        await self.bot.http.request(
            route,
            json={
                "invites_disabled_until": ends_at,
                "dms_disabled_until": ends_at,
            },
        )

        with suppress(HTTPException):
            embed = Embed(
                title="Raid Detected",
                description=f"Detected {len(members)} simultaneous joins",
            )

            embed.add_field(
                name="**Action**",
                value=(
                    "New members & DMs "
                    "have been temporarily restricted for an **hour**"
                ),
                inline=True,
            )
            embed.set_footer(text="The mitigation task has been initialized")

            await self.bot.notify(
                guild,
                content=f"<@{guild.owner_id}>",
                embed=embed,
            )

        await sleep(5)
        await self.bot.db.execute(
            """
            UPDATE antiraid
            SET locked = FALSE
            WHERE guild_id = $1
            """,
            guild.id,
        )

    async def do_punishment(
        self,
        guild: Guild,
        member: Member | User,
        *,
        punishment: str,
        reason: str,
    ) -> bool:
        """
        Attempt to punish the member.
        """

        with suppress(HTTPException):
            if punishment == "ban":
                await guild.ban(
                    member,
                    delete_message_days=7,
                    reason=reason,
                )
                return True

            elif isinstance(member, User):
                return False

            elif punishment == "kick":
                await member.kick(
                    reason=reason,
                )
                return True

            elif punishment == "timeout":
                await member.timeout(
                    timedelta(days=27),
                    reason=reason,
                )
                return True

        return False

    @Cog.listener("on_member_join")
    async def check_raid(self, member: Member) -> None:
        """
        Check for simultaneous joins & default avatars.
        """

        if member.bot:
            return

        config = cast(
            Optional[Dict[str, AmountFlags.Schema]],
            await self.bot.db.fetchrow(
                """
                SELECT *
                FROM antiraid
                WHERE guild_id = $1
                """,
                member.guild.id,
            ),
        )
        if not config:
            return

        elif config["locked"] is True and (config := config["joins"]) is not None:
            punished = await self.do_punishment(
                member.guild,
                member,
                punishment=config["punishment"],
                reason="Server is on lockdown. (ANTIRAID ACTIVE)",
            )

            return log.info(
                "%s %s (%s) during an active raid in %s (%s).",
                "Punished" if punished else "Failed to punish",
                member,
                member.id,
                member.guild,
                member.guild.id,
            )

        elif (
            self.is_default(member.avatar)
            and (avatar := config.get("avatar")) is not None
        ):
            punished = await self.do_punishment(
                member.guild,
                member,
                punishment=avatar["punishment"],
                reason="Default avatar detected",
            )

            return log.debug(
                "Default avatar detected from %s (%s) in %s (%s) [%s].",
                member,
                member.id,
                member.guild,
                member.guild.id,
                "PUNISHED" if punished else "FAILED TO PUNISH",
            )

        elif (
            member.web_status != DiscordStatus.offline
            and all(
                status == DiscordStatus.offline
                for status in [member.mobile_status, member.desktop_status]
            )
            and (browser := config.get("browser")) is not None
        ):
            punished = await self.do_punishment(
                member.guild,
                member,
                punishment=browser["punishment"],
                reason="Spoofed gateway detected (BROWSER)",
            )

            return log.debug(
                "Spoofed gateway detected from %s (%s) in %s (%s) [%s].",
                member,
                member.id,
                member.guild,
                member.guild.id,
                "PUNISHED" if punished else "FAILED TO PUNISH",
            )

        elif not (config := config.get("joins")):
            return

        key = f"sec.joins:{member.guild.id}"

        pipe = self.bot.redis.pipeline()
        pipe.sadd(key, member.id)
        pipe.smembers(key)

        _, member_ids = cast(
            Tuple[bytes, List[bytes]],
            await pipe.execute(),
        )
        members: List[Member] = []

        # cleaner
        pipe = self.bot.redis.pipeline()
        now = utcnow()

        for member_id in member_ids:
            m = member.guild.get_member(int(member_id))
            if not m or not m.joined_at:
                pipe.srem(key, member_id)
                continue

            dif = abs((now - m.joined_at).total_seconds())
            if dif >= 15:
                pipe.srem(key, member_id)
                continue

            members.append(m)

        self.bot.loop.create_task(pipe.execute())
        if len(members) < config["amount"]:
            return

        future = self.submit_incident(member.guild, members)
        self.bot.loop.create_task(future)

        pipe = self.bot.redis.pipeline()
        for member in members:
            if not isinstance(member, Member):
                pipe.srem(key, member.id)
                continue

            await self.do_punishment(
                member.guild,
                member,
                punishment=config["punishment"],
                reason=f"Detected {len(members)}/{config['amount']} simultaneous joins",
            )

    @Cog.listener("on_message")
    async def check_mentions(self, message: Message) -> None:
        """
        Check for mention spam.
        """

        if (
            not message.guild
            or not isinstance(message.author, Member)
            or message.author.bot
            or message.author.guild_permissions.manage_messages
        ):
            return

        mentions = sum(
            not member.bot and member.id != message.author.id
            for member in message.mentions
        )
        if not mentions or mentions <= 2:
            return

        config = cast(
            Optional[AmountFlags.Schema],
            await self.bot.db.fetchval(
                """
                SELECT mentions
                FROM antiraid
                WHERE guild_id = $1
                """,
                message.guild.id,
            ),
        )
        if not config or config and not mentions > config["amount"]:
            return

        punished = await self.do_punishment(
            message.guild,
            message.author,
            punishment=config["punishment"],
            reason=f"Mention spam detected ({mentions}/{config['amount']})",
        )
        log.info(
            "Mention spam detected from %s (%s) in %s (%s) [%s].",
            message.author,
            message.author.id,
            message.guild,
            message.guild.id,
            "PUNISHED" if punished else "FAILED TO PUNISH",
        )
