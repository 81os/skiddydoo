from __future__ import annotations

from json import JSONDecodeError, loads
from typing import Optional

from bs4 import BeautifulSoup
from cashews import cache
from discord.ext.commands import CommandError
from pydantic import BaseModel, Field
from typing_extensions import Self

from cogs.social.models.tiktok import ClientSession
from tools.client import Context


class Statistics(BaseModel):
    follower_count: int = Field(alias="followerCount")
    following_count: int = Field(alias="followingCount")
    heart_count: int = Field(alias="heart")
    video_count: int = Field(alias="videoCount")


class BasicUser(BaseModel):
    id: int
    sec_uid: str = Field(alias="secUid")
    username: str = Field(alias="uniqueId")
    full_name: str = Field(alias="nickname")
    avatar_url: str = Field(alias="avatarThumb")
    biography: str = Field(alias="signature")

    def __str__(self) -> str:
        return self.full_name or self.username

    @property
    def _variable(self) -> str:
        return "tiktok"

    @property
    def url(self) -> str:
        return f"https://www.tiktok.com/@{self.username}"


class User(BasicUser):
    is_verified: bool = Field(alias="verified")
    is_private: bool = Field(alias="privateAccount")
    statistics: Statistics = Field(alias="stats")

    @classmethod
    @cache(ttl="6h")
    async def fetch(cls, username: str) -> Optional[Self]:
        """
        Fetches a user's profile.
        """

        username = username.strip("@")
        async with ClientSession() as session:
            async with session.get(
                f"https://www.tiktok.com/@{username}",
            ) as resp:
                if not resp.ok:
                    return None

                data = await resp.text()
                soup = BeautifulSoup(data, "lxml")

                script = soup.find("script", id="__UNIVERSAL_DATA_FOR_REHYDRATION__")
                if not script:
                    return

                try:
                    user = loads(script.text)["__DEFAULT_SCOPE__"][
                        "webapp.user-detail"
                    ]["userInfo"]
                except (JSONDecodeError, KeyError):
                    return

                return cls(
                    **user,
                    **user["user"],
                )

    @classmethod
    async def convert(cls, ctx: Context, argument: str) -> Self:
        async with ctx.typing():
            if user := await cls.fetch(argument):
                return user

        raise CommandError("No **TikTok user** found with that name!")
