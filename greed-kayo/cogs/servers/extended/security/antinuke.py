from contextlib import suppress
from datetime import timedelta
from logging import getLogger
from time import time
from typing import Annotated, List, Optional, cast
from colorama import Fore

from discord import (
    AuditLogEntry,
    Embed,
    Guild,
    HTTPException,
    Member,
    Message,
    Object,
    User,
)
from discord.ext.commands import Cog, Range, flag, group
from discord.utils import utcnow
from humanize import naturaldelta
from pydantic import BaseConfig, BaseModel
from typing_extensions import Self
from xxhash import xxh32_hexdigest

from config import CLIENT
from main import zyn
from tools import CompositeMetaClass, MixinMeta
from tools.client import Context, FlagConverter
from tools.conversion import Duration, Status
from tools.formatter import codeblock, plural
from tools.paginator import Paginator

log = getLogger("zyn/nuke")


class Flags(FlagConverter):
    threshold: Range[int, 1, 12] = flag(
        default=3,
        aliases=["limit"],
        description="The threshold for the module to trigger.",
    )
    duration: timedelta = flag(
        aliases=["time", "per"],
        converter=Duration(
            max=timedelta(hours=12),
        ),
        default=timedelta(minutes=60),
        description="The duration before the threshold resets.",
    )


class Module(BaseModel):
    threshold: int = 5
    duration: int = 60


class Settings(BaseModel):
    guild: Guild
    whitelist: List[int] = []
    trusted_admins: List[int] = []
    bot: bool = False
    ban: Optional[Module]
    kick: Optional[Module]
    role: Optional[Module]
    channel: Optional[Module]
    webhook: Optional[Module]
    emoji: Optional[Module]

    def __bool__(self) -> bool:
        """
        Check if the settings are enabled.
        """

        return any(
            getattr(self, module)
            for module in ("ban", "kick", "role", "channel", "webhook", "emoji")
        )

    def __getitem__(self, module: str) -> Optional[Module]:
        """
        Get the module settings.
        """

        return getattr(self, module)

    def is_trusted(self, member: Context | Member) -> bool:
        """
        Check if a member is trusted.
        """

        if isinstance(member, Context):
            member = member.author

        return member.id in {
            self.guild.owner_id,
            *self.trusted_admins,
            *CLIENT.OWNER_IDS,
        }

    def is_whitelisted(self, member: Member) -> bool:
        """
        Check if a member is whitelisted.
        """

        return member.id in {
            self.guild.owner_id,
            self.guild.me.id,
            *self.whitelist,
            *self.trusted_admins,
            *CLIENT.OWNER_IDS,
        }

    async def dispatch_log(
        self,
        bot: zyn,
        member: Member,
        module: str,
        *,
        elapsed: float = 0.0,
        failure: bool = False,
        details: Optional[str] = None,
        description: Optional[str] = None,
        application: Optional[Member | User | Object] = None,
    ) -> None:
        """
        Notify the guild owner of a malicious action.
        """

        guild = member.guild
        if not guild.owner:
            return

        key = xxh32_hexdigest(f"antinuke.log:{guild.id}:{module}")
        locked = await bot.redis.get(key)
        if locked:
            return

        await bot.redis.set(key, 1, 60)
        log.debug(
            "Dispatching antinuke log for %s (%s) in %s (%s).",
            member,
            member.id,
            guild,
            guild.id,
        )

        embed = Embed(
            title="Antinuke Notification",
            timestamp=utcnow(),
        )
        embed.set_author(
            url=guild.vanity_url,
            name=guild.name,
            icon_url=guild.icon,
        )
        embed.add_field(
            name="**Perpetrator**",
            value=f"{member} (`{member.id}`)",
        )
        if application:
            embed.add_field(
                name="**Application**",
                value=f"{application} (`{application.id}`)",
            )

        embed.set_footer(text=f"Action took {elapsed:.2f}s")

        embed.description = description or (
            f"Mass {module} attempt has been detected"
            if module != "bot"
            else "Bot addition attempt has been detected"
        )
        if failure:
            embed.description += "\n> **FAILED TO PUNISH PERPETRATOR**"

        if details:
            embed.add_field(
                name="**Details**",
                value=f">>> {codeblock(details)}",
                inline=False,
            )

        with suppress(HTTPException):
            await guild.owner.send(embed=embed)

    async def check_threshold(self, bot: zyn, member: Member, module: str) -> bool:
        """
        Check if a member exceeds the threshold for a module.
        """

        if self.is_whitelisted(member):
            return False

        config: Optional[Module] = getattr(self, module)
        if not config:
            return False

        key = xxh32_hexdigest(f"antinuke_{module}:{self.guild.id}-{member.id}")
        pipe = bot.redis.pipeline()
        pipe.incr(key)
        pipe.expire(key, config.duration)
        value, _ = cast(
            tuple[int, int],
            await pipe.execute(),
        )

        if value >= config.threshold:
            log.debug(
                f"{Fore.LIGHTMAGENTA_EX}{member}{Fore.RESET} exceeded the antinuke {Fore.LIGHTCYAN_EX}{module}{Fore.RESET} threshold in {Fore.LIGHTYELLOW_EX}{self.guild}{Fore.RESET}."
            )
            return True

        return False

    @classmethod
    async def revalidate(cls, bot: zyn, guild: Guild) -> Optional[Self]:
        """
        Revalidate the settings for a guild.
        This will update the cache in redis.
        """

        key = xxh32_hexdigest(f"antinuke:{guild.id}")
        await bot.redis.delete(key)

        record = await bot.db.fetchrow(
            """
            SELECT *
            FROM antinuke
            WHERE guild_id = $1
            """,
            guild.id,
        )
        if not record:
            return

        settings = cls(**record, guild=guild)
        await bot.redis.set(key, settings.dict(exclude={"guild"}))
        return settings

    @classmethod
    async def fetch(cls, bot: zyn, guild: Guild) -> Self:
        """
        Fetch the settings for a guild.
        This will cache the settings in redis.
        """

        key = xxh32_hexdigest(f"antinuke:{guild.id}")
        cached = cast(
            Optional[dict],
            await bot.redis.get(key),
        )
        if cached:
            return cls(**cached, guild=guild)

        record = await bot.db.fetchrow(
            """
            INSERT INTO antinuke (guild_id)
            VALUES ($1)
            ON CONFLICT (guild_id)
            DO NOTHING
            RETURNING *
            """,
            guild.id,
        )

        settings = cls(**record or {}, guild=guild)
        await bot.redis.set(key, settings.dict(exclude={"guild"}))
        return settings

    class Config(BaseConfig):
        arbitrary_types_allowed = True


