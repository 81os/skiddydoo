import asyncio
from random import choice
import textwrap
from asyncio import to_thread
from typing import Any, Dict, List, Optional, cast
from contextlib import suppress
from discord import (
    File,
    Embed,
    User,
    Member,
    Message,
    NotFound,
    Reaction,
    Interaction,
    ButtonStyle,
    NotFound,
)
from discord.ext.commands import (
    Cog,
    group,
    has_permissions,
    command,
    hybrid_command,
    hybrid_group,
    CommandError,
    cooldown,
    BucketType,
    CommandOnCooldown,
)
from discord.ui import View, Button, button
from pydantic import BaseModel
from typing_extensions import Self
from xxhash import xxh64_hexdigest

from main import zyn
from tools import uwuify
from tools.client import Context
from tools.client.redis import Redis
from tools.formatter import plural
from PIL import Image, ImageDraw, ImageFont
from io import BytesIO
import random
from asyncio import to_thread as thread


class Blacktea(BaseModel):
    message_id: int
    channel_id: int
    waiting: bool = True
    players: Dict[int, int] = {}
    used_words: List[str] = []

    @staticmethod
    def key(channel_id: int) -> str:
        return xxh64_hexdigest(f"blacktea:{channel_id}")

    @classmethod
    async def get(cls, redis: Redis, channel_id: int) -> Optional[Self]:
        key = cls.key(channel_id)
        data = cast(Optional[Dict[str, Any]], await redis.get(key))
        if not data:
            return

        return cls(**data)

    async def save(self, redis: Redis, **kwargs) -> None:
        key = self.key(self.channel_id)
        await redis.set(key, self.dict(), **kwargs)

    async def delete(self, redis: Redis) -> None:
        key = self.key(self.channel_id)
        await redis.delete(key)


class TicTacToeButton(Button):
    def __init__(self, x: int, y: int, player1: Member, player2: Member):
        super().__init__(style=ButtonStyle.secondary, label="\u200b", row=y)
        self.x = x
        self.y = y
        self.player1 = player1
        self.player2 = player2

    async def callback(self, interaction: Interaction):
        assert self.view is not None
        view: "TicTacToe" = self.view
        state = view.board[self.y][self.x]

        if state in (view.X, view.O):
            return

        if view.current_player == view.X:
            if interaction.user.id != self.player1.id:
                return await interaction.response.send_message(
                    "It's not your turn", ephemeral=True
                )
            self.style = ButtonStyle.danger
            self.label = "X"
            view.current_player = view.O
        else:
            if interaction.user.id != self.player2.id:
                return await interaction.response.send_message(
                    "It's not your turn", ephemeral=True
                )
            self.style = ButtonStyle.success
            self.label = "O"
            view.current_player = view.X

        self.disabled = True
        view.board[self.y][self.x] = view.current_player * -1

        content = f"It's **{self.player2.mention if view.current_player == view.O else self.player1.mention}**'s turn"

        winner = view.check_board_winner()
        if winner is not None:
            content = (
                "It's a tie"
                if winner == view.Tie
                else f"**{self.player1.mention if winner == view.X else self.player2.mention}** won!"
            )
            for child in view.children:
                child.disabled = True
            view.stop()

        await interaction.response.edit_message(content=content, view=view)


class TicTacToe(View):
    children: List[TicTacToeButton]
    X = -1
    O = 1
    Tie = 0

    def __init__(self, player1: Member, player2: Member):
        super().__init__(timeout=60)
        self.current_player = self.X
        self.player1 = player1
        self.player2 = player2
        self.board = [[0 for _ in range(3)] for _ in range(3)]

        for y in range(3):
            for x in range(3):
                self.add_item(TicTacToeButton(x, y, player1, player2))

    def check_board_winner(self):
        board = self.board
        lines = (
            board
            + [list(x) for x in zip(*board)]
            + [[board[i][i] for i in range(3)], [board[i][2 - i] for i in range(3)]]
        )
        for line in lines:
            if all(x == self.O for x in line):
                return self.O
            if all(x == self.X for x in line):
                return self.X

        if all(cell != 0 for row in board for cell in row):
            return self.Tie
        return None

    async def on_timeout(self):
        for item in self.children:
            item.disabled = True
        if hasattr(self, "message"):
            await self.message.edit(disabled=True)


