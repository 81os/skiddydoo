import asyncio
from collections import defaultdict
from contextlib import suppress
from datetime import timedelta
from io import BytesIO
from logging import getLogger
from random import uniform
from secrets import token_urlsafe
from textwrap import shorten
from typing import Dict, List, cast

from discord import AllowedMentions, Embed, File, HTTPException, TextChannel, Thread
from discord.utils import utcnow

from cogs.social.models.tiktok.posts import BasicUser, Post, Posts
from cogs.social.reposters.tiktok import TikTok as TikTokReposter
from main import zyn
from tools.parser import Script

from .base import BaseRecord, Feed

log = getLogger("zyn/tiktok")


class Record(BaseRecord):
    tiktok_id: int
    tiktok_name: str


class TikTok(Feed):
    """
    Listener for new posts.
    """

    reposter: TikTokReposter

    def __init__(self, bot: zyn):
        super().__init__(
            bot,
            name="TikTok",
        )
        self.reposter = TikTokReposter(bot, add_listener=False)

    async def feed(self) -> None:
        while True:
            records = await self.get_records()
            for username, records in records.items():
                self.bot.loop.create_task(self.get_posts(username, records))
                await asyncio.sleep(uniform(4, 9))

            if self.scheduled_deletion:
                await self.bot.db.execute(
                    """
                    DELETE FROM feeds.tiktok
                    WHERE channel_id = ANY($1::BIGINT[])
                    """,
                    self.scheduled_deletion,
                )
                self.scheduled_deletion.clear()

            await asyncio.sleep(60 * 10)

    async def get_records(self) -> dict[str, List[Record]]:
        records = cast(
            List[Record],
            await self.bot.db.fetch(
                """
                SELECT *
                FROM feeds.tiktok
                """,
            ),
        )

        result: Dict[str, List[Record]] = defaultdict(list)
        for record in records:
            result[record["tiktok_name"]].append(record)

        return result

    async def get_posts(self, username: str, records: List[Record]) -> None:
        """
        Fetch and dispatch new posts.
        """

        data = await Posts.fetch(self.bot.browser, username)
        if data is False:
            # await self.bot.db.execute(
            #     """
            #     DELETE FROM feeds.tiktok
            #     WHERE tiktok_name = $1
            #     """,
            #     username,
            # )
            log.warning("No TikTok user found for %s.", username)
            return

        if not data or not data.user:
            log.debug(
                "No posts available for @%s (%s).",
                username,
                records[0]["tiktok_id"],
            )
            return

        for post in reversed(data.posts[:3]):
            if utcnow() - post.created_at > timedelta(hours=1):
                continue

            if await self.redis.sismember(self.key, str(post.id)):
                continue

            await self.redis.sadd(self.key, str(post.id))
            self.bot.loop.create_task(self.dispatch(data.user, post, records))
            self.posted += 1

    async def dispatch(
        self,
        user: BasicUser,
        post: Post,
        records: List[Record],
    ) -> None:
        """
        Dispatch a post to the subscription channels.
        """

        log.debug("Dispatching post %r from @%s (%s).", post.id, user.username, user.id)

        embed = Embed(
            url=post.url,
            title=shorten(post.caption or "", width=256),
            timestamp=post.created_at,
        )
        embed.set_author(
            name=user.full_name or user.username,
            icon_url=user.avatar_url,
            url=user.url,
        )

        data = await self.reposter.fetch(post.url)
        if not data or not data.url:
            log.warning(
                "No data found for post %r from @%s (%s).",
                post.id,
                user.username,
                user.id,
            )
            return

        response = await self.bot.session.get(data.url)
        if not response.ok:
            return

        buffer = await response.read()
        for record in records:
            guild = self.bot.get_guild(record["guild_id"])
            if not guild:
                self.scheduled_deletion.append(record["channel_id"])
                continue

            channel = guild.get_channel_or_thread(record["channel_id"])
            if (
                not isinstance(channel, (TextChannel, Thread))
                or isinstance(channel, (TextChannel, Thread))
                and not self.can_post(channel)
            ):
                self.scheduled_deletion.append(record["channel_id"])
                continue

            with suppress(HTTPException):
                if len(buffer) >= channel.guild.filesize_limit:
                    continue

                file = File(
                    BytesIO(buffer),
                    filename=f"Zyn{self.name}{token_urlsafe(6)}.mp4",
                )

                script = Script(
                    record["template"] or "",
                    [channel.guild, channel, user, post],
                )
                await channel.send(
                    content=script.content,
                    embed=script.embed or embed,
                    file=file,
                    allowed_mentions=AllowedMentions.all(),
                )

            await asyncio.sleep(uniform(1, 3.5))
