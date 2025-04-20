from __future__ import annotations

from typing import List, Optional

from aiohttp import ClientSession, FormData
from pydantic import BaseModel
from typing_extensions import Self


class Lens(BaseModel):
    id: int
    repin_count: int
    description: Optional[str]
    image_large_url: str

    @property
    def url(self) -> str:
        return f"https://www.pinterest.com/pin/{self.id}/"

    @property
    def image_url(self) -> str:
        return self.image_large_url

    @classmethod
    async def from_image(
        cls,
        session: ClientSession,
        buffer: bytes,
    ) -> List[Self]:
        async with session.put(
            "https://api.pinterest.com/v3/visual_search/extension/image/",
            data=FormData(
                {
                    "image": buffer,
                    "page_size": "25",
                    "camera_type": "0",
                    "search_type": "0",
                    "source_type": "0",
                    "crop_source": "5",
                    "x": "0",
                    "y": "0",
                    "w": "1",
                    "h": "1",
                },
            ),
        ) as response:
            if not response.ok:
                return []

            data = await response.json()
            items = data["data"]
            items.sort(key=lambda item: item["repin_count"], reverse=True)

            return [cls(**item) for item in items]