class AntiNuke(MixinMeta, metaclass=CompositeMetaClass):
    """
    Protect your server from malicious administrators.
    """

    async def cog_load(self) -> None:
        self.bot.add_check(self.is_trusted_admin)
        return await super().cog_load()

    async def cog_unload(self) -> None:
        self.bot.remove_check(self.is_trusted_admin)
        return await super().cog_unload()

    async def is_trusted_admin(self, target: Context | Member) -> bool:
        """
        Check if the author of the command is trusted.

        They'll be trusted if they're the owner of the server,
        or if they were manually added as a trusted member by the owner.
        """

        if isinstance(target, Context):
            command = target.command
            member = target.author
            guild = target.guild
            if not command.qualified_name.startswith("antinuke"):
                return True

        else:
            member = target
            guild = member.guild

        if member.id in {guild.owner_id, *self.bot.owner_ids}:
            return True

        settings = await Settings.fetch(self.bot, guild)
        if not settings.is_trusted(member):
            if isinstance(target, Context):
                await target.warn(
                    "You must be a **trusted administrator** to use this command"
                )

            return False

        return True

    @group(
        aliases=[
            "antiwizz",
            "an",
            "aw",
        ],
        invoke_without_command=True,
        description="antinuke owner & admin",
    )
    async def antinuke(self, ctx: Context) -> Message:
        """
        Protect your server from malicious administrators.
        """

        return await ctx.send_help(ctx.command)

    @antinuke.command(
        name="settings", aliases=["config"], description="antinuke owner & admin"
    )
    async def antinuke_settings(self, ctx: Context) -> Message | None:
        """
        View the antinuke settings.
        """

        config = await Settings.fetch(self.bot, ctx.guild)
        if not config:
            return await ctx.warn("The **antinuke system** hasn't been configured yet")

        await ctx.send(
            config.json(
                indent=4,
                exclude={"guild"},
            )
        )

    @antinuke.group(
        name="whitelist",
        aliases=["wl"],
        description="antinuke owner & admin",
        invoke_without_command=True,
    )
    async def antinuke_whitelist(self, ctx: Context, *, member: Member) -> Message:
        """
        Whitelist a member from the antinuke system.
        """

        config = await Settings.fetch(self.bot, ctx.guild)
        if member.id in config.whitelist:
            await ctx.prompt(
                f"**{member}** is already whitelisted from the **antinuke system**",
                "Would you like to remove them from the whitelist?",
            )
            config.whitelist.remove(member.id)
        else:
            config.whitelist.append(member.id)

        await self.bot.db.execute(
            """
            UPDATE antinuke
            SET whitelist = $2
            WHERE guild_id = $1
            """,
            ctx.guild.id,
            config.whitelist,
        )
        await Settings.revalidate(self.bot, ctx.guild)

        return await ctx.approve(
            f"Now exempting **{member}** from being punished"
            if member.id in config.whitelist
            else f"Now punishing **{member}** for malicious actions"
        )

    @antinuke_whitelist.command(
        name="list", aliases=["ls"], description="antinuke owner & admin"
    )
    async def antinuke_whitelist_list(self, ctx: Context) -> Message:
        """
        View all whitelisted members.
        """

        config = await Settings.fetch(self.bot, ctx.guild)
        members = [
            f"**{member}** (`{member.id}`)"
            for member_id in config.whitelist
            if (member := ctx.guild.get_member(member_id))
        ]
        if not members:
            return await ctx.warn("No members are exempt from the **antinuke system**")

        paginator = Paginator(
            ctx,
            entries=members,
            embed=Embed(title="Whitelisted Members"),
        )
        return await paginator.start()

    @antinuke.group(
        name="trust",
        aliases=["admin"],
        description="antinuke owner",
        invoke_without_command=True,
    )
    async def antinuke_trust(self, ctx: Context, *, member: Member) -> Message:
        """
        Allow a member to manage the antinuke system.
        """

        config = await Settings.fetch(self.bot, ctx.guild)
        if member.id in config.trusted_admins:
            await ctx.prompt(
                f"**{member}** is already trusted with the **antinuke system**",
                "Would you like to remove them from the trusted list?",
            )
            config.trusted_admins.remove(member.id)
        else:
            config.trusted_admins.append(member.id)

        await self.bot.db.execute(
            """
            UPDATE antinuke
            SET trusted_admins = $2
            WHERE guild_id = $1
            """,
            ctx.guild.id,
            config.trusted_admins,
        )
        await Settings.revalidate(self.bot, ctx.guild)

        return await ctx.approve(
            f"{'Now' if member.id in config.trusted_admins else 'No longer'} allowing **{member}** to manage the **antinuke system**"
        )

    @antinuke_trust.command(
        name="list", aliases=["ls"], description="antinuke owner & admin"
    )
    async def antinuke_trust_list(self, ctx: Context) -> Message:
        """
        View all trusted admins.
        """

        config = await Settings.fetch(self.bot, ctx.guild)
        members = [
            f"**{member}** (`{member.id}`)"
            for member_id in config.trusted_admins
            if (member := ctx.guild.get_member(member_id))
        ]
        if not members:
            return await ctx.warn(
                "No members are allowed to manage the **antinuke system**"
            )

        paginator = Paginator(
            ctx,
            entries=members,
            embed=Embed(title="Trusted Admins"),
        )
        return await paginator.start()

    @antinuke.command(
        name="bot",
        aliases=[
            "bots",
            "botadd",
        ],
        description="antinuke owner & admin",
        usage="<status>",
        brief="yes",
    )
    async def antinuke_bot(
        self,
        ctx: Context,
        status: Annotated[
            bool,
            Status,
        ],
    ) -> Message:
        """
        Prevent bots from being added to the server.

        Whitelisted members will be exempt from this.
        """

        config = await Settings.fetch(self.bot, ctx.guild)
        if config.bot == status:
            return await ctx.warn(
                f"Protection against bots is already **{'enabled' if status else 'disabled'}**"
            )

        await self.bot.db.execute(
            """
            UPDATE antinuke
            SET bot = $2
            WHERE guild_id = $1
            """,
            ctx.guild.id,
            status,
        )
        await Settings.revalidate(self.bot, ctx.guild)

        return await ctx.approve(
            f"{'Now' if status else 'No longer'} preventing bots from being added to the server"
        )

    @antinuke.command(
        name="ban",
        aliases=["bans"],
        description="antinuke owner & admin",
        usage="<status> [flags]",
        brief="yes",
    )
    async def antinuke_ban(
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
        Prevent members from being banned.
        """

        config = await Settings.fetch(self.bot, ctx.guild)
        if not status and not config.ban:
            return await ctx.warn(
                "The **antinuke system** isn't preventing members from being banned"
            )

        config.ban = None
        if status:
            config.ban = Module(
                threshold=flags.threshold,
                duration=int(flags.duration.total_seconds()),
            )

        await self.bot.db.execute(
            """
            UPDATE antinuke
            SET ban = $2
            WHERE guild_id = $1
            """,
            ctx.guild.id,
            config.ban.dict() if config.ban else None,
        )
        await Settings.revalidate(self.bot, ctx.guild)

        if not status:
            return await ctx.approve("No longer preventing members from being banned")

        return await ctx.approve(
            f"Now punishing the perpetrator if {plural(flags.threshold, md='`'):member is|members are} banned within **{naturaldelta(flags.duration)}**"
        )

    @antinuke.command(
        name="kick",
        aliases=["kicks"],
        description="antinuke owner & admin",
        usage="<status> [flags]",
        brief="yes",
    )
    async def antinuke_kick(
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
        Prevent members from being kicked.
        """

        config = await Settings.fetch(self.bot, ctx.guild)
        if not status and not config.kick:
            return await ctx.warn(
                "The **antinuke system** isn't preventing members from being kicked"
            )

        config.kick = None
        if status:
            config.kick = Module(
                threshold=flags.threshold,
                duration=int(flags.duration.total_seconds()),
            )

        await self.bot.db.execute(
            """
            UPDATE antinuke
            SET kick = $2
            WHERE guild_id = $1
            """,
            ctx.guild.id,
            config.kick.dict() if config.kick else None,
        )
        await Settings.revalidate(self.bot, ctx.guild)

        if not status:
            return await ctx.approve("No longer monitoring members from being kicked")

        return await ctx.approve(
            f"Now punishing the perpetrator if {plural(flags.threshold, md='`'):member is|members are} kicked within **{naturaldelta(flags.duration)}**"
        )

    @antinuke.command(
        name="role",
        aliases=["roles"],
        description="antinuke owner & admin",
        usage="<status> [flags]",
        brief="yes",
    )
    async def antinuke_role(
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
        Prevent roles from being created, deleted, or modified.
        """

        config = await Settings.fetch(self.bot, ctx.guild)
        if not status and not config.role:
            return await ctx.warn(
                "The **antinuke system** isn't preventing roles from being modified"
            )

        config.role = None
        if status:
            config.role = Module(
                threshold=flags.threshold,
                duration=int(flags.duration.total_seconds()),
            )

        await self.bot.db.execute(
            """
            UPDATE antinuke
            SET role = $2
            WHERE guild_id = $1
            """,
            ctx.guild.id,
            config.role.dict() if config.role else None,
        )
        await Settings.revalidate(self.bot, ctx.guild)

        if not status:
            return await ctx.approve("No longer monitoring role modifications")

        return await ctx.approve(
            f"Now punishing the perpetrator if {plural(flags.threshold, md='`'):role is|roles are} modified within **{naturaldelta(flags.duration)}**"
        )

    @antinuke.command(
        name="channel",
        aliases=["channels"],
        description="antinuke owner & admin",
        usage="<status> [flags]",
        brief="yes",
    )
    async def antinuke_channel(
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
        Prevent channels from being created, deleted, or modified.
        """

        config = await Settings.fetch(self.bot, ctx.guild)
        if not status and not config.channel:
            return await ctx.warn(
                "The **antinuke system** isn't preventing channels from being modified"
            )

        config.channel = None
        if status:
            config.channel = Module(
                threshold=flags.threshold,
                duration=int(flags.duration.total_seconds()),
            )

        await self.bot.db.execute(
            """
            UPDATE antinuke
            SET channel = $2
            WHERE guild_id = $1
            """,
            ctx.guild.id,
            config.channel.dict() if config.channel else None,
        )
        await Settings.revalidate(self.bot, ctx.guild)

        if not status:
            return await ctx.approve("No longer monitoring channel modifications")

        return await ctx.approve(
            f"Now punishing the perpetrator if {plural(flags.threshold, md='`'):channel is|channels are} modified within **{naturaldelta(flags.duration)}**"
        )

    @antinuke.command(
        name="webhook",
        aliases=[
            "webhooks",
            "hook",
            "hooks",
            "wh",
        ],
        description="antinuke owner & admin",
        usage="<status> [flags]",
        brief="yes",
    )
    async def antinuke_webhook(
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
        Prevent webhooks from being created, deleted, or modified.
        """

        config = await Settings.fetch(self.bot, ctx.guild)
        if not status and not config.webhook:
            return await ctx.warn(
                "The **antinuke system** isn't preventing webhooks from being modified"
            )

        config.webhook = None
        if status:
            config.webhook = Module(
                threshold=flags.threshold,
                duration=int(flags.duration.total_seconds()),
            )

        await self.bot.db.execute(
            """
            UPDATE antinuke
            SET webhook = $2
            WHERE guild_id = $1
            """,
            ctx.guild.id,
            config.webhook.dict() if config.webhook else None,
        )
        await Settings.revalidate(self.bot, ctx.guild)

        if not status:
            return await ctx.approve("No longer monitoring webhook modifications")

        return await ctx.approve(
            f"Now punishing the perpetrator if {plural(flags.threshold, md='`'):webhook is|webhooks are} modified within **{naturaldelta(flags.duration)}**"
        )

    @antinuke.command(
        name="emoji",
        aliases=[
            "emojis",
            "emote",
            "emotes",
            "em",
        ],
        description="antinuke owner & admin",
        usage="<status> [flags]",
        brief="yes",
    )
    async def antinuke_emoji(
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
        Prevent emojis from being created, deleted, or modified.
        """

        config = await Settings.fetch(self.bot, ctx.guild)
        if not status and not config.emoji:
            return await ctx.warn(
                "The **antinuke system** isn't preventing emojis from being modified"
            )

        config.emoji = None
        if status:
            config.emoji = Module(
                threshold=flags.threshold,
                duration=int(flags.duration.total_seconds()),
            )

        await self.bot.db.execute(
            """
            UPDATE antinuke
            SET emoji = $2
            WHERE guild_id = $1
            """,
            ctx.guild.id,
            config.emoji.dict() if config.emoji else None,
        )
        await Settings.revalidate(self.bot, ctx.guild)

        if not status:
            return await ctx.approve("No longer monitoring emoji modifications")

        return await ctx.approve(
            f"Now punishing the perpetrator if {plural(flags.threshold, md='`'):emoji is|emojis are} modified within **{naturaldelta(flags.duration)}**"
        )

    @antinuke.command(name="reset", description="antinuke owner & admin")
    async def antinuke_reset(self, ctx: Context) -> Message:
        """
        Reset the antinuke settings.
        """

        await ctx.prompt(
            "Are you sure you want to reset the **antinuke settings**?",
            "This will remove all whitelisted members and trusted admins",
        )

        await self.bot.db.execute(
            """
            DELETE FROM antinuke
            WHERE guild_id = $1
            """,
            ctx.guild.id,
        )
        await Settings.revalidate(self.bot, ctx.guild)

        return await ctx.approve("Successfully  reset the **antinuke settings**")

    @Cog.listener("on_audit_log_entry_bot_add")
    async def antinuke_monitor_bot(self, entry: AuditLogEntry):
        start = time()
        guild = entry.guild
        perpetrator = entry.user
        application = cast(Member | User | Object, entry.target)
        if not isinstance(perpetrator, Member):
            return

        config = await Settings.fetch(self.bot, guild)
        if (
            not config
            or not config.bot
            or config
            and config.bot
            and config.is_whitelisted(perpetrator)
        ):
            return

        elapsed = time() - start
        try:
            await guild.ban(
                application,
                reason="Bot addition attempt detected",
            )
            await guild.ban(
                perpetrator,
                reason="Bot addition attempt detected",
            )
        except HTTPException as exc:
            return await config.dispatch_log(
                self.bot,
                perpetrator,
                module="bot",
                elapsed=elapsed,
                failure=True,
                details=exc.text,
                application=application,
            )

        await config.dispatch_log(
            self.bot,
            perpetrator,
            module="bot",
            elapsed=elapsed,
            application=application,
        )

    @Cog.listener("on_audit_log_entry_ban")
    async def antinuke_monitor_ban(self, entry: AuditLogEntry):
        start = time()
        guild = entry.guild
        perpetrator = entry.user
        if not isinstance(perpetrator, Member):
            return

        config = await Settings.fetch(self.bot, guild)
        if (
            not config
            or not config.ban
            or config
            and config.ban
            and config.is_whitelisted(perpetrator)
        ):
            return

        elif not await config.check_threshold(self.bot, perpetrator, "ban"):
            return

        elapsed = time() - start
        try:
            await guild.ban(
                perpetrator,
                reason=(
                    "User exceeded the antinuke ban threshold "
                    f"({plural(config.ban.threshold):ban} in {naturaldelta(config.ban.duration)})"
                ),
            )
        except HTTPException as exc:
            return await config.dispatch_log(
                self.bot,
                perpetrator,
                module="ban",
                elapsed=elapsed,
                failure=True,
                details=exc.text,
            )

        await config.dispatch_log(
            self.bot,
            perpetrator,
            module="ban",
            elapsed=elapsed,
        )

    @Cog.listener("on_audit_log_entry_kick")
    async def antinuke_monitor_kick(self, entry: AuditLogEntry):
        start = time()
        guild = entry.guild
        perpetrator = entry.user
        if not isinstance(perpetrator, Member):
            return

        config = await Settings.fetch(self.bot, guild)
        if (
            not config
            or not config.kick
            or config
            and config.kick
            and config.is_whitelisted(perpetrator)
        ):
            return

        elif not await config.check_threshold(self.bot, perpetrator, "kick"):
            return

        elapsed = time() - start
        try:
            await guild.ban(
                perpetrator,
                reason=(
                    "User exceeded the antinuke kick threshold "
                    f"({plural(config.kick.threshold):kick} in {naturaldelta(config.kick.duration)})"
                ),
            )
        except HTTPException as exc:
            return await config.dispatch_log(
                self.bot,
                perpetrator,
                module="kick",
                elapsed=elapsed,
                failure=True,
                details=exc.text,
            )

        await config.dispatch_log(
            self.bot,
            perpetrator,
            module="kick",
            elapsed=elapsed,
        )

    @Cog.listener("on_audit_log_entry_role_create")
    @Cog.listener("on_audit_log_entry_role_delete")
    @Cog.listener("on_audit_log_entry_role_update")
    async def antinuke_monitor_role(self, entry: AuditLogEntry):
        start = time()
        guild = entry.guild
        perpetrator = entry.user
        if not isinstance(perpetrator, Member):
            return

        config = await Settings.fetch(self.bot, guild)
        if (
            not config
            or not config.role
            or config
            and config.role
            and config.is_whitelisted(perpetrator)
        ):
            return

        elif not await config.check_threshold(self.bot, perpetrator, "role"):
            return

        elapsed = time() - start
        verb = (
            ("created", "creation")
            if entry.action == "role_create"
            else (
                ("deleted", "deletion")
                if entry.action == "role_delete"
                else ("updated", "modification")
            )
        )
        try:
            await guild.ban(
                perpetrator,
                reason=(
                    "User exceeded the antinuke role threshold "
                    f"({plural(config.role.threshold):role} {verb[0]} in {naturaldelta(config.role.duration)})"
                ),
            )
        except HTTPException as exc:
            return await config.dispatch_log(
                self.bot,
                perpetrator,
                module="role",
                elapsed=elapsed,
                failure=True,
                details=exc.text,
                description=f"Role {verb[1]} attempt has been detected",
            )

        await config.dispatch_log(
            self.bot,
            perpetrator,
            module="role",
            elapsed=elapsed,
            description=f"Role {verb[1]} attempt has been detected",
        )

    @Cog.listener("on_audit_log_entry_channel_create")
    @Cog.listener("on_audit_log_entry_channel_delete")
    @Cog.listener("on_audit_log_entry_channel_update")
    async def antinuke_monitor_channel(self, entry: AuditLogEntry):
        start = time()
        guild = entry.guild
        perpetrator = entry.user
        if not isinstance(perpetrator, Member):
            return

        config = await Settings.fetch(self.bot, guild)
        if (
            not config
            or not config.channel
            or config
            and config.channel
            and config.is_whitelisted(perpetrator)
        ):
            return

        elif not await config.check_threshold(self.bot, perpetrator, "channel"):
            return

        elapsed = time() - start
        verb = (
            ("created", "creation")
            if entry.action == "channel_create"
            else (
                ("deleted", "deletion")
                if entry.action == "channel_delete"
                else ("updated", "modification")
            )
        )
        try:
            await guild.ban(
                perpetrator,
                reason=(
                    "User exceeded the antinuke channel threshold "
                    f"({plural(config.channel.threshold):channel} {verb[0]} in {naturaldelta(config.channel.duration)})"
                ),
            )
        except HTTPException as exc:
            return await config.dispatch_log(
                self.bot,
                perpetrator,
                module="channel",
                elapsed=elapsed,
                failure=True,
                details=exc.text,
                description=f"Channel {verb[1]} attempt has been detected",
            )

        await config.dispatch_log(
            self.bot,
            perpetrator,
            module="channel",
            elapsed=elapsed,
            description=f"Channel {verb[1]} attempt has been detected",
        )

    @Cog.listener("on_audit_log_entry_webhook_create")
    async def antinuke_monitor_webhook(self, entry: AuditLogEntry):
        start = time()
        guild = entry.guild
        perpetrator = entry.user
        if not isinstance(perpetrator, Member):
            return

        config = await Settings.fetch(self.bot, guild)
        if (
            not config
            or not config.webhook
            or config
            and config.webhook
            and config.is_whitelisted(perpetrator)
        ):
            return

        elif not await config.check_threshold(self.bot, perpetrator, "webhook"):
            return

        elapsed = time() - start
        try:
            await guild.ban(
                perpetrator,
                reason=(
                    "User exceeded the antinuke webhook threshold "
                    f"({plural(config.webhook.threshold):webhook} in {naturaldelta(config.webhook.duration)})"
                ),
            )
        except HTTPException as exc:
            return await config.dispatch_log(
                self.bot,
                perpetrator,
                module="webhook",
                elapsed=elapsed,
                failure=True,
                details=exc.text,
            )

        await config.dispatch_log(
            self.bot,
            perpetrator,
            module="webhook",
            elapsed=elapsed,
        )

    @Cog.listener("on_audit_log_entry_emoji_create")
    @Cog.listener("on_audit_log_entry_emoji_delete")
    @Cog.listener("on_audit_log_entry_emoji_update")
    async def antinuke_monitor_emoji(self, entry: AuditLogEntry):
        start = time()
        guild = entry.guild
        perpetrator = entry.user
        if not isinstance(perpetrator, Member):
            return

        config = await Settings.fetch(self.bot, guild)
        if (
            not config
            or not config.emoji
            or config
            and config.emoji
            and config.is_whitelisted(perpetrator)
        ):
            return

        elif not await config.check_threshold(self.bot, perpetrator, "emoji"):
            return

        elapsed = time() - start
        verb = (
            ("created", "creation")
            if entry.action == "emoji_create"
            else (
                ("deleted", "deletion")
                if entry.action == "emoji_delete"
                else ("updated", "modification")
            )
        )
        try:
            await guild.ban(
                perpetrator,
                reason=(
                    "User exceeded the antinuke emoji threshold "
                    f"({plural(config.emoji.threshold):emoji} {verb[0]} in {naturaldelta(config.emoji.duration)})"
                ),
            )
        except HTTPException as exc:
            return await config.dispatch_log(
                self.bot,
                perpetrator,
                module="emoji",
                elapsed=elapsed,
                failure=True,
                details=exc.text,
                description=f"Emoji {verb[1]} attempt has been detected",
            )

        await config.dispatch_log(
            self.bot,
            perpetrator,
            module="emoji",
            elapsed=elapsed,
            description=f"Emoji {verb[1]} attempt has been detected",
        )
