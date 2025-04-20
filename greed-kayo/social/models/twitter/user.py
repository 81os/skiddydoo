from contextlib import suppress
from json import dumps
from typing import Optional

from cashews import cache
from discord.ext.commands import CommandError
from pydantic import BaseModel
from typing_extensions import Self

from cogs.social.models.twitter import API, ClientSession
from tools.client import Context

ENDPOINT = API["graphql"]["UserByScreenName"]


class BasicUser(BaseModel):
    id: int
    screen_name: str
    name: str
    profile_image_url_https: str

    def __str__(self) -> str:
        return self.name or self.screen_name

    @property
    def _variable(self) -> str:
        return "twitter"

    @property
    def url(self) -> str:
        return f"https://twitter.com/{self.screen_name}"

    @property
    def avatar_url(self) -> str:
        return self.profile_image_url_https.replace("_normal", "")


class User(BasicUser):
    friends_count: int
    followers_count: int
    favourites_count: int
    friends_count: int
    media_count: int
    statuses_count: int
    profile_image_url_https: str
    verified: bool
    description: Optional[str] = None

    def __str__(self) -> str:
        return self.name

    @classmethod
    @cache(ttl="6h")
    async def fetch(cls, username: str) -> Optional[Self]:
        async with ClientSession() as session:
            async with session.request(
                ENDPOINT["method"],
                ENDPOINT["url"],
                params={
                    "variables": dumps(
                        {
                            "screen_name": username,
                            "withSafetyModeUserFields": True,
                        }
                    ),
                    "features": dumps(ENDPOINT["features"]),
                },
            ) as resp:
                if not resp.ok:
                    print("Error (NOT OK)", resp.status, await resp.text())
                    return None

                data = await resp.json()
                if "user" not in data["data"]:
                    print("Error (NO USER)")
                    return None

                user = data["data"]["user"]["result"]

                with suppress(KeyError):
                    return cls(**user["legacy"], id=user["rest_id"])

    @classmethod
    async def convert(cls, ctx: Context, argument: str) -> Self:
        async with ctx.typing():
            if user := await cls.fetch(argument):
                return user

        raise CommandError("No **Twitter user** found with that name!")
