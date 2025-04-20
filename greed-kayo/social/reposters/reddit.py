from io import BytesIO
from secrets import token_urlsafe
from textwrap import shorten
from typing import Optional

from cashews import cache
from discord import Embed, File, Message

from cogs.social.reposters.base import Information, Reposter
from cogs.social.reposters.extraction import download
from main import zyn
from tools import CACHE_ROOT
from tools.client import Context


class Reddit(Reposter):
    def __init__(self, bot: zyn, **kwargs):
        super().__init__(
            bot,
            **kwargs,
            name="Reddit",
            regex=[
                r"\<?(https?://(?:www\.)?reddit\.com/r/(?P<channel>[^/]+)/comments/(?P<id>[^/?#&]+))\>?",
                r"\<?(https?://(?:www\.)?reddit\.com/r/(?P<channel>[^/]+)/s/(?P<id>[^/?#&]+))\>?",
            ],
        )

    @cache(ttl="1h", prefix="reddit")
    async def fetch(self, url: str) -> Optional[Information]:
        await CACHE_ROOT.mkdir(parents=True, exist_ok=True)
        return await download(url, download=True)

    async def dispatch(
        self,
        ctx: Context,
        data: Information,
        buffer: BytesIO,
    ) -> Optional[Message]:
        if not data.requested_downloads:
            return

        buffer = await data.requested_downloads[-1].read()
        embed = Embed(
            url=data.webpage_url,
            title=shorten(data.title or "", width=256),
        )
        embed.set_author(
            name=f"{data.uploader} (r/{data.channel_id})" or ctx.author.display_name,
            url=f"https://reddit.com/u/{data.uploader}",
        )
        embed.set_footer(
            text=f"❤️ {data.like_count or 0:,} 💬 {data.comment_count or 0:,} ",
            icon_url="https://i.imgur.com/t90f67x.png",
        )

        return await ctx.send(
            embed=embed if ctx.settings.reposter_embed else None,
            file=File(
                buffer,
                filename=f"Zyn{self.name}{token_urlsafe(6)}.{data.ext}",
            ),
            no_reference=ctx.settings.reposter_delete,
        )
