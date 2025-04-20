from __future__ import annotations

from datetime import datetime
from io import BytesIO
from typing import (
    TYPE_CHECKING,
    Any,
    List,
    Literal,
    Optional,
    Sequence,
    Type,
    cast,
    TypeVar,
)
from aiomisc import PeriodicCallback
from dataclasses import dataclass
from functools import partial

import discord
from aiohttp import ClientSession
from cashews import cache
from discord import (
    ButtonStyle,
    Colour,
    File,
    Guild,
    HTTPException,
    Member,
    Message,
    NotFound,
    TextChannel,
    Thread,
    VoiceChannel,
    SelectOption,
    Interaction,
    Forbidden,
)
from discord import Embed, Message as BaseMessage
from discord.context_managers import Typing as DefaultTyping
from discord.ext.commands import Command, HelpCommand, Group
from discord.ext.commands import Context as OriginalContext
from discord.ext.commands import Group, UserInputError, command, Cog
from discord.ext import commands
from discord.ext.commands.cog import Cog
from discord.ext.commands.flags import FlagConverter as DefaultFlagConverter
from discord.ext.commands.flags import FlagsMeta
from discord.ext.commands.help import Paginator as HelpPaginator
from discord.types.embed import EmbedType
from discord.ui import button, Select
from discord.utils import MISSING, cached_property, get
from pydantic import BaseConfig, BaseModel
from typing_extensions import Self
from xxhash import xxh32_hexdigest
from contextlib import suppress
import config
from tools import View, quietly_delete
from tools.client.database import Database, Settings
from tools.client.redis import Redis
from tools.conversion import Status
from tools.paginator import Paginator
from logging import getLogger

log = getLogger("context")

if TYPE_CHECKING:
    from main import zyn
    from types import TracebackType

BE = TypeVar("BE", bound=BaseException)


class ReskinConfig(BaseModel):
    member: Member
    username: Optional[str]
    avatar_url: Optional[str]

    @classmethod
    def key(cls, member: Member) -> str:
        return xxh32_hexdigest(f"reskin.config:{member.id}")

    @classmethod
    async def revalidate(cls, bot: zyn, member: Member) -> Optional[Self]:
        """
        Revalidate the reskin for a member.
        This will update the cache in redis.
        """

        key = cls.key(member)
        await bot.redis.delete(key)

        record = await bot.db.fetchrow(
            """
            SELECT *
            FROM reskin.config
            WHERE user_id = $1
            """,
            member.id,
        )
        if not record:
            return

        settings = cls(**record, member=member)
        await bot.redis.set(key, settings.dict(exclude={"member"}))
        return settings

    @classmethod
    async def fetch(cls, bot: zyn, member: Member) -> Optional[Self]:
        """
        Fetch the reskin for a member.
        This will cache the settings in redis.
        """

        key = cls.key(member)
        cached = cast(
            Optional[dict],
            await bot.redis.get(key),
        )
        if cached:
            return cls(**cached, member=member)

        record = await bot.db.fetchrow(
            """
            SELECT *
            FROM reskin.config
            WHERE user_id = $1
            """,
            member.id,
        )
        if not record:
            return

        settings = cls(**record, member=member)
        await bot.redis.set(key, settings.dict(exclude={"member"}))
        return settings

    class Config(BaseConfig):
        arbitrary_types_allowed = True


class Interaction(Interaction):
    async def warn(self, content: str) -> WebhookMessage:
        embed = Embed(
            description=f"{config.EMOJIS.CONFIG.WARN} {self.user.mention}: {content}",
            color=config.CLIENT.COLORS.WARN,
        )
        await self.response.send_message(embed=embed, ephemeral=True)

    async def approve(self, content: str) -> WebhookMessage:
        embed = Embed(
            description=f"{config.EMOJIS.CONFIG.APPROVE} {self.user.mention}: {content}",
            color=config.CLIENT.COLORS.APPROVE,
        )
        await self.response.send_message(embed=embed, ephemeral=True)

    async def deny(self, content: str) -> WebhookMessage:
        embed = Embed(
            description=f"{config.EMOJIS.CONFIG.DENY} {self.user.mention}: {content}",
            color=config.CLIENT.COLORS.WARN,
        )
        await self.response.send_message(embed=embed, ephemeral=True)


