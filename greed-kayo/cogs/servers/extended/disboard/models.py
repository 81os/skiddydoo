from datetime import datetime
from typing import Optional, TypedDict

from discord import Member, User
from pydantic import BaseConfig, BaseModel


class DisboardRecord(TypedDict):
    guild_id: int
    channel_id: Optional[int]
    status: bool
    last_channel_id: int
    last_user_id: int
    message: Optional[str]
    thank_message: Optional[str]
    next_bump: Optional[datetime]
    bumps: Optional[int]


class DisboardV(TypedDict):
    thank_message: Optional[str]
    user_bumps: int
    bumps: int


class DisboardVariables(BaseModel):
    last_user: Member | User
    user_bumps: int = 0
    bumps: int = 0

    def __str__(self) -> str:
        return self.bump

    @property
    def _variable(self) -> str:
        return "disboard"

    @property
    def bump(self) -> str:
        return "</bump:947088344167366698>"

    class Config(BaseConfig):
        arbitrary_types_allowed = True
