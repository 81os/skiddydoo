from io import BytesIO
from secrets import token_urlsafe
from textwrap import shorten

from discord import Embed, File, Message

from cogs.social.reposters.base import Information, Reposter
from main import zyn
from tools.client import Context


class YouTube(Reposter):
    def __init__(self, bot: zyn):
        super().__init__(
            bot,
            name="YouTube",
            regex=[
                r"(?:http(?:s)?:\/\/)?(?:www\.)?(?:youtube\.com\/watch\?v=|youtu\.be\/|youtube\.com\/shorts\/)([a-zA-Z0-9_-]+)"
            ],
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
            text=f"👀 {data.view_count or 0:,} 💬 {data.comment_count or 0:,}",
        )

        return await ctx.send(
            embed=embed if ctx.settings.reposter_embed else None,
            file=File(
                buffer,
                filename=f"Zyn{self.name}{token_urlsafe(6)}.{data.ext}",
            ),
            no_reference=ctx.settings.reposter_delete,
        )
