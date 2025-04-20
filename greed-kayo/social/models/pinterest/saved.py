from __future__ import annotations

from json import dumps
from typing import List, Optional

from aiohttp import ClientSession
from discord import Color
from pydantic import BaseModel
from typing_extensions import Self


class Pinner(BaseModel):
    id: str
    username: str
    full_name: Optional[str]
    image_small_url: str

    def __str__(self) -> str:
        return self.full_name or self.username

    @property
    def url(self) -> str:
        return f"https://www.pinterest.com/{self.username}/"

    @property
    def avatar_url(self) -> str:
        return self.image_small_url


class Pin(BaseModel):
    id: str
    dominant_color: str
    image_url: str
    title: Optional[str]
    pinner: Pinner
    board_name: str

    @property
    def url(self) -> str:
        return f"https://www.pinterest.com/pin/{self.id}/"

    @property
    def color(self) -> Color:
        return Color(int(self.dominant_color[1:], 16))


class SavedPins(BaseModel):
    bookmark: Optional[str]
    pins: List[Pin] = []

    @classmethod
    async def fetch(
        cls,
        session: ClientSession,
        username: str,
        board_id: Optional[str] = None,
        bookmark: Optional[str] = None,
    ) -> Optional[Self]:
        async with session.get(
            f"https://www.pinterest.com/resource/{'UserPinsResource' if not board_id else 'BoardFeedResource'}/get/",
            params={
                "source_url": f"/{username}/_saved/",
                "data": dumps(
                    {
                        "options": {
                            "add_vase": True,
                            "field_set_key": (
                                "mobile_grid_item" if not board_id else "react_grid_pin"
                            ),
                            "is_own_profile_pins": False,
                            "username": username,
                            "page_size": 250,
                            **({"bookmarks": [bookmark]} if bookmark else {}),
                            **({"board_id": board_id or {}}),
                        },
                        "context": {},
                    }
                ),
            },
        ) as response:
            if not response.ok:
                return None

            data = await response.json()
            pins = data["resource_response"]["data"]

            return cls(
                bookmark=data["resource_response"].get("bookmark"),
                pins=[
                    Pin(
                        **pin,
                        image_url=list(pin["images"].items())[-1][1]["url"],
                        board_name=pin["board"]["name"],
                    )
                    for pin in pins
                    if pin.get("videos") is None and pin.get("images") is not None
                ],
            )