class Confirmation(View):
    value: Optional[bool]

    def __init__(self, ctx: Context, *, timeout: Optional[int] = 60):
        super().__init__(timeout=timeout)
        self.ctx = ctx
        self.value = None

    @button(label="Approve", style=ButtonStyle.green)
    async def approve(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ):
        self.value = True
        self.stop()

    @button(label="Decline", style=ButtonStyle.danger)
    async def decline(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ):
        self.value = False
        self.stop()


class Typing(DefaultTyping):
    ctx: Context

    def __init__(self, ctx: Context):
        super().__init__(ctx.channel)
        self.ctx = ctx

    async def do_typing(self) -> None:
        if self.ctx.settings.reskin:
            return

        return await super().do_typing()


class Loading:
    callback: Optional[PeriodicCallback]
    ctx: Context
    channel: VoiceChannel | TextChannel | Thread

    def __init__(self, ctx: Context) -> None:
        self.ctx = ctx
        self.channel = ctx.channel
        self.callback = None

    @property
    def redis(self) -> Redis:
        return self.ctx.bot.redis

    @property
    def key(self) -> str:
        return xxh32_hexdigest(f"loader:{self.channel.id}")

    async def locked(self) -> bool:
        if await self.redis.exists(self.key):
            return True

        await self.redis.set(self.key, 1, ex=30)
        return False

    async def task(self) -> None:
        if not self.ctx.response:
            return

        value = self.ctx.response.embeds[0].description  # type: ignore
        if not value:
            return

        value = value.replace(">>> ", "")
        if not value.endswith("..."):
            value += "."
        else:
            value = value.rstrip(".")

        await self.ctx.neutral(value, patch=self.ctx.response)

    async def __aenter__(self) -> None:
        if await self.locked():
            return

        self.callback = PeriodicCallback(self.task)
        self.callback.start(10, delay=2)

    async def __aexit__(
        self,
        exc_type: Optional[Type[BE]],
        exc: Optional[BE],
        traceback: Optional[TracebackType],
    ) -> None:
        await self.redis.delete(self.key)
        if self.callback:
            self.callback.stop()


