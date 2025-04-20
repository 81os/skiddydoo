from __future__ import annotations

from contextlib import suppress
from datetime import datetime, timedelta, timezone
from random import sample
from typing import List, Optional

from __main__ import zyn
from discord import Embed, HTTPException, Member, Message, TextChannel, User
from discord.ext.commands import CommandError, MessageConverter
from discord.utils import format_dt, get, utcnow
from pydantic import BaseConfig, BaseModel
from typing_extensions import Self

from tools.client import Context


class GiveawayEntry(BaseModel):
    bot: zyn
    guild_id: int
    user_id: int
    channel_id: int
    message_id: int = 0
    prize: str
    emoji: str
    winners: int
    ends_at: datetime
    ended: bool = False
    created_at: datetime = utcnow()

    class Config(BaseConfig):
        arbitrary_types_allowed = True

    def __str__(self) -> str:
        return f"{f'{self.winners}x ' if self.winners > 1 else ''}{self.prize}"

    def __repr__(self) -> str:
        return f"<GiveawayEntry guild_id={self.guild_id} channel_id={self.channel_id} message_id={self.message_id} prize={self.prize!r} winners={self.winners} ends_at={self.ends_at!r}>"

    def __eq__(self, other) -> bool:
        if not isinstance(other, GiveawayEntry):
            return NotImplemented

        return self.message_id == other.message_id

    @property
    def is_ended(self) -> bool:
        return self.ends_at <= utcnow() or self.ended

    @property
    def channel(self) -> Optional[TextChannel]:
        return self.bot.get_channel(self.channel_id)  # type: ignore

    @property
    def user(self) -> Optional[User]:
        return self.bot.get_user(self.user_id)

    @property
    def message_url(self) -> str:
        return f"https://discord.com/channels/{self.guild_id}/{self.channel_id}/{self.message_id}"

    def embed(self, winners: List[Member] = []) -> Embed:
        embed = Embed(title=self)
        if not self.is_ended:
            embed.description = (
                f"React with {self.emoji} to enter"
                f"\n> Ends {format_dt(self.ends_at, 'R')}"
            )
        else:
            if not winners:
                embed.description = "No winner was drawn 🥺"
            else:
                embed.description = (
                    f"Congratulations 🎉"
                    f"\n> {', '.join(winner.mention for winner in winners)}"
                )

        if self.user:
            embed.set_footer(text=f"Started by {self.user}")

        return embed

    async def message(self) -> Optional[Message]:
        if (channel := self.channel) is not None:
            with suppress(HTTPException):
                return await channel.fetch_message(self.message_id)

    async def entrants(self, message: Message) -> List[Member]:
        reaction = get(message.reactions, emoji=self.emoji)
        if not reaction:
            return []

        return [
            member
            async for member in reaction.users()
            if not member.bot and isinstance(member, Member)
        ]

    async def draw_winners(self, message: Message) -> List[Member]:
        entrants = await self.entrants(message)
        if not entrants:
            return []

        with suppress(ValueError):
            return sample(entrants, self.winners)

        return []

    async def end(self) -> None:
        self.ended = True
        await self.bot.db.execute(
            """
            UPDATE giveaway
            SET ended = TRUE
            WHERE guild_id = $1
            AND channel_id = $2
            AND message_id = $3
            """,
            self.guild_id,
            self.channel_id,
            self.message_id,
        )

    async def save(self, message: Message) -> None:
        created_at = datetime.now(timezone.utc).replace(tzinfo=None)
        await self.bot.db.execute(
            """
            INSERT INTO giveaway (
                guild_id,
                user_id,
                channel_id,
                message_id,
                prize,
                emoji,
                winners,
                ends_at,
                created_at
            )
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
            """,
            self.guild_id,
            self.user_id,
            self.channel_id,
            message.id,
            self.prize,
            self.emoji,
            self.winners,
            self.ends_at,
            created_at,
        )

    @classmethod
    def from_record(cls, bot: "zyn", record) -> Self:
        return cls(
            bot=bot,
            guild_id=record["guild_id"],
            user_id=record["user_id"],
            channel_id=record["channel_id"],
            message_id=record["message_id"],
            prize=record["prize"],
            emoji=record["emoji"],
            winners=record["winners"],
            ended=record["ended"],
            ends_at=record["ends_at"],
            created_at=record["created_at"],
        )

    @classmethod
    async def fetch(cls, ctx: Context, message: Message) -> Optional[Self]:
        record = await ctx.bot.db.fetchrow(
            """
            SELECT *
            FROM giveaway
            WHERE guild_id = $1
            AND channel_id = $2
            AND message_id = $3
            """,
            ctx.guild.id,
            message.channel.id,
            message.id,
        )
        if record:
            return cls.from_record(ctx.bot, record)

    @classmethod
    async def convert(cls, ctx: Context, argument: str) -> Self:
        message = await MessageConverter().convert(ctx, argument)
        if message.guild != ctx.guild:
            raise CommandError("The message must be in this server")

        record = await cls.fetch(ctx, message)
        if not record:
            raise CommandError(
                f"No giveaway exists for that [`message`]({message.jump_url})"
            )

        return record

    @classmethod
    async def fallback(cls, ctx: Context) -> Self:
        """
        A fallback for when conversion fails.
        """

        if not ctx.replied_message:
            record = await ctx.bot.db.fetchrow(
                """
                SELECT *
                FROM giveaway
                WHERE guild_id = $1
                ORDER BY created_at DESC
                """,
                ctx.guild.id,
            )
            if record:
                return cls.from_record(ctx.bot, record)

            raise CommandError("No giveaways exist for this server")

        with suppress(CommandError):
            return await cls.convert(ctx, ctx.replied_message.jump_url)

        raise CommandError("No giveaways exist for this server")
