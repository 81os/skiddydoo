import asyncio
from collections import defaultdict
from contextlib import suppress
from datetime import timedelta
from logging import getLogger
from random import uniform
from typing import Dict, List, Optional, cast

from discord import AllowedMentions, Color, Embed, HTTPException, TextChannel, Thread
from discord.utils import get, utcnow

from cogs.social.models.twitter.tweets import BasicUser, Tweet, Tweets
from main import zyn
from tools.parser import Script

from .base import BaseRecord, Feed

log = getLogger("zyn/twitter")


class Record(BaseRecord):
    twitter_id: int
    twitter_name: str
    color: Optional[str]


class Twitter(Feed):
    """
    Listener for new tweets.
    """

    def __init__(self, bot: zyn):
        super().__init__(
            bot,
            name="Twitter",
        )

    async def feed(self) -> None:
        while True:
            records = await self.get_records()
            for twitter_id, records in records.items():
                self.bot.loop.create_task(self.get_tweets(twitter_id, records))
                await asyncio.sleep(uniform(0.5, 1.5))

            if self.scheduled_deletion:
                await self.bot.db.execute(
                    """
                    DELETE FROM feeds.twitter
                    WHERE channel_id = ANY($1::BIGINT[])
                    """,
                    self.scheduled_deletion,
                )
                self.scheduled_deletion.clear()

            await asyncio.sleep(60 * 9)

    async def get_records(self) -> dict[int, List[Record]]:
        records = cast(
            List[Record],
            await self.bot.db.fetch(
                """
                SELECT *
                FROM feeds.twitter
                """,
            ),
        )

        result: Dict[int, List[Record]] = defaultdict(list)
        for record in records:
            result[record["twitter_id"]].append(record)

        return result

    async def get_tweets(self, user_id: int, records: List[Record]) -> None:
        """
        Fetch and dispatch new tweets.
        """

        data = await Tweets.fetch(user_id)
        if not data or not data.user:
            log.debug(
                "No tweets available for %s (%s).",
                records[0]["twitter_name"],
                user_id,
            )
            return

        for tweet in reversed(data.tweets[:6]):
            if utcnow() - tweet.posted_at > timedelta(hours=1):
                continue

            elif tweet.source == "Advertisement":
                continue

            if await self.redis.sismember(self.key, str(tweet.id)):
                continue

            await self.redis.sadd(self.key, str(tweet.id))
            self.bot.loop.create_task(self.dispatch(data.user, tweet, records))
            self.posted += 1

    async def dispatch(
        self,
        user: BasicUser,
        tweet: Tweet,
        records: List[Record],
    ) -> None:
        """
        Dispatch a tweet to the subscription channels.
        """

        log.debug(
            "Dispatching tweet %r from @%s (%s).", tweet.id, user.screen_name, user.id
        )

        embed = Embed(
            description=tweet.text,
            timestamp=tweet.posted_at,
        )
        embed.set_author(
            url=user.url,
            name=user.name,
            icon_url=user.avatar_url,
        )
        embed.set_footer(
            text=tweet.source,
        )
        for media in tweet.media:
            if media.type in ("photo", "animated_gif"):
                embed.set_image(url=media.url)
                break

        for record in records:
            embed.color = Color.dark_embed()
            if record["color"]:
                embed.color = (
                    Color.random()
                    if record["color"] == "random"
                    else Color(int(record["color"]))
                )

            guild = self.bot.get_guild(record["guild_id"])
            if not guild:
                self.scheduled_deletion.append(record["channel_id"])
                continue

            channel = guild.get_channel_or_thread(record["channel_id"])
            if not isinstance(channel, (TextChannel, Thread)):
                self.scheduled_deletion.append(record["channel_id"])
                continue

            elif not self.can_post(channel):
                self.scheduled_deletion.append(record["channel_id"])
                continue

            elif tweet.possibly_sensitive and not channel.is_nsfw():
                continue

            with suppress(HTTPException):
                script = Script(
                    record["template"] or "",
                    [channel.guild, channel, user, tweet],
                )

                media = get(tweet.media, type="video")
                if media:
                    file = await media.to_file()
                    if len(file.fp.read()) <= channel.guild.filesize_limit and len(
                        file.fp.read()
                    ):
                        await channel.send(
                            content=script.content,
                            embed=script.embed or embed,
                            file=file,
                            allowed_mentions=AllowedMentions.all(),
                        )
                        continue

                if script.embed:
                    for media in tweet.media:
                        if media.type in ("photo", "animated_gif"):
                            script.embed.set_image(url=media.url)
                            break

                await channel.send(
                    content=script.content,
                    embed=script.embed or embed,
                    allowed_mentions=AllowedMentions.all(),
                )