class Context(OriginalContext):
    bot: "zyn"
    guild: Guild
    author: Member
    channel: VoiceChannel | TextChannel | Thread
    command: Command[Any, ..., Any]
    settings: Settings
    response: Optional[Message] = None

    @property
    def session(self) -> ClientSession:
        return self.bot.session

    @property
    def db(self) -> Database:
        return self.bot.database

    @cached_property
    def replied_message(self) -> Optional[Message]:
        reference = self.message.reference
        if reference and isinstance(reference.resolved, Message):
            return reference.resolved

        return None

    @property
    def color(self) -> Colour:
        return Colour(config.CLIENT.COLORS.NEUTRAL)

    def typing(self) -> Typing:
        return Typing(self)

    def loading(self, *args: str, **kwargs) -> Loading:
        if args:
            self.bot.loop.create_task(self.neutral(*args))

        return Loading(self)

    async def add_check(self) -> None:
        with suppress(NotFound):
            return await self.message.add_reaction("✅")

    async def send(self, *args, **kwargs) -> Message:
        if kwargs.pop("no_reference", False):
            reference = None
        else:
            reference = kwargs.pop("reference", self.message)

        patch = kwargs.pop("patch", None)

        embed = kwargs.get("embed")
        if embed and not embed.color:
            embed.color = self.color

        if args:
            kwargs["content"] = args[0]
            args = ()

        if kwargs.get("content") and len(str(kwargs["content"])) > 2000:
            kwargs["file"] = File(
                BytesIO(str(kwargs["content"]).encode("utf-8")),
                filename="message.txt",
            )
            kwargs["content"] = None

        if file := kwargs.pop("file", None):
            kwargs["files"] = [file]

        if kwargs.get("view") is None:
            kwargs.pop("view", None)

        if self.settings.reskin:
            reskin = await ReskinConfig.fetch(self.bot, self.author)
            if reskin:
                webhook = await self.reskin_webhook()
                if webhook:
                    delete_after = kwargs.pop("delete_after", None)
                    for item in ("stickers", "reference"):
                        kwargs.pop(item, None)

                    try:
                        if patch:
                            self.response = await webhook.edit_message(
                                message_id=patch.id,
                                **kwargs,
                            )
                        else:
                            kwargs["username"] = reskin.username
                            kwargs["avatar_url"] = reskin.avatar_url
                            kwargs["wait"] = True
                            self.response = await webhook.send(*args, **kwargs)

                        if delete_after:
                            await self.response.delete(delay=delete_after)

                        return self.response

                    except NotFound:
                        await self.bot.db.execute(
                            """
                            DELETE FROM reskin.webhook
                            WHERE guild_id = $1
                            AND channel_id = $2
                            """,
                            self.guild.id,
                            self.channel.id,
                        )
                        await cache.delete(
                            f"reskin:webhook:{self.guild.id}:{self.channel.id}"
                        )

        if patch:
            self.response = await patch.edit(**kwargs)
        else:
            if reference:
                kwargs["reference"] = reference

            try:

                if isinstance(self.channel, Thread):
                    self.response = await self.channel.send(*args, **kwargs)
                else:
                    self.response = await super().send(*args, **kwargs)
            except Forbidden:
                log.error(
                    f"Bot does not have permission to send messages in {self.channel}."
                )
            except HTTPException as e:
                log.error(f"HTTPException encountered: {e}")
                kwargs.pop("reference", None)
                with suppress(NotFound):
                    self.response = await super().send(*args, **kwargs)

        return self.response

    async def reply(self, *args, **kwargs) -> Message:
        with suppress(NotFound):
            return await self.send(*args, **kwargs)

    async def neutral(
        self,
        *args: str,
        **kwargs,
    ) -> Message:
        """
        Send an approve embed.
        """

        description = "\n".join(str(arg) for arg in args)
        embed = Embed(
            description=description,
            color=kwargs.pop("color", config.CLIENT.COLORS.NEUTRAL),
        )
        with suppress(NotFound):
            return await self.send(embed=embed, **kwargs)

    async def approve(
        self,
        *args: str,
        **kwargs,
    ) -> Message:
        """
        Send an approve embed.
        """

        description = "\n".join(
            f"{config.EMOJIS.CONFIG.APPROVE} {str(arg)}" for arg in args
        )
        embed = Embed(
            description=description,
            color=kwargs.pop("color", config.CLIENT.COLORS.APPROVE),
        )
        with suppress(NotFound):
            return await self.send(embed=embed, **kwargs)

    async def warn(
        self,
        *args: str,
        **kwargs,
    ) -> Message:
        """
        Send an error embed.
        """

        description = "\n".join(
            f"{config.EMOJIS.CONFIG.WARN} {str(arg)}" for arg in args
        )
        embed = Embed(
            description=description,
            color=kwargs.pop("color", config.CLIENT.COLORS.WARN),
        )
        with suppress(NotFound):
            return await self.send(embed=embed, **kwargs)

    async def prompt(
        self,
        *args: str,
        timeout: int = 60,
        delete_after: bool = True,
    ) -> Literal[True]:
        """
        An interactive reaction confirmation dialog.

        Raises UserInputError if the user denies the prompt.
        """

        key = xxh32_hexdigest(f"prompt:{self.author.id}:{self.command.qualified_name}")
        async with self.bot.redis.get_lock(key):
            embed = Embed(
                description="\n".join(
                    (">>> " if len(args) == 1 or index == len(args) - 1 else "")
                    + str(arg)
                    for index, arg in enumerate(args)
                ),
            )
            view = Confirmation(self, timeout=timeout)

            try:
                message = await self.send(embed=embed, view=view)
            except HTTPException as exc:
                raise UserInputError("Failed to send prompt message!") from exc

            await view.wait()
            if delete_after:
                await quietly_delete(message)

            if view.value is True:
                return True

            raise UserInputError("Confirmation prompt wasn't approved!")

    @cache(ttl="2h", prefix="reskin:webhook", key="{self.guild.id}:{self.channel.id}")
    async def reskin_webhook(self) -> Optional[discord.Webhook]:
        if not isinstance(self.channel, TextChannel):
            return

        webhook_id = cast(
            Optional[int],
            await self.bot.db.fetchval(
                """
                SELECT webhook_id
                FROM reskin.webhook
                WHERE guild_id = $1
                AND channel_id = $2
                """,
                self.guild.id,
                self.channel.id,
            ),
        )
        if not webhook_id:
            return

        webhooks = await self.channel.webhooks()
        webhook = get(webhooks, id=webhook_id)
        if webhook:
            return webhook

        cache.invalidate(self.reskin_webhook)  # type: ignore
        await self.bot.db.execute(
            """
            DELETE FROM reskin.webhook
            WHERE guild_id = $1
            AND channel_id = $2
            """,
            self.guild.id,
            self.channel.id,
        )


