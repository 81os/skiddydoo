import asyncio
from datetime import datetime
from logging import getLogger
from typing import Iterator, List, Literal, Optional

from cashews import cache
from playwright.async_api import Response
from pydantic import BaseModel, Field
from typing_extensions import Self

from tools.browser import BrowserHandler

from .user import BasicUser

log = getLogger("zyn/tiktok")


class Statistics(BaseModel):
    like_count: int = Field(alias="diggCount")
    comment_count: int = Field(alias="commentCount")
    play_count: int = Field(alias="playCount")
    share_count: int = Field(alias="shareCount")

    def __str__(self) -> str:
        return f"👀 {self.play_count:,} ❤️ {self.like_count:,}"


class Video(BaseModel):
    url: str = Field(alias="downloadAddr")
    width: int = Field(alias="width")
    height: int = Field(alias="height")
    duration: int = Field(alias="duration")


class Post(BaseModel):
    id: int
    author: BasicUser
    caption: Optional[str] = Field(alias="desc", default="..")
    created_at: datetime = Field(alias="createTime")
    statistics: Statistics = Field(alias="stats")
    video: Video

    def __str__(self) -> str:
        return self.caption or ".."

    @property
    def url(self) -> str:
        return f"{self.author.url}/video/{self.id}"


class Posts(BaseModel):
    user: Optional[BasicUser] = None
    posts: List[Post] = []

    def __str__(self) -> str:
        return str(self.user) if self.user else "TikTok Posts"

    def __len__(self) -> int:
        return len(self.posts)

    def __iter__(self) -> Iterator[Post]:
        return iter(self.posts)

    def __bool__(self) -> bool:
        return bool(self.user or self.posts)

    @classmethod
    @cache(ttl="5m")
    async def fetch(
        cls,
        browser: BrowserHandler,
        username: str,
    ) -> Optional[Self] | Literal[False]:
        """
        Fetches a user's recent posts.
        """

        res = cls()
        event = asyncio.Event()
        username = username.strip("@").lower()
        url = f"https://www.tiktok.com/@{username}"

        async def handle_resp(resp: Response):
            if event.is_set():
                return

            if "/api/post/item_list/" in resp.url:
                data = await resp.json()
                if data["statusCode"] != 0:
                    log.debug(
                        "TikTok API returned an error for @%s / %s.",
                        username,
                        data["statusCode"],
                    )
                    return

                for post in data["itemList"]:
                    if post.get("imagePost") or not post["video"].get("downloadAddr"):
                        continue

                    try:
                        res.user = BasicUser(**post["author"])
                        res.posts.append(Post(**post))
                    except Exception as exc:
                        log.warning(
                            "Failed to parse TikTok post %s: %s",
                            post["id"],
                            exc,
                        )
                        break

                event.set()

        async with browser.borrow_page() as page:
            page.on("response", handle_resp)
            await page.goto(url, wait_until="commit")
            # await asyncio.sleep(6)
            # with suppress(PlaywrightError):
            #     if username not in (await page.title()).lower():
            #         return False

            try:
                await asyncio.wait_for(event.wait(), timeout=10)
            except asyncio.TimeoutError:
                return None
            finally:
                page.remove_listener("response", handle_resp)

        return res or None
