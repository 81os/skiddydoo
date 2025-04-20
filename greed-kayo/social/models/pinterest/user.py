from __future__ import annotations

from json import dumps
from typing import List, Optional

from aiohttp import ClientSession
from discord.ext.commands import CommandError
from pydantic import BaseModel
from typing_extensions import Self

from tools.client import Context


class Board(BaseModel):
    id: str
    name: str
    pin_count: Optional[int] = 0


class User(BaseModel):
    id: str
    follower_count: int = 0
    full_name: Optional[str]
    image_xlarge_url: Optional[str]
    pin_count: int = 0
    about: Optional[str]
    first_name: str
    following_count: int = 0
    username: str
    domain_url: Optional[str]
    website_url: Optional[str]
    is_private_profile: bool = False

    def __str__(self) -> str:
        return self.full_name or self.username

    @property
    def url(self) -> str:
        return f"https://www.pinterest.com/{self.username}/"

    @property
    def avatar_url(self) -> Optional[str]:
        return self.image_xlarge_url

    async def boards(self, session: ClientSession) -> List[Board]:
        async with session.get(
            "https://www.pinterest.com/resource/BoardsFeedResource/get/",
            params={
                "source_url": f"/{self.username}/_saved/",
                "data": dumps(
                    {
                        "options": {
                            "field_set_key": "profile_grid_item",
                            "filter_stories": False,
                            "sort": "last_pinned_to",
                            "username": self.username,
                        },
                        "context": {},
                    }
                ),
            },
        ) as response:
            if not response.ok:
                return []

            data = await response.json()
            boards = data["resource_response"]["data"]

            return [
                Board(**board)
                for board in boards
                if board.get("name") and board.get("privacy") == "public"
            ]

    @classmethod
    async def fetch(
        cls,
        session: ClientSession,
        username: str,
    ) -> Optional[Self]:
        async with session.get(
            "https://www.pinterest.com/resource/UserResource/get/",
            params={
                "source_url": f"/{username}/",
                "data": dumps(
                    {
                        "options": {
                            "field_set_key": "unauth_profile",
                            "is_mobile_fork": True,
                            "username": username,
                        },
                        "context": {},
                    }
                ),
            },
        ) as response:
            if not response.ok:
                return None

            data = await response.json()
            user = data["resource_response"]["data"]

            return cls(**user)

    @classmethod
    async def convert(cls, ctx: Context, argument: str) -> Self:
        async with ctx.typing():
            if user := await cls.fetch(ctx.bot.session, argument):
                return user

        raise CommandError("No **Pinterest user** found with that name!")
