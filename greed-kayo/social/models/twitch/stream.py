from __future__ import annotations

from datetime import datetime
from typing import List

from aiohttp import ClientSession
from discord.utils import as_chunks, utcnow
from pydantic import BaseModel
from yarl import URL

from .authorization import TwitchAuthorization


class Stream(BaseModel):
    id: int
    user_id: int
    user_name: str
    game_id: int
    game_name: str
    type: str
    title: str
    viewer_count: int
    started_at: datetime
    language: str
    thumbnail_url: str
    tags: List[str]
    is_mature: bool

    def __str__(self) -> str:
        return self.title

    @property
    def url(self) -> str:
        return f"https://twitch.tv/{self.user_name}"

    @property
    def thumbnail(self) -> str:
        return (
            self.thumbnail_url.replace("{width}", "1920").replace("{height}", "1080")
            + f"?t={utcnow().timestamp()}"
        )

    @classmethod
    async def fetch(
        cls,
        session: ClientSession,
        user_ids: List[int | str],
    ) -> List[Stream]:
        """
        Fetch multiple streams from their user ids.
        """

        AUTHORIZATION = await TwitchAuthorization.get(session)
        streams: List[Stream] = []

        for chunk in as_chunks(user_ids, 100):
            query = ""
            for user_id in chunk:
                key = "user_id" if isinstance(user_id, int) else "user_login"
                query += f"{key}={user_id}&"

            async with session.get(
                URL.build(
                    scheme="https",
                    host="api.twitch.tv",
                    path="/helix/streams",
                ).with_query(query[:-1]),
                headers={
                    "AUTHORIZATION": f"Bearer {AUTHORIZATION.access_token}",
                    "Client-ID": AUTHORIZATION.client_id,
                },
            ) as response:
                data = await response.json()

                streams.extend([cls.parse_obj(stream) for stream in data["data"]])

        return streams
