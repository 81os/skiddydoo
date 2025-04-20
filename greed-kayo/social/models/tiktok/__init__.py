from http.cookiejar import MozillaCookieJar
from typing import Literal, Optional

from aiohttp import ClientSession as _ClientSession
from pydantic import BaseConfig, BaseModel

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
        from_attributes = True


class ClientSession(_ClientSession):
    msToken: Optional[str] = None

    def __init__(self, *args, **kwargs):
        for cookie in jar:
            if cookie.name == "msToken":
                self.msToken = cookie.value
                break

        super().__init__(
            *args,
            cookies={
                cookie.name: cookie.value
                for _cookie in jar
                if (cookie := CookieModel.from_orm(_cookie))
                and "tiktok" in (cookie.domain or "")
            },
            **kwargs,
        )
        self.headers.update(
            {
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                    "(KHTML, like Gecko) Chrome/80.0.3987.149 Safari/537.36"
                ),
                "msToken": self.msToken or "",
            }
        )
