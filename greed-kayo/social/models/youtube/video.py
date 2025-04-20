from __future__ import annotations

from datetime import datetime, timedelta
from typing import List, Optional

from aiohttp import ClientSession
from pydantic import BaseModel
from yarl import URL

from config import PIPED_API


class Video(BaseModel):
    id: str
    uploader: str
    title: str
    description: Optional[str]
    duration: timedelta
    views: int
    is_short: bool
    thumbnail_url: str
    created_at: datetime

    def __str__(self) -> str:
        return self.title

    @property
    def url(self) -> str:
        return f"https://www.youtube.com/watch?v={self.id}"

    @property
    def is_live(self) -> bool:
        return not self.duration

    @classmethod
    def parse(cls, data: dict) -> Video:
        return cls(
            id=data["url"].split("?v=")[-1],
            uploader=data["uploaderName"],
            title=data["title"],
            description=data["shortDescription"],
            duration=timedelta(seconds=data["duration"]),
            views=data["views"],
            is_short=data["isShort"],
            thumbnail_url=data["thumbnail"],
            created_at=datetime.fromtimestamp(data["uploaded"] / 1000),
        )

    @classmethod
    async def search(
        cls,
        session: ClientSession,
        query: str,
    ) -> List[Video]:
        async with session.get(
            URL.build(
                scheme="https",
                host=PIPED_API,
                path="/search",
            ),
            params={
                "q": query,
                "filter": "all",
            },
        ) as response:
            if not response.ok:
                return []

            data = await response.json()
            videos = list(filter(lambda item: item["type"] == "stream", data["items"]))

            return list(map(cls.parse, videos))