class Fun(Cog):
    def __init__(self, bot: zyn):
        self.bot = bot
        self.words: List[str] = []

    async def cog_load(self) -> None:
        async with self.bot.session.get(
            "https://www.mit.edu/~ecprice/wordlist.100000"
        ) as resp:
            buffer = await resp.text()
            self.words = buffer.splitlines()

    async def cog_unload(self) -> None:
        self.words = []

    async def get_caption(self, ctx: Context, message: Optional[Message] = None):
        if message is None:
            msg = ctx.message.reference
            if msg is None:
                return await ctx.warn(f"no **message** or **reference** provided")
            id = msg.message_id
            message = await ctx.fetch_message(id)

        image = BytesIO(await message.author.display_avatar.read())
        image.seek(0)
        file_name = "icon.jpeg"

        if message.content.replace("\n", "").isascii():
            para = textwrap.wrap(message.clean_content, width=26)
        else:
            para = textwrap.wrap(message.clean_content, width=13)

        def do_caption(para, image, message):
            icon = Image.open(image)
            haikei = Image.open("quote/grad.jpeg")
            black = Image.open("quote/black.jpeg")
            w, h = (680, 370)
            haikei = haikei.resize((w, h))
            black = black.resize((w, h))
            icon = icon.resize((h, h))

            new = Image.new(mode="L", size=(w, h))
            icon = icon.convert("L")
            black = black.convert("L")
            icon = icon.crop((40, 0, 680, 370))
            new.paste(icon)

            sa = Image.composite(new, black, haikei.convert("L"))
            draw = ImageDraw.Draw(sa)
            fnt = ImageFont.truetype("quote/Arial.ttf", 28)

            _, _, w2, h2 = draw.textbbox((0, 0), "a", font=fnt)
            i = (int(len(para) / 2) * w2) + len(para) * 5
            current_h, pad = 120 - i, 0

            for line in para:
                if message.content.replace("\n", "").isascii():
                    _, _, w3, h3 = draw.textbbox(
                        (0, 0), line.ljust(int(len(line) / 2 + 11), " "), font=fnt
                    )
                    draw.text(
                        (11 * (w - w3) / 13 + 10, current_h + h2),
                        line.ljust(int(len(line) / 2 + 11), " "),
                        font=fnt,
                        fill="#FFF",
                    )
                else:
                    _, _, w3, h3 = draw.textbbox(
                        (0, 0), line.ljust(int(len(line) / 2 + 5), "　"), font=fnt
                    )
                    draw.text(
                        (11 * (w - w3) / 13 + 10, current_h + h2),
                        line.ljust(int(len(line) / 2 + 5), "　"),
                        font=fnt,
                        fill="#FFF",
                    )

                current_h += h3 + pad

            dr = ImageDraw.Draw(sa)
            font = ImageFont.truetype("quote/Arial.ttf", 15)
            _, _, authorw, authorh = dr.textbbox(
                (0, 0), f"-{str(message.author)}", font=font
            )

            output = BytesIO()
            dr.text(
                (480 - int(authorw / 2), current_h + h2 + 10),
                f"-{str(message.author)}",
                font=font,
                fill="#FFF",
            )
            sa.save(output, format="JPEG")
            output.seek(0)
            return output

        output = await thread(do_caption, para, image, message)
        file = File(fp=output, filename="quote.png")
        return await ctx.send(file=file)

    @Cog.listener()
    async def on_reaction_add(self, reaction: Reaction, member: Member) -> None:
        if member.bot or reaction.emoji != "🍵":
            return

        session = await Blacktea.get(self.bot.redis, reaction.message.channel.id)
        if (
            not session
            or not session.waiting
            or session.message_id != reaction.message.id
        ):
            return

        if member.id in session.players:
            return

        session.players[member.id] = 2
        await session.save(self.bot.redis)

        embed = Embed(description=f"**{member}** joined the game")
        await reaction.message.reply(embed=embed, delete_after=3)

    @hybrid_group(invoke_without_command=True, usage="blacktea", brief="blacktea")
    async def blacktea(self, ctx: Context) -> Optional[Message]:
        """
        Start a game of Blacktea in the server with members who reacted.
        """

        session = await Blacktea.get(self.bot.redis, ctx.channel.id)
        if session:
            return await ctx.warn("There is already a game in progress.")

        embed = Embed(
            title="Blacktea",
            description="\n> ".join(
                [
                    "React with `🍵` to join the game.",
                    "You have 20 seconds to join with a minimum of 2 people joining.",
                    "You'll have **10 seconds** type a word containing the given letters.",
                    "The word must be at least **3 letters long** and **not used before**.",
                ]
            ),
        )
        message = await ctx.channel.send(embed=embed)

        session = Blacktea(message_id=message.id, channel_id=ctx.channel.id)
        await session.save(self.bot.redis)
        await message.add_reaction("🍵")

        await asyncio.sleep(30)
        session = await Blacktea.get(self.bot.redis, ctx.channel.id)
        if not session or len(session.players) < 2:
            await self.bot.redis.delete(Blacktea.key(ctx.channel.id))
            return await ctx.warn("Not enough players to start the game.")

        session.waiting = False
        await session.save(self.bot.redis, ex=600)

        while True:
            for member_id, lives in list(session.players.items()):
                member = ctx.guild.get_member(member_id)
                if not member:
                    if len(session.players) == 1:
                        await session.delete(self.bot.redis)
                        return await ctx.warn("The winner left the server.")

                    continue

                if len(session.players) == 1:
                    await session.delete(self.bot.redis)
                    return await ctx.approve(f"**{member}** has won the game.")

                letters = choice(
                    [
                        segment.upper()
                        for word in self.words
                        if (segment := word[: round(len(word) / 4)])
                        and len(segment) == 3
                    ]
                )
                embed = Embed(description=f"Type a **word** containing `{letters}`")
                prompt = await ctx.channel.send(content=member.mention, embed=embed)

                for index in range(4):
                    try:
                        message: Message = await self.bot.wait_for(
                            "message",
                            check=lambda m: (
                                m.content
                                and m.channel == ctx.channel
                                and m.author == member
                                and m.content.lower() in self.words
                                and letters.lower() in m.content.lower()
                                and m.content.lower() not in session.used_words
                            ),
                            timeout=(7 if index == 0 else 1),
                        )
                    except asyncio.TimeoutError:
                        if index == 3:
                            lives = session.players[member_id] - 1
                            if not lives:
                                del session.players[member_id]
                                embed = Embed(
                                    description=f"**{member}** has been **eliminated**."
                                )

                            else:
                                session.players[member_id] = lives
                                embed = Embed(
                                    description="\n> ".join(
                                        [
                                            f"You ran out of time, **{member}**",
                                            f"You have {plural(lives, md='**'):life|lives} remaining",
                                        ]
                                    )
                                )

                            await ctx.channel.send(embed=embed)
                            break

                        elif index != 0:
                            reactions = {
                                1: "3️⃣",
                                2: "2️⃣",
                                3: "1️⃣",
                            }
                            try:
                                await prompt.add_reaction(reactions[index])
                            except NotFound:
                                ...

                        continue
                    else:
                        await message.add_reaction("✅")
                        session.used_words.append(message.content.lower())

                        break

    @blacktea.command(
        name="end",
        description="manage messages",
        usage="blacktea end",
        brief="blacktea end",
    )
    @has_permissions(manage_messages=True)
    async def blacktea_end(self, ctx: Context) -> Message | None:
        """
        End the current game of Blacktea.
        """

        session = await Blacktea.get(self.bot.redis, ctx.channel.id)
        if not session:
            return await ctx.warn("There is no game in progress.")

        await session.delete(self.bot.redis)
        await ctx.approve("The game has been ended.")

    @hybrid_command(
        name="tictactoe",
        aliases=["ttt"],
        usage="tictactoe <member>",
        brief="tictactoe @yurrion",
    )
    async def tictactoe(self, ctx: Context, *, member: Member):
        """Play a Tic Tac Toe game with your friends and gain statistics."""
        if member == ctx.author:
            return await ctx.warn("You can't play with yourself.")

        if member.bot:
            return await ctx.warn("Bots cannot play.")
        game = TicTacToe(ctx.author, member)
        await ctx.send(f"**{ctx.author.mention}** goes first", view=game)

    @command(
        name="uwuify",
        aliases=["uwu"],
        usage="<message>",
        brief="hello chat",
        description="manage messages",
    )
    async def uwuify(self, ctx: Context, *, message: str) -> Message:
        if message:
            await ctx.send(uwuify(message))

    @command(name="caption", aliases=["quote"], brief="hello world")
    async def caption(self, ctx: Context, message: Optional[Message] = None) -> Message:
        return await self.get_caption(ctx, message)

    @command()
    async def bible(self, ctx: Context) -> Message:
        """
        Get a random bible verse
        """

        params = {"format": "json", "order": "random"}
        async with self.bot.session.get(
            "https://beta.ourmanna.com/api/v1/get", params=params
        ) as response:
            if response.status == 200:
                result = await response.json()
                embed = Embed(description=result["verse"]["details"]["text"])
                embed.set_author(name=result["verse"]["details"]["reference"])
                await ctx.send(embed=embed)

    @command()
    async def quran(self, ctx: Context) -> Message:
        """
        Get a random Quran verse.
        """
        async with self.bot.session.get(
            "http://api.alquran.cloud/v1/ayah/random"
        ) as response:
            if response.status == 200:
                result = await response.json()
                verse = result["data"]["text"]
                reference = f"Surah {result['data']['surah']['englishName']} ({result['data']['surah']['number']}:{result['data']['number']})"
                embed = Embed(description=verse)
                embed.set_author(name=reference)
                return await ctx.send(embed=embed)
            else:
                return await ctx.warn(
                    "Could not fetch a Quran verse at this time. Please try again later."
                )

    @hybrid_group(name="vape", aliases=["juul"], invoke_without_command=True)
    @cooldown(1, 30, BucketType.member)
    async def vape(self, ctx: Context) -> Message:
        """
        Base command for vape.
        """
        await ctx.invoke(self.bot.get_command("vape hit"))

    @vape.command(name="hit", aliases=["smoke"])
    @cooldown(1, 30, BucketType.member)
    async def vape_hit(self, ctx: Context) -> Message:
        """
        Hit the vape.
        """
        check = await self.bot.db.fetchrow(
            "SELECT * FROM vape WHERE guild_id = $1", ctx.guild.id
        )
        if (
            check
            and check["user_id"] != ctx.author.id
            and ctx.guild.get_member(check["user_id"])
        ):
            return await ctx.warn(
                "You don't have the **vape**! "
                f"Steal it from {ctx.guild.get_member(check['user_id']).mention}"
            )

        msg = await ctx.send("Hitting the **vape**...")

        if check:
            await self.bot.db.execute(
                "UPDATE vape SET hits = hits + 1 WHERE guild_id = $1", ctx.guild.id
            )
        else:
            await self.bot.db.execute(
                "INSERT INTO vape VALUES ($1, $2, $3, $4)",
                ctx.guild.id,
                ctx.author.id,
                1,
                None,
            )

        res = await self.bot.db.fetchrow(
            "SELECT * FROM vape WHERE guild_id = $1", ctx.guild.id
        )
        embed = Embed(
            description=f"{ctx.author.mention}: Hit the **vape**! The server now has `{res['hits']}` hits",
        )

        await asyncio.sleep(random.randint(1, 4))
        with suppress(NotFound):
            await msg.edit(embed=embed)

    @vape.command(name="steal", aliases=["take"])
    @cooldown(1, 30, BucketType.guild)
    async def vape_steal(self, ctx: Context) -> Message:
        """
        Steal the vape from a member.
        """
        check = await self.bot.db.fetchrow(
            "SELECT * FROM vape WHERE guild_id = $1", ctx.guild.id
        )

        if check is None:
            await self.bot.db.execute(
                "UPDATE vape SET user_id = $1 WHERE guild_id = $2",
                ctx.author.id,
                ctx.guild.id,
            )
            return await ctx.approve("Found the **vape** somewhere and took it")

        if check["user_id"] is None:
            await self.bot.db.execute(
                "UPDATE vape SET user_id = $1 WHERE guild_id = $2",
                ctx.author.id,
                ctx.guild.id,
            )
            return await ctx.approve("Found the **vape** somewhere and took it")

        if check["user_id"] == ctx.author.id:
            return await ctx.warn("You already have the **vape**!")

        await self.bot.db.execute(
            "UPDATE vape SET user_id = $1 WHERE guild_id = $2",
            ctx.author.id,
            ctx.guild.id,
        )

        if ctx.guild.get_member(check["user_id"]):
            await ctx.neutral(
                f"Stole the **vape** from {ctx.guild.get_member(check['user_id']).mention}"
            )
        else:
            await ctx.approve("Found the **vape** somewhere and took it")

    @vape.command(name="hits")
    async def vape_hits(self, ctx: Context) -> Message:
        """
        View the number of hits in the server.
        """
        result = await self.bot.db.fetchrow(
            "SELECT * FROM vape WHERE guild_id = $1", ctx.guild.id
        )
        await ctx.neutral(f"This server has `{result['hits']}` **vape hits**")

    @vape.command(name="flavor")
    async def vape_flavor(self, ctx: Context, flavor: str = None) -> Message:
        """
        Choose your vape flavor. If no flavor is specified, show the current flavor.
        """
        flavors = [
            "Strawberry",
            "Mango",
            "Watermelon",
            "Blue Raspberry",
            "Pineapple",
            "Grape",
            "Cherry",
            "Peach",
            "Apple",
            "Pomegranate",
            "Raspberry",
            "Blackberry",
            "Blueberry",
            "Lemon",
            "Lime",
            "Orange",
            "Cranberry",
            "Tropical Punch",
            "Fruit Medley",
            "Tobacco",
        ]

        if flavor is None:
            result = await self.bot.db.fetchrow(
                "SELECT flavor FROM vape WHERE guild_id = $1", ctx.guild.id
            )
            current_flavor = result["flavor"] if result and result["flavor"] else "None"
            return await ctx.neutral(
                f"Please choose a valid flavor. Current flavor: **{current_flavor}**"
            )

        if flavor not in flavors:
            return await ctx.neutral(
                f"Invalid flavor! Please choose a valid flavor. Execute (vape flavors) to view all flavors."
            )

        await self.bot.db.execute(
            "UPDATE vape SET flavor = $1 WHERE guild_id = $2", flavor, ctx.guild.id
        )
        await ctx.approve(f"Flavor set to **{flavor}**!")

    @vape.command(name="flavors")
    async def vape_flavors(self, ctx: Context) -> Message:
        """
        View all available vape flavors.
        """
        flavors = [
            "Strawberry",
            "Mango",
            "Watermelon",
            "Blue Raspberry",
            "Pineapple",
            "Grape",
            "Cherry",
            "Peach",
            "Apple",
            "Pomegranate",
            "Raspberry",
            "Blackberry",
            "Blueberry",
            "Lemon",
            "Lime",
            "Orange",
            "Cranberry",
            "Tropical Punch",
            "Fruit Medley",
            "Tobacco",
        ]
        flavors_list = "\n".join(flavors)
        await ctx.neutral(f"Available flavors:\n{flavors_list}")

    async def cooldown_error_handler(self, ctx: Context, error: CommandError):
        if isinstance(error, CommandOnCooldown):
            return await ctx.warn(
                f"Please wait **{error.retry_after:.2f} seconds** before vaping again!"
            )

    @vape.error
    @vape_steal.error
    @vape_hit.error
    async def handle_vape_cooldown(self, ctx: Context, error: CommandError):
        await self.cooldown_error_handler(ctx, error)

    @hybrid_command(name="8ball", brief="am i okay?")
    async def eightball(self, ctx: Context, *, question: str):
        """
        Ask the 8ball a question
        """

        await ctx.send(
            f"question: {question}{'?' if not question.endswith('?') else ''}\n{random.choice(['yes', 'no', 'never', 'most likely', 'absolutely', 'absolutely not', 'of course not'])}"
        )

    @hybrid_command(brief="@yurrion")
    async def ship(self, ctx: Context, member: Member):
        """
        Check the ship rate between you and a member
        """

        return await ctx.send(
            f"**{ctx.author.name}** 💞 **{member.name}** = **{random.randrange(101)}%**"
        )
