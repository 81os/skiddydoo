from datetime import datetime, timedelta

from aiohttp import ClientSession
from discord.utils import utcnow
from pydantic import BaseModel
from yarl import URL

from config import AUTHORIZATION
from tools.cache import cache


class TwitchAuthorization(BaseModel):
    access_token: str
    expires_in: int
    token_type: str

    @property
    def expires_at(self) -> datetime:
        return utcnow() + timedelta(seconds=self.expires_in)

    @property
    def is_expired(self) -> bool:
        return self.expires_at <= utcnow()

    @property
    def client_id(self) -> str:
        return AUTHORIZATION.TWITCH.CLIENT_ID

    @classmethod
    @cache()
    async def get(cls, session: ClientSession) -> "TwitchAuthorization":
        async with session.post(
            URL.build(
                scheme="https",
                host="id.twitch.tv",
                path="/oauth2/token",
            ),
            params={
                "client_id": AUTHORIZATION.TWITCH.CLIENT_ID,
                "client_secret": AUTHORIZATION.TWITCH.CLIENT_SECRET,
                "grant_type": "client_credentials",
            },
        ) as response:
            data = await response.json()

            return cls(**data)
