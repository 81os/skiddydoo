from contextlib import suppress
from datetime import datetime
from typing import List, Optional

from discord.ext.commands import CommandError
from pydantic import BaseConfig, BaseModel, Field
from roblox import AvatarThumbnailType, Client, UserNotFound
from roblox.users import User
from roblox.utilities.exceptions import BadRequest
from typing_extensions import Self

from tools.client import Context

client = Client()


class Badge(BaseModel):
    id: int
    name: str
    description: str
    image_url: str

    @property
    def url(self) -> str:
        return f"https://www.roblox.com/info/roblox-badges#Badge{self.id}"


class Presence(BaseModel):
    status: str
    location: Optional[str]
    last_online: Optional[datetime]


class Model(BaseModel):
    id: int
    name: str
    display_name: str
    description: str
    is_banned: bool
    created_at: datetime
    original: User = Field(..., repr=False)

    @property
    def url(self) -> str:
        return f"https://www.roblox.com/users/{self.id}/profile"

    async def avatar_url(self) -> Optional[str]:
        thumbnails = await client.thumbnails.get_user_avatar_thumbnails(
            users=[self.id],
            type=AvatarThumbnailType.full_body,
            size=(420, 420),
        )

        return thumbnails[0].image_url

    async def badges(self) -> List[Badge]:
        badges = await self.original.get_roblox_badges()

        return [
            Badge(
                id=badge.id,
                name=badge.name,
                description=badge.description,
                image_url=badge.image_url,
            )
            for badge in badges
        ]

    async def follower_count(self) -> int:
        return await self.original.get_follower_count()

    async def following_count(self) -> int:
        return await self.original.get_following_count()

    async def friend_count(self) -> int:
        return await self.original.get_friend_count()

    async def presence(self) -> Optional[Presence]:
        presence = await self.original.get_presence()
        if not presence:
            return None

        return Presence(
            status=presence.user_presence_type.name,
            location=presence.last_location,
            last_online=presence.last_online,
        )

    async def names(self) -> List[str]:
        names: List[str] = []
        with suppress(BadRequest):
            async for name in self.original.username_history():
                names.append(str(name))

        return names

    class Config(BaseConfig):
        arbitrary_types_allowed = True

    @classmethod
    async def fetch(cls, username: str) -> Optional[Self]:
        try:
            user = await client.get_user_by_username(username, expand=True)
        except (UserNotFound, BadRequest):
            return None

        if not isinstance(user, User):
            return None

        return cls(
            id=user.id,
            name=user.name,
            display_name=user.display_name,
            description=user.description,
            is_banned=user.is_banned,
            created_at=user.created,
            original=user,
        )

    @classmethod
    async def convert(cls, ctx: Context, argument: str) -> Self:
        async with ctx.typing():
            if user := await cls.fetch(argument):
                return user

        raise CommandError("No **Roblox user** found with that name!")
