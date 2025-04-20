from __future__ import annotations

from datetime import datetime, timedelta
from typing import List, Literal, Optional, Union

from discord import Color
from discord.utils import utcnow
from pydantic import BaseModel

from main import zyn


class Config(BaseModel):
    user_id: int
    username: str
    color: Optional[int]
    command: Optional[str]
    reactions: List[str]
    embed_mode: Union[Literal["default", "minimal", "compact"], str]
    last_indexed: datetime

    @property
    def should_index(self) -> bool:
        return self.last_indexed < utcnow() - timedelta(hours=24)

    @property
    def embed_color(self) -> Color:  # sourcery skip: assign-if-exp, reintroduce-else
        if self.color in (None, 1337):
            return Color.dark_embed()

        return Color(self.color)

    @property
    def reactions_disabled(self) -> bool:
        return "disabled" in self.reactions

    @classmethod
    async def fetch(cls, bot: zyn, user_id: int) -> Optional[Config]:
        record = await bot.db.fetchrow(
            """
            SELECT *
            FROM lastfm.config
            WHERE user_id = $1
            """,
            user_id,
        )
        if not record:
            return

        return cls(**record)
