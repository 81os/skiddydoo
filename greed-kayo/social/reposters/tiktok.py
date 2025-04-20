from datetime import datetime
from io import BytesIO
from secrets import token_urlsafe
from textwrap import shorten
from typing import List, Optional

from discord import Embed, File, Message
from pydantic import BaseModel
from yarl import URL
from json import loads

from cogs.social.reposters.base import Reposter
from main import zyn
from tools.client import Context
from tools.paginator import Paginator


class Uploader(BaseModel):
    id: int
    username: str
    nickname: str
    avatar_url: str

    @property
    def url(self) -> str:
        return f"https://tiktok.com/@{self.username}"

    def __str__(self) -> str:
        return self.nickname


class Information(BaseModel):
    id: str
    title: Optional[str]
    uploader: Uploader
    created_at: datetime
    view_count: int
    like_count: int
    comment_count: int
    url: Optional[str]
    images: List[str] = []

    @property
    def webpage_url(self) -> str:
        return f"https://tiktok.com/@{self.uploader.username}/video/{self.id}"


class TikTok(Reposter):
    def __init__(self, bot: zyn, **kwargs):
        super().__init__(
            bot,
            **kwargs,
            name="TikTok",
            regex=[
                r"\<?((?:https?://(?:vt|vm|www)\.tiktok\.com/(?:t/)?[a-zA-Z\d]+\/?|"
                r"https?://(?:www\.)?tiktok\.com/[@\w.]+/(?:video|photo)/\d+))(?:\/\?.*\>?)?\>?"
            ],
        )

    async def fetch(self, url: str | URL) -> Optional[Information]:
        """
        TikTok got rid of the old API, so now we have to scrape :3
        """

        if not isinstance(url, URL):
            url = URL(url)

        if not url.path.startswith("/@"):
            response = await self.bot.session.get(url, allow_redirects=True)
            url = response.url
            if not url.path.startswith("/@"):
                return None

        if len(url.parts) < 4:
            return None

        aweme_id = url.parts[3]
        async with self.bot.session.get(
            f"https://www.tiktok.com/@i/video/{aweme_id}",
            headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/",
            },
        ) as response:
            if not response.ok:
                return None

            text = await response.text()
            data = loads(
                text.split(
                    '<script id="__UNIVERSAL_DATA_FOR_REHYDRATION__" type="application/json">'
                )[1].split("</script>")[0]
            )
            post = data["__DEFAULT_SCOPE__"]["webapp.video-detail"]["itemInfo"][
                "itemStruct"
            ]

            if post["id"] != aweme_id:
                return None

            return Information(
                id=post["id"],
                title=post["desc"],
                uploader=Uploader(
                    id=post["author"]["id"],
                    username=post["author"]["uniqueId"],
                    nickname=post["author"]["nickname"],
                    avatar_url=post["author"]["avatarLarger"],
                ),
                created_at=datetime.fromtimestamp(int(post["createTime"])),
                view_count=post["stats"]["playCount"],
                like_count=post["stats"]["diggCount"],
                comment_count=post["stats"]["commentCount"],
                url=post["video"]["playAddr"] or None,
                images=(
                    [
                        image["imageURL"]["urlList"][-1]
                        for image in post["imagePost"]["images"]
                    ]
                    if "imagePost" in post and "images" in post["imagePost"]
                    else []
                ),
            )

    async def dispatch(
        self,
        ctx: Context,
        data: Information,
        buffer: Optional[BytesIO],
    ) -> Optional[Message]:
        embed = Embed(
            url=data.webpage_url,
            title=shorten(data.title or "", width=256),
            timestamp=data.created_at,
        )
        embed.set_author(
            name=data.uploader,
            icon_url=data.uploader.avatar_url,
            url=data.uploader.url,
        )
        embed.set_footer(
            text=f"❤️ {data.like_count or 0:,} 👀 {data.view_count or 0:,} 💬 {data.comment_count or 0:,}",
        )

        if data.images:
            embeds: List[Embed] = []
            for image_url in data.images:
                embed = embed.copy()
                embed.set_image(url=image_url)
                embeds.append(embed)

            paginator = Paginator(
                ctx,
                entries=embeds,
            )
            return await paginator.start()

        if buffer:
            return await ctx.send(
                embed=embed if ctx.settings.reposter_embed else None,
                file=File(
                    buffer,
                    filename=f"Zyn{self.name}{token_urlsafe(4)}.mp4",
                ),
                no_reference=ctx.settings.reposter_delete,
            )
