import re
import textwrap
import unicodedata
from datetime import datetime, timedelta, timezone
from hashlib import sha1, sha224, sha256, sha384, sha512
from re import Pattern, compile
from io import BytesIO
from typing import Annotated, Dict, List, Optional, cast
from urllib.parse import quote_plus
from PIL import Image, ImageOps

import dateparser
from bs4 import BeautifulSoup
from dateutil.tz import gettz
from discord import (
    Attachment,
    Embed,
    File,
    HTTPException,
    Member,
    User,
    Message,
    RawReactionActionEvent,
    TextChannel,
    Thread,
)
from discord.ext.commands import (
    BadArgument,
    BucketType,
    Cog,
    clean_content,
    command,
    cooldown,
    group,
    max_concurrency,
    parameter,
    is_owner,
    has_permissions,
    UserConverter,
    hybrid_command,
)
from discord.utils import format_dt, utcnow
from humanize import ordinal
from shazamio import Serialize as ShazamSerialize
from shazamio import Shazam as ShazamClient
from yarl import URL

from config import AUTHORIZATION

from main import zyn
from tools import dominant_color
from tools.client import Context
from tools.parser import Script
from tools.paginator import Paginator
from tools.conversion.discord import Donator
from tools.formatter import shorten, codeblock
from tools.conversion import PartialAttachment, Timezone


from cogs.social.models import YouTubeVideo
from .models.google import Google, GoogleTranslate
from .models.embedbuilder import EmbedBuilding

from .extended import Extended
from math import ceil


