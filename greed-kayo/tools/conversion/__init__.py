from __future__ import annotations

import re
from datetime import timedelta
from typing import TYPE_CHECKING, Dict, List, Literal, Optional, Callable, Type

from aiohttp import ClientSession
from discord import Asset, Forbidden, HTTPException, Member, Message, NotFound, User
from discord.ext.commands import (
    BadArgument,
    CommandError,
    Converter,
    MemberConverter,
    MemberNotFound,
    UserConverter,
    UserNotFound,
    check,
)
from yarl import URL

import config

from .discord import StrictRole, TouchableMember, TicketChecks

if TYPE_CHECKING:
    from tools.client import Context

MEDIA_URL_PATTERN = re.compile(
    r"(?:http\:|https\:)?\/\/.*\.(?P<mime>png|jpg|jpeg|webp|gif|mp4|mp3|mov|wav|ogg|zip)"
)
DURATION_PATTERN = r"\s?".join(
    [
        r"((?P<years>\d+?)\s?(years?|y))?",
        r"((?P<months>\d+?)\s?(months?|mo))?",
        r"((?P<weeks>\d+?)\s?(weeks?|w))?",
        r"((?P<days>\d+?)\s?(days?|d))?",
        r"((?P<hours>\d+?)\s?(hours?|hrs|hr?))?",
        r"((?P<minutes>\d+?)\s?(minutes?|mins?|m(?!o)))?",
        r"((?P<seconds>\d+?)\s?(seconds?|secs?|s))?",
    ]
)


class Status(Converter[bool]):
    async def convert(self, ctx: Context, argument: str) -> bool:
        return argument.lower() in {"enable", "yes", "on", "true"}


class StrictUser(UserConverter):
    async def convert(self, ctx: Context, argument: str) -> User:
        if ctx.command.name.startswith("purge"):
            pattern = r"<@!?\d+>$"
        else:
            pattern = r"\d+$|<@!?\d+>$"

        if re.match(pattern, argument):
            return await super().convert(ctx, argument)

        raise UserNotFound(argument)


class StrictMember(MemberConverter):
    async def convert(self, ctx: Context, argument: str) -> Member:
        if ctx.command.name.startswith("purge"):
            pattern = r"<@!?\d+>$"
        else:
            pattern = r"\d+$|<@!?\d+>$"

        if re.match(pattern, argument):
            return await super().convert(ctx, argument)

        raise MemberNotFound(argument)


class Duration(Converter[timedelta]):
    def __init__(
        self: "Duration",
        min: Optional[timedelta] = None,
        max: Optional[timedelta] = None,
        units: Optional[List[str]] = None,
    ):
        self.min = min
        self.max = max
        self.units = units or [
            "weeks",
            "days",
            "hours",
            "minutes",
            "seconds",
        ]

    async def convert(self: "Duration", ctx: Context, argument: str) -> timedelta:
        if not (matches := re.fullmatch(DURATION_PATTERN, argument, re.IGNORECASE)):
            raise CommandError("The duration provided didn't pass validation!")

        units: Dict[str, int] = {
            unit: int(amount) for unit, amount in matches.groupdict().items() if amount
        }
        for unit in units:
            if unit not in self.units:
                raise CommandError(f"The unit `{unit}` is not valid for this command!")

        try:
            duration = timedelta(**units)
        except OverflowError as exc:
            raise CommandError("The duration provided is too long!") from exc

        if self.min and duration < self.min:
            raise CommandError("The duration provided is too short!")

        if self.max and duration > self.max:
            raise CommandError("The duration provided is too long!")

        return duration


