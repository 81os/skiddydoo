import asyncio
from contextlib import suppress
from io import BytesIO
from logging import getLogger
from random import shuffle, uniform
from textwrap import shorten
from typing import List, Optional, cast

from discord import Embed, File, HTTPException, TextChannel, Thread
from discord.utils import as_chunks
from xxhash import xxh32_hexdigest

from cogs.social.models.pinterest.saved import Pin, SavedPins
from main import zyn
from tools.formatter import plural

from .base import BaseRecord, Feed

log = getLogger("zyn/pinterest")


class Record(BaseRecord):
    pinterest_id: str
    pinterest_name: str
    board: Optional[str]
    board_id: Optional[str]
    embeds: bool
    only_new: bool


class Pinterest(Feed):
    """
    Listener for new saved pins.
    """

    def __init__(self, bot: zyn):
        super().__init__(
            bot,
            name="Pinterest",
        )

    async def feed(self) -> None:
        while True:
            records = cast(
                List[Record],
                await self.bot.db.fetch(
                    """
                    SELECT *
                    FROM feeds.pinterest
                    """
                ),
            )
            for record in records:
                self.bot.loop.create_task(self.get_pins(record))
                await asyncio.sleep(uniform(1, 3.5))

            if self.scheduled_deletion:
                await self.bot.db.execute(
                    """
                    DELETE FROM feeds.pinterest
                    WHERE channel_id = ANY($1::BIGINT[])
                    """,
                    self.scheduled_deletion,
                )
                self.scheduled_deletion.clear()

            await asyncio.sleep(60 * 2)

    async def get_pins(self, record: Record) -> None:
        """
        Fetches new pins for a user.
        """

        username, user_id = record["pinterest_name"], record["pinterest_id"]
        book_key = xxh32_hexdigest(f"bookmark_{user_id}:{record['channel_id']}")
        sent_key = xxh32_hexdigest(
            f"{self.key}_{user_id}{record['board_id'] or ''}:{record['channel_id']}"
        )

        bookmark = cast(Optional[str], await self.bot.redis.get(book_key))
        data = await SavedPins.fetch(
            self.bot.session,
            record["pinterest_name"],
            record["board_id"],
            bookmark,
        )
        if not data or not data.pins:
            if bookmark:
                if not record["only_new"]:
                    await self.bot.redis.delete(sent_key)

                await self.bot.redis.delete(book_key)

            log.debug(
                "No saved pins available for @%s (%s).",
                username,
                user_id,
            )
            return

        sent_pins = await self.bot.redis.smembers(sent_key)
        pins = [pin for pin in data.pins if pin.id not in sent_pins]
        if not pins:
            if not data.bookmark:
                log.debug(
                    "We posted all pins for @%s (%s). Resetting the bookmark.",
                    username,
                    user_id,
                )
                if not record["only_new"]:
                    await self.bot.redis.delete(sent_key)

                await self.bot.redis.delete(book_key)

            elif not record["only_new"]:
                log.debug(
                    "We posted all pins for @%s (%s). Setting bookmark to %s...",
                    username,
                    user_id,
                    data.bookmark[:12],
                )
                await self.bot.redis.set(book_key, data.bookmark)

            else:
                log.debug(
                    "No new pins are available for @%s (%s).",
                    username,
                    user_id,
                )
            return

        shuffle(pins)
        for chunk in as_chunks(pins[:15], 3):
            await self.dispatch(sent_key, record, chunk)
            await asyncio.sleep(uniform(1, 2.5))

    async def dispatch(self, sent_key: str, record: Record, pins: List[Pin]) -> None:
        """
        Dispatch chunks of pins to the subscription channel.
        """

        guild = self.bot.get_guild(record["guild_id"])
        if not guild:
            self.scheduled_deletion.append(record["channel_id"])
            return

        channel = guild.get_channel_or_thread(record["channel_id"])
        if (
            not isinstance(channel, (TextChannel, Thread))
            or isinstance(channel, (TextChannel, Thread))
            and not self.can_post(channel)
        ):
            self.scheduled_deletion.append(record["channel_id"])
            return

        log.debug(
            "Dispatching %s from %s to %s/%s (%s).",
            format(plural(pins), "pin"),
            pins[0].pinner.full_name,
            channel.name,
            guild.name,
            guild.id,
        )
        if record["embeds"]:
            for pin in pins:
                embed = Embed(
                    url=pin.url,
                    color=pin.color,
                    title=shorten(pin.title or "", width=256),
                )
                embed.set_author(
                    url=pin.pinner.url,
                    name=pin.pinner.full_name or pin.pinner.username,
                    icon_url=pin.pinner.avatar_url,
                )
                embed.set_footer(
                    text="Pinterest",
                )
                embed.set_image(url=pin.image_url)

                with suppress(HTTPException):
                    await channel.send(embed=embed)

                await asyncio.sleep(uniform(1, 2.5))
        else:
            files: List[File] = []
            for pin in pins:
                response = await self.bot.session.get(pin.image_url)
                buffer = await response.read()
                files.append(
                    File(
                        BytesIO(buffer),
                        filename=f"{xxh32_hexdigest(pin.id)}.jpg",
                    )
                )

            with suppress(HTTPException):
                for chunk in as_chunks(files, 3):
                    await channel.send(files=chunk)

        self.posted += len(pins)
        await self.bot.redis.sadd(sent_key, *[pin.id for pin in pins])