class Utility(Extended, Cog):
    def __init__(self, bot: zyn):
        self.bot = bot
        self.shazamio = ShazamClient()

    @Cog.listener("on_message_without_command")
    async def afk_listener(self, ctx: Context) -> Optional[Message]:
        if left_at := cast(
            Optional[datetime],
            await self.bot.db.fetchval(
                """
                DELETE FROM afk
                WHERE user_id = $1
                RETURNING left_at
                """,
                ctx.author.id,
            ),
        ):
            return await ctx.neutral(
                f"Welcome back, you left {format_dt(left_at, 'R')}",
                reference=ctx.message,
            )

        if len(ctx.message.mentions) == 1:
            user = ctx.message.mentions[0]

            if record := await self.bot.db.fetchrow(
                """
                SELECT status, left_at
                FROM afk
                WHERE user_id = $1
                """,
                user.id,
            ):
                return await ctx.neutral(
                    f"{user.mention} is currently AFK: **{record['status']}** - {format_dt(record['left_at'], 'R')}",
                    reference=ctx.message,
                )

    @hybrid_command(aliases=["away"])
    async def afk(
        self,
        ctx: Context,
        *,
        status: str = "AFK",
    ) -> Optional[Message]:
        """
        Set an AFK status.
        """

        status = shorten(status, 200)
        if await self.bot.db.execute(
            """
            INSERT INTO afk (user_id, status)
            VALUES ($1, $2)
            ON CONFLICT (user_id) DO NOTHING
            """,
            ctx.author.id,
            status,
        ):
            return await ctx.approve(f"You're now **AFK** with the status **{status}**")

    @command(aliases=["recognize"])
    @max_concurrency(1, wait=True)
    @cooldown(1, 5, BucketType.guild)
    async def shazam(
        self,
        ctx: Context,
        attachment: PartialAttachment = parameter(
            default=PartialAttachment.fallback,
        ),
    ) -> Message:
        """
        Recognize a song from an attachment.
        """

        if not attachment.is_video() and not attachment.is_audio():
            return await ctx.warn("The attachment must be a video!")

        async with ctx.typing():
            data = await self.shazamio.recognize(attachment.buffer)
            output = ShazamSerialize.full_track(data)

        if not (track := output.track):
            return await ctx.warn(
                f"No tracks were found from [`{attachment.filename}`]({attachment.url})!"
            )

        return await ctx.approve(
            f"Found [**{track.title}**]({track.shazam_url}) "
            f"by [**`{track.subtitle}`**]({URL(f'https://google.com/search?q={track.subtitle}')})"
        )

    @group(
        aliases=["bday", "bd"],
        invoke_without_command=True,
    )
    async def birthday(
        self,
        ctx: Context,
        *,
        member: Member = parameter(
            default=lambda ctx: ctx.author,
        ),
    ) -> Message:
        """
        View your birthday.
        """

        birthday = cast(
            Optional[datetime],
            await self.bot.db.fetchval(
                """
                SELECT birthday
                FROM birthdays
                WHERE user_id = $1
                """,
                member.id,
            ),
        )
        if not birthday:
            if member == ctx.author:
                return await ctx.warn(
                    "You have not set your birthday yet,",
                    f"Use `{ctx.clean_prefix}birthday set [date]` to set it",
                )

            return await ctx.warn(f"**{member}** hasn't set their birthday yet")

        current = utcnow()
        next_birthday = current.replace(
            year=current.year + 1,
            month=birthday.month,
            day=birthday.day,
        )
        if next_birthday.day == current.day and next_birthday.month == current.month:
            phrase = "**today**, happy birthday! 🎊"
        elif (
            next_birthday.day + 1 == current.day
            and next_birthday.month == current.month
        ):
            phrase = "**tomorrow**, happy early birthday! 🎊"
        else:
            days_until_birthday = (next_birthday - current).days
            if days_until_birthday > 365:
                next_birthday = current.replace(
                    year=current.year,
                    month=birthday.month,
                    day=birthday.day,
                )
                days_until_birthday = (next_birthday - current).days

            phrase = f"**{next_birthday.strftime('%B')} {ordinal(next_birthday.day)}**, that's {format_dt(next_birthday, 'R')}"

        return await ctx.neutral(
            f"Your birthday is {phrase}"
            if member == ctx.author
            else f"**{member}**'s birthday is {phrase}"
        )

    @birthday.command(name="set")
    async def birthday_set(
        self,
        ctx: Context,
        *,
        date: str,
    ) -> Message:
        """
        Set your birthday.
        """

        birthday = dateparser.parse(date)
        if not birthday:
            return await ctx.warn(f"Date not found for **{date}**")

        await self.bot.db.execute(
            """
            INSERT INTO birthdays (user_id, birthday)
            VALUES ($1, $2)
            ON CONFLICT (user_id) DO UPDATE
            SET birthday = EXCLUDED.birthday
            """,
            ctx.author.id,
            birthday,
        )
        return await ctx.approve(
            f"Your birthday has been set to **{birthday:%B} {ordinal(birthday.strftime('%-d'))}**"
        )

    @group(
        aliases=["time", "tz"],
        invoke_without_command=True,
    )
    async def timezone(
        self,
        ctx: Context,
        *,
        member: Member = parameter(
            default=lambda ctx: ctx.author,
        ),
    ) -> Message:
        """
        View your local time.
        """

        timezone = cast(
            Optional[str],
            await self.bot.db.fetchval(
                """
                SELECT timezone
                FROM timezones
                WHERE user_id = $1
                """,
                member.id,
            ),
        )
        if not timezone:
            if member == ctx.author:
                return await ctx.warn(
                    "You have not set a timezone yet,",
                    f"Use `{ctx.clean_prefix}timezone set <location>` to set it",
                )

            return await ctx.warn(f"**{member}** hasn't set their timezone yet!")

        timestamp = utcnow().astimezone(gettz(timezone))
        return await ctx.neutral(
            f"It's currently **{timestamp.strftime('%B %d, %I:%M %p')}** "
            + ("for you" if member == ctx.author else f"for {member.mention}")
        )

    @timezone.command(name="set")
    async def timezone_set(
        self,
        ctx: Context,
        *,
        timezone: Annotated[
            str,
            Timezone,
        ],
    ) -> Message:
        """
        Set your local timezone.
        """

        await self.bot.db.execute(
            """
            INSERT INTO timezones (user_id, timezone)
            VALUES ($1, $2)
            ON CONFLICT (user_id) DO UPDATE
            SET timezone = EXCLUDED.timezone
            """,
            ctx.author.id,
            timezone,
        )
        return await ctx.approve(f"Your timezone has been set to `{timezone}`")

    @timezone.command(name="list")
    async def timezone_list(self, ctx: Context) -> Message:
        """
        Get the timezones of everyone in this server
        """

        ids = list(map(lambda m: str(m.id), ctx.guild.members))
        results = await self.bot.db.fetch(
            f"SELECT timezone, user_id FROM timezones WHERE user_id IN ({', '.join(ids)})"
        )

        entries = [
            f"<@{result['user_id']}> - **{result['timezone']}**" for result in results
        ]

        if not entries:
            return await ctx.warn("No one in this server has set their timezone yet.")

        paginator = Paginator(
            ctx,
            entries=entries,
            embed=Embed(title=f"Timezones ({len(entries)})"),
            per_page=10,
            counter=False,
        )
        await paginator.start()

    @command(
        aliases=[
            "dictionary",
            "define",
            "urban",
            "ud",
        ],
    )
    async def urbandictionary(
        self,
        ctx: Context,
        *,
        word: str,
    ) -> Message:
        """
        Define a word with Urban Dictionary.
        """

        async with ctx.typing():
            response = await self.bot.session.get(
                URL.build(
                    scheme="https",
                    host="api.urbandictionary.com",
                    path="/v0/define",
                    query={
                        "term": word,
                    },
                ),
            )
            data = await response.json()
            if not data["list"]:
                return await ctx.warn(f"No definitions were found for **{word}**!")

        embeds: List[Embed] = []
        for result in data["list"]:
            embed = Embed(
                url=result["permalink"],
                title=result["word"],
                description=re.sub(
                    r"\[(.*?)\]",
                    lambda m: f"[{m[1]}](https://www.urbandictionary.com/define.php?term={quote_plus(m[1])})",
                    result["definition"],
                )[:4096],
            )

            embed.add_field(
                name="**Example**",
                value=re.sub(
                    r"\[(.*?)\]",
                    lambda m: f"[{m[1]}](https://www.urbandictionary.com/define.php?term={quote_plus(m[1])})",
                    result["example"],
                )[:1024],
            )
            embeds.append(embed)

        paginator = Paginator(
            ctx,
            entries=embeds,
            embed=[embed],
        )
        return await paginator.start()

    @command(
        name="translate",
        aliases=[
            "translation",
            "tr",
        ],
    )
    async def translate(
        self,
        ctx: Context,
        destination: Annotated[
            str,
            Optional[GoogleTranslate],
        ] = "en",
        *,
        text: Annotated[
            Optional[str],
            clean_content,
        ] = None,
    ) -> Message:
        """
        Translate text with Google Translate.
        This is an alias for the `google translate` command.
        """

        return await self.google_translate(
            ctx,
            destination=destination,
            text=text,
        )

    @command(
        aliases=[
            "rimg",
            "sauce",
        ]
    )
    async def reverse(
        self,
        ctx: Context,
        attachment: PartialAttachment = parameter(
            default=PartialAttachment.fallback,
        ),
    ) -> Message:
        """
        Reverse search an image on Google.
        This is an alias for the `google reverse` command.
        """

        return await self.google_reverse(ctx, attachment=attachment)

    @group(
        aliases=["g", "ddg"],
        invoke_without_command=True,
    )
    @cooldown(3, 60, BucketType.user)
    async def google(self, ctx: Context, *, query: str) -> Message:
        """
        Search a query on Google.
        """
        async with ctx.typing():
            data = await Google.search(self.bot.session, query)
            if not data.results:
                return await ctx.send(f"No results were found for **{query}**")

        embeds = []
        per_page = 3
        total_results = len(data.results)
        total_pages = ceil(total_results / per_page)

        if panel := data.panel:
            embed = Embed(
                title=f"{data.header or 'Google Search - ' + query}"
                + (f" - {data.description}" if data.description else "")
            )
            if panel.source:
                embed.url = panel.source.url

            embed.description = shorten(panel.description, 200)
            for item in panel.items:
                embed.description += f"\n> **{item.name}:** `{item.value}`"

            embeds.append(embed)

        fields: List[Dict[str, Union[str, bool]]] = []

        for result in data.results:
            if any(result.title in field["name"] for field in fields):
                continue

            snippet = result.snippet or (".." if not result.tweets else "")
            for highlight in result.highlights:
                snippet = snippet.replace(highlight, f"**{highlight}**")

            extended_links = "\n".join(
                [
                    f"> [`{extended.title}`]({extended.url}): {shorten(extended.snippet or '...', 46, placeholder='..')}"
                    for extended in result.extended_links
                ]
            )

            tweets = "\n".join(
                [
                    f"> [`{shorten(tweet.text, 46, placeholder='..')}`]({tweet.url}) **{tweet.footer}**"
                    for tweet in result.tweets[:3]
                ]
            )

            field_value = f"**{result.url.split('?', 1)[0]}**\n{shorten(snippet, 200)}\n{extended_links}\n{tweets}"
            fields.append(
                {
                    "name": f"**{result.title}**",
                    "value": field_value,
                    "inline": False,
                }
            )

        if not fields:
            await ctx.send(f"No relevant results were found for **{query}**!")
            return

        for i in range(0, total_results, per_page):
            page_embeds = data.results[i : i + per_page]
            embed = Embed(title=f"Google Search - {query}", description="")
            for result in page_embeds:
                embed.add_field(
                    name=f"**{result.title}**", value=field_value, inline=False
                )
            embed.set_footer(text=f"Page {i//per_page + 1} of {total_pages}")
            embeds.append(embed)

        paginator = Paginator(ctx, entries=embeds, embed=embeds, per_page=1)
        await paginator.start()

    @google.command(
        name="translate",
        aliases=[
            "translation",
            "tr",
        ],
    )
    async def google_translate(
        self,
        ctx: Context,
        destination: Annotated[
            str,
            Optional[GoogleTranslate],
        ] = "en",
        *,
        text: Annotated[
            Optional[str],
            clean_content,
        ] = None,
    ) -> Message:
        """
        Translate text with Google Translate.
        """

        if not text:
            reply = ctx.replied_message
            if reply and reply.content:
                text = reply.clean_content
            else:
                return await ctx.send_help(ctx.command)

        async with ctx.typing():
            result = await GoogleTranslate.translate(
                self.bot.session,
                text,
                target=destination,
            )

        embed = Embed(title="Google Translate")
        embed.add_field(
            name=f"**{result.source_language} to {result.target_language}**",
            value=result.translated,
            inline=False,
        )

        return await ctx.send(embed=embed)

    @google.command(
        name="youtube",
        aliases=["yt"],
    )
    async def google_youtube(self, ctx: Context, *, query: str) -> Message:
        """
        Search a query on YouTube.
        """

        async with ctx.typing():
            results = await YouTubeVideo.search(self.bot.session, query)
            if not results:
                return await ctx.warn(f"No videos were found for **{query}**!")

            paginator = Paginator(
                ctx,
                entries=[result.url for result in results],
            )
            return await paginator.start()

    @google.command(
        name="reverse",
        aliases=["rimg"],
    )
    @cooldown(1, 10, BucketType.user)
    async def google_reverse(
        self,
        ctx: Context,
        attachment: PartialAttachment = parameter(
            default=PartialAttachment.fallback,
        ),
    ) -> Message:
        """
        Reverse search an image on Google.
        """

        if not attachment.is_image():
            return await ctx.warn("The attachment must be an image")

        async with ctx.typing():
            classes: Dict[str, str | Pattern[str]] = {
                "description": compile("VwiC3b yXK7lf"),
                "result": "srKDX cvP2Ce",
                "related": "fKDtNb",
            }
            response = await self.bot.session.get(
                URL.build(
                    scheme="https",
                    host="www.google.com",
                    path="/searchbyimage",
                    query={
                        "safe": "off" if ctx.channel.is_nsfw() else "on",
                        "sbisrc": "tg",
                        "image_url": attachment.url,
                    },
                ),
                headers={
                    "User-Agent": (
                        "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:109.0) "
                        "Gecko/20100101 Firefox/111.0"
                    )
                },
            )
            content = await response.text()

            data = BeautifulSoup(content, "lxml")
            related = data.find("a", class_=classes["related"])
            results = data.findAll("div", class_=classes["result"])
            if not related or not results:
                return await ctx.warn(
                    f"No results were found for [`{attachment.filename}`]({attachment.url})"
                )

        embed = Embed(
            title="Reverse Image Search",
            description=f"*`{related.text}`*",
        )
        embed.set_thumbnail(url=attachment.url)
        if stats := data.find("div", id="result-stats"):
            embed.set_footer(text=stats.text)

        for result in results[:3]:
            link = result.a.get("href")
            title = result.find("h3").text
            description = (
                result.find("div", class_=classes["description"]).text
                if result.find("div", class_=classes["description"])
                else ""
            )

            embed.add_field(
                name=title,
                value=f">>> [`{shorten(description, 65)}`]({link})",
                inline=False,
            )

        return await ctx.send(embed=embed)

    @command(aliases=["ai", "ask", "chatgpt"])
    @Donator()
    async def gemini(self, ctx: Context, *, question: str) -> Optional[Message]:
        """
        Ask AI a question.
        """

        async with ctx.typing():
            response = await self.bot.session.post(
                URL.build(
                    scheme="https",
                    host="generativelanguage.googleapis.com",
                    path="/v1/models/gemini-pro:generateContent",
                    query={
                        "key": AUTHORIZATION.GEMINI,
                    },
                ),
                json={"contents": [{"parts": [{"text": question}]}]},
            )

            if not (data := await response.json()):
                return await ctx.warn("No responses were found for that question")

            if not (content := data.get("candidates", [])[0].get("content")) or not (
                parts := content.get("parts")
            ):
                return await ctx.warn("No responses were found for that question")

            await ctx.reply(parts[0]["text"])

    @command(aliases=["w"])
    async def wolfram(
        self,
        ctx: Context,
        *,
        question: str,
    ) -> Message:
        """
        Solve a question with Wolfram Alpha.
        """

        async with ctx.typing():
            response = await self.bot.session.get(
                URL.build(
                    scheme="https",
                    host="api.wolframalpha.com",
                    path="/v1/result",
                    query={
                        "i": question,
                        "appid": AUTHORIZATION.WOLFRAM,
                    },
                ),
            )
            if not response.ok:
                return await ctx.warn("No solution was found for that question")

            content = await response.read()

        return await ctx.reply(content.decode("utf-8"))

    @command(aliases=["parse", "ce"])
    @has_permissions(manage_messages=True)
    async def embed(self, ctx: Context, *, script: Script) -> Message:
        """
        Parse a script into an embed.
        """

        try:
            return await script.send(ctx)
        except HTTPException as exc:
            return await ctx.warn(
                "Something is wrong with your **script**",
                codeblock(exc.text),
            )

    @command(aliases=["embedcode", "ec"])
    @has_permissions(manage_messages=True)
    async def copyembed(
        self,
        ctx: Context,
        message: Optional[Message],
    ) -> Message:
        """
        Copy a script from a message.
        """

        message = message or ctx.replied_message
        if not message:
            return await ctx.send_help(ctx.command)

        script = Script.from_message(message)
        if not script:
            return await ctx.warn(
                f"The [`message`]({message.jump_url}) does not have any content"
            )

        return await ctx.reply(codeblock(script.template))

    @command(name="recolor")
    async def recolor(self, ctx: Context, hex_color: str, image_url: str = None):
        if not hex_color.startswith("#") or len(hex_color) != 7:
            await ctx.warn("Please provide a valid hex color code.")
            return
        image_source = None
        if ctx.message.attachments:
            image_source = ctx.message.attachments[0].url
        elif image_url is not None:
            image_source = image_url
        else:
            await ctx.warn("Please provide an image URL or attachment.")
            return
        async with self.bot.session.get(image_source) as response:
            if response.status != 200:
                await ctx.warn("Failed to download image.")
                return

            image_data = await response.read()

            image = Image.open(BytesIO(image_data))

        image = ImageOps.grayscale(image)
        image = ImageOps.colorize(image, black="black", white=hex_color)

        with BytesIO() as image_binary:
            image.save(image_binary, "PNG")
            image_binary.seek(0)

            await ctx.send(file=File(fp=image_binary, filename="recolor.png"))

    @command(name="guildvanity", aliases=["gv"])
    async def guild_vanity(self, ctx: Context):
        """Displays the guild's vanity URL if any is set."""
        vanity_url = await ctx.guild.vanity_invite()
        if vanity_url:
            await ctx.neutral(f"The vanity URL for this guild is: {vanity_url.url}")
        else:
            await ctx.warn("This guild does not have a vanity URL set.")

    @command(name="joins")
    async def joins(self, ctx: Context):
        """Returns a list of members that joined in the last 24 hours."""
        now = datetime.now(timezone.utc)
        one_day_ago = now - timedelta(days=1)
        recent_members = [
            member
            for member in ctx.guild.members
            if member.joined_at and member.joined_at > one_day_ago
        ]

        if not recent_members:
            await ctx.warn("No members have joined in the last 24 hours.")
            return

        entries = [
            f"{member.mention} joined <t:{int(member.joined_at.timestamp())}:R>"
            for member in recent_members
        ]

        embed = Embed(
            title="Members joined in the last 24 hours",
        )

        paginator = Paginator(
            ctx,
            entries=entries,
            embed=embed,
            per_page=5,
        )
        await paginator.start()

    @command(name="timedout")
    async def timedout(self, ctx: Context):
        """Returns a list of members that are currently timed out in the server."""
        now = datetime.now(timezone.utc)
        timed_out_members = [
            member for member in ctx.guild.members if member.is_timed_out()
        ]

        if not timed_out_members:
            await ctx.warn("No members are currently timed out.")
            return

        entries = [
            f"{member.mention} is timed out until <t:{int(member.timed_out_until.timestamp())}:R>"
            for member in timed_out_members
        ]

        embed = Embed(title="Currently Timed Out Members", color=ctx.guild.me.color)

        paginator = Paginator(
            ctx,
            entries=entries,
            embed=embed,
            per_page=5,
        )
        await paginator.start()

    @command(name="dominant", usage="<user | url>", brief="@nyrtour")
    async def dominant(self, ctx: Context, *, target: str = None):
        if target:
            if target.startswith(("http://", "https://")):
                async with self.bot.session.get(target) as response:
                    if response.status == 200:
                        data = await response.read()
                        color = await dominant_color(data)
                        embed = Embed(description=f"HEX: {color}", color=color)
                        embed.set_image(url=target)
                        await ctx.send(embed=embed)
                    else:
                        await ctx.warn(
                            "Could not fetch the image from the provided URL."
                        )
            else:
                try:
                    user: User = await UserConverter().convert(ctx, target)
                    avatar_url = user.avatar.url
                    async with self.bot.session.get(str(avatar_url)) as response:
                        if response.status == 200:
                            data = await response.read()
                            color = await dominant_color(data)
                            embed = Embed(
                                title=f"Dominant Color of {user.name}'s Avatar",
                                description=f"HEX: {color}",
                                color=color,
                            )
                            embed.set_thumbnail(url=avatar_url)
                            await ctx.send(embed=embed)
                        else:
                            await ctx.warn("Could not fetch the user's avatar.")
                except BadArgument:
                    await ctx.warn("Could not find this user.")
        else:
            if ctx.message.attachments:
                attachment: Attachment = ctx.message.attachments[0]
                if attachment.content_type.startswith("image/"):
                    data = await attachment.read()
                    color = await dominant_color(data)
                    embed = Embed(
                        title="Dominant color of image",
                        description=f"HEX: {color}",
                        color=color,
                    )
                    embed.set_image(url=attachment.url)
                    await ctx.send(embed=embed)
                else:
                    await ctx.warn("Please attach a valid image file.")

    @command(name="setname", brief="zyn server", description="manage guild")
    @has_permissions(manage_guild=True)
    async def set_name(self, ctx: Context, *, new_name: str) -> Message:
        """Set the guild's name."""
        await ctx.guild.edit(name=new_name)
        await ctx.approve(f"Guild name changed to {new_name}")

    @command(
        name="setbanner", brief="https://zyn.bot/zyn.png", description="manage guild"
    )
    @has_permissions(manage_guild=True)
    async def set_banner(self, ctx: Context, banner_url: str) -> Message:
        """Set the guild's banner."""
        async with self.bot.session.get(banner_url) as response:
            if response.status != 200:
                return await ctx.warn("Could not fetch the banner image.")
            data = await response.read()
            await ctx.guild.edit(banner=data)
            await ctx.approve("Guild banner updated.")

    @command(
        name="seticon", brief="https://zyn.bot/zyn.png", description="manage guild"
    )
    @has_permissions(manage_guild=True)
    async def set_icon(self, ctx: Context, icon_url: str) -> Message:
        """Set the guild's icon."""
        async with self.bot.session.get(icon_url) as response:
            if response.status != 200:
                return await ctx.warn("Could not fetch the icon image.")
            data = await response.read()
            await ctx.guild.edit(icon=data)
            await ctx.approve("Guild icon updated.")

    @command(
        name="setsplash", brief="https://zyn.bot/zyn.png", description="manage guild"
    )
    @has_permissions(manage_guild=True)
    async def set_splash(self, ctx: Context, splash_url: str) -> Message:
        """Set the guild's splash image."""
        async with self.bot.session.get(splash_url) as response:
            if response.status != 200:
                return await ctx.warn("Could not fetch the splash image.")
            data = await response.read()
            await ctx.guild.edit(splash=data)
            await ctx.approve("Guild splash image updated.")

    @command(aliases=["is"], brief="yurrion")
    async def invitestats(
        self, ctx: Context, member: Optional[Member] = None
    ) -> Message:
        """Shows the number of invites for a specific member or the command author."""
        if not member:
            member = ctx.author

        total_invites = 0
        for invite in await ctx.guild.invites():
            if invite.inviter == member:
                total_invites += invite.uses

        await ctx.approve(f"{member.display_name} has {total_invites} invites.")

    @hybrid_command(description="manage_messages")
    @has_permissions(manage_messages=True)
    async def embedsetup(self, ctx: Context):
        """Create an embed using buttons and return an embed code"""
        embed = Embed(description="Created an embed")
        view = EmbedBuilding(ctx)
        return await ctx.send(embed=embed, view=view)