class PartialAttachment:
    url: str
    buffer: bytes
    filename: str
    content_type: Optional[str]

    def __init__(
        self,
        url: URL | Asset | str,
        buffer: bytes,
        filename: Optional[str] = None,
        content_type: Optional[str] = None,
    ):
        self.url = str(url)
        self.buffer = buffer
        self.extension = content_type.split("/")[-1] if content_type else "bin"
        self.filename = filename or f"unknown.{self.extension}"
        self.content_type = content_type

    def __str__(self) -> str:
        return self.filename

    def is_image(self) -> bool:
        return self.content_type.startswith("image") if self.content_type else False

    def is_video(self) -> bool:
        return self.content_type.startswith("video") if self.content_type else False

    def is_audio(self) -> bool:
        return self.content_type.startswith("audio") if self.content_type else False

    def is_gif(self) -> bool:
        return self.content_type == "image/gif" if self.content_type else False

    def is_archive(self) -> bool:
        return (
            self.content_type.startswith("application") if self.content_type else False
        )

    @staticmethod
    async def read(url: URL | str) -> tuple[bytes, str]:
        async with ClientSession() as client:
            async with client.get(url, proxy=config.WARP) as resp:
                if resp.content_length and resp.content_length > 50 * 1024 * 1024:
                    raise CommandError("Attachment exceeds the decompression limit!")

                elif resp.status == 200:
                    buffer = await resp.read()
                    return (buffer, resp.content_type)

                elif resp.status == 404:
                    raise NotFound(resp, "asset not found")

                elif resp.status == 403:
                    raise Forbidden(resp, "cannot retrieve asset")

                else:
                    raise HTTPException(resp, "failed to get asset")

    @classmethod
    def get_attachment(cls, message: Message) -> Optional[str]:
        if message.attachments:
            return message.attachments[0].url

        elif message.stickers:
            return message.stickers[0].url

        elif message.embeds:
            if message.embeds[0].image:
                return message.embeds[0].image.url

            elif message.embeds[0].thumbnail:
                return message.embeds[0].thumbnail.url

    @classmethod
    async def convert(cls, ctx: Context, argument: str) -> "PartialAttachment":
        try:
            member = await MemberConverter().convert(ctx, argument)
        except CommandError:
            pass
        else:
            buffer, content_type = await cls.read(member.display_avatar.url)
            return cls(member.display_avatar, buffer, None, content_type)

        if not MEDIA_URL_PATTERN.match(argument):
            raise BadArgument("The provided **URL** couldn't be validated!")

        url = argument
        buffer, content_type = await cls.read(url)
        return cls(url, buffer, None, content_type)

    @classmethod
    async def fallback(cls, ctx: Context) -> "PartialAttachment":
        attachment_url: Optional[str] = None

        if ctx.replied_message:
            attachment_url = cls.get_attachment(ctx.replied_message)

        else:
            async for message in ctx.channel.history():
                attachment_url = cls.get_attachment(message)
                if attachment_url:
                    break

        if not attachment_url:
            raise BadArgument("You must provide an attachment!")

        buffer, content_type = await cls.read(attachment_url)
        return cls(
            attachment_url,
            buffer,
            f"{ctx.author.id}.{attachment_url.split('.')[-1].split('?')[0]}",
            content_type,
        )


class Timezone(Converter[str]):
    async def convert(self, ctx: Context, argument: str) -> str:
        response = await ctx.bot.session.get(
            URL.build(
                scheme="https",
                host="api.weatherapi.com",
                path="/v1/timezone.json",
                query={
                    "q": argument.lower(),
                    "key": config.AUTHORIZATION.WEATHER,
                },
            ),
        )
        if not response.ok:
            raise CommandError(f"Timezone not found for **{argument}**!")

        data = await response.json()
        return data["location"]["tz_id"]


class Timeframe:
    period: Literal["overall", "7day", "1month", "3month", "6month", "12month"]

    def __init__(
        self,
        period: Literal["overall", "7day", "1month", "3month", "6month", "12month"],
    ):
        self.period = period

    def __str__(self) -> str:
        if self.period == "7day":
            return "weekly"

        elif self.period == "1month":
            return "monthly"

        elif self.period == "3month":
            return "past 3 months"

        elif self.period == "6month":
            return "past 6 months"

        elif self.period == "12month":
            return "yearly"

        return "overall"

    @property
    def current(self) -> str:
        if self.period == "7day":
            return "week"

        elif self.period == "1month":
            return "month"

        elif self.period == "3month":
            return "3 months"

        elif self.period == "6month":
            return "6 months"

        elif self.period == "12month":
            return "year"

        return "overall"

    @classmethod
    async def convert(cls, ctx: Context, argument: str) -> "Timeframe":
        if argument in {"weekly", "week", "1week", "7days", "7day", "7ds", "7d"}:
            return cls("7day")

        elif argument in {
            "monthly",
            "month",
            "1month",
            "1m",
            "30days",
            "30day",
            "30ds",
            "30d",
        }:
            return cls("1month")

        elif argument in {
            "3months",
            "3month",
            "3ms",
            "3m",
            "90days",
            "90day",
            "90ds",
            "90d",
        }:
            return cls("3month")

        elif argument in {
            "halfyear",
            "6months",
            "6month",
            "6mo",
            "6ms",
            "6m",
            "180days",
            "180day",
            "180ds",
            "180d",
        }:
            return cls("6month")

        elif argument in {
            "yearly",
            "year",
            "yr",
            "1year",
            "1y",
            "12months",
            "12month",
            "12mo",
            "12ms",
            "12m",
            "365days",
            "365day",
            "365ds",
            "365d",
        }:
            return cls("12month")

        return cls("overall")


def get_ticket() -> Callable[[Context], Type[check]]:
    return check(TicketChecks.is_ticket_channel)


def manage_ticket() -> Callable[[Context], Type[check]]:
    return check(TicketChecks.has_manage_ticket_permission)


def ticket_exists() -> Callable[[Context], Type[check]]:
    return check(TicketChecks.ensure_ticket_exists)


__all__ = (
    "Status",
    "Duration",
    "Timezone",
    "StrictUser",
    "StrictMember",
    "PartialAttachment",
    "TouchableMember",
    "StrictRole",
    "Timeframe",
)