class HelpView(View):
    def __init__(self, ctx, cogs):
        super().__init__()
        self.ctx = ctx
        self.cogs = cogs

        options = [
            SelectOption(label=cog.qualified_name, value=cog.qualified_name)
            for cog in cogs
        ]

        if not options:
            options.append(
                SelectOption(label="No categories available", value="no_categories")
            )

        self.select = Select(placeholder="Choose a category...", options=options)
        self.select.callback = self.select_callback
        self.add_item(self.select)

    async def select_callback(self, interaction: Interaction):
        try:
            selected_cog_name = interaction.data["values"][0]
            selected_cog = next(
                (cog for cog in self.cogs if cog.qualified_name == selected_cog_name),
                None,
            )

            if selected_cog:
                command_names = [
                    f"{cmd.name}{'*' if isinstance(cmd, commands.Group) else ''}"
                    for cmd in selected_cog.get_commands()
                ]
                description = "```" + ", ".join(command_names) + "```"
                embed = (
                    Embed(
                        title=f"Category: {selected_cog.qualified_name}",
                        description=description,
                    )
                    .set_author(
                        name=f"{self.ctx.bot.user.name.title()} Command Menu",
                        icon_url=self.ctx.bot.user.display_avatar.url,
                    )
                    .set_footer(text=f"{len(selected_cog.get_commands())} commands")
                )
                await interaction.response.edit_message(embed=embed, view=self)
            else:
                await interaction.response.send_message("Selected category not found.")
        except Exception as e:
            print(f"Error in select_callback: {e}")


