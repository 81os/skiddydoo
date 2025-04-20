import asyncio
import math
from contextlib import suppress
from datetime import datetime
from html import unescape
from io import BytesIO
from json import dumps
from logging import getLogger
from typing import List, Literal, Optional

from cashews import cache
from discord import File
from humanfriendly import format_timespan
from pydantic import BaseModel, Field
from typing_extensions import Self

from cogs.social.models.twitter import API, ClientSession

from .user import BasicUser

ENDPOINT = API["graphql"]["UserTweets"]

log = getLogger("zyn/twitter")


class Media(BaseModel):
    url: str
    short_url: str
    type: Literal["photo", "video", "animated_gif"]

    @property
    def name(self) -> str:
        return self.url.split("/")[-1].split("?")[0]

    async def to_file(self) -> File:
        async with ClientSession() as session:
            async with session.request("GET", self.url) as resp:
                buffer = await resp.read()
                return File(BytesIO(buffer), filename=self.name)


class Tweet(BaseModel):
    id: int = Field(alias="id_str")
    url: str
    full_text: Optional[str]
    media: List[Media] = []
    possibly_sensitive: Optional[bool] = False
    posted_at: datetime
    source_html: str = Field(alias="source")

    def __str__(self) -> str:
        return self.text

    @property
    def text(self) -> str:
        text = self.full_text or ""
        for media in self.media:
            text = text.replace(media.short_url, "")

        for _ in ("ampt;", "amp;"):
            text = text.replace(_, "")

        return unescape(text.strip())

    @property
    def source(self) -> str:
        return (
            self.source_html.split(">")[1]
            .split("<")[0]
            .replace("advertiser-interface", "Advertisement")
        )


class RateLimit(BaseModel):
    limit: int = Field(
        description="The total number of requests allowed in the current rate limit window."
    )
    remaining: int = Field(
        description="The number of requests remaining in the current rate limit window."
    )
    reset: int = Field(
        description="The timestamp when the rate limit resets. Usually ~15 minutes."
    )

    @property
    def reset_at(self) -> datetime:
        return datetime.fromtimestamp(self.reset)

    async def wait(self) -> None:
        """
        Even if we aren't rate limited, we want to wait a bit.
        We determine how long to wait based on the remaining limit and the reset time.
        """

        if self.reset_at < datetime.now():
            return

        if self.remaining <= 1:
            await asyncio.sleep((self.reset_at - datetime.now()).total_seconds())
        else:
            await asyncio.sleep(
                math.ceil(
                    (self.reset_at - datetime.now()).total_seconds() / self.remaining
                )
            )


class Tweets(BaseModel):
    user: Optional[BasicUser] = None
    tweets: List[Tweet] = []
    ratelimit: RateLimit

    @classmethod
    @cache(ttl="5m")
    async def fetch(cls, user_id: int) -> Optional[Self]:
        async with ClientSession() as session:
            async with session.request(
                ENDPOINT["method"],
                ENDPOINT["url"],
                params={
                    "variables": dumps(
                        {
                            "userId": str(user_id),
                            "count": 6,
                            "includePromotedContent": True,
                            "withQuickPromoteEligibilityTweetFields": True,
                            "withSuperFollowsUserFields": True,
                            "withDownvotePerspective": False,
                            "withReactionsMetadata": False,
                            "withReactionsPerspective": False,
                            "withSuperFollowsTweetFields": True,
                            "withVoice": True,
                            "withV2Timeline": True,
                        }
                    ),
                    "features": dumps(ENDPOINT["features"]),
                },
            ) as resp:
                ratelimit = RateLimit(
                    limit=int(resp.headers["x-rate-limit-limit"]),
                    remaining=int(resp.headers["x-rate-limit-remaining"]),
                    reset=int(resp.headers["x-rate-limit-reset"]),
                )

                if not resp.ok:
                    if resp.status == 429:
                        log.debug(
                            "We've been rate limited by Twitter, retrying in %s..",
                            format_timespan(ratelimit.reset_at - datetime.now()),
                        )
                        await ratelimit.wait()
                        return await cls.fetch(user_id)

                    return None

                if ratelimit.remaining <= 10:
                    log.debug(
                        "We're running low on requests, we have %s in the next %s remaining.",
                        ratelimit.remaining,
                        format_timespan(ratelimit.reset_at - datetime.now()),
                    )

                data = await resp.json()
                if "result" not in data["data"]["user"]:
                    return None

                data = data["data"]["user"]["result"]["timeline_v2"]["timeline"][
                    "instructions"
                ]

                r = cls(ratelimit=ratelimit)
                for instructions in data:
                    with suppress(KeyError):
                        for entry in instructions["entries"]:
                            if "itemContent" in entry["content"]:
                                tweet = entry["content"]["itemContent"][
                                    "tweet_results"
                                ]["result"]
                                user = entry["content"]["itemContent"]["tweet_results"][
                                    "result"
                                ]["core"]["user_results"]["result"]

                                if int(user["rest_id"]) == user_id:
                                    r.user = BasicUser(
                                        **user["legacy"], id=user["rest_id"]
                                    )

                                r.tweets.append(
                                    Tweet(
                                        **tweet["legacy"],
                                        media=[
                                            Media(
                                                type=media["type"],
                                                short_url=media["url"],
                                                url=(
                                                    media["media_url_https"]
                                                    if not media.get("video_info")
                                                    else media["video_info"][
                                                        "variants"
                                                    ][0]["url"]
                                                ),
                                            )
                                            for media in tweet["legacy"]
                                            .get("extended_entities", {})
                                            .get("media", [])
                                        ],
                                        source=tweet["source"],
                                        url=f"https://twitter.com/{user['legacy']['screen_name']}/status/{tweet['legacy']['id_str']}",
                                        posted_at=datetime.strptime(
                                            tweet["legacy"]["created_at"],
                                            "%a %b %d %H:%M:%S %z %Y",
                                        ),
                                    ),
                                )

                return r
