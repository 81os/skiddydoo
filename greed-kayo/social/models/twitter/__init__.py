from http.cookiejar import MozillaCookieJar
from json import loads
from pathlib import Path
from typing import Literal, Optional

from aiohttp import ClientSession as _ClientSession
from pydantic import BaseConfig, BaseModel

#  This file is in the same directory as config.json
path = Path(__file__).parent / "api.json"
API = loads(path.read_text())


jar = MozillaCookieJar()
jar.load("cookies.txt")


class CookieModel(BaseModel):
    name: str
    value: str
    url: Optional[str]
    domain: Optional[str]
    path: Optional[str]
    expires: int = -1
    httpOnly: Optional[bool]
    secure: Optional[bool]
    sameSite: Optional[Literal["Lax", "None", "Strict"]]

    class Config(BaseConfig):
        orm_mode = True


class ClientSession(_ClientSession):
    def __init__(self, *args, **kwargs):
        super().__init__(
            *args,
            cookies={
                cookie.name: cookie.value
                for _cookie in jar
                if (cookie := CookieModel.from_orm(_cookie))
                and "x" in (cookie.domain or "")
            },
            **kwargs,
        )
        self.headers.update(
            {
                "X-Csrf-Token": "210fbabe3ccc8633532b6c4ba48ea9798cfc934e307b515802adfeeb17cb9bae52ef1c2ea5590c9de3de086efa70dfdd30a958e56a43e6700a061efc3d9710f6dd0de24b3e19eadd07bd00cd5ff2311f",
                **API["header"],
            }
        )

    # async def __aenter__(self):
    #     resp = await self.post("https://api.twitter.com/1.1/guest/activate.json")
    #     json = await resp.json()
    #     self.headers.update(
    #         {
    #             "content-type": "application/json",
    #             "x-guest-token": json["guest_token"],
    #             "x-twitter-active-user": "yes",
    #         }
    #     )
    #     return self