class HelpCommand(HelpCommand):
    def __init__(self, **options):
        super().__init__(**options)

    async def send_bot_help(self, mapping: dict[Cog, list[Command]]):
        """Send the default command menu"""
        ctx = self.context

        cogs = [
            cog
            for cog in ctx.bot.cogs.values()
            if cog.get_commands()
            and not getattr(cog, "hidden", False)
            and cog.qualified_name not in ("Jishaku", "Owner")
        ]
        cogs = sorted(cogs, key=lambda cog: cog.qualified_name)
        cog_count = len(cogs)

        embed = (
            Embed()
            .set_author(
                name=f"{ctx.bot.user.name.title()} Command Menu",
                icon_url=ctx.bot.user.display_avatar.url,
            )
            .add_field(name="Information", value="> [] = optional, <> = required")
            .add_field(
                name="Invite",
                value=f"[**Invite**](https://discordapp.com/oauth2/authorize?client_id={ctx.bot.user.id}&scope=bot+applications.commands&permissions=8) \u2022 [**Support**](https://discord.gg/zyn) \u2022 [**View on Web**](https://zyn.bot/commands)",
                inline=False,
            )
            .set_thumbnail(url=ctx.bot.user.display_avatar.url)
            .set_footer(text=f"Select a category from the dropdown menu below")
        )

        view = HelpView(ctx, cogs)
        await ctx.send(embed=embed, view=view)

    def _add_flag_formatting(self, embed: Embed, annotation: DefaultFlagConverter):
        optional_flags: List[str] = [
            f"`--{name}{' on/off' if isinstance(flag.annotation, Status) else ''}`: {flag.description}"
            for name, flag in annotation.get_flags().items()
            if flag.default is not MISSING
        ]
        required_flags: List[str] = [
            f"`--{name}{' on/off' if isinstance(flag.annotation, Status) else ''}`: {flag.description}"
            for name, flag in annotation.get_flags().items()
            if flag.default is MISSING
        ]

        if required_flags:
            embed.add_field(
                name="Required Flags:", value="\n".join(required_flags), inline=True
            )

        if optional_flags:
            embed.add_field(
                name="Optional Flags:", value="\n".join(optional_flags), inline=True
            )

    async def send_command_help(self, command: Command):
        ctx = self.context
        cog = command.cog.qualified_name if command.cog else "No Cog"

        command_name = (
            f"{command.full_parent_name} {command.name}"
            if command.parent
            else command.name
        )

        description = (
            (command.help or "No description available.")
            + f"\n```ruby\nSyntax: {ctx.clean_prefix}{command_name} {command.signature}\nExample: {ctx.clean_prefix}{command_name} {command.brief if command.brief else ''}```"
        )

        embed = Embed(title=f"{command_name} • {cog} module", description=description)

        permissions = command.description

        embed.add_field(
            name="Permissions",
            value=permissions if permissions else "None",
            inline=True,
        )

        for param in command.clean_params.values():
            if isinstance(param.annotation, FlagsMeta):
                self._add_flag_formatting(embed, param.annotation)

        aliases = ", ".join(command.aliases) if command.aliases else "None"
        embed.set_footer(
            text=f"Aliases: {aliases} • zyn.bot",
            icon_url=(
                ctx.author.avatar.url
                if ctx.author.avatar
                else "https://none.com/nonenone"
            ),
        )

        await ctx.send(embed=embed)

    async def send_group_help(self, group: Group):
        ctx = self.context
        cog = group.cog.qualified_name if group.cog else "No Cog"

        embeds = []
        for command in sorted(group.commands, key=lambda c: c.name):
            command_name = (
                f"{command.full_parent_name} {command.name}"
                if command.parent
                else command.name
            )

            description = (
                (command.help or "No description available.")
                + f"\n```ruby\nSyntax: {ctx.clean_prefix}{command_name} {command.signature}\nExample: {ctx.clean_prefix}{command_name} {command.brief if command.brief else ''}```"
            )

            embed = Embed(
                title=f"{command_name} • {cog} module", description=description
            )

            permissions = command.description

            embed.add_field(
                name="Permissions",
                value=permissions if permissions else "None",
                inline=True,
            )

            for param in command.clean_params.values():
                if isinstance(param.annotation, FlagsMeta):
                    self._add_flag_formatting(embed, param.annotation)

            aliases = ", ".join(command.aliases) if command.aliases else "None"
            embed.set_footer(
                text=f"Aliases: {aliases} • zyn.bot",
                icon_url=ctx.author.avatar.url or "https://none.com/nonenone",
            )

            embeds.append(embed)

        paginator = Paginator(ctx, entries=embeds, embed=embeds, per_page=1)
        await paginator.start()

    async def send_pages(self) -> Message:
        embeds = [Embed(description=entry) for entry in self.paginator.pages]

        paginator = Paginator(self.context, entries=embeds, embed=embeds, per_page=1)  # type: ignore
        return await paginator.start()


class Embed(discord.Embed):
    def __init__(
        self,
        value: Optional[str] = None,
        *,
        colour: Optional[int] = None,
        color: Optional[int] = None,
        title: Optional[Any] = None,
        type: EmbedType = "rich",
        url: Optional[Any] = None,
        description: Optional[Any] = None,
        timestamp: Optional[datetime] = None,
    ):
        description = description or value
        super().__init__(
            colour=colour,
            color=color or config.CLIENT.COLORS.NEUTRAL,
            title=title,
            type=type,
            url=url,
            description=description[:4096] if description else None,
            timestamp=timestamp,
        )


discord.Embed = Embed
