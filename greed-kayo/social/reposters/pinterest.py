import re
from io import BytesIO
from json import dumps
from secrets import token_urlsafe
from textwrap import shorten
from typing import Optional

from discord import Embed, File, Message
from pydantic import BaseModel

from cogs.social.reposters.base import Reposter
from main import zyn
from tools.client import Context


class Information(BaseModel):
    id: str
    url: str
    ext: str
    title: Optional[str]
    uploader: str
    uploader_url: str
    download_count: int = 0
    comment_count: int = 0

    @property
    def webpage_url(self) -> str:
        return f"https://www.pinterest.com/pin/{self.id}/"


class Pinterest(Reposter):
    def __init__(self, bot: zyn):
        super().__init__(
            bot,
            name="Pinterest",
            regex=[
                r"(?x) https?://(?:[^/]+\.)?pinterest\.(?: com|fr|de|ch|jp|cl|ca|it|co\.uk|nz|ru|com\.au|at|pt|co\.kr|es|com\.mx|"
                r" dk|ph|th|com\.uy|co|nl|info|kr|ie|vn|com\.vn|ec|mx|in|pe|co\.at|hu|"
                r" co\.in|co\.nz|id|com\.ec|com\.py|tw|be|uk|com\.bo|com\.pe)/pin/(?P<id>\d+)",
            ],
        )

    async def fetch(self, url: str) -> Optional[Information]:
        identifier = re.match(self.regex[0], url)["id"]  # type: ignore

        async with self.bot.session.get(
            "https://www.pinterest.com/resource/PinResource/get/",
            params={
                "data": dumps(
                    {
                        "options": {
                            "id": identifier,
                            "field_set_key": "unauth_react_main_pin",
                        },
                    }
                ),
            },
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:109.0) "
                    "Gecko/20100101 Firefox/111.0"
                )
            },
        ) as response:
            if not response.ok:
                return None

            data = await response.json()
            if not data["resource_response"]["data"]:
                return None

            data = data["resource_response"]["data"]
            if data["videos"]:
                url = next(iter(data["videos"]["video_list"].values()))["url"]
            else:
                url = data["images"]["orig"]["url"]

            return Information(
                id=identifier,
                url=url,
                ext=url.split(".")[-1],
                title=data["title"],
                uploader=data["pinner"]["full_name"],
                uploader_url=f"https://www.pinterest.com/{data['pinner']['username']}/",
                download_count=data["aggregated_pin_data"]["aggregated_stats"]["saves"],
                comment_count=data["aggregated_pin_data"]["comment_count"],
            )

    async def dispatch(
        self,
        ctx: Context,
        data: Information,
        buffer: BytesIO,
    ) -> Message:
        embed = Embed(
            url=data.webpage_url,
            title=shorten(data.title or "", width=256),
        )
        embed.set_author(
            name=data.uploader or ctx.author.display_name,
            url=data.uploader_url,
        )
        embed.set_footer(
            text=f"💬 {data.comment_count:,}",
        )

        return await ctx.send(
            embed=embed if ctx.settings.reposter_embed else None,
            file=File(
                buffer,
                filename=f"Zyn{self.name}{token_urlsafe(6)}.{data.ext}",
            ),
            no_reference=ctx.settings.reposter_delete,
        )
