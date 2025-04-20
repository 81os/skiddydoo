from __future__ import annotations

from datetime import datetime
from typing import Optional

from aiohttp import ClientSession
from discord.ext.commands import CommandError
from pydantic import BaseModel
from yarl import URL

from tools.client import Context

from .authorization import TwitchAuthorization


class User(BaseModel):
    id: int
    login: str
    display_name: str
    type: str
    broadcaster_type: str
    description: str
    profile_image_url: str
    offline_image_url: str
    view_count: int
    created_at: datetime

    def __str__(self) -> str:
        return self.display_name

    @property
    def url(self) -> str:
        return f"https://twitch.tv/{self.login}"

    @classmethod
    async def search(
        cls,
        session: ClientSession,
        user_login: str,
    ) -> Optional[User]:  # sourcery skip: assign-if-exp, reintroduce-else
        """
        Fetch a user from their login name.
        """

        AUTHORIZATION = await TwitchAuthorization.get(session)

        async with session.get(
            URL.build(
                scheme="https",
                host="api.twitch.tv",
                path="/helix/users",
            ),
            params={
                "login": user_login,
            },
            headers={
                "AUTHORIZATION": f"Bearer {AUTHORIZATION.access_token}",
                "Client-ID": AUTHORIZATION.client_id,
            },
        ) as response:
            data = await response.json()
            if not data.get("data"):
                return None

            user = data["data"][0]
            user["id"] = int(user["id"])

            return cls.parse_obj(user)

    @classmethod
    async def convert(
        cls,
        ctx: Context,
        argument: str,
    ) -> User:
        user = await cls.search(ctx.bot.session, argument)
        if not user:
            raise CommandError("No **Twitch user** found with that query!")

        return user
